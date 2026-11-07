import json
import logging
from typing import Any, AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession  # SQLModel's AsyncSession adds .exec()

logger = logging.getLogger(__name__)


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


class Database:

    def __init__(
        self,
        db_url: str,
        *,
        echo: bool = False,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: int = 30,              # seconds to wait for a free connection
        pool_recycle: int = 1800,            # recycle connections every 30 min (proxies/firewalls)
        connect_timeout: int = 10,           # seconds to establish a connection
        statement_timeout_ms: int = 30_000,  # kill runaway queries server-side
        app_name: str = "football-api",
    ) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url=db_url,
            echo=echo,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            json_serializer=_json_dumps,
            json_deserializer=json.loads,
            connect_args={
                "timeout": connect_timeout,
                "server_settings": {
                    "application_name": app_name,
                    "timezone": "UTC",
                    "statement_timeout": str(statement_timeout_ms),
                },
            },
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,  # objects stay usable after commit (needed for response models)
            autoflush=False,         # flush explicitly in repositories
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Request-scoped session: commit on success, rollback on error."""
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def ping(self) -> bool:
        """For /health endpoints and startup checks."""
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("Database ping failed")
            return False

    async def close(self) -> None:
        await self._engine.dispose()
        logger.info("Database engine disposed")