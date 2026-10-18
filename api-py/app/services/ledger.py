"""
Port of modules/ledger/ledger.service.js: append-only double-entry ledger.

Every write happens inside the CALLER's transaction, so ledger rows commit atomically
with the state change that caused them. Python adds an explicit invariant check:
an unbalanced set of entries raises before anything reaches the database.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import LedgerAccount, LedgerEntryType
from app.db.models import LedgerEntry


class LedgerImbalance(Exception):
    pass


def capture_entries(txn_id: str, amount: int, fee_amount: int = 0) -> list[LedgerEntry]:
    """Customer owes the full amount; merchant is owed amount - fee; platform earns the fee."""
    fee_amount = fee_amount or 0
    entries = [
        LedgerEntry(txn_id=txn_id, entry_type=LedgerEntryType.DEBIT,
                    account=LedgerAccount.CUSTOMER_RECEIVABLE, amount=amount),
        LedgerEntry(txn_id=txn_id, entry_type=LedgerEntryType.CREDIT,
                    account=LedgerAccount.MERCHANT_PAYABLE, amount=amount - fee_amount),
    ]
    if fee_amount > 0:
        entries.append(LedgerEntry(txn_id=txn_id, entry_type=LedgerEntryType.CREDIT,
                                   account=LedgerAccount.PLATFORM_REVENUE, amount=fee_amount))
    assert_balanced(entries)
    return entries


def assert_balanced(entries: list[LedgerEntry]) -> None:
    debits = sum(e.amount for e in entries if e.entry_type == LedgerEntryType.DEBIT)
    credits = sum(e.amount for e in entries if e.entry_type == LedgerEntryType.CREDIT)
    if debits != credits:
        raise LedgerImbalance(f"debits {debits} != credits {credits}")


def write_capture_entries(session: AsyncSession, *, txn_id: str, amount: int, fee_amount: int = 0) -> None:
    session.add_all(capture_entries(txn_id, amount, fee_amount))
