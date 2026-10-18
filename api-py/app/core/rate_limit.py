"""
Port of middleware/rateLimiter.js — sliding-window log in a Redis sorted set.

The Redis keys are IDENTICAL to Express's (`ratelimit:<tier>:<merchantId>`), so while
both services are live a merchant has ONE budget, not one per backend. Otherwise
splitting traffic across two services would silently double everyone's limit.
"""
import math
import random
import time

from fastapi import Depends, Request

from app.core.http import RawError
from app.core.redis import get_redis
from app.core.security import CurrentMerchant, authenticate

TIERS = {
    "write": {"limit": 30, "window_ms": 60_000},
    "read": {"limit": 120, "window_ms": 60_000},
    "auth": {"limit": 10, "window_ms": 60_000},
}


def rate_limit(tier: str = "read"):
    cfg = TIERS[tier]
    limit, window_ms = cfg["limit"], cfg["window_ms"]
    window_s = math.ceil(window_ms / 1000)

    async def _dep(request: Request, merchant: CurrentMerchant = Depends(authenticate)) -> None:
        # Runs after authenticate, exactly like `authenticate, rateLimit('read')` in Express.
        key = f"ratelimit:{tier}:{merchant.id}"
        now = int(time.time() * 1000)

        pipe = get_redis().pipeline(transaction=False)
        pipe.zremrangebyscore(key, 0, now - window_ms)
        pipe.zadd(key, {f"{now}-{random.random()}": now})
        pipe.zcard(key)
        pipe.expire(key, window_s)
        count = (await pipe.execute())[2]

        headers = request.state.response_headers
        headers["X-RateLimit-Limit"] = str(limit)
        headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        if count > limit:
            headers["Retry-After"] = str(window_s)
            raise RawError(429, "Rate limit exceeded")

    return _dep
