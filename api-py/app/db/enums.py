"""
Python mirrors of the Postgres enum types created by Prisma migrations.

`StrEnum` so values serialise as plain strings, exactly like Prisma returns them.
Bound to the existing PG types with create_type=False: Prisma owns the DDL.
"""
from enum import StrEnum

from sqlalchemy.dialects.postgresql import ENUM


class Role(StrEnum):
    ADMIN = "ADMIN"
    MERCHANT = "MERCHANT"
    VIEWER = "VIEWER"


class PaymentMethod(StrEnum):
    CARD = "CARD"
    UPI = "UPI"
    NET_BANKING = "NET_BANKING"
    WALLET = "WALLET"


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class Gateway(StrEnum):
    RAZORX = "RAZORX"
    STRIPEIN = "STRIPEIN"
    PAYFLOW = "PAYFLOW"
    SWIFTPAY = "SWIFTPAY"


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class LedgerEntryType(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerAccount(StrEnum):
    CUSTOMER_RECEIVABLE = "CUSTOMER_RECEIVABLE"
    MERCHANT_PAYABLE = "MERCHANT_PAYABLE"
    PLATFORM_REVENUE = "PLATFORM_REVENUE"
    MERCHANT_BANK = "MERCHANT_BANK"


class SettlementStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SETTLED = "SETTLED"


class ReconStatus(StrEnum):
    CLEAN = "CLEAN"
    FLAGGED = "FLAGGED"


class WebhookStatus(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class ReconRunStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ReconJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DiscrepancyType(StrEnum):
    MISSING_AT_GATEWAY = "MISSING_AT_GATEWAY"
    MISSING_IN_DB = "MISSING_IN_DB"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    STATUS_MISMATCH = "STATUS_MISMATCH"


class DiscrepancyStatus(StrEnum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class RefundStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


def pg_enum(py_enum: type[StrEnum]) -> ENUM:
    """Bind to the existing PG type named after the Prisma enum (e.g. "PaymentStatus")."""
    return ENUM(
        py_enum,
        name=py_enum.__name__,
        create_type=False,
        values_callable=lambda e: [m.value for m in e],
    )
