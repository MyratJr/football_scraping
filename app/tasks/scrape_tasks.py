import asyncio
import logging
import random
import time
from pathlib import Path
import requests

from playwright.sync_api import Error as PWError
from yt_dlp.utils import DownloadError

from app.core.config import get_settings
from app.core.container import Container
from app.models.posts import post_url
from app.services.face_filter_service import get_face_filter
from app.tasks.caption import split_caption
from app.tasks.celery_app import celery_app
from app.tasks.gallery_downloader import GalleryError, download_gallery
from app.tasks.instagram_listing import fetch_profile_posts
from app.tasks.video_downloader import download_post


settings = get_settings()
logger = logging.getLogger(__name__)


def _download_cover(shortcode: str, cover_url: str | None) -> str | None:
    """Save the grid cover as media/thumbs/<shortcode>.jpg. These URLs are signed, so use them right away."""
    if not cover_url:
        return None
    try:
        r = requests.get(cover_url, timeout=20)
        r.raise_for_status()
        out = Path(settings.MEDIA_DIR) / "thumbs" / f"{shortcode}.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(r.content)
        return str(out)
    except Exception as exc:
        logger.warning("Cover download failed for %s: %s", shortcode, exc)
        return None


async def _with_container(fn):
    """Fresh container (and DB engine) per call: asyncpg pools are bound to the event loop."""
    container = Container()
    try:
        return await fn(container)
    finally:
        await container.db().close()


def _db(fn):
    return asyncio.run(_with_container(fn))


def _delete_media(info: dict) -> None:
    paths = [info.get("thumbnail_path"), *(info.get("image_paths") or []), *(info.get("video_paths") or [])]
    for p in dict.fromkeys(x for x in paths if x):
        Path(p).unlink(missing_ok=True)


def _scrape_one(shortcode: str, kind: str, alt: str | None, cover_url: str | None = None) -> None:
    """Download one post, run the face filter, save the result. Never raises."""
    url = post_url(shortcode, kind)
    try:
        if kind == "reel":
            info = download_post(shortcode, url)
            info["media_type"] = "video"
        else:
            info = download_gallery(shortcode, url)
    except (DownloadError, GalleryError) as exc:
        logger.warning("Failed %s: %s", shortcode, exc)
        _db(lambda c: c.post_service().mark_failed(shortcode, str(exc)))
        return
    except PWError as exc:
        # connection / browser problem: leave the row pending, the next run tries again
        logger.warning("Browser error on %s, will retry next run: %s", shortcode, exc)
        return
    except Exception:
        logger.exception("Unexpected error on %s, will retry next run", shortcode)
        return


    # a post with videos: one thumbnail, the post's own cover from the profile grid
    if kind == "post" and info.get("video_paths"):
        info["thumbnail_path"] = _download_cover(shortcode, cover_url) or info.get("thumbnail_path")

    # face filter: if he appears, delete the files and keep only a "skipped" row
    if settings.FACE_FILTER_ENABLED:
        try:
            reason = get_face_filter().find_match(info.get("image_paths"), info.get("video_paths"))
        except Exception as exc:
            logger.exception("Face filter failed for %s", shortcode)
            _delete_media(info)
            _db(lambda c: c.post_service().mark_failed(shortcode, f"face filter error: {exc}"))
            return
        if reason:
            logger.info("Skipping %s: %s", shortcode, reason)
            _delete_media(info)
            _db(lambda c: c.post_service().mark_skipped(shortcode, reason))
            return

    title, desc = split_caption(alt)
    if not (title or desc):
        title, desc = split_caption(info.get("description"))
    info["title"], info["description"] = title, desc

    _db(lambda c: c.post_service().mark_done(shortcode, info))
    logger.info("Saved %s (%s)", shortcode, info.get("media_type"))


@celery_app.task(name="tasks.check_new_posts")
def check_new_posts(limit: int = settings.IG_SCRAPE_LIMIT) -> list[str]:
    time.sleep(random.uniform(0, 20))  # jitter
    listed = fetch_profile_posts(limit)  # (shortcode, kind, alt, cover_url), newest first
    alts = {sc: alt for sc, _, alt, _ in listed}
    covers = {sc: cv for sc, _, _, cv in listed}
    items = [(sc, kind) for sc, kind, _, _ in reversed(listed)]  # oldest first

    async def run(c: Container):
        service = c.post_service()
        new = await service.register_new(items)
        pending = await service.list_pending()  # new posts + anything left over from earlier runs
        return new, pending

    new, pending = _db(run)
    logger.info("Found %d new posts, %d pending to scrape", len(new), len(pending))

    for shortcode, kind in pending:
        _scrape_one(shortcode, kind, alts.get(shortcode), covers.get(shortcode))
        time.sleep(random.uniform(2, 5))  # small pause between posts

    return [sc for sc, _ in new]