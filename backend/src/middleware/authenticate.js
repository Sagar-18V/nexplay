const jwt = require('jsonwebtoken');
const prisma = require('../config/prisma');

async function authenticate(req, res, next) {
    try {
        const authHeader = req.headers.authorization;

        if (!authHeader || !authHeader.startsWith('Bearer ')) {
            return res.status(401).json({
                success: false,
                message: 'Authorization header missing'
            });
        }

        const token = authHeader.split(' ')[1];
        const payload = jwt.verify(token, process.env.JWT_SECRET);

        const merchant = await prisma.merchant.findUnique({
            where: { id: payload.merchantId },
            select: {
                id: true,
                name: true,
                email: true,
                apiKey: true,
                isActive: true
            }
        });

        if (!merchant || !merchant.isActive) {
            return res.status(401).json({
                success: false,
                message: 'Merchant not found or inactive'
            });
        }

        req.merchant = merchant;
        next();
    } catch (err) {
        return res.status(401).json({
            success: false,
            message: 'Invalid or expired token'
        });
    }
}

module.exports = authenticate;