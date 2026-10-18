"""
GET /v1/health — the first route owned by FastAPI.

Express never had this route (docker-compose's healthcheck was curling a 404),
so it's a zero-risk first cutover that still exercises the whole path:
gateway -> FastAPI -> Postgres + Redis.
"""
import asyncio
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import get_engine
from app.core.redis import get_redis

router = APIRouter()

CHECK_TIMEOUT_S = 2.0


async def check_postgres() -> dict:
    start = time.perf_counter()
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "up", "latencyMs": round((time.perf_counter() - start) * 1000)}


async def check_redis() -> dict:
    start = time.perf_counter()
    await get_redis().ping()
    return {"status": "up", "latencyMs": round((time.perf_counter() - start) * 1000)}


async def _run(check) -> dict:
    try:
        return await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_S)
    except Exception as exc:  # report, don't raise — health must always answer
        return {"status": "down", "error": type(exc).__name__}


@router.get("/v1/health")
async def health():
    postgres, redis = await asyncio.gather(_run(check_postgres), _run(check_redis))
    healthy = postgres["status"] == "up" and redis["status"] == "up"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "success": healthy,
            "data": {
                "service": "nexpay-api-py",
                "status": "ok" if healthy else "degraded",
                "checks": {"postgres": postgres, "redis": redis},
            },
        },
    )
