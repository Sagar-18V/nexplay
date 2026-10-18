"""Idempotency keys are unique per merchant, not globally (real fix for D14 / D20).

Revision ID: 0002_per_merchant_idempotency
Revises: 0001_prisma_baseline
Create Date: 2026-10-18

With a global unique index, two merchants can't use the same key ("order-1"), and the
replay lookup had to choose between leaking another merchant's object (Express, D14/D20)
or refusing with 409 (Steps 5-6 stopgap). Scoping the key to the merchant is how payment
APIs behave: each merchant has its own key namespace.

Zero-downtime on a live table:
  * the new index is built CONCURRENTLY (no write lock), BEFORE the old one is dropped,
    so there is never a moment without a uniqueness guarantee;
  * CONCURRENTLY can't run inside a transaction, hence autocommit_block();
  * no data change is needed: global uniqueness implies per-merchant uniqueness.
Downgrade restores the global index and fails if merchants have since reused keys.
"""
from alembic import op

revision = "0002_per_merchant_idempotency"
down_revision = "0001_prisma_baseline"
branch_labels = None
depends_on = None

TABLES = ("payment_intents", "refunds")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for table in TABLES:
            # A previous interrupted run can leave an INVALID index behind: start clean.
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{table}_merchantId_idempotencyKey_key"')
            op.execute(f'CREATE UNIQUE INDEX CONCURRENTLY "{table}_merchantId_idempotencyKey_key" '
                       f'ON "{table}" ("merchantId", "idempotencyKey")')
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{table}_idempotencyKey_key"')


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for table in TABLES:
            op.execute(f'CREATE UNIQUE INDEX CONCURRENTLY "{table}_idempotencyKey_key" ON "{table}" ("idempotencyKey")')
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{table}_merchantId_idempotencyKey_key"')
