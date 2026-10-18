"""Baseline: the schema exactly as Prisma's four migrations left it.

Revision ID: 0001_prisma_baseline
Revises:
Create Date: 2026-10-18

Step 7 hands schema ownership from Prisma to Alembic. This revision is Prisma's own SQL,
verbatim and in order, so a fresh database built by Alembic is identical to one built by
`prisma migrate deploy` (verified with a pg_dump --schema-only diff; see MIGRATION.md).

Existing databases already have this schema: they are STAMPED at this revision, never
upgraded through it. `python -m app.ops.migrate` does that automatically, and only after
confirming all four Prisma migrations below are recorded as applied.
"""
from alembic import op

revision = "0001_prisma_baseline"
down_revision = None
branch_labels = None
depends_on = None

PRISMA_MIGRATIONS = [
    # ---- prisma/migrations/20260617185009_init/migration.sql (verbatim)
    ("20260617185009_init", r"""
-- CreateEnum
CREATE TYPE "PaymentMethod" AS ENUM ('CARD', 'UPI', 'NET_BANKING', 'WALLET');

-- CreateEnum
CREATE TYPE "PaymentStatus" AS ENUM ('CREATED', 'PROCESSING', 'SUCCESS', 'FAILED', 'REFUNDED');

-- CreateEnum
CREATE TYPE "Gateway" AS ENUM ('RAZORX', 'STRIPEIN', 'PAYFLOW', 'SWIFTPAY');

-- CreateEnum
CREATE TYPE "TransactionStatus" AS ENUM ('PENDING', 'SUCCESS', 'FAILED');

-- CreateEnum
CREATE TYPE "LedgerEntryType" AS ENUM ('DEBIT', 'CREDIT');

-- CreateEnum
CREATE TYPE "LedgerAccount" AS ENUM ('CUSTOMER_RECEIVABLE', 'MERCHANT_PAYABLE', 'PLATFORM_REVENUE', 'MERCHANT_BANK');

-- CreateEnum
CREATE TYPE "SettlementStatus" AS ENUM ('PENDING', 'PROCESSING', 'SETTLED');

-- CreateEnum
CREATE TYPE "ReconStatus" AS ENUM ('CLEAN', 'FLAGGED');

-- CreateEnum
CREATE TYPE "WebhookStatus" AS ENUM ('PENDING', 'DELIVERED', 'FAILED');

-- CreateTable
CREATE TABLE "merchants" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "password" TEXT NOT NULL,
    "apiKey" TEXT NOT NULL,
    "webhookUrl" TEXT,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "merchants_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "payment_intents" (
    "id" TEXT NOT NULL,
    "merchantId" TEXT NOT NULL,
    "amount" INTEGER NOT NULL,
    "currency" TEXT NOT NULL DEFAULT 'INR',
    "method" "PaymentMethod" NOT NULL,
    "status" "PaymentStatus" NOT NULL DEFAULT 'CREATED',
    "idempotencyKey" TEXT NOT NULL,
    "metadata" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "payment_intents_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "transactions" (
    "id" TEXT NOT NULL,
    "intentId" TEXT NOT NULL,
    "gateway" "Gateway" NOT NULL,
    "amount" INTEGER NOT NULL,
    "status" "TransactionStatus" NOT NULL DEFAULT 'PENDING',
    "gatewayTxnId" TEXT,
    "latencyMs" INTEGER,
    "feeAmount" INTEGER,
    "failureReason" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "transactions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "gateway_stats" (
    "id" TEXT NOT NULL,
    "gateway" "Gateway" NOT NULL,
    "method" "PaymentMethod" NOT NULL,
    "successCount" INTEGER NOT NULL DEFAULT 0,
    "failureCount" INTEGER NOT NULL DEFAULT 0,
    "avgLatencyMs" INTEGER NOT NULL DEFAULT 0,
    "lastUpdated" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "gateway_stats_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ledger_entries" (
    "id" TEXT NOT NULL,
    "txnId" TEXT NOT NULL,
    "entryType" "LedgerEntryType" NOT NULL,
    "account" "LedgerAccount" NOT NULL,
    "amount" INTEGER NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ledger_entries_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "settlements" (
    "id" TEXT NOT NULL,
    "merchantId" TEXT NOT NULL,
    "amount" INTEGER NOT NULL,
    "status" "SettlementStatus" NOT NULL DEFAULT 'PENDING',
    "gateway" "Gateway" NOT NULL,
    "settlementDate" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "settlements_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "reconciliation_reports" (
    "id" TEXT NOT NULL,
    "merchantId" TEXT NOT NULL,
    "runDate" TIMESTAMP(3) NOT NULL,
    "totalTxns" INTEGER NOT NULL,
    "matched" INTEGER NOT NULL,
    "mismatched" INTEGER NOT NULL,
    "missing" INTEGER NOT NULL,
    "discrepancies" JSONB,
    "status" "ReconStatus" NOT NULL DEFAULT 'CLEAN',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "reconciliation_reports_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "webhook_logs" (
    "id" TEXT NOT NULL,
    "merchantId" TEXT NOT NULL,
    "event" TEXT NOT NULL,
    "payload" JSONB NOT NULL,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "lastAttemptedAt" TIMESTAMP(3),
    "deliveredAt" TIMESTAMP(3),
    "status" "WebhookStatus" NOT NULL DEFAULT 'PENDING',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "webhook_logs_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "merchants_email_key" ON "merchants"("email");

-- CreateIndex
CREATE UNIQUE INDEX "merchants_apiKey_key" ON "merchants"("apiKey");

-- CreateIndex
CREATE UNIQUE INDEX "payment_intents_idempotencyKey_key" ON "payment_intents"("idempotencyKey");

-- CreateIndex
CREATE UNIQUE INDEX "gateway_stats_gateway_method_key" ON "gateway_stats"("gateway", "method");

-- AddForeignKey
ALTER TABLE "payment_intents" ADD CONSTRAINT "payment_intents_merchantId_fkey" FOREIGN KEY ("merchantId") REFERENCES "merchants"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "transactions" ADD CONSTRAINT "transactions_intentId_fkey" FOREIGN KEY ("intentId") REFERENCES "payment_intents"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ledger_entries" ADD CONSTRAINT "ledger_entries_txnId_fkey" FOREIGN KEY ("txnId") REFERENCES "transactions"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "settlements" ADD CONSTRAINT "settlements_merchantId_fkey" FOREIGN KEY ("merchantId") REFERENCES "merchants"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reconciliation_reports" ADD CONSTRAINT "reconciliation_reports_merchantId_fkey" FOREIGN KEY ("merchantId") REFERENCES "merchants"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "webhook_logs" ADD CONSTRAINT "webhook_logs_merchantId_fkey" FOREIGN KEY ("merchantId") REFERENCES "merchants"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
"""),
    # ---- prisma/migrations/20260618120000_add_merchant_role/migration.sql (verbatim)
    ("20260618120000_add_merchant_role", r"""
-- CreateEnum
CREATE TYPE "Role" AS ENUM ('ADMIN', 'MERCHANT', 'VIEWER');

-- AlterTable
ALTER TABLE "merchants" ADD COLUMN     "role" "Role" NOT NULL DEFAULT 'MERCHANT';
"""),
    # ---- prisma/migrations/20260702070650_add_reconciliation_models/migration.sql (verbatim)
    ("20260702070650_add_reconciliation_models", r"""
-- CreateEnum
CREATE TYPE "ReconRunStatus" AS ENUM ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'PARTIAL', 'FAILED');

-- CreateEnum
CREATE TYPE "ReconJobStatus" AS ENUM ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED');

-- CreateEnum
CREATE TYPE "DiscrepancyType" AS ENUM ('MISSING_AT_GATEWAY', 'MISSING_IN_DB', 'AMOUNT_MISMATCH', 'STATUS_MISMATCH');

-- CreateEnum
CREATE TYPE "DiscrepancyStatus" AS ENUM ('OPEN', 'INVESTIGATING', 'RESOLVED', 'IGNORED');

-- CreateTable
CREATE TABLE "reconciliation_runs" (
    "id" TEXT NOT NULL,
    "runDate" DATE NOT NULL,
    "status" "ReconRunStatus" NOT NULL DEFAULT 'PENDING',
    "startedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),

    CONSTRAINT "reconciliation_runs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "reconciliation_gateway_jobs" (
    "id" TEXT NOT NULL,
    "runId" TEXT NOT NULL,
    "gateway" "Gateway" NOT NULL,
    "status" "ReconJobStatus" NOT NULL DEFAULT 'QUEUED',
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "totalInDb" INTEGER NOT NULL DEFAULT 0,
    "totalInFile" INTEGER NOT NULL DEFAULT 0,
    "matchedCount" INTEGER NOT NULL DEFAULT 0,
    "discrepancyCount" INTEGER NOT NULL DEFAULT 0,
    "expectedAmount" BIGINT NOT NULL DEFAULT 0,
    "reportedAmount" BIGINT NOT NULL DEFAULT 0,
    "errorMessage" TEXT,
    "startedAt" TIMESTAMP(3),
    "completedAt" TIMESTAMP(3),

    CONSTRAINT "reconciliation_gateway_jobs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "reconciliation_discrepancies" (
    "id" TEXT NOT NULL,
    "gatewayJobId" TEXT NOT NULL,
    "type" "DiscrepancyType" NOT NULL,
    "status" "DiscrepancyStatus" NOT NULL DEFAULT 'OPEN',
    "paymentId" TEXT,
    "gatewayTxnRef" TEXT,
    "ourAmount" BIGINT,
    "gatewayAmount" BIGINT,
    "ourStatus" TEXT,
    "gatewayStatus" TEXT,
    "resolutionNote" TEXT,
    "resolvedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "reconciliation_discrepancies_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "reconciliation_runs_runDate_key" ON "reconciliation_runs"("runDate");

-- CreateIndex
CREATE UNIQUE INDEX "reconciliation_gateway_jobs_runId_gateway_key" ON "reconciliation_gateway_jobs"("runId", "gateway");

-- CreateIndex
CREATE INDEX "reconciliation_discrepancies_status_idx" ON "reconciliation_discrepancies"("status");

-- CreateIndex
CREATE INDEX "reconciliation_discrepancies_type_idx" ON "reconciliation_discrepancies"("type");

-- AddForeignKey
ALTER TABLE "reconciliation_gateway_jobs" ADD CONSTRAINT "reconciliation_gateway_jobs_runId_fkey" FOREIGN KEY ("runId") REFERENCES "reconciliation_runs"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reconciliation_discrepancies" ADD CONSTRAINT "reconciliation_discrepancies_gatewayJobId_fkey" FOREIGN KEY ("gatewayJobId") REFERENCES "reconciliation_gateway_jobs"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
"""),
    # ---- prisma/migrations/20260708131609_add_refunds/migration.sql (verbatim)
    ("20260708131609_add_refunds", r"""
-- CreateEnum
CREATE TYPE "RefundStatus" AS ENUM ('PENDING', 'PROCESSING', 'SUCCEEDED', 'FAILED');

-- AlterEnum
ALTER TYPE "PaymentStatus" ADD VALUE 'PARTIALLY_REFUNDED';

-- AlterTable
ALTER TABLE "ledger_entries" ADD COLUMN     "refundId" TEXT;

-- AlterTable
ALTER TABLE "transactions" ADD COLUMN     "refundedAmount" INTEGER NOT NULL DEFAULT 0;

-- CreateTable
CREATE TABLE "refunds" (
    "id" TEXT NOT NULL,
    "transactionId" TEXT NOT NULL,
    "merchantId" TEXT NOT NULL,
    "amount" INTEGER NOT NULL,
    "status" "RefundStatus" NOT NULL DEFAULT 'PENDING',
    "reason" TEXT,
    "gatewayRefundRef" TEXT,
    "failureReason" TEXT,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "idempotencyKey" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "processedAt" TIMESTAMP(3),

    CONSTRAINT "refunds_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "refunds_idempotencyKey_key" ON "refunds"("idempotencyKey");

-- CreateIndex
CREATE INDEX "refunds_transactionId_idx" ON "refunds"("transactionId");

-- CreateIndex
CREATE INDEX "refunds_merchantId_createdAt_idx" ON "refunds"("merchantId", "createdAt");

-- AddForeignKey
ALTER TABLE "ledger_entries" ADD CONSTRAINT "ledger_entries_refundId_fkey" FOREIGN KEY ("refundId") REFERENCES "refunds"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "refunds" ADD CONSTRAINT "refunds_transactionId_fkey" FOREIGN KEY ("transactionId") REFERENCES "transactions"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
"""),
]
PRISMA_MIGRATION_NAMES = ['20260617185009_init', '20260618120000_add_merchant_role', '20260702070650_add_reconciliation_models', '20260708131609_add_refunds']


def upgrade() -> None:
    for _name, sql in PRISMA_MIGRATIONS:
        op.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("The baseline is not reversible: drop the database instead.")
