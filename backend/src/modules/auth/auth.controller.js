const authService = require('./auth.service');

const REFRESH_COOKIE = 'refreshToken';

function refreshCookieOptions() {
    return {
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'strict',
        path: '/v1/auth',
        maxAge: 7 * 24 * 60 * 60 * 1000 // 7 days
    };
}

async function register(req, res, next) {
    try {
        const { name, email, password, webhookUrl } = req.body;

        if (!name || !email || !password) {
            return res.status(400).json({
                success: false,
                message: 'name, email and password are required'
            });
        }

        if (typeof password !== 'string' || password.length < 8) {
            return res.status(400).json({
                success: false,
                message: 'password must be at least 8 characters'
            });
        }

        const emailOk = typeof email === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
        if (!emailOk) {
            return res.status(400).json({
                success: false,
                message: 'a valid email is required'
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

        // set refresh token in httpOnly cookie (scoped to the auth path)
        res.cookie(REFRESH_COOKIE, result.refreshToken, refreshCookieOptions());

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
        const token = req.cookies?.[REFRESH_COOKIE];

        if (!token) {
            return res.status(401).json({
                success: false,
                message: 'Refresh token missing'
            });
        }

        const result = await authService.refresh(token);

        // rotation: replace the cookie with the freshly-issued refresh token
        res.cookie(REFRESH_COOKIE, result.refreshToken, refreshCookieOptions());

        res.json({ success: true, data: { accessToken: result.accessToken } });
    } catch (err) {
        next(err);
    }
}

async function logout(req, res, next) {
    try {
        const token = req.cookies?.[REFRESH_COOKIE];
        await authService.logout(token);

        res.clearCookie(REFRESH_COOKIE, { path: '/v1/auth' });
        res.json({ success: true, message: 'Logged out' });
    } catch (err) {
        next(err);
    }
}

async function me(req, res) {
    res.json({ success: true, data: req.merchant });
}

module.exports = { register, login, refresh, logout, me };
