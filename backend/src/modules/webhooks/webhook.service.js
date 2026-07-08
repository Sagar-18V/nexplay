const prisma = require('../../config/prisma');
const { webhookQueue } = require('./webhook.queue');

/**
 * Records + enqueues a webhook event for a merchant.
 * Call AFTER the state-changing DB transaction commits — an event
 * must describe something that definitely happened.
 */
async function emitWebhookEvent(merchantId, event, payload) {
    const merchant = await prisma.merchant.findUnique({
        where: { id: merchantId },
        select: { webhookUrl: true },
    });
    if (!merchant?.webhookUrl) return null;   // merchant hasn't opted in — skip silently

    const log = await prisma.webhookLog.create({
        data: { merchantId, event, payload },
    });

    await webhookQueue.add('deliver', { webhookLogId: log.id }, {
        jobId: `webhook-${log.id}`,
        attempts: 3,
        backoff: { type: 'exponential', delay: 2000 },  // 2s, 4s, 8s
    });

    return log;
}

module.exports = { emitWebhookEvent };