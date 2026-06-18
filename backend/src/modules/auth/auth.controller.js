const authService = require('./auth.service');

async function register(req, res, next) {
    try {
        const { name, email, password, webhookUrl } = req.body;

        if (!name || !email || !password) {
            return res.status(400).json({
                success: false,
                message: 'name, email and password are required'
            });
        }

        const result = await authService.register({ name, email, password, webhookUrl });
        res.status(201).json({ success: true, data: result });
    } catch (err) {
        next(err);
    }
}

async function login(req, res, next) {
    try {
        const { email, password } = req.body;

        if (!email || !password) {
            return res.status(400).json({
                success: false,
                message: 'email and password are required'
            });
        }

        const result = await authService.login({ email, password });

        // set refresh token in httpOnly cookie
        res.cookie('refreshToken', result.refreshToken, {
            httpOnly: true,
            secure: process.env.NODE_ENV === 'production',
            sameSite: 'strict',
            maxAge: 7 * 24 * 60 * 60 * 1000 // 7 days
        });

        res.json({
            success: true,
            data: {
                accessToken: result.accessToken,
                merchant: result.merchant
            }
        });
    } catch (err) {
        next(err);
    }
}

async function refresh(req, res, next) {
    try {
        const token = req.cookies?.refreshToken;

        if (!token) {
            return res.status(401).json({
                success: false,
                message: 'Refresh token missing'
            });
        }

        const result = await authService.refresh(token);
        res.json({ success: true, data: { accessToken: result.accessToken } });
    } catch (err) {
        next(err);
    }
}

async function me(req, res) {
    res.json({ success: true, data: req.merchant });
}

module.exports = { register, login, refresh, me };