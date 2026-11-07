from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout
from yt_dlp.utils import DownloadError

from app.core.config import get_settings
from app.tasks.caption import caption_from_og
from app.tasks.video_downloader import download_videos

settings = get_settings()

MAX_SLIDES = 20
POPUP_BUTTONS = ("Not Now", "Not now", "Decline optional cookies", "Allow all cookies", "Close")


class GalleryError(Exception):
    pass


# Collects this post's own images (not the "more posts" thumbnails) plus caption data.
_COLLECT_JS = """
() => {
  const root = document.querySelector('article') || document.querySelector('main') || document;
  const POST_LINK = 'a[href*="/p/"], a[href*="/reel/"], a[href*="/reels/"]';
  const own = (i) => !i.closest(POST_LINK);   // suggested posts are wrapped in links to other posts

  const best = (img) => {
    const set = (img.getAttribute('srcset') || '').split(',')
      .map(s => s.trim().split(/\\s+/)).filter(p => p[0])
      .map(p => [p[0], parseInt(p[1]) || 0]);
    if (!set.length) return img.src;
    return set.sort((a, b) => b[1] - a[1])[0][0];
  };

  // carousel: the <ul> whose <li> items contain this post's own images
  const carousel = [...root.querySelectorAll('ul')].find(u => {
    const im = u.querySelector('li img');
    return im && own(im);
  });
  const scope = carousel || root;

  return {
    images: [...scope.querySelectorAll('img')]
      .filter(i => own(i) && !/profile picture/i.test(i.alt || '') && !i.closest('header') && i.src.includes('fbcdn')
                   && !(i.closest('li') && i.closest('li').querySelector('video')))
      .map(best),
    hasVideo: !!scope.querySelector('video'),
    caption: (root.querySelector('h1') || {}).innerText || null,
    og: (document.querySelector('meta[property="og:description"]') || {}).content || null,
    time: (root.querySelector('time[datetime]') || {}).dateTime || null,
  };
}
"""


def _check_session(page: Page) -> None:
    """Fail fast with a clear message if Instagram shows a login wall."""
    if "/accounts/login" in page.url or page.locator('input[name="username"]').count():
        raise GalleryError("Instagram session expired, re-run login_once.py")


def _dismiss_popups(page: Page) -> None:
    """Close cookie / 'Not now' dialogs that sit on top of the post."""
    for label in POPUP_BUTTONS:
        try:
            btn = page.get_by_role("button", name=label, exact=True)
            if btn.count():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(300)
        except Exception:
            pass


def _wait_for_carousel(page: Page) -> bool:
    """Wait for the 'Next' button to be rendered. Single-image posts never get one."""
    try:
        page.wait_for_selector('button[aria-label="Next"]', state="attached", timeout=5000)
        return True
    except PWTimeout:
        return False


def _next_slide(page: Page) -> bool:
    """Go to the next slide. Returns False when there is no next button."""
    nxt = page.locator('button[aria-label="Next"]')
    if nxt.count() == 0:
        return False

    before = page.evaluate("document.querySelectorAll('article img, main img').length")
    try:
        nxt.first.click(timeout=3000)
    except Exception:
        page.keyboard.press("ArrowRight")  # overlay covers the button

    # wait until the carousel renders something new (up to ~2.5 s)
    try:
        page.wait_for_function(
            "b => document.querySelectorAll('article img, main img').length !== b",
            arg=before,
            timeout=2500,
        )
    except PWTimeout:
        pass
    page.wait_for_timeout(300)
    return True


def download_gallery(shortcode: str, url: str) -> dict:
    media = Path(settings.MEDIA_DIR)
    (media / "images").mkdir(parents=True, exist_ok=True)

    # delete leftovers from earlier runs of this post
    for old in (media / "images").glob(f"{shortcode}_*.jpg"):
        old.unlink(missing_ok=True)

    urls: dict[str, str] = {}  # dedupe by URL path, keeps slide order
    has_video, caption, taken = False, None, None
    paths: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            storage_state=settings.IG_STORAGE_STATE,
            viewport={"width": 1280, "height": 1800},
        )
        page = ctx.new_page()
        page.set_default_timeout(15_000)
        try:
            page.goto(url, wait_until="domcontentloaded")
            _check_session(page)
            page.wait_for_selector("article img, main img, article video")
            page.wait_for_load_state("load")
            _dismiss_popups(page)
            _check_session(page)
            is_carousel = _wait_for_carousel(page)  # once, after the page is loaded

            idle = 0  # consecutive steps that added no new image
            for _ in range(MAX_SLIDES):
                data = page.evaluate(_COLLECT_JS)
                has_video = has_video or data["hasVideo"]
                caption = caption or caption_from_og(data["og"]) or data["caption"]
                taken = taken or data["time"]

                before = len(urls)
                for u in data["images"]:
                    urls.setdefault(u.split("?")[0], u)

                idle = idle + 1 if len(urls) == before else 0
                if idle >= 3:  # last slide reached (or nothing is changing)
                    break
                if not _next_slide(page):
                    break

            if not is_carousel and urls:
                # single-image post: keep only the main image
                first_key = next(iter(urls))
                urls = {first_key: urls[first_key]}

            if not urls and not has_video:
                raise GalleryError("no images found on the page")

            for i, u in enumerate(urls.values(), start=1):
                resp = ctx.request.get(u)  # same cookies, no extra auth code
                if not resp.ok:
                    continue
                p = media / "images" / f"{shortcode}_{i}.jpg"
                p.write_bytes(resp.body())
                paths.append(str(p))
        finally:
            browser.close()

    # video slides: yt-dlp downloads every video of the post (no thumbnails)
    video_paths: list[str] = []
    duration = None
    if has_video:
        try:
            v = download_videos(url, thumbs=False)
            video_paths, duration = v["video_paths"], v["duration"]
        except DownloadError:
            pass

    if not paths and not video_paths:
        raise GalleryError("image download failed")

    total = len(paths) + len(video_paths)
    if total > 1:
        media_type = "gallery"
    elif video_paths:
        media_type = "video"
    else:
        media_type = "image"

    return {
        "title": None,  # set by the caller from the caption
        "description": caption,
        "timestamp": datetime.fromisoformat(taken.replace("Z", "+00:00")).timestamp() if taken else None,
        "duration": duration,
        "video_path": video_paths[0] if video_paths else None,
        "video_paths": video_paths or None,
        "thumbnail_path": paths[0] if paths else None,  # for video posts the caller sets the web cover
        "image_paths": paths or None,
        "media_type": media_type,
    }