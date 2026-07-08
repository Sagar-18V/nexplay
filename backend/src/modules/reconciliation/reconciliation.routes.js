const express = require('express');
const router = express.Router();
const prisma = require('../../config/prisma');
const authenticate = require('../../middleware/authenticate');

/**
 * GET /v1/reconciliation/runs
 * List reconciliation runs with per-gateway job summary.
 * Platform-wide (not merchant-scoped) — recon reflects gateway-level truth.
 */
router.get('/runs', authenticate, async (req, res, next) => {
    try {
        const runs = await prisma.reconciliationRun.findMany({
            orderBy: { runDate: 'desc' },
            take: 30,
            include: { gatewayJobs: true },
        });
        res.json({ success: true, data: runs });
    } catch (err) { next(err); }
});

/**
 * GET /v1/reconciliation/runs/:id
 * One run, all gateway jobs, all discrepancies.
 */
router.get('/runs/:id', authenticate, async (req, res, next) => {
    try {
        const run = await prisma.reconciliationRun.findUnique({
            where: { id: req.params.id },
            include: {
                gatewayJobs: {
                    include: { discrepancies: { orderBy: { createdAt: 'desc' } } },
                },
            },
        });
        if (!run) return res.status(404).json({ success: false, message: 'Run not found' });
        res.json({ success: true, data: run });
    } catch (err) { next(err); }
});

/**
 * POST /v1/reconciliation/runs/trigger
 * Manual trigger for demo purposes — real system waits for the 2 AM scheduler.
 */
router.post('/runs/trigger', authenticate, async (req, res, next) => {
    try {
        const { createReconciliationFlow } = require('./queues/createReconciliationFlow');
        const runDate = req.body.runDate ? new Date(req.body.runDate) : (() => {
            const d = new Date(); d.setUTCDate(d.getUTCDate() - 1); d.setUTCHours(0, 0, 0, 0); return d;
        })();
        const run = await createReconciliationFlow(runDate);
        if (!run) return res.status(409).json({ success: false, message: 'Run already exists for this date' });
        res.status(202).json({ success: true, data: run });
    } catch (err) { next(err); }
});

module.exports = router;