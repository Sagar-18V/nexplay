// src/middleware/requestLogger.js
const crypto = require('crypto');

function requestLogger(req, res, next) {
    // Reuse the gateway's id (nginx sets X-Request-Id) so a request is traceable
    // across gateway, Express and FastAPI logs. Fall back for direct calls.
    req.requestId = req.get('x-request-id') || crypto.randomUUID();
    res.set('X-Request-Id', req.requestId);
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