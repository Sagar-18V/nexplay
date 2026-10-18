"""Synchronous SQLAlchemy session for Celery tasks (same Postgres, same models)."""
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings, to_sync_dsn


@lru_cache
def _sessionmaker() -> sessionmaker[Session]:
    engine = create_engine(
        to_sync_dsn(get_settings().database_url),
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        # Same reason as the async engine: TIMESTAMP WITHOUT TIME ZONE columns hold UTC.
        connect_args={"options": "-c timezone=UTC"},
    )
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope():
    with _sessionmaker()() as session:
        yield session
