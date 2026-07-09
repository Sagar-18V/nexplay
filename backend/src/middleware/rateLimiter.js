const redis = require('../config/redis');

const TIERS = {
    write: { limit: 30, windowMs: 60_000 },   // POST /intents, /refunds — 30/min
    read: { limit: 120, windowMs: 60_000 },  // GET listings — 120/min
    auth: { limit: 10, windowMs: 60_000 },   // login/register — 10/min, per-IP not per-key
};

function rateLimit(tier = 'read') {
    const { limit, windowMs } = TIERS[tier];

    return async (req, res, next) => {
        try {
            const identity = req.merchant?.id || req.ip;
            const key = `ratelimit:${tier}:${identity}`;
            const now = Date.now();
            const windowStart = now - windowMs;

            const pipeline = redis.pipeline();
            pipeline.zremrangebyscore(key, 0, windowStart);   // trim old entries
            pipeline.zadd(key, now, `${now}-${Math.random()}`); // unique member
            pipeline.zcard(key);                               // count in window
            pipeline.expire(key, Math.ceil(windowMs / 1000));

            const results = await pipeline.exec();
            const count = results[2][1];

            res.set('X-RateLimit-Limit', limit);
            res.set('X-RateLimit-Remaining', Math.max(0, limit - count));

            if (count > limit) {
                res.set('Retry-After', Math.ceil(windowMs / 1000));
                return res.status(429).json({ success: false, message: 'Rate limit exceeded' });
            }
            next();
        } catch (err) { next(err); }
    };
}

module.exports = { rateLimit };