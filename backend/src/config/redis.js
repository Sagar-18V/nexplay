const { Redis } = require('ioredis');

// General-purpose Redis client (for caching, pub/sub, etc.)
const redis = new Redis(process.env.REDIS_URL);
redis.on('connect', () => console.log('Redis connected'));
redis.on('error', (err) => console.error('Redis error:', err));

/**
 * BullMQ connection options — passed as a plain object, NOT an ioredis instance.
 * When BullMQ receives options it creates its own internal connections and
 * automatically sets maxRetriesPerRequest: null (required for blocking commands
 * like BLMOVE that Workers use). If you pass an ioredis instance instead,
 * BullMQ validates that maxRetriesPerRequest === null and throws if it isn't.
 */
const bullmqConnection = (() => {
    const url = new URL(process.env.REDIS_URL);
    return {
        host: url.hostname,
        port: Number(url.port) || 6379,
        ...(url.password ? { password: decodeURIComponent(url.password) } : {}),
        ...(url.username && url.username !== 'default' ? { username: url.username } : {}),
        ...(url.protocol === 'rediss:' ? { tls: {} } : {}),
    };
})();

module.exports = redis;
module.exports.bullmqConnection = bullmqConnection;