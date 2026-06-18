const express = require('express');
const router = express.Router();
const { register, login, refresh, logout, me } = require('./auth.controller');
const authenticate = require('../../middleware/authenticate');
const { requireRole } = require('../../middleware/authorize');

router.post('/register', register);
router.post('/login', login);
router.post('/refresh', refresh);
router.post('/logout', logout);
router.get('/me', authenticate, me);

// Example admin-only endpoint demonstrating role-based authorization.
// Lists all merchants — only an ADMIN may call it.
router.get('/merchants', authenticate, requireRole('ADMIN'), async (req, res, next) => {
    try {
        const prisma = require('../../config/prisma');
        const merchants = await prisma.merchant.findMany({
            select: { id: true, name: true, email: true, role: true, isActive: true, createdAt: true },
            orderBy: { createdAt: 'desc' }
        });
        res.json({ success: true, data: merchants });
    } catch (err) {
        next(err);
    }
});

module.exports = router;
