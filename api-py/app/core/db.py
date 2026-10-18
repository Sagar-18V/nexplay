"""
Async SQLAlchemy engine against the SAME Postgres database Express uses.

Ownership rule during the migration: Prisma migrations remain the single source
of truth for the schema. FastAPI never runs DDL — it only reads/writes rows.
(Alembic takes over schema ownership at the very end, once Node is retired.)
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings, to_async_dsn

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    dsn, connect_args = to_async_dsn(get_settings().database_url)
    _engine = create_async_engine(
        dsn,
        connect_args=connect_args,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("DB engine not initialised")
    return _engine


async def dispose_engine() -> None:
    if _engine is not None:
        await _engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    if _sessionmaker is None:
        raise RuntimeError("DB engine not initialised")
    async with _sessionmaker() as session:
        yield session
