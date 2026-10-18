"""
Celery port of modules/refunds/refund.worker.js.

Contract kept from Node:
  * idempotent re-entry: a SUCCEEDED/FAILED refund is never sent to the gateway again
  * retryable gateway failure -> retry, 3 attempts total, backoff 3 s then 6 s
  * terminal rejection, or retries exhausted -> FAILED with failureReason
  * success is ONE transaction: refund SUCCEEDED + two reversal ledger rows (balanced)
    + transactions.refundedAmount += amount + intent REFUNDED / PARTIALLY_REFUNDED

Added: a Postgres advisory lock per refund. Celery is at-least-once (acks_late), so the
same task can run twice at the same moment (worker restart, visibility timeout). The
lock makes the second copy back off, so a refund can't be sent to the gateway twice.
"""
import sys

from celery import Task
from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload

from app.core.observability import _now_iso, log_json
from app.db.enums import LedgerAccount, LedgerEntryType, PaymentStatus, RefundStatus
from app.db.models import LedgerEntry, PaymentIntent, Refund, Transaction, utcnow_ms
from app.services.gateways import process_refund
from app.services.ledger import assert_balanced
from app.worker.celery_app import celery_app
from app.worker.db import session_scope

MAX_ATTEMPTS = 3
BASE_DELAY_S = 3


class RetryableRefundError(Exception):
    pass


@celery_app.task(name="refunds.process", bind=True, max_retries=MAX_ATTEMPTS - 1)
def process_refund_task(self: Task, refund_id: str) -> str:
    try:
        return _process(refund_id)
    except RetryableRefundError as exc:
        if self.request.retries + 1 >= MAX_ATTEMPTS:
            _mark_failed(refund_id, str(exc))
            return "failed"
        raise self.retry(exc=exc, countdown=BASE_DELAY_S * 2 ** self.request.retries)  # 3 s, 6 s


def _process(refund_id: str) -> str:
    with session_scope() as session:
        # Session-level advisory lock keyed on the refund id; released in `finally`.
        locked = session.scalar(select(func.pg_try_advisory_lock(func.hashtext(refund_id))))
        if not locked:
            return "in-progress-elsewhere"
        try:
            return _process_locked(session, refund_id)
        finally:
            session.rollback()  # end any open transaction before unlocking on this connection
            session.execute(select(func.pg_advisory_unlock(func.hashtext(refund_id))))
            session.commit()


def _process_locked(session, refund_id: str) -> str:
    refund = session.scalar(select(Refund).where(Refund.id == refund_id).options(joinedload(Refund.transaction)))
    if refund is None:
        log_json({"level": "warn", "task": "refunds.process", "refundId": refund_id,
                  "message": "refund not found; dropping", "timestamp": _now_iso()}, stream=sys.stderr)
        return "missing"
    if refund.status in (RefundStatus.SUCCEEDED, RefundStatus.FAILED):
        return "already-terminal"   # never re-hit the gateway

    refund.status = RefundStatus.PROCESSING
    refund.attempts += 1
    session.commit()

    txn = refund.transaction
    result = process_refund(txn.gateway.value, refund.amount)
    if not result.success:
        if result.retryable:
            raise RetryableRefundError(result.error)
        refund.status = RefundStatus.FAILED
        refund.failure_reason = result.error
        refund.processed_at = utcnow_ms()
        session.commit()
        return "rejected"

    # ---- success: everything below commits together or not at all
    refund.status = RefundStatus.SUCCEEDED
    refund.gateway_refund_ref = result.gateway_refund_ref
    refund.processed_at = utcnow_ms()

    # Mirror of the capture entries, directions flipped. Append-only.
    reversal = [
        LedgerEntry(txn_id=txn.id, refund_id=refund.id, entry_type=LedgerEntryType.DEBIT,
                    account=LedgerAccount.MERCHANT_PAYABLE, amount=refund.amount),
        LedgerEntry(txn_id=txn.id, refund_id=refund.id, entry_type=LedgerEntryType.CREDIT,
                    account=LedgerAccount.CUSTOMER_RECEIVABLE, amount=refund.amount),
    ]
    assert_balanced(reversal)
    session.add_all(reversal)

    # Atomic increment in SQL (not read-modify-write), then derive the intent status.
    refunded, captured = session.execute(
        update(Transaction).where(Transaction.id == txn.id)
        .values(refunded_amount=Transaction.refunded_amount + refund.amount)
        .returning(Transaction.refunded_amount, Transaction.amount)
    ).one()
    session.execute(
        update(PaymentIntent).where(PaymentIntent.id == txn.intent_id).values(
            status=PaymentStatus.REFUNDED if refunded >= captured else PaymentStatus.PARTIALLY_REFUNDED,
            updated_at=utcnow_ms())
    )
    session.commit()
    return "succeeded"


def _mark_failed(refund_id: str, reason: str) -> None:
    try:
        with session_scope() as session:
            session.execute(
                update(Refund)
                .where(Refund.id == refund_id, Refund.status.notin_([RefundStatus.SUCCEEDED, RefundStatus.FAILED]))
                .values(status=RefundStatus.FAILED, failure_reason=reason, processed_at=utcnow_ms())
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001 - never crash the worker (D10)
        log_json({"level": "error", "task": "refunds.process", "refundId": refund_id,
                  "message": f"could not mark FAILED: {exc}", "timestamp": _now_iso()}, stream=sys.stderr)

