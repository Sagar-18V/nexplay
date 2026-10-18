"""
SQLAlchemy 2.0 models mapped onto the tables Prisma created.

Conventions
-----------
- Python attributes are snake_case; the DB column names are Prisma's camelCase
  (`merchant_id` -> "merchantId"). The serializer emits column names, so API JSON
  keys match what Prisma/Express return.
- Prisma generates `@default(uuid())` and `@updatedAt` in the CLIENT, not the DB,
  so we must do the same here or inserts from Python will fail / go stale.
- Timestamps are `TIMESTAMP(3)` WITHOUT time zone holding UTC. We store naive UTC
  truncated to milliseconds (see `utcnow_ms`), matching JS Date precision.
- tests/integration/test_schema_drift.py checks these models against the live,
  Prisma-migrated schema. If Prisma adds a column, that test fails first.
"""
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.enums import (
    DiscrepancyStatus, DiscrepancyType, Gateway, LedgerAccount, LedgerEntryType,
    PaymentMethod, PaymentStatus, ReconJobStatus, ReconRunStatus, ReconStatus,
    RefundStatus, Role, SettlementStatus, TransactionStatus, WebhookStatus, pg_enum,
)


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow_ms() -> datetime:
    """Naive UTC, millisecond precision — what Prisma writes to TIMESTAMP(3)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


TS = TIMESTAMP(precision=3, timezone=False)


class Base(DeclarativeBase):
    pass


def pk() -> Mapped[str]:
    return mapped_column("id", Text, primary_key=True, default=new_id)


def created_at() -> Mapped[datetime]:
    return mapped_column("createdAt", TS, nullable=False, default=utcnow_ms)


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column("name", Text)
    email: Mapped[str] = mapped_column("email", Text, unique=True)
    password: Mapped[str] = mapped_column("password", Text)
    role: Mapped[Role] = mapped_column("role", pg_enum(Role), default=Role.MERCHANT)
    api_key: Mapped[str] = mapped_column("apiKey", Text, unique=True, default=new_id)
    webhook_url: Mapped[str | None] = mapped_column("webhookUrl", Text)
    is_active: Mapped[bool] = mapped_column("isActive", Boolean, default=True)
    created_at: Mapped[datetime] = created_at()

    payment_intents: Mapped[list["PaymentIntent"]] = relationship(back_populates="merchant")


class PaymentIntent(Base):
    __tablename__ = "payment_intents"

    id: Mapped[str] = pk()
    merchant_id: Mapped[str] = mapped_column("merchantId", Text, ForeignKey("merchants.id"))
    amount: Mapped[int] = mapped_column("amount", Integer)
    currency: Mapped[str] = mapped_column("currency", Text, default="INR")
    method: Mapped[PaymentMethod] = mapped_column("method", pg_enum(PaymentMethod))
    status: Mapped[PaymentStatus] = mapped_column(
        "status", pg_enum(PaymentStatus), default=PaymentStatus.CREATED
    )
    idempotency_key: Mapped[str] = mapped_column("idempotencyKey", Text, unique=True)
    metadata_: Mapped[Any | None] = mapped_column("metadata", JSONB)  # `metadata` is reserved
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", TS, nullable=False, default=utcnow_ms, onupdate=utcnow_ms
    )

    merchant: Mapped[Merchant] = relationship(back_populates="payment_intents")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="intent")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = pk()
    intent_id: Mapped[str] = mapped_column("intentId", Text, ForeignKey("payment_intents.id"))
    gateway: Mapped[Gateway] = mapped_column("gateway", pg_enum(Gateway))
    amount: Mapped[int] = mapped_column("amount", Integer)
    status: Mapped[TransactionStatus] = mapped_column(
        "status", pg_enum(TransactionStatus), default=TransactionStatus.PENDING
    )
    gateway_txn_id: Mapped[str | None] = mapped_column("gatewayTxnId", Text)
    latency_ms: Mapped[int | None] = mapped_column("latencyMs", Integer)
    fee_amount: Mapped[int | None] = mapped_column("feeAmount", Integer)
    failure_reason: Mapped[str | None] = mapped_column("failureReason", Text)
    created_at: Mapped[datetime] = created_at()
    refunded_amount: Mapped[int] = mapped_column("refundedAmount", Integer, default=0)

    intent: Mapped[PaymentIntent] = relationship(back_populates="transactions")
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="transaction")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="transaction")


class GatewayStat(Base):
    __tablename__ = "gateway_stats"
    __table_args__ = (UniqueConstraint("gateway", "method", name="gateway_stats_gateway_method_key"),)

    id: Mapped[str] = pk()
    gateway: Mapped[Gateway] = mapped_column("gateway", pg_enum(Gateway))
    method: Mapped[PaymentMethod] = mapped_column("method", pg_enum(PaymentMethod))
    success_count: Mapped[int] = mapped_column("successCount", Integer, default=0)
    failure_count: Mapped[int] = mapped_column("failureCount", Integer, default=0)
    avg_latency_ms: Mapped[int] = mapped_column("avgLatencyMs", Integer, default=0)
    last_updated: Mapped[datetime] = mapped_column("lastUpdated", TS, nullable=False, default=utcnow_ms)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[str] = pk()
    txn_id: Mapped[str] = mapped_column("txnId", Text, ForeignKey("transactions.id"))
    entry_type: Mapped[LedgerEntryType] = mapped_column("entryType", pg_enum(LedgerEntryType))
    account: Mapped[LedgerAccount] = mapped_column("account", pg_enum(LedgerAccount))
    amount: Mapped[int] = mapped_column("amount", Integer)
    created_at: Mapped[datetime] = created_at()
    refund_id: Mapped[str | None] = mapped_column(
        "refundId", Text, ForeignKey("refunds.id", ondelete="SET NULL")
    )

    transaction: Mapped[Transaction] = relationship(back_populates="ledger_entries")
    refund: Mapped["Refund | None"] = relationship(back_populates="ledger_entries")


class Settlement(Base):
    __tablename__ = "settlements"

    id: Mapped[str] = pk()
    merchant_id: Mapped[str] = mapped_column("merchantId", Text, ForeignKey("merchants.id"))
    amount: Mapped[int] = mapped_column("amount", Integer)
    status: Mapped[SettlementStatus] = mapped_column(
        "status", pg_enum(SettlementStatus), default=SettlementStatus.PENDING
    )
    gateway: Mapped[Gateway] = mapped_column("gateway", pg_enum(Gateway))
    settlement_date: Mapped[datetime] = mapped_column("settlementDate", TS)
    created_at: Mapped[datetime] = created_at()


class ReconciliationReport(Base):
    __tablename__ = "reconciliation_reports"

    id: Mapped[str] = pk()
    merchant_id: Mapped[str] = mapped_column("merchantId", Text, ForeignKey("merchants.id"))
    run_date: Mapped[datetime] = mapped_column("runDate", TS)
    total_txns: Mapped[int] = mapped_column("totalTxns", Integer)
    matched: Mapped[int] = mapped_column("matched", Integer)
    mismatched: Mapped[int] = mapped_column("mismatched", Integer)
    missing: Mapped[int] = mapped_column("missing", Integer)
    discrepancies: Mapped[Any | None] = mapped_column("discrepancies", JSONB)
    status: Mapped[ReconStatus] = mapped_column("status", pg_enum(ReconStatus), default=ReconStatus.CLEAN)
    created_at: Mapped[datetime] = created_at()


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id: Mapped[str] = pk()
    merchant_id: Mapped[str] = mapped_column("merchantId", Text, ForeignKey("merchants.id"))
    event: Mapped[str] = mapped_column("event", Text)
    payload: Mapped[Any] = mapped_column("payload", JSONB)
    attempts: Mapped[int] = mapped_column("attempts", Integer, default=0)
    last_attempted_at: Mapped[datetime | None] = mapped_column("lastAttemptedAt", TS)
    delivered_at: Mapped[datetime | None] = mapped_column("deliveredAt", TS)
    status: Mapped[WebhookStatus] = mapped_column(
        "status", pg_enum(WebhookStatus), default=WebhookStatus.PENDING
    )
    created_at: Mapped[datetime] = created_at()

    merchant: Mapped["Merchant"] = relationship()


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[str] = pk()
    run_date: Mapped[date] = mapped_column("runDate", Date, unique=True)
    status: Mapped[ReconRunStatus] = mapped_column(
        "status", pg_enum(ReconRunStatus), default=ReconRunStatus.PENDING
    )
    started_at: Mapped[datetime] = mapped_column("startedAt", TS, nullable=False, default=utcnow_ms)
    completed_at: Mapped[datetime | None] = mapped_column("completedAt", TS)

    gateway_jobs: Mapped[list["ReconciliationGatewayJob"]] = relationship(back_populates="run")


class ReconciliationGatewayJob(Base):
    __tablename__ = "reconciliation_gateway_jobs"
    __table_args__ = (
        UniqueConstraint("runId", "gateway", name="reconciliation_gateway_jobs_runId_gateway_key"),
    )

    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column("runId", Text, ForeignKey("reconciliation_runs.id"))
    gateway: Mapped[Gateway] = mapped_column("gateway", pg_enum(Gateway))
    status: Mapped[ReconJobStatus] = mapped_column(
        "status", pg_enum(ReconJobStatus), default=ReconJobStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column("attempts", Integer, default=0)
    total_in_db: Mapped[int] = mapped_column("totalInDb", Integer, default=0)
    total_in_file: Mapped[int] = mapped_column("totalInFile", Integer, default=0)
    matched_count: Mapped[int] = mapped_column("matchedCount", Integer, default=0)
    discrepancy_count: Mapped[int] = mapped_column("discrepancyCount", Integer, default=0)
    expected_amount: Mapped[int] = mapped_column("expectedAmount", BigInteger, default=0)
    reported_amount: Mapped[int] = mapped_column("reportedAmount", BigInteger, default=0)
    error_message: Mapped[str | None] = mapped_column("errorMessage", Text)
    started_at: Mapped[datetime | None] = mapped_column("startedAt", TS)
    completed_at: Mapped[datetime | None] = mapped_column("completedAt", TS)

    run: Mapped[ReconciliationRun] = relationship(back_populates="gateway_jobs")
    discrepancies: Mapped[list["ReconciliationDiscrepancy"]] = relationship(back_populates="gateway_job")


class ReconciliationDiscrepancy(Base):
    __tablename__ = "reconciliation_discrepancies"

    id: Mapped[str] = pk()
    gateway_job_id: Mapped[str] = mapped_column(
        "gatewayJobId", Text, ForeignKey("reconciliation_gateway_jobs.id")
    )
    type: Mapped[DiscrepancyType] = mapped_column("type", pg_enum(DiscrepancyType), index=True)
    status: Mapped[DiscrepancyStatus] = mapped_column(
        "status", pg_enum(DiscrepancyStatus), default=DiscrepancyStatus.OPEN, index=True
    )
    payment_id: Mapped[str | None] = mapped_column("paymentId", Text)
    gateway_txn_ref: Mapped[str | None] = mapped_column("gatewayTxnRef", Text)
    our_amount: Mapped[int | None] = mapped_column("ourAmount", BigInteger)
    gateway_amount: Mapped[int | None] = mapped_column("gatewayAmount", BigInteger)
    our_status: Mapped[str | None] = mapped_column("ourStatus", Text)
    gateway_status: Mapped[str | None] = mapped_column("gatewayStatus", Text)
    resolution_note: Mapped[str | None] = mapped_column("resolutionNote", Text)
    resolved_at: Mapped[datetime | None] = mapped_column("resolvedAt", TS)
    created_at: Mapped[datetime] = created_at()

    gateway_job: Mapped[ReconciliationGatewayJob] = relationship(back_populates="discrepancies")


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[str] = pk()
    transaction_id: Mapped[str] = mapped_column(
        "transactionId", Text, ForeignKey("transactions.id"), index=True
    )
    merchant_id: Mapped[str] = mapped_column("merchantId", Text)  # denormalised, no FK (as in Prisma)
    amount: Mapped[int] = mapped_column("amount", Integer)
    status: Mapped[RefundStatus] = mapped_column("status", pg_enum(RefundStatus), default=RefundStatus.PENDING)
    reason: Mapped[str | None] = mapped_column("reason", Text)
    gateway_refund_ref: Mapped[str | None] = mapped_column("gatewayRefundRef", Text)
    failure_reason: Mapped[str | None] = mapped_column("failureReason", Text)
    attempts: Mapped[int] = mapped_column("attempts", Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column("idempotencyKey", Text, unique=True)
    created_at: Mapped[datetime] = created_at()
    processed_at: Mapped[datetime | None] = mapped_column("processedAt", TS)

    transaction: Mapped[Transaction] = relationship(back_populates="refunds")
    ledger_entries: Mapped[list[LedgerEntry]] = relationship(back_populates="refund")
