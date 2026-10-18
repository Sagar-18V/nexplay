"""
GET /v1/reconciliation/runs[/:id] — read half of reconciliation.routes.js.
Platform-wide on purpose (recon is gateway-level truth): any authenticated merchant
can read it today. Preserved for parity; worth an ADMIN check later (see D3-style note).
POST /runs/trigger moved in Step 6: it creates the run and enqueues four Celery tasks
(app/worker/recon_tasks.py) in place of the BullMQ flow.
"""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.core.db import get_session
from app.core.errors import AppError
from app.core.http import RawError, js_truthy, json_body
from app.core.security import CurrentMerchant, authenticate
from app.core.serialization import to_json
from app.db.enums import Gateway
from app.db.models import ReconciliationDiscrepancy, ReconciliationGatewayJob, ReconciliationRun

router = APIRouter(prefix="/v1/reconciliation")


@router.get("/runs")
async def list_runs(_: CurrentMerchant = Depends(authenticate), session: AsyncSession = Depends(get_session)):
    runs = await session.scalars(
        select(ReconciliationRun)
        .options(selectinload(ReconciliationRun.gateway_jobs))
        .order_by(ReconciliationRun.run_date.desc())
        .limit(30)
    )
    data = []
    for run in runs:
        # Prisma's `include: { gatewayJobs: true }` has no ORDER BY, so rows come back in the
        # database's order. selectinload runs the same unordered query; don't re-sort (an
        # earlier id sort diverged from Express once runs had random UUIDs: shadow_diff caught it).
        data.append({**to_json(run), "gatewayJobs": [to_json(j) for j in run.gateway_jobs]})
    return {"success": True, "data": data}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    _: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    run = await session.scalar(
        select(ReconciliationRun)
        .where(ReconciliationRun.id == run_id)
        .options(
            selectinload(ReconciliationRun.gateway_jobs)
            .selectinload(ReconciliationGatewayJob.discrepancies)
        )
    )
    if run is None:
        raise RawError(404, "Run not found")  # hand-written in Express: no requestId

    jobs = []
    for job in run.gateway_jobs:                                     # DB order, as above
        discrepancies = sorted(job.discrepancies, key=_newest_first)  # stable: ties keep DB order
        jobs.append({**to_json(job), "discrepancies": [to_json(d) for d in discrepancies]})
    return {"success": True, "data": {**to_json(run), "gatewayJobs": jobs}}


def _newest_first(d: ReconciliationDiscrepancy):
    # orderBy: { createdAt: 'desc' } only. A batch shares one createdAt, so ties are the
    # norm; Python's sort is stable, leaving them in database order exactly like Postgres
    # returns them to Prisma. (No id tie-break: Express doesn't have one.)
    return -d.created_at.timestamp()


def _parse_run_date(raw) -> date:
    """
    Express: `new Date(req.body.runDate)`, and an unparseable value throws a RangeError ->
    500 (D1 class). We accept ISO 8601 dates/datetimes and take the UTC calendar date,
    which is what Prisma stores into the @db.Date column. Anything else -> 400.
    """
    if not isinstance(raw, str):
        raise AppError("runDate must be an ISO 8601 date (YYYY-MM-DD)", 400)
    try:
        if len(raw) == 10:
            return date.fromisoformat(raw)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise AppError("runDate must be an ISO 8601 date (YYYY-MM-DD)", 400) from None
    return (parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed).date()


@router.post("/runs/trigger")
async def trigger_run(
    request: Request,
    _: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    from app.worker.recon_tasks import GATEWAYS, default_run_date, enqueue_gateway_jobs

    body = await json_body(request)
    run_date = _parse_run_date(body["runDate"]) if js_truthy(body.get("runDate")) else default_run_date()

    run = ReconciliationRun(run_date=run_date,
                            gateway_jobs=[ReconciliationGatewayJob(gateway=Gateway(g)) for g in GATEWAYS])
    session.add(run)
    try:
        await session.commit()
    except IntegrityError:                    # @@unique([runDate])
        await session.rollback()
        raise RawError(409, "Run already exists for this date") from None

    jobs = list(run.gateway_jobs)
    await run_in_threadpool(enqueue_gateway_jobs, run.id, run_date, [(j.id, j.gateway.value) for j in jobs])
    return JSONResponse({"success": True, "data": {**to_json(run), "gatewayJobs": [to_json(j) for j in jobs]}},
                        status_code=202)
