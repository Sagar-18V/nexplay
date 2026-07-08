const express = require('express');
const router = express.Router();
const prisma = require('../../config/prisma');
const { webhookQueue } = require('./webhook.queue');
const { authenticate } = require('../auth/auth.middleware'); // match your import style

router.get('/failed', authenticate, async (req, res, next) => {
    try {
        const failed = await prisma.webhookLog.findMany({
            where: { merchantId: req.merchant.id, status: 'FAILED' },
            orderBy: { createdAt: 'desc' },
        });
        res.json({ success: true, data: failed });
    } catch (err) { next(err); }
});

router.post('/:id/redeliver', authenticate, async (req, res, next) => {
    try {
        const log = await prisma.webhookLog.findUnique({ where: { id: req.params.id } });
        if (!log || log.merchantId !== req.merchant.id) {
            return res.status(404).json({ success: false, message: 'Webhook not found' });
        }
        if (log.status === 'DELIVERED') {
            return res.status(422).json({ success: false, message: 'Already delivered' });
        }
        await prisma.webhookLog.update({
            where: { id: log.id },
            data: { status: 'PENDING' },
        });
        // fresh jobId — the original is burned in BullMQ's dedup set
        await webhookQueue.add('deliver', { webhookLogId: log.id }, {
            jobId: `webhook-${log.id}-redeliver-${Date.now()}`,
            attempts: 3,
            backoff: { type: 'exponential', delay: 2000 },
        });
        res.json({ success: true, message: 'Redelivery queued' });
    } catch (err) { next(err); }
});

module.exports = router;