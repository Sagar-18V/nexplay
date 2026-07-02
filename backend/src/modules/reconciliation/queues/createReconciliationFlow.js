const prisma = require('../../../config/prisma');
const { flowProducer, RECON_GATEWAY_QUEUE, RECON_RUN_QUEUE } = require('./queues');

const GATEWAYS = ['RAZORX', 'STRIPEIN', 'PAYFLOW', 'SWIFTPAY'];

/**
 * Creates the DB records + BullMQ flow for one settlement date.
 * Parent job (finalize) runs ONLY after all 4 children resolve.
 */
async function createReconciliationFlow(runDate) {
    const dateKey = runDate.toISOString().slice(0, 10);

    // DB-level idempotency: @@unique([runDate]) makes double-scheduling a no-op
    let run;
    try {
        run = await prisma.reconciliationRun.create({
            data: {
                runDate,
                gatewayJobs: {
                    create: GATEWAYS.map((gateway) => ({ gateway })),
                },
            },
            include: { gatewayJobs: true },
        });
    } catch (err) {
        if (err.code === 'P2002') {
            console.log(`[recon] Run for ${dateKey} already exists, skipping`);
            return null;
        }
        throw err;
    }

    await flowProducer.add({
        name: 'finalize-run',
        queueName: RECON_RUN_QUEUE,
        data: { runId: run.id, runDate: dateKey },
        opts: {
            jobId: `recon-run-${dateKey}`,          // queue-level idempotency
        },
        children: run.gatewayJobs.map((gj) => ({
            name: `recon-${gj.gateway}`,
            queueName: RECON_GATEWAY_QUEUE,
            data: {
                gatewayJobId: gj.id,
                runId: run.id,
                gateway: gj.gateway,
                runDate: dateKey,
            },
            opts: {
                jobId: `recon-${dateKey}-${gj.gateway}`,
                attempts: 3,
                backoff: { type: 'exponential', delay: 5000 },
                // CRITICAL: parent must still run even if a child exhausts retries —
                // otherwise one dead gateway blocks the whole run forever
                ignoreDependencyOnFailure: true,
            },
        })),
    });

    return run;
}

module.exports = { createReconciliationFlow, GATEWAYS };