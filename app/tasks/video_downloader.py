import os
from pathlib import Path

from yt_dlp import YoutubeDL

from app.core.config import get_settings

settings = get_settings()


def _rel(fp: str) -> str:
    """Relative to the project folder, like every other stored path."""
    try:
        return os.path.relpath(fp)
    except ValueError:  # different drive: keep as is
        return fp

def _run(url: str, thumbs: bool) -> tuple[dict, list[str]]:
    media = Path(settings.MEDIA_DIR)
    (media / "reels").mkdir(parents=True, exist_ok=True)
    (media / "thumbs").mkdir(parents=True, exist_ok=True)

    opts = {
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": {
            "default": str(media / "reels" / "%(id)s.%(ext)s"),
            "thumbnail": str(media / "thumbs" / "%(id)s.%(ext)s"),
        },
        "writethumbnail": thumbs,
        "cookiefile": settings.IG_COOKIES_TXT,
        "quiet": True,
        "noprogress": True,
        "retries": 3,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # a carousel comes back as a playlist with one entry per video slide
    entries = [e for e in (info.get("entries") or [info]) if e]
    paths: list[str] = []
    for e in entries:
        for d in e.get("requested_downloads") or []:
            fp = d.get("filepath")
            if fp and Path(fp).exists() and _rel(fp) not in paths:
                paths.append(_rel(fp))  # real merged file, stored relative to the project
    return info, paths


def download_videos(url: str, thumbs: bool = False) -> dict:
    """All videos of a post (reel, single video or carousel)."""
    info, paths = _run(url, thumbs)
    first = next((e for e in (info.get("entries") or [info]) if e), info)
    thumb = None
    if thumbs and first.get("id"):
        thumb = next((str(p) for p in (Path(settings.MEDIA_DIR) / "thumbs").glob(f"{first['id']}.*")), None)
    return {
        "video_paths": paths,
        "duration": first.get("duration"),
        "thumbnail_path": thumb,
        "title": info.get("title"),
        "description": info.get("description"),
        "timestamp": info.get("timestamp"),
    }


def download_post(shortcode: str, url: str) -> dict:
    """Reel: same return shape as before, plus video_paths."""
    v = download_videos(url, thumbs=True)
    return {**v, "video_path": v["video_paths"][0] if v["video_paths"] else None}