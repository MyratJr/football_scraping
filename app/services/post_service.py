from __future__ import annotations  # the method named `list` would otherwise hide the built-in in annotations

from datetime import datetime, timezone

from app.models.posts import Post
from app.repositories.post_repository import PostRepository


class PostService:
    def __init__(self, post_repository: PostRepository):
        self._repo = post_repository

    async def register_new(self, items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return await self._repo.insert_new_pending(items)

    async def list_pending(self) -> list[tuple[str, str]]:
        return await self._repo.list_pending()

    async def mark_done(self, shortcode: str, info: dict) -> None:
        ts = info.get("timestamp")
        await self._repo.update_by_shortcode(
            shortcode,
            status="done",
            title=info.get("title"),
            caption=info.get("description"),
            title_tk=info.get("title_tk"),
            caption_tk=info.get("caption_tk"),
            video_path=info.get("video_path"),
            thumbnail_path=info.get("thumbnail_path"),
            slides=info.get("slides"),
            image_paths=info.get("image_paths"),
            video_paths=info.get("video_paths"),
            media_type=info.get("media_type"),
            duration=info.get("duration"),
            posted_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None,
            error=None,
        )

    async def mark_failed(self, shortcode: str, error: str) -> None:
        await self._repo.update_by_shortcode(shortcode, status="failed", error=error[:2000])

    async def mark_skipped(self, shortcode: str, reason: str) -> None:
        await self._repo.update_by_shortcode(shortcode, status="skipped", error=reason[:2000])

    async def get(self, shortcode: str) -> Post | None:
        return await self._repo.get_by_shortcode(shortcode)

    async def list(self, limit: int, offset: int) -> list[Post]:
        return await self._repo.list_posts(limit, offset)

    async def list_untranslated(self, limit: int = 5) -> list[tuple[str, str | None, str | None]]:
        return await self._repo.list_untranslated(limit)

    async def save_translation(self, shortcode: str, title_tk: str | None, caption_tk: str | None) -> None:
        await self._repo.update_by_shortcode(shortcode, title_tk=title_tk, caption_tk=caption_tk)

    async def mark_translation_failed(self, shortcode: str) -> None:
        await self._repo.update_by_shortcode(shortcode, tk_attempts=Post.tk_attempts + 1)