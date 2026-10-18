"""
Deterministic dataset for contract tests: fixed ids, fixed timestamps, every status
and every tricky type (BigInt > 2^53, @db.Date, JSONB, nullable FKs, cross-tenant rows).

Because the data is fixed, golden snapshots can hold exact values — any difference
between Express and FastAPI is a real behavioural difference, not noise.

It also proves the SQLAlchemy models can WRITE rows the Prisma-owned schema accepts,
and that Python bcrypt hashes verify in Node's bcryptjs (the logins go through Express).

    python -m tests.contract.seed      # uses CONTRACT_DATABASE_URL / CONTRACT_REDIS_URL
"""
import os
from datetime import date, datetime, timedelta

import bcrypt
import redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.enums import (
    DiscrepancyStatus as DS, DiscrepancyType as DT, Gateway as G, LedgerAccount as LA,
    LedgerEntryType as LE, PaymentMethod as PM, PaymentStatus as PS, ReconJobStatus as RJ,
    ReconRunStatus as RR, RefundStatus as RS, Role, TransactionStatus as TS, WebhookStatus as WS,
)
from app.db.models import (
    Base, GatewayStat, LedgerEntry, Merchant, PaymentIntent, ReconciliationDiscrepancy,
    ReconciliationGatewayJob, ReconciliationRun, Refund, Transaction, WebhookLog,
)

PASSWORD = "password123"
T0 = datetime(2026, 9, 1, 9, 0, 0)


def sid(n: int) -> str:
    """Readable fixed UUIDs: 00000000-0000-4000-8000-000000000001 ..."""
    return f"00000000-0000-4000-8000-{n:012d}"


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


ALPHA, BETA, ADMIN = sid(1), sid(2), sid(3)
SEED_EMAILS = {"alpha@nexpay.test", "beta@nexpay.test", "admin@nexpay.test"}


def _guard(url: str) -> None:
    """Refuse to wipe anything that might be a real database."""
    if os.getenv("CONTRACT_ALLOW_RESET") != "1":
        raise SystemExit("Refusing to reset DB: set CONTRACT_ALLOW_RESET=1 (test databases only).")
    if any(host in url for host in ("neon.tech", "upstash.io", "amazonaws.com")):
        raise SystemExit(f"Refusing to reset a hosted database: {url.split('@')[-1]}")


def build() -> list:
    pw = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=10)).decode()
    rows: list = [
        Merchant(id=ALPHA, name="Alpha Store", email="alpha@nexpay.test", password=pw,
                 role=Role.MERCHANT, api_key=sid(101), webhook_url="https://alpha.test/hook",
                 created_at=at(0)),
        Merchant(id=BETA, name="Beta Mart", email="beta@nexpay.test", password=pw,
                 role=Role.MERCHANT, api_key=sid(102), created_at=at(1)),
        Merchant(id=ADMIN, name="Ops Admin", email="admin@nexpay.test", password=pw,
                 role=Role.ADMIN, api_key=sid(103), created_at=at(2)),
    ]

    # --- Alpha: one intent per interesting status ---------------------------------
    rows += [
        # i11: fallback happened (RAZORX failed -> STRIPEIN succeeded), then partially refunded
        PaymentIntent(id=sid(11), merchant_id=ALPHA, amount=50_000, method=PM.UPI,
                      status=PS.PARTIALLY_REFUNDED, idempotency_key="seed-i11",
                      metadata_={"orderId": "ORD-11", "items": [1, 2]},
                      created_at=at(10), updated_at=at(15)),
        Transaction(id=sid(21), intent_id=sid(11), gateway=G.RAZORX, amount=50_000, status=TS.FAILED,
                    latency_ms=812, failure_reason="GATEWAY_TIMEOUT", created_at=at(11)),
        Transaction(id=sid(22), intent_id=sid(11), gateway=G.STRIPEIN, amount=50_000, status=TS.SUCCESS,
                    gateway_txn_id="stp_seed_22", latency_ms=143, fee_amount=1_000,
                    refunded_amount=10_000, created_at=at(12)),
        # i12: created, never processed
        PaymentIntent(id=sid(12), merchant_id=ALPHA, amount=25_000, method=PM.CARD,
                      status=PS.CREATED, idempotency_key="seed-i12", metadata_=None,
                      created_at=at(20), updated_at=at(20)),
        Transaction(id=sid(23), intent_id=sid(12), gateway=G.PAYFLOW, amount=25_000,
                    status=TS.PENDING, created_at=at(20)),
        # i13: failed everywhere
        PaymentIntent(id=sid(13), merchant_id=ALPHA, amount=9_900, method=PM.NET_BANKING,
                      status=PS.FAILED, idempotency_key="seed-i13",
                      created_at=at(30), updated_at=at(31)),
        Transaction(id=sid(24), intent_id=sid(13), gateway=G.SWIFTPAY, amount=9_900, status=TS.FAILED,
                    latency_ms=2_004, failure_reason="INSUFFICIENT_FUNDS", created_at=at(31)),
        # --- Beta: must never be visible to Alpha -------------------------------------
        PaymentIntent(id=sid(14), merchant_id=BETA, amount=77_700, method=PM.WALLET,
                      status=PS.CREATED, idempotency_key="seed-i14",
                      created_at=at(40), updated_at=at(40)),
        Transaction(id=sid(25), intent_id=sid(14), gateway=G.RAZORX, amount=77_700,
                    status=TS.PENDING, created_at=at(40)),
    ]

    # --- Refunds --------------------------------------------------------------------
    rows += [
        Refund(id=sid(31), transaction_id=sid(22), merchant_id=ALPHA, amount=10_000, status=RS.SUCCEEDED,
               reason="customer_request", gateway_refund_ref="rf_seed_31", attempts=1,
               idempotency_key="seed-r31", created_at=at(13), processed_at=at(14)),
        Refund(id=sid(32), transaction_id=sid(22), merchant_id=ALPHA, amount=5_000, status=RS.FAILED,
               failure_reason="GATEWAY_REJECTED", attempts=3,
               idempotency_key="seed-r32", created_at=at(16)),
        Refund(id=sid(33), transaction_id=sid(25), merchant_id=BETA, amount=700, status=RS.PENDING,
               idempotency_key="seed-r33", created_at=at(41)),
    ]

    # --- Double-entry ledger for the capture + the refund reversal -------------------
    rows += [
        LedgerEntry(id=sid(41), txn_id=sid(22), entry_type=LE.DEBIT, account=LA.CUSTOMER_RECEIVABLE,
                    amount=50_000, created_at=at(12)),
        LedgerEntry(id=sid(42), txn_id=sid(22), entry_type=LE.CREDIT, account=LA.MERCHANT_PAYABLE,
                    amount=49_000, created_at=at(12)),
        LedgerEntry(id=sid(43), txn_id=sid(22), entry_type=LE.CREDIT, account=LA.PLATFORM_REVENUE,
                    amount=1_000, created_at=at(12)),
        LedgerEntry(id=sid(44), txn_id=sid(22), refund_id=sid(31), entry_type=LE.DEBIT,
                    account=LA.MERCHANT_PAYABLE, amount=10_000, created_at=at(14)),
        LedgerEntry(id=sid(45), txn_id=sid(22), refund_id=sid(31), entry_type=LE.CREDIT,
                    account=LA.CUSTOMER_RECEIVABLE, amount=10_000, created_at=at(14)),
    ]

    # --- Webhooks ---------------------------------------------------------------------
    rows += [
        WebhookLog(id=sid(51), merchant_id=ALPHA, event="payment.failed",
                   payload={"intent_id": sid(13), "reason": "INSUFFICIENT_FUNDS"}, attempts=3,
                   last_attempted_at=at(35), status=WS.FAILED, created_at=at(32)),
        WebhookLog(id=sid(52), merchant_id=ALPHA, event="payment.success",
                   payload={"intent_id": sid(11)}, attempts=1, last_attempted_at=at(13),
                   delivered_at=at(13), status=WS.DELIVERED, created_at=at(13)),
        WebhookLog(id=sid(53), merchant_id=BETA, event="payment.failed",
                   payload={"intent_id": sid(14)}, attempts=3, status=WS.FAILED, created_at=at(42)),
    ]

    # --- Reconciliation (platform-wide), incl. BigInt beyond JS safe-integer range ---
    rows += [
        ReconciliationRun(id=sid(61), run_date=date(2026, 9, 1), status=RR.PARTIAL,
                          started_at=at(1_000), completed_at=at(1_005)),
        ReconciliationGatewayJob(id=sid(71), run_id=sid(61), gateway=G.RAZORX, status=RJ.COMPLETED,
                                 attempts=1, total_in_db=2, total_in_file=2, matched_count=0,
                                 discrepancy_count=2, expected_amount=9_007_199_254_740_993,
                                 reported_amount=9_007_199_254_740_000,
                                 started_at=at(1_000), completed_at=at(1_002)),
        ReconciliationGatewayJob(id=sid(72), run_id=sid(61), gateway=G.STRIPEIN, status=RJ.FAILED,
                                 attempts=3, error_message="settlement file not found",
                                 started_at=at(1_000), completed_at=at(1_005)),
        ReconciliationDiscrepancy(id=sid(81), gateway_job_id=sid(71), type=DT.AMOUNT_MISMATCH,
                                  status=DS.OPEN, payment_id=sid(22), gateway_txn_ref="rzx_81",
                                  our_amount=9_007_199_254_740_993, gateway_amount=9_007_199_254_740_000,
                                  our_status="SUCCESS", gateway_status="SUCCESS", created_at=at(1_001)),
        ReconciliationDiscrepancy(id=sid(82), gateway_job_id=sid(71), type=DT.MISSING_IN_DB,
                                  status=DS.RESOLVED, gateway_txn_ref="rzx_82", gateway_amount=1_234,
                                  gateway_status="SUCCESS", resolution_note="test txn from gateway",
                                  resolved_at=at(2_000), created_at=at(1_002)),
        ReconciliationRun(id=sid(62), run_date=date(2026, 9, 2), status=RR.COMPLETED,
                          started_at=at(2_440), completed_at=at(2_441)),
    ]

    # --- Gateway stats (for /v1/metrics) ---------------------------------------------
    rows += [
        GatewayStat(id=sid(91), gateway=G.STRIPEIN, method=PM.UPI, success_count=41, failure_count=9,
                    avg_latency_ms=143, last_updated=at(12)),
        GatewayStat(id=sid(92), gateway=G.RAZORX, method=PM.UPI, success_count=0, failure_count=0,
                    avg_latency_ms=0, last_updated=at(11)),
    ]
    return rows


def reset_and_seed(db_url: str, redis_url: str) -> None:
    _guard(db_url)
    engine = create_engine(db_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with Session(engine) as s, s.begin():
        tables = ", ".join(f'"{t}"' for t in Base.metadata.tables)
        s.execute(text(f"TRUNCATE {tables} CASCADE"))
        # Insert in FK order: SQLAlchemy's unit of work sorts by dependency.
        s.add_all(build())
    engine.dispose()

    r = redis.Redis.from_url(redis_url)
    for key in r.scan_iter("ratelimit:*"):
        r.delete(key)
    r.close()


if __name__ == "__main__":
    reset_and_seed(os.environ["CONTRACT_DATABASE_URL"], os.environ["CONTRACT_REDIS_URL"])
    print("seeded")


def reset_gateway_stats(db_url: str) -> None:
    """
    Restore only the seeded gateway_stats rows. Processing payments (write and interop
    tests) legitimately bumps these counters, and the /metrics golden pins the seed values,
    so the metrics contract re-seeds them first instead of depending on test order.
    """
    _guard(db_url)
    engine = create_engine(db_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with Session(engine) as s, s.begin():
        s.execute(text("DELETE FROM gateway_stats"))
        s.add_all([r for r in build() if isinstance(r, GatewayStat)])
    engine.dispose()
