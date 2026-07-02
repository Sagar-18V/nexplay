const { Queue, Worker } = require('bullmq');
const connection = require('../../config/redis');
const { createReconciliationFlow } = require('./createReconciliationFlow');

const schedulerQueue = new Queue('recon-scheduler', { connection });

async function registerReconciliationSchedule() {
    await schedulerQueue.add(
        'daily-recon',
        {},
        {
            repeat: { pattern: '0 2 * * *' },   // 2 AM daily
            jobId: 'daily-recon-schedule',      // dedup across API instances
        }
    );
}

const schedulerWorker = new Worker(
    'recon-scheduler',
    async () => {
        const yesterday = new Date();
        yesterday.setUTCDate(yesterday.getUTCDate() - 1);
        yesterday.setUTCHours(0, 0, 0, 0);
        return createReconciliationFlow(yesterday);
    },
    { connection }
);

module.exports = { registerReconciliationSchedule, schedulerWorker };