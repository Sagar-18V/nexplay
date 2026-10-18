"""
GET /v1/reconciliation/runs[/:id] — read half of reconciliation.routes.js.
Platform-wide on purpose (recon is gateway-level truth): any authenticated merchant
can read it today. Preserved for parity; worth an ADMIN check later (see D3-style note).
POST /runs/trigger creates a BullMQ flow, so it moves in Step 6.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_session
from app.core.http import RawError
from app.core.security import CurrentMerchant, authenticate
from app.core.serialization import to_json
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
        jobs = sorted(run.gateway_jobs, key=lambda j: j.id)  # stable order (Prisma: PK order)
        data.append({**to_json(run), "gatewayJobs": [to_json(j) for j in jobs]})
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
    for job in sorted(run.gateway_jobs, key=lambda j: j.id):
        discrepancies = sorted(job.discrepancies, key=_newest_first)
        jobs.append({**to_json(job), "discrepancies": [to_json(d) for d in discrepancies]})
    return {"success": True, "data": {**to_json(run), "gatewayJobs": jobs}}


def _newest_first(d: ReconciliationDiscrepancy):
    # orderBy: { createdAt: 'desc' }; id breaks ties so output is deterministic.
    return (-d.created_at.timestamp(), d.id)
