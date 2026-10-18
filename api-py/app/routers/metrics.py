"""
GET /v1/metrics — port of metrics.routes.js.

Unauthenticated today (finding D3); preserved for parity, ADMIN-gate it next.

Queue section, same shape as Express's BullMQ getJobCounts() so the dashboard works
unchanged, but sourced from what exists after Step 7:
  * waiting / active / delayed  <- Celery's Redis broker: the queue list, plus the
    `unacked` hash (tasks a worker holds; a future `eta` means a scheduled retry)
  * completed / failed          <- the database: the business outcome of each job
    (refunds SUCCEEDED/FAILED, webhooks DELIVERED/FAILED, recon jobs COMPLETED/FAILED).
    Celery keeps no job history (results are ignored), and BullMQ's counters were only
    ever a proxy for these rows anyway.
  * paused / prioritized / waiting-children: BullMQ-only states, always 0, kept so the
    response shape (a contract) doesn't change.
Steps 4-6 read BullMQ's own keys here instead (and never wrote to them, D11).
"""
import json
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.redis import get_redis
from app.core.serialization import iso_js
from app.db.enums import ReconJobStatus, RefundStatus, WebhookStatus
from app.db.models import GatewayStat, ReconciliationGatewayJob, Refund, WebhookLog

router = APIRouter()

# dashboard name -> (Celery queue, model, completed status, failed status)
QUEUES = {
    "refunds": ("refunds", Refund, RefundStatus.SUCCEEDED, RefundStatus.FAILED),
    "webhooks": ("webhooks", WebhookLog, WebhookStatus.DELIVERED, WebhookStatus.FAILED),
    "reconciliation": ("recon", ReconciliationGatewayJob, ReconJobStatus.COMPLETED, ReconJobStatus.FAILED),
}


def js_to_fixed(value: float, digits: int) -> str:
    """
    Number.prototype.toFixed: rounds the exact binary value, ties go UP.
    Python's format() ties to EVEN, e.g. 1/16*100 = 6.25 -> JS "6.3", Python "6.2".
    """
    return str(Decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def success_rate(success: int, failure: int) -> str:
    total = success + failure
    return js_to_fixed(success / total * 100, 1) + "%" if total > 0 else "n/a"


async def _broker_counts() -> dict[str, dict[str, int]]:
    """waiting/active/delayed per Celery queue, from the Redis broker (read-only)."""
    redis = get_redis()
    names = [q for q, *_ in QUEUES.values()]
    pipe = redis.pipeline(transaction=False)
    for q in names:
        pipe.llen(q)
    pipe.hvals("unacked")
    *lengths, unacked = await pipe.execute()

    out = {q: {"waiting": n or 0, "active": 0, "delayed": 0} for q, n in zip(names, lengths)}
    now = datetime.now(timezone.utc)
    for raw in unacked:
        try:
            message, _exchange, routing_key = json.loads(raw)
            eta = message.get("headers", {}).get("eta")
        except (ValueError, TypeError):
            continue
        if routing_key in out:
            delayed = eta is not None and datetime.fromisoformat(eta) > now
            out[routing_key]["delayed" if delayed else "active"] += 1
    return out


async def _outcome_counts(session: AsyncSession, model, ok, failed) -> tuple[int, int]:
    row = (await session.execute(
        select(func.count().filter(model.status == ok), func.count().filter(model.status == failed))
    )).one()
    return row[0], row[1]


async def queue_counts(session: AsyncSession) -> dict[str, dict[str, int]]:
    broker = await _broker_counts()
    result = {}
    for name, (queue, model, ok, failed) in QUEUES.items():
        completed, failed_n = await _outcome_counts(session, model, ok, failed)
        b = broker[queue]
        result[name] = {"active": b["active"], "completed": completed, "delayed": b["delayed"], "failed": failed_n,
                        "paused": 0, "prioritized": 0, "waiting": b["waiting"], "waiting-children": 0}
    return result


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
            "queues": await queue_counts(session),
        },
    }
