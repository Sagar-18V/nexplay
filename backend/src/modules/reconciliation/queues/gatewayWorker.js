const { Worker } = require('bullmq');
const prisma = require('../../../config/prisma');
const connection = require('../../../config/redis');
const { RECON_GATEWAY_QUEUE } = require('./queues');
const { generateSettlementFile } = require('../../services/settlement/settlementFileGenerator');
const { reconcile } = require('../../services/reconciliation/reconciliationEngine');

const gatewayWorker = new Worker(
    RECON_GATEWAY_QUEUE,
    async (job) => {
        const { gatewayJobId, gateway, runDate } = job.data;
        const dayStart = new Date(`${runDate}T00:00:00.000Z`);
        const dayEnd = new Date(dayStart);
        dayEnd.setUTCDate(dayEnd.getUTCDate() + 1);

        await prisma.reconciliationGatewayJob.update({
            where: { id: gatewayJobId },
            data: { status: 'RUNNING', startedAt: new Date(), attempts: job.attemptsMade + 1 },
        });

        // 1. Our side
        const payments = await prisma.payment.findMany({
            where: {
                gateway,
                status: { in: ['CAPTURED', 'FAILED', 'REFUNDED'] },
                updatedAt: { gte: dayStart, lt: dayEnd },
            },
            select: { id: true, amount: true, status: true },
        });

        // 2. Their side (in prod: fetch/download; here: deterministic mock)
        const settlementFile = await generateSettlementFile(gateway, dayStart);

        // 3. Pure matching
        const { summary, discrepancies } = reconcile(payments, settlementFile);

        // 4. Persist atomically — summary + findings are one unit of truth.
        //    Delete-then-insert makes retries idempotent: a retry after a
        //    partial write replaces, never duplicates.
        await prisma.$transaction([
            prisma.reconciliationDiscrepancy.deleteMany({
                where: { gatewayJobId },
            }),
            prisma.reconciliationDiscrepancy.createMany({
                data: discrepancies.map((d) => ({ ...d, gatewayJobId })),
            }),
            prisma.reconciliationGatewayJob.update({
                where: { id: gatewayJobId },
                data: {
                    status: 'COMPLETED',
                    completedAt: new Date(),
                    totalInDb: summary.totalInDb,
                    totalInFile: summary.totalInFile,
                    matchedCount: summary.matchedCount,
                    discrepancyCount: summary.discrepancyCount,
                    expectedAmount: summary.expectedAmount,
                    reportedAmount: summary.reportedAmount,
                },
            }),
        ]);

        return { gateway, ...summaryToLog(summary) };
    },
    { connection, concurrency: 4 }   // all 4 gateways in parallel
);

function summaryToLog(s) {
    return { matched: s.matchedCount, flagged: s.discrepancyCount };
}

// Terminal failure (retries exhausted) -> mark FAILED in DB
gatewayWorker.on('failed', async (job, err) => {
    if (job && job.attemptsMade >= job.opts.attempts) {
        await prisma.reconciliationGatewayJob.update({
            where: { id: job.data.gatewayJobId },
            data: { status: 'FAILED', errorMessage: err.message, completedAt: new Date() },
        });
    }
});

module.exports = { gatewayWorker };