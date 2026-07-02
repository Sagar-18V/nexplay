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
