const express = require('express');
const router = express.Router();
const prisma = require('../../config/prisma');
const authenticate = require('../../middleware/authenticate');
const AppError = require('../../utils/AppError');
const { routePayment } = require('../routing/routing.service');
const { getGatewayAdapter } = require('../gateways');
const { writeCaptureEntries } = require('../ledger/ledger.service');
const { emitWebhookEvent } = require('../webhooks/webhook.service');
const { rateLimit } = require('../../middleware/rateLimiter');

const FALLBACK_ORDER_BASE = ['RAZORX', 'STRIPEIN', 'PAYFLOW', 'SWIFTPAY'];

async function attemptWithFallback({ intent, firstGateway }) {
    const tried = [];
    let gateway = firstGateway;
    let lastTxn = null;
    let lastResult = null;

    for (let attempt = 0; attempt < 3; attempt++) {
        tried.push(gateway);

        const txn = attempt === 0
            ? await prisma.transaction.findFirst({ where: { intentId: intent.id, status: 'PENDING' } })
            : await prisma.transaction.create({ data: { intentId: intent.id, gateway, amount: intent.amount } });

        const adapter = getGatewayAdapter(gateway);
        const result = await adapter.processPayment({ amount: intent.amount, method: intent.method, intentId: intent.id });

        lastTxn = txn; lastResult = result;
        if (result.success) return { txn, result, tried };

        await prisma.transaction.update({
            where: { id: txn.id },
            data: { status: 'FAILED', latencyMs: result.latencyMs, failureReason: result.error },
        });

        // pick next untried gateway by weighted preference, excluding ones already tried
        const remaining = FALLBACK_ORDER_BASE.filter((g) => !tried.includes(g));
        if (remaining.length === 0) break;
        gateway = routePayment({ method: intent.method, amount: intent.amount, exclude: tried })
            ?? remaining[0];
    }
    return { txn: lastTxn, result: lastResult, tried, exhausted: true };
}
/**
 * POST /v1/payments/intents
 * Create a payment intent and route it to a gateway.
 */
router.post('/intents', authenticate, rateLimit('write'), async (req, res, next) => {
    try {
        const { amount, method, currency = 'INR', metadata } = req.body;

        if (!amount || !method) {
            throw new AppError('amount and method are required', 400);
        }
        if (!Number.isInteger(amount) || amount <= 0) {
            throw new AppError('amount must be a positive integer (paise)', 400);
        }

        const idempotencyKey = req.headers['idempotency-key'];
        if (!idempotencyKey) {
            throw new AppError('Idempotency-Key header is required', 400);
        }

        // Idempotency: return existing intent if key already used
        const existing = await prisma.paymentIntent.findUnique({
            where: { idempotencyKey },
        });
        if (existing) {
            // Keys are globally unique: never hand another merchant's intent back (D14).
            if (existing.merchantId !== req.merchant.id) {
                throw new AppError('Idempotency-Key is already in use; use a unique key per request', 409);
            }
            return res.status(200).json({ success: true, data: existing });
        }

        // Route to best gateway
        const gateway = await routePayment({ method, amount });

        const intent = await prisma.paymentIntent.create({
            data: {
                merchantId: req.merchant.id,
                amount,
                currency,
                method,
                idempotencyKey,
                metadata: metadata ?? undefined,
                transactions: {
                    create: {
                        gateway,
                        amount,
                        status: 'PENDING',
                    },
                },
            },
            include: { transactions: true },
        });

        res.status(201).json({ success: true, data: intent });
    } catch (err) {
        next(err);
    }
});

/**
 * GET /v1/payments/intents
 * List payment intents for the authenticated merchant.
 */
router.get('/intents', authenticate, rateLimit('read'), async (req, res, next) => {
    try {
        const { status, limit = 20, offset = 0 } = req.query;

        const where = { merchantId: req.merchant.id };
        if (status) where.status = status;

        const [intents, total] = await Promise.all([
            prisma.paymentIntent.findMany({
                where,
                orderBy: { createdAt: 'desc' },
                take: Number(limit),
                skip: Number(offset),
                include: { transactions: { orderBy: { createdAt: 'desc' }, take: 1 } },
            }),
            prisma.paymentIntent.count({ where }),
        ]);

        res.json({ success: true, data: intents, meta: { total, limit: Number(limit), offset: Number(offset) } });
    } catch (err) {
        next(err);
    }
});

/**
 * GET /v1/payments/intents/:id
 * Get a single payment intent with all transactions.
 */
router.get('/intents/:id', authenticate, async (req, res, next) => {
    try {
        const intent = await prisma.paymentIntent.findFirst({
            where: { id: req.params.id, merchantId: req.merchant.id },
            include: { transactions: { orderBy: { createdAt: 'asc' } } },
        });

        if (!intent) throw new AppError('Payment intent not found', 404);

        res.json({ success: true, data: intent });
    } catch (err) {
        next(err);
    }
});

/**
 * POST /v1/payments/intents/:id/process
 * Executes the intent's pending transaction through its assigned gateway.
 */
router.post('/intents/:id/process', authenticate, rateLimit('write'), async (req, res, next) => {
    try {
        const intent = await prisma.paymentIntent.findUnique({ where: { id: req.params.id } });
        if (!intent || intent.merchantId !== req.merchant.id) {
            return res.status(404).json({ success: false, message: 'Intent not found' });
        }
        if (intent.status !== 'CREATED') {
            return res.status(422).json({ success: false, message: `Intent is ${intent.status}, cannot process` });
        }

        // 1. Reuse the PENDING transaction created at intent time (routing already picked a first gateway)
        const pendingTxn = await prisma.transaction.findFirst({
            where: { intentId: intent.id, status: 'PENDING' },
        });
        if (!pendingTxn) {
            return res.status(422).json({ success: false, message: 'No pending transaction on this intent' });
        }

        // Atomic claim (D13): only one concurrent caller can flip CREATED -> PROCESSING.
        // The status check above is a read; without this, N parallel calls charged N times.
        const claimed = await prisma.paymentIntent.updateMany({
            where: { id: intent.id, status: 'CREATED' },
            data: { status: 'PROCESSING' },
        });
        if (claimed.count === 0) {
            const current = await prisma.paymentIntent.findUnique({ where: { id: intent.id } });
            return res.status(422).json({ success: false, message: `Intent is ${current.status}, cannot process` });
        }

        // 2. Fallback loop — tries up to 3 gateways, outside any DB transaction
        const { txn, result, tried, exhausted } = await attemptWithFallback({
            intent, firstGateway: pendingTxn.gateway,
        });
        const gateway = txn.gateway;

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

            await emitWebhookEvent(intent.merchantId, 'payment.success', {
                intent_id: intent.id, transaction_id: txn.id,
                amount: intent.amount, gateway, method: intent.method,
                fallback_chain: tried,   // visibility into which gateways were tried
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

            await emitWebhookEvent(intent.merchantId, 'payment.failed', {
                intent_id: intent.id, transaction_id: txn.id,
                amount: intent.amount, gateway, reason: result.error,
                fallback_chain: tried, exhausted,
            });
        }

        const allTxns = await prisma.transaction.findMany({
            where: { intentId: intent.id },
            orderBy: { createdAt: 'asc' },
        });
        res.json({ success: true, data: { gateway, tried, transactions: allTxns } });
    } catch (err) { next(err); }
});

module.exports = router;