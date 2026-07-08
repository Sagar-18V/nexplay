/**
 * Worker bootstrap — import this once at startup to start all BullMQ workers.
 * Workers are long-lived; they stay alive as long as the process runs.
 *
 * NOTE: In a scaled deployment you'd run workers in a separate process
 * (so you can scale them independently of the HTTP server). For now,
 * running in-process keeps the dev setup simple.
 */

const { refundWorker } = require('./modules/refunds/refund.worker');

// Reconciliation workers (gateway + run finalizer)
const { gatewayWorker } = require('./modules/reconciliation/queues/gatewayWorker');
const { runWorker } = require('./modules/reconciliation/runWorker');

function logWorkerEvents(worker) {
    worker.on('completed', (job) => {
        console.log(`[worker:${worker.name}] job ${job.id} completed`);
    });
    worker.on('failed', (job, err) => {
        console.error(`[worker:${worker.name}] job ${job?.id} failed: ${err.message}`);
    });
    worker.on('error', (err) => {
        console.error(`[worker:${worker.name}] error: ${err.message}`);
    });
}

[refundWorker, gatewayWorker, runWorker].forEach(logWorkerEvents);

console.log('[workers] refund, recon-gateway, recon-run workers started');

module.exports = { refundWorker, gatewayWorker, runWorker };
