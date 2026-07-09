// src/middleware/requestLogger.js
const crypto = require('crypto');

function requestLogger(req, res, next) {
    req.requestId = crypto.randomUUID();
    const start = Date.now();

    res.on('finish', () => {
        console.log(JSON.stringify({
            requestId: req.requestId,
            method: req.method,
            path: req.originalUrl,
            status: res.statusCode,
            durationMs: Date.now() - start,
            merchantId: req.merchant?.id ?? null,
            timestamp: new Date().toISOString(),
        }));
    });

    next();
}

module.exports = requestLogger;