"""
Celery port of the reconciliation flow (createReconciliationFlow + gatewayWorker +
runWorker + scheduler).

BullMQ ran this as a FlowProducer: 4 gateway children, then a parent "finalize" job,
with ignoreDependencyOnFailure so one dead gateway can't block the run. Celery's
equivalent (a chord) needs a result backend AND skips its callback when a child fails:
precisely the failure mode the Node design guards against. So instead the database is
the coordinator (the Node runWorker already said "truth comes from the DB"):

  every gateway task, after reaching a terminal state (COMPLETED or FAILED), runs ONE
  conditional UPDATE that finalizes the run only if no job is still non-terminal and the
  run isn't finalized yet. Whichever task finishes last wins; the rest are no-ops.

Scheduling: BullMQ's 2 AM repeatable job was never registered (finding D18), so daily
reconciliation never ran. Celery beat schedules `recon.daily` (see celery_app.py).
"""
import sys
from datetime import date, datetime, timedelta, timezone

from celery import Task
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core.observability import _now_iso, log_json
from app.db.enums import Gateway, ReconJobStatus, TransactionStatus
from app.db.models import (
    ReconciliationDiscrepancy, ReconciliationGatewayJob, ReconciliationRun, Transaction, utcnow_ms,
)
from app.services.reconciliation import Payment, generate_settlement_file, reconcile
from app.worker.celery_app import celery_app
from app.worker.db import session_scope

GATEWAYS = ["RAZORX", "STRIPEIN", "PAYFLOW", "SWIFTPAY"]
MAX_ATTEMPTS = 3
BASE_DELAY_S = 5   # BullMQ: attempts 3, backoff exponential delay 5000 -> 5 s, 10 s


def default_run_date() -> date:
    """Yesterday in UTC, as both the Node trigger route and scheduler compute it."""
    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


def enqueue_gateway_jobs(run_id: str, run_date: date, jobs: list[tuple[str, str]]) -> None:
    for job_id, gateway in jobs:
        reconcile_gateway.apply_async(
            kwargs={"gateway_job_id": job_id, "run_id": run_id, "gateway": gateway, "run_date": run_date.isoformat()},
            queue="recon",
        )


@celery_app.task(name="recon.gateway", bind=True, max_retries=MAX_ATTEMPTS - 1)
def reconcile_gateway(self: Task, gateway_job_id: str, run_id: str, gateway: str, run_date: str) -> str:
    try:
        result = _reconcile(gateway_job_id, gateway, date.fromisoformat(run_date), self.request.retries + 1)
    except Exception as exc:  # noqa: BLE001 - any failure is retried, like a throwing BullMQ processor
        if self.request.retries + 1 >= MAX_ATTEMPTS:
            _mark_failed(gateway_job_id, str(exc))
            _finalize_if_done(run_id)
            return "failed"
        raise self.retry(exc=exc, countdown=BASE_DELAY_S * 2 ** self.request.retries)
    _finalize_if_done(run_id)
    return result


def _reconcile(gateway_job_id: str, gateway: str, run_date: date, attempt: int) -> str:
    day_start = datetime(run_date.year, run_date.month, run_date.day)
    day_end = day_start + timedelta(days=1)
    with session_scope() as session:
        session.execute(update(ReconciliationGatewayJob).where(ReconciliationGatewayJob.id == gateway_job_id)
                        .values(status=ReconJobStatus.RUNNING, started_at=utcnow_ms(), attempts=attempt))
        session.commit()

        rows = session.scalars(
            select(Transaction).where(
                Transaction.gateway == Gateway(gateway),
                Transaction.status.in_([TransactionStatus.SUCCESS, TransactionStatus.FAILED]),
                Transaction.created_at >= day_start, Transaction.created_at < day_end,
            ).order_by(Transaction.created_at.asc(), Transaction.id.asc())
        ).all()
        payments = [Payment(id=t.id, amount=t.amount, status=t.status.value, created_at=t.created_at) for t in rows]

        file = generate_settlement_file(gateway, day_start, payments)   # prod: download from the gateway
        summary, discrepancies = reconcile(payments, file)

        # Summary + findings are one unit. Delete-then-insert keeps retries idempotent.
        session.execute(delete(ReconciliationDiscrepancy).where(ReconciliationDiscrepancy.gateway_job_id == gateway_job_id))
        batch_ts = utcnow_ms()   # createMany -> DEFAULT CURRENT_TIMESTAMP: one value per batch
        session.add_all([ReconciliationDiscrepancy(
            gateway_job_id=gateway_job_id, created_at=batch_ts, type=d["type"], payment_id=d["paymentId"], gateway_txn_ref=d["gatewayTxnRef"],
            our_amount=d["ourAmount"], gateway_amount=d["gatewayAmount"],
            our_status=d["ourStatus"], gateway_status=d["gatewayStatus"]) for d in discrepancies])
        session.execute(update(ReconciliationGatewayJob).where(ReconciliationGatewayJob.id == gateway_job_id).values(
            status=ReconJobStatus.COMPLETED, completed_at=utcnow_ms(),
            total_in_db=summary["totalInDb"], total_in_file=summary["totalInFile"],
            matched_count=summary["matchedCount"], discrepancy_count=summary["discrepancyCount"],
            expected_amount=summary["expectedAmount"], reported_amount=summary["reportedAmount"]))
        session.commit()
        return f"{gateway}: {summary['matchedCount']} matched, {summary['discrepancyCount']} flagged"


def _mark_failed(gateway_job_id: str, reason: str) -> None:
    try:
        with session_scope() as session:
            session.execute(update(ReconciliationGatewayJob).where(ReconciliationGatewayJob.id == gateway_job_id)
                            .values(status=ReconJobStatus.FAILED, error_message=reason, completed_at=utcnow_ms()))
            session.commit()
    except Exception as exc:  # noqa: BLE001 - never crash the worker (D10)
        log_json({"level": "error", "task": "recon.gateway", "gatewayJobId": gateway_job_id,
                  "message": f"could not mark FAILED: {exc}", "timestamp": _now_iso()}, stream=sys.stderr)


# One statement = race-free "last one finalizes". Status rule copied from runWorker.js:
# no failures -> COMPLETED, no successes -> FAILED, otherwise PARTIAL.
_FINALIZE_SQL = text("""
    UPDATE reconciliation_runs r
    SET status = (CASE
            WHEN s.failed = 0    THEN 'COMPLETED'
            WHEN s.completed = 0 THEN 'FAILED'
            ELSE 'PARTIAL' END)::"ReconRunStatus",
        "completedAt" = :now
    FROM (SELECT count(*) FILTER (WHERE status = 'COMPLETED') AS completed,
                 count(*) FILTER (WHERE status = 'FAILED')    AS failed,
                 count(*) FILTER (WHERE status NOT IN ('COMPLETED', 'FAILED')) AS pending
          FROM reconciliation_gateway_jobs WHERE "runId" = :run_id) s
    WHERE r.id = :run_id AND r."completedAt" IS NULL AND s.pending = 0
    RETURNING r.status
""")


def _finalize_if_done(run_id: str) -> None:
    with session_scope() as session:
        status = session.scalar(_FINALIZE_SQL, {"run_id": run_id, "now": utcnow_ms()})
        session.commit()
    if status:
        log_json({"level": "info", "task": "recon.finalize", "runId": run_id, "status": status,
                  "timestamp": _now_iso()})


def create_run_sync(run_date: date) -> ReconciliationRun | None:
    """Same as the API's create path, for beat. None if a run for that date exists."""
    with session_scope() as session:
        run = ReconciliationRun(run_date=run_date,
                                gateway_jobs=[ReconciliationGatewayJob(gateway=Gateway(g)) for g in GATEWAYS])
        session.add(run)
        try:
            session.commit()
        except IntegrityError:   # @@unique([runDate]): double-scheduling is a no-op
            session.rollback()
            return None
        enqueue_gateway_jobs(run.id, run_date, [(j.id, j.gateway.value) for j in run.gateway_jobs])
        return run


@celery_app.task(name="recon.daily")
def daily_reconciliation() -> str:
    run_date = default_run_date()
    run = create_run_sync(run_date)
    return f"started {run.id} for {run_date}" if run else f"run for {run_date} already exists"
