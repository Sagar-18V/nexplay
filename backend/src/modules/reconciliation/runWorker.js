const { Worker } = require('bullmq');
const prisma = require('../../config/prisma');
const { bullmqConnection } = require('../../config/redis');
const { RECON_RUN_QUEUE } = require('./queues/queues');

const runWorker = new Worker(
    RECON_RUN_QUEUE,
    async (job) => {
        const { runId } = job.data;

        // Truth comes from the DB, not from BullMQ return values —
        // children already persisted their outcomes.
        const gatewayJobs = await prisma.reconciliationGatewayJob.findMany({
            where: { runId },
        });

        const completed = gatewayJobs.filter((g) => g.status === 'COMPLETED').length;
        const failed = gatewayJobs.filter((g) => g.status === 'FAILED').length;

        const status =
            failed === 0 ? 'COMPLETED' :
                completed === 0 ? 'FAILED' :
                    'PARTIAL';

        await prisma.reconciliationRun.update({
            where: { id: runId },
            data: { status, completedAt: new Date() },
        });

        console.log(`[recon] Run ${runId} finalized: ${status} (${completed} ok, ${failed} failed)`);
        return { status, completed, failed };
    },
    { connection: bullmqConnection }
);

module.exports = { runWorker };