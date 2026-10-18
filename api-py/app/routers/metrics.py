"""
GET /v1/metrics — port of metrics.routes.js.

Unauthenticated today (finding D3); preserved for parity, ADMIN-gate it after cutover.

Queue counts are read straight from BullMQ's Redis keys, because the queues are still
owned by Node until Step 6. This mirrors BullMQ 5.x Queue#getJobCounts() exactly,
EXCEPT one thing: BullMQ's getCounts.lua RPOPs a deprecated "0:" marker off the wait
list while counting. We apply the same correction to the number but never write:
a migrated read endpoint must not mutate queues another service owns.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.redis import get_redis
from app.core.serialization import iso_js
from app.db.models import GatewayStat

router = APIRouter()

BULL_PREFIX = "bull"
# Queue#getJobCounts() with no args -> this list, in this order (sanitizeJobTypes).
JOB_TYPES = ["active", "completed", "delayed", "failed", "paused", "prioritized", "waiting", "waiting-children"]
LIST_TYPES = {"wait", "paused", "active"}
QUEUES = {"refunds": "refunds", "webhooks": "webhooks", "reconciliation": "recon-gateway"}


def js_to_fixed(value: float, digits: int) -> str:
    """
    Number.prototype.toFixed: rounds the exact binary value, ties go UP.
    Python's format() ties to EVEN, e.g. 1/16*100 = 6.25 -> JS "6.3", Python "6.2".
    """
    return str(Decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def success_rate(success: int, failure: int) -> str:
    total = success + failure
    return js_to_fixed(success / total * 100, 1) + "%" if total > 0 else "n/a"


async def job_counts(queue: str) -> dict[str, int]:
    base = f"{BULL_PREFIX}:{queue}:"
    redis_types = ["wait" if t == "waiting" else t for t in JOB_TYPES]  # getCountsArgs

    pipe = get_redis().pipeline(transaction=False)
    for t in redis_types:
        if t in LIST_TYPES:
            pipe.llen(base + t)
            pipe.lindex(base + t, -1)
        else:
            pipe.zcard(base + t)
    results = iter(await pipe.execute())

    counts: dict[str, int] = {}
    for name, t in zip(JOB_TYPES, redis_types):
        count = next(results)
        if t in LIST_TYPES:
            tail = next(results)
            if t != "active" and tail is not None and str(tail).startswith("0:"):
                count = count - 1 if count > 1 else 0  # marker, not a job
        counts[name] = count or 0
    return counts


@router.get("/v1/metrics")
@router.get("/v1/metrics/", include_in_schema=False)  # Express routes match with or without slash
async def metrics(session: AsyncSession = Depends(get_session)):
    stats = await session.scalars(select(GatewayStat))  # findMany() with no orderBy: same SQL
    gateways = [{
        "gateway": g.gateway.value,
        "method": g.method.value,
        "successCount": g.success_count,
        "failureCount": g.failure_count,
        "successRate": success_rate(g.success_count, g.failure_count),
        "avgLatencyMs": g.avg_latency_ms,
    } for g in stats]

    return {
        "success": True,
        "data": {
            "timestamp": iso_js(datetime.now(timezone.utc).replace(tzinfo=None)),
            "gateways": gateways,
            "queues": {name: await job_counts(q) for name, q in QUEUES.items()},
        },
    }
