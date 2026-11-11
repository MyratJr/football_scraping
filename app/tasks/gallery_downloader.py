import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

from app.core.config import get_settings
from app.tasks.caption import caption_from_og

settings = get_settings()

logger = logging.getLogger(__name__)

MAX_SLIDES = 20
POPUP_BUTTONS = ("Not Now", "Not now", "Decline optional cookies", "Allow all cookies", "Close")


class GalleryError(Exception):
    pass


# Caption data and the first image (used for single-image posts).
_COLLECT_JS = """
() => {
  const root = document.querySelector('article') || document.querySelector('main') || document;
  const POST_LINK = 'a[href*="/p/"], a[href*="/reel/"], a[href*="/reels/"]';
  const own = (i) => !i.closest(POST_LINK);
  const best = (img) => {
    const set = (img.getAttribute('srcset') || '').split(',')
      .map(s => s.trim().split(/\\s+/)).filter(p => p[0])
      .map(p => [p[0], parseInt(p[1]) || 0]);
    if (!set.length) return img.src;
    return set.sort((a, b) => b[1] - a[1])[0][0];
  };
  const carousel = [...root.querySelectorAll('ul')].find(u => {
    const im = u.querySelector('li img');
    return im && own(im);
  });
  const scope = carousel || root;
  return {
    images: [...scope.querySelectorAll('img')]
      .filter(i => own(i) && !/profile picture/i.test(i.alt || '') && !i.closest('header') && i.src.includes('fbcdn'))
      .map(best),
    hasVideo: !!scope.querySelector('video'),
    caption: (root.querySelector('h1') || {}).innerText || null,
    og: (document.querySelector('meta[property="og:description"]') || {}).content || null,
    time: (root.querySelector('time[datetime]') || {}).dateTime || null,
  };
}
"""

# Finds the slide that is currently visible in the carousel: {key, video, src}.
_ACTIVE_BODY = """
  const POST_LINK = 'a[href*="/p/"], a[href*="/reel/"], a[href*="/reels/"]';
  const root = document.querySelector('article') || document.querySelector('main') || document;
  const own = (el) => !el.closest(POST_LINK);
  const best = (img) => {
    const set = (img.getAttribute('srcset') || '').split(',')
      .map(s => s.trim().split(/\\s+/)).filter(p => p[0])
      .map(p => [p[0], parseInt(p[1]) || 0]);
    if (!set.length) return img.src;
    return set.sort((a, b) => b[1] - a[1])[0][0];
  };
  const activeSlide = () => {
    const ul = [...root.querySelectorAll('ul')].find(u => {
      const m = u.querySelector('li img, li video');
      return m && own(m);
    });
    if (!ul) return null;
    let clip = ul.parentElement;
    while (clip && getComputedStyle(clip).overflowX === 'visible') clip = clip.parentElement;
    const box = (clip || ul.parentElement).getBoundingClientRect();
    let active = null, bestOverlap = 0;
    for (const li of ul.children) {
      const r = li.getBoundingClientRect();
      if (r.width < 20) continue;
      const overlap = Math.min(r.right, box.right) - Math.max(r.left, box.left);
      if (overlap > bestOverlap) { bestOverlap = overlap; active = li; }
    }
    if (!active) return null;
    const img = [...active.querySelectorAll('img')].find(i => own(i) && i.src.includes('fbcdn'));
    return { key: active.style.transform || '', video: !!active.querySelector('video'), src: img ? best(img) : null };
  };
"""
_SLIDE_JS = "() => {" + _ACTIVE_BODY + " return activeSlide(); }"
_CHANGED_JS = "(k) => {" + _ACTIVE_BODY + " const s = activeSlide(); return !!s && s.key !== k; }"

# Plays the visible video muted and returns its duration.
_PLAY_JS = """
async () => {
  const v = [...document.querySelectorAll('video')].find(x => {
    const r = x.getBoundingClientRect();
    return r.width > 50 && r.right > 0 && r.left < window.innerWidth;
  });
  if (!v) return null;
  v.muted = true;
  try { await v.play(); } catch (e) {}
  for (let i = 0; i < 40 && !(v.duration > 0 && isFinite(v.duration)); i++)
    await new Promise(r => setTimeout(r, 250));
  return { duration: v.duration, w: v.videoWidth, h: v.videoHeight };
}
"""


# ---------------------------------------------------------------- page helpers
def _check_session(page: Page) -> None:
    if "/accounts/login" in page.url or page.locator('input[name="username"]').count():
        raise GalleryError("Instagram session expired, re-run login_once.py")


def _dismiss_popups(page: Page) -> None:
    for label in POPUP_BUTTONS:
        try:
            btn = page.get_by_role("button", name=label, exact=True)
            if btn.count():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(300)
        except Exception:
            pass


def _wait_for_carousel(page: Page) -> bool:
    try:
        page.wait_for_selector('button[aria-label="Next"]', state="attached", timeout=5000)
        return True
    except PWTimeout:
        return False


def _read_slide(page: Page) -> dict | None:
    """Read the visible slide. A video is mounted a moment after its cover image, so an
    image slide is read twice before it is accepted as an image."""
    s = page.evaluate(_SLIDE_JS)
    if s and not s["video"]:
        page.wait_for_timeout(700)
        s2 = page.evaluate(_SLIDE_JS)
        if s2 and s2["key"] == s["key"]:
            s = s2
    return s


def _next_slide(page: Page, prev_key: str) -> bool:
    nxt = page.locator('button[aria-label="Next"]')
    if nxt.count() == 0:
        return False
    try:
        nxt.first.click(timeout=3000)
    except Exception:
        page.keyboard.press("ArrowRight")  # overlay covers the button
    try:
        page.wait_for_function(_CHANGED_JS, arg=prev_key, timeout=3000)
    except PWTimeout:
        pass
    page.wait_for_timeout(300)
    return True


# ---------------------------------------------------------------- video capture
def _probe(path: Path) -> dict | None:
    """What is inside a downloaded file: video/audio streams, duration, size in pixels."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        d = json.loads(out.stdout or "{}")
    except Exception:
        return None
    streams = d.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        dur = float(d.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        dur = None
    return {
        "video": v is not None,
        "audio": a is not None,
        "duration": dur,
        "pixels": (v.get("width", 0) * v.get("height", 0)) if v else 0,
    }


def _whole_file_url(url: str) -> str:
    """Drop the byte-range parameters, so the whole file is downloaded instead of a piece."""
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k not in ("bytestart", "byteend")]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


def _capture_video(page: Page, ctx: BrowserContext, pending: list, store: dict, used: set, shortcode: str, n: int) -> tuple[str | None, float | None]:
    """Play the visible video slide and save it. Returns (path, duration).
    The player loads videos before their slide is shown, so every file seen so far is kept in `store`
    (url -> (temp file, probe info)) and matched to slides by duration. `used` holds files already given to a slide."""
    info = page.evaluate(_PLAY_JS)
    if not info or not info.get("duration"):
        return None, None
    page.wait_for_timeout(2000)

    tmp = Path(settings.MEDIA_DIR) / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    # download and probe every new file once
    batch = pending[:]
    del pending[:len(batch)]
    for r in batch:
        u = _whole_file_url(r.url)
        if u in store:
            continue
        store[u] = None  # mark as tried, so a failed file is not retried
        try:
            resp = ctx.request.get(u, timeout=60_000)
            if not resp.ok:
                continue
            f = tmp / f"{shortcode}_{len(store)}.mp4"
            f.write_bytes(resp.body())
            meta = _probe(f)
            if meta:
                store[u] = (f, meta)
            else:
                f.unlink(missing_ok=True)
        except Exception:
            continue

    cands = [(u, v[0], v[1]) for u, v in store.items() if v and u not in used]
    want = float(info["duration"])
    match = lambda m: m["duration"] is not None and abs(m["duration"] - want) <= 0.7
    videos = sorted((c for c in cands if c[2]["video"] and match(c[2])), key=lambda c: -c[2]["pixels"])
    audios = [c for c in cands if c[2]["audio"] and not c[2]["video"] and match(c[2])]

    if not videos:
        logger.warning("%s video %d: no captured file matches duration %.1fs (files seen: %s)", shortcode, n, want,
                       [(round(c[2]["duration"] or 0, 1), c[2]["video"], c[2]["audio"]) for c in cands])
        return None, want

    vu, vf, vm = videos[0]
    dest = Path(settings.MEDIA_DIR) / "reels" / f"{shortcode}_v{n}.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if vm["audio"] or not audios:
        shutil.copyfile(vf, dest)
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(vf), "-i", str(audios[0][1]), "-c", "copy", "-shortest", str(dest)],
            capture_output=True, timeout=120,
        )
        if not dest.exists():
            shutil.copyfile(vf, dest)
        used.add(audios[0][0])
    used.add(vu)
    return str(dest), want


# ---------------------------------------------------------------- main
def download_gallery(shortcode: str, url: str) -> dict:
    media = Path(settings.MEDIA_DIR)
    (media / "images").mkdir(parents=True, exist_ok=True)
    for old in (media / "images").glob(f"{shortcode}_*.jpg"):
        old.unlink(missing_ok=True)
    for old in (media / "reels").glob(f"{shortcode}_v*.mp4"):
        old.unlink(missing_ok=True)

    metas: list[dict] = []   # slides in order: {"video": bool, "src": str | None, "path": str | None}
    caption, taken = None, None
    duration = None
    slides: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            storage_state=settings.IG_STORAGE_STATE,
            viewport={"width": 1280, "height": 1800},
        )
        page = ctx.new_page()
        page.set_default_timeout(15_000)

        pending: list = []   # video responses seen by the page; bodies are read later, outside the handler
        store: dict = {}          # every video/audio file seen on the page: url -> (temp file, info)
        used: set[str] = set()    # files already given to a slide
        ctx.route("**/*", lambda route: route.continue_())   # routing turns off the browser cache, so every file is requested
        page.on("response", lambda r: pending.append(r) if "video" in (r.headers.get("content-type") or "") else None)

        try:
            page.goto(url, wait_until="domcontentloaded")
            _check_session(page)
            page.wait_for_selector("article img, main img, article video")
            page.wait_for_load_state("load")
            _dismiss_popups(page)
            _check_session(page)
            is_carousel = _wait_for_carousel(page)

            data = page.evaluate(_COLLECT_JS)
            caption = caption_from_og(data["og"]) or data["caption"]
            taken = data["time"]
            vn = 0

            if is_carousel:
                seen: set[str] = set()
                idle = 0
                for _ in range(MAX_SLIDES):
                    s = _read_slide(page)
                    if s is None:
                        break
                    if s["key"] in seen:
                        idle += 1
                        if idle >= 3:
                            break
                    else:
                        idle = 0
                        seen.add(s["key"])
                        if s["video"]:
                            vn += 1
                            s["path"], dur = _capture_video(page, ctx, pending, store, used, shortcode, vn)
                            duration = duration or dur
                        metas.append(s)
                    if not _next_slide(page, s["key"]):
                        break

            if not metas:
                # single post (or the carousel could not be read)
                if data["hasVideo"]:
                    path, duration = _capture_video(page, ctx, pending, store, used, shortcode, 1)
                    metas = [{"video": True, "src": None, "path": path}]
                elif data["images"]:
                    metas = [{"video": False, "src": data["images"][0], "path": None}]

            if not metas:
                raise GalleryError("no slides found on the page")

            logger.info("%s slides: %s", shortcode, ["video" if m["video"] else "image" for m in metas])

            # save the image slides, keeping their position; video slides already have their file
            n = 0
            for m in metas:
                if m["video"]:
                    if m.get("path"):
                        slides.append({"type": "video", "path": m["path"]})
                    else:
                        logger.warning("%s: a video slide could not be downloaded and was dropped", shortcode)
                    continue
                if not m["src"]:
                    continue
                resp = ctx.request.get(m["src"])
                if not resp.ok:
                    continue
                n += 1
                p = media / "images" / f"{shortcode}_{n}.jpg"
                p.write_bytes(resp.body())
                slides.append({"type": "image", "path": str(p)})
        finally:
            for v in store.values():
                if v:
                    v[0].unlink(missing_ok=True)
            browser.close()

    if not slides:
        raise GalleryError("download failed")

    image_paths = [s["path"] for s in slides if s["type"] == "image"]
    video_paths = [s["path"] for s in slides if s["type"] == "video"]
    media_type = "gallery" if len(slides) > 1 else ("video" if video_paths else "image")

    return {
        "title": None,  # set by the caller from the caption
        "description": caption,
        "timestamp": datetime.fromisoformat(taken.replace("Z", "+00:00")).timestamp() if taken else None,
        "duration": duration,
        "slides": slides,
        "image_paths": image_paths or None,
        "video_paths": video_paths or None,
        "video_path": video_paths[0] if video_paths else None,
        "thumbnail_path": slides[0]["path"] if slides[0]["type"] == "image" else None,
        "media_type": media_type,
    }