from datetime import datetime, timezone, timedelta
from typing import Any
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select, update

from app.models.posts import Post
from app.repositories.base import Repository
from app.models.posts import post_url


class PostRepository(Repository):

    async def insert_new_pending(self, items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Insert unseen (shortcode, kind) pairs; returns only the new ones."""
        if not items:
            return []
        now = datetime.now(timezone.utc)
        rows = [
            {"shortcode": sc, "kind": kind, "status": "pending", "url": post_url(sc, kind),
             "created_at": now, "updated_at": now}
            for sc, kind in items
        ]
        stmt = (
            pg_insert(Post).values(rows)
            .on_conflict_do_nothing(index_elements=["shortcode"])
            .returning(Post.shortcode, Post.kind)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            new = [(r[0], r[1]) for r in result.all()]
            await session.commit()
        return new

    async def list_pending(self) -> list[tuple[str, str]]:
        async with self._session_factory() as session:
            res = await session.exec(
                select(Post.shortcode, Post.kind).where(Post.status == "pending").order_by(Post.id)
            )
            return [(r[0], r[1]) for r in res.all()]

    async def update_by_shortcode(self, shortcode: str, **values: Any) -> None:
        values["updated_at"] = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            await session.exec(update(Post).where(Post.shortcode == shortcode).values(**values))
            await session.commit()

    async def get_by_shortcode(self, shortcode: str) -> Post | None:
        async with self._session_factory() as session:
            res = await session.exec(select(Post).where(Post.shortcode == shortcode))
            return res.first()

    async def list_posts(self, limit: int = 20, offset: int = 0) -> list[Post]:
        async with self._session_factory() as session:
            res = await session.exec(
                select(Post)
                .where(Post.status == "done")
                .order_by(Post.posted_at.desc().nullslast(), Post.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(res.all())
