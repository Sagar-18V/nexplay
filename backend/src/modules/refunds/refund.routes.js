const express = require('express');
const router = express.Router();
const authenticate = require('../../middleware/authenticate');
const { createRefund } = require('./refund.service');
const AppError = require('../../utils/AppError');
const prisma = require('../../config/prisma');

/**
 * POST /v1/refunds/transactions/:txnId
 * Initiate a (partial or full) refund on a successful transaction.
 *
 * Requires Idempotency-Key header — safe to retry on network errors.
 */
router.post('/transactions/:txnId', authenticate, async (req, res, next) => {
    try {
        const idempotencyKey = req.headers['idempotency-key'];
        if (!idempotencyKey) {
            throw new AppError('Idempotency-Key header is required', 400);
        }

        // Idempotency: return existing refund for this key
        const existing = await prisma.refund.findUnique({ where: { idempotencyKey } });
        if (existing) {
            return res.status(200).json({ success: true, data: existing });
        }

        const refund = await createRefund({
            transactionId: req.params.txnId,
            merchantId: req.merchant.id,
            amount: req.body.amount,
            reason: req.body.reason,
            idempotencyKey,
        });

        res.status(202).json({ success: true, data: refund });
    } catch (err) {
        next(err);
    }
});

/**
 * GET /v1/refunds/:refundId
 * Poll the status of a specific refund.
 */
router.get('/:refundId', authenticate, async (req, res, next) => {
    try {
        const refund = await prisma.refund.findFirst({
            where: { id: req.params.refundId, merchantId: req.merchant.id },
        });

        if (!refund) throw new AppError('Refund not found', 404);

        res.json({ success: true, data: refund });
    } catch (err) {
        next(err);
    }
});

/**
 * GET /v1/refunds
 * List all refunds for the authenticated merchant.
 */
router.get('/', authenticate, async (req, res, next) => {
    try {
        const { status, limit = 20, offset = 0 } = req.query;

        const where = { merchantId: req.merchant.id };
        if (status) where.status = status;

        const [refunds, total] = await Promise.all([
            prisma.refund.findMany({
                where,
                orderBy: { createdAt: 'desc' },
                take: Number(limit),
                skip: Number(offset),
            }),
            prisma.refund.count({ where }),
        ]);

        res.json({ success: true, data: refunds, meta: { total, limit: Number(limit), offset: Number(offset) } });
    } catch (err) {
        next(err);
    }
});

module.exports = router;
