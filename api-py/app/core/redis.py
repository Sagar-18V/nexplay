"""Shared async Redis client — same Redis instance as Express/BullMQ."""
from redis.asyncio import Redis

from app.core.config import get_settings

_redis: Redis | None = None


def init_redis() -> Redis:
    global _redis
    _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised")
    return _redis


async def close_redis() -> None:
    if _redis is not None:
        await _redis.aclose()
