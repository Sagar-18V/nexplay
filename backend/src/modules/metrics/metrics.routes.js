const express = require('express');
const router = express.Router();
const prisma = require('../../config/prisma');
const { reconGatewayQueue, reconRunQueue } = require('../reconciliation/queues/queues');
const { refundQueue } = require('../refunds/refund.queue');
const { webhookQueue } = require('../webhooks/webhook.queue');

router.get('/', async (req, res, next) => {
    try {
        const [gatewayStats, queueCounts] = await Promise.all([
            prisma.gatewayStat.findMany(),
            Promise.all([
                refundQueue.getJobCounts(),
                webhookQueue.getJobCounts(),
                reconGatewayQueue.getJobCounts(),
            ]),
        ]);

        const gateways = gatewayStats.map((g) => ({
            gateway: g.gateway,
            method: g.method,
            successCount: g.successCount,
            failureCount: g.failureCount,
            successRate: g.successCount + g.failureCount > 0
                ? (g.successCount / (g.successCount + g.failureCount) * 100).toFixed(1) + '%'
                : 'n/a',
            avgLatencyMs: g.avgLatencyMs,
        }));

        res.json({
            success: true,
            data: {
                timestamp: new Date().toISOString(),
                gateways,
                queues: {
                    refunds: queueCounts[0],
                    webhooks: queueCounts[1],
                    reconciliation: queueCounts[2],
                },
            },
        });
    } catch (err) { next(err); }
});

module.exports = router;