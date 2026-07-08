const express = require('express');
const router = express.Router();
const prisma = require('../../config/prisma');
const authenticate = require('../../middleware/authenticate');
const AppError = require('../../utils/AppError');
const { routePayment } = require('../routing/routing.service');
const { getGatewayAdapter } = require('../gateways');
const { writeCaptureEntries } = require('../ledger/ledger.service');
const { emitWebhookEvent } = require('../webhooks/webhook.service');

/**
 * POST /v1/payments/intents/:id/process
 * Executes the intent's pending transaction through its assigned gateway.
 */
router.post('/intents/:id/process', authenticate, async (req, res, next) => {
    try {
        const intent = await prisma.paymentIntent.findUnique({ where: { id: req.params.id } });
        if (!intent || intent.merchantId !== req.merchant.id) {
            return res.status(404).json({ success: false, message: 'Intent not found' });
        }
        if (intent.status !== 'CREATED') {
            return res.status(422).json({ success: false, message: `Intent is ${intent.status}, cannot process` });
        }

        // 1. Reuse the PENDING transaction created at intent time (routing already ran)
        const txn = await prisma.transaction.findFirst({
            where: { intentId: intent.id, status: 'PENDING' },
        });
        if (!txn) {
            return res.status(422).json({ success: false, message: 'No pending transaction on this intent' });
        }
        const gateway = txn.gateway;

        await prisma.paymentIntent.update({
            where: { id: intent.id },
            data: { status: 'PROCESSING' },
        });

        // 2. Gateway call — outside any DB transaction (never hold locks across network I/O)
        const adapter = getGatewayAdapter(gateway);
        const result = await adapter.processPayment({
            amount: intent.amount, method: intent.method, intentId: intent.id,
        });

        // 3. Persist outcome atomically
        if (result.success) {
            await prisma.$transaction(async (tx) => {
                await tx.transaction.update({
                    where: { id: txn.id },
                    data: {
                        status: 'SUCCESS',
                        gatewayTxnId: result.gatewayTxnId,
                        latencyMs: result.latencyMs,
                        feeAmount: result.feeAmount,
                    },
                });
                await tx.paymentIntent.update({
                    where: { id: intent.id },
                    data: { status: 'SUCCESS' },
                });
                await writeCaptureEntries(tx, {
                    txnId: txn.id, amount: intent.amount, feeAmount: result.feeAmount,
                });
                await tx.gatewayStat.upsert({
                    where: { gateway_method: { gateway, method: intent.method } },
                    create: { gateway, method: intent.method, successCount: 1, avgLatencyMs: result.latencyMs },
                    update: {
                        successCount: { increment: 1 },
                        avgLatencyMs: result.latencyMs,
                        lastUpdated: new Date(),
                    },
                });
            });

            // 4a. Announce AFTER commit
            await emitWebhookEvent(intent.merchantId, 'payment.success', {
                intent_id: intent.id, transaction_id: txn.id,
                amount: intent.amount, gateway, method: intent.method,
            });
        } else {
            await prisma.$transaction(async (tx) => {
                await tx.transaction.update({
                    where: { id: txn.id },
                    data: { status: 'FAILED', latencyMs: result.latencyMs, failureReason: result.error },
                });
                await tx.paymentIntent.update({
                    where: { id: intent.id },
                    data: { status: 'FAILED' },
                });
                await tx.gatewayStat.upsert({
                    where: { gateway_method: { gateway, method: intent.method } },
                    create: { gateway, method: intent.method, failureCount: 1 },
                    update: { failureCount: { increment: 1 }, lastUpdated: new Date() },
                });
            });

            // 4b. Failures are announcements too
            await emitWebhookEvent(intent.merchantId, 'payment.failed', {
                intent_id: intent.id, transaction_id: txn.id,
                amount: intent.amount, gateway, reason: result.error,
            });
        }

        const finalTxn = await prisma.transaction.findUnique({ where: { id: txn.id } });
        res.json({ success: true, data: { gateway, transaction: finalTxn } });
    } catch (err) { next(err); }
});

module.exports = router;