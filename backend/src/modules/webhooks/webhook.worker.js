const { Worker } = require('bullmq');
const crypto = require('crypto');
const { bullmqConnection } = require('../../config/redis');
const prisma = require('../../config/prisma');

const webhookWorker = new Worker('webhooks', async (job) => {
    const { webhookLogId } = job.data;

    const log = await prisma.webhookLog.findUnique({
        where: { id: webhookLogId },
        include: { merchant: { select: { webhookUrl: true, apiKey: true } } },
    });
    if (!log) throw new Error(`WebhookLog ${webhookLogId} not found`);
    if (log.status === 'DELIVERED') return;   // idempotent re-entry
    if (!log.merchant.webhookUrl) return;

    await prisma.webhookLog.update({
        where: { id: webhookLogId },
        data: { attempts: { increment: 1 }, lastAttemptedAt: new Date() },
    });

    // Canonical body — sign EXACTLY what we send
    const body = JSON.stringify({
        id: log.id,                      // receiver-side dedup key
        event: log.event,
        payload: log.payload,
        created_at: log.createdAt.toISOString(),
    });

    const signature = crypto
        .createHmac('sha256', log.merchant.apiKey)
        .update(body)
        .digest('hex');

    // Node 25 has global fetch; AbortSignal.timeout enforces the deadline
    const res = await fetch(log.merchant.webhookUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-NexPay-Signature': signature,
            'X-NexPay-Event': log.event,
        },
        body,
        signal: AbortSignal.timeout(5000),
    });

    // Any non-2xx = failed delivery -> throw -> BullMQ retries with backoff
    if (res.status < 200 || res.status >= 300) {
        throw new Error(`Receiver responded ${res.status}`);
    }

    await prisma.webhookLog.update({
        where: { id: webhookLogId },
        data: { status: 'DELIVERED', deliveredAt: new Date() },
    });
}, { connection: bullmqConnection, concurrency: 10 });

// Retries exhausted -> dead letter
webhookWorker.on('failed', async (job, err) => {
    if (job && job.attemptsMade >= job.opts.attempts) {
        await prisma.webhookLog.update({
            where: { id: job.data.webhookLogId },
            data: { status: 'FAILED' },
        });
    }
});

module.exports = { webhookWorker };