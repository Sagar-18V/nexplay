require('dotenv').config();
const express = require('express');
const app = express();

// Global BigInt JSON serialization support
BigInt.prototype.toJSON = function () {
    return this.toString();
};

const requestLogger = require('./middleware/requestLogger');
app.use(requestLogger);   // before express.json(), so it wraps the whole request lifecycle
app.use(express.json());

const cookieParser = require('cookie-parser');
app.use(cookieParser());


// health check
app.get('/', (req, res) => res.json({ service: 'NexPay API', docs: '/api/health' }));

const cors = require('cors');
app.use(cors({
  origin: process.env.FRONTEND_URL,
  credentials: true,
}));

// routes (we'll add more here each day)
app.use('/v1/auth', require('./modules/auth/auth.routes'));
app.use('/v1/payments', require('./modules/payments/payments.routes'));
app.use('/v1/refunds', require('./modules/refunds/refund.routes'));
app.use('/v1/reconciliation', require('./modules/reconciliation/reconciliation.routes'));
app.use('/v1/webhooks', require('./modules/webhooks/webhook.routes'));
app.use('/v1/metrics', require('./modules/metrics/metrics.routes'));

// BullMQ workers (refund, webhook, reconciliation). Step 6 moved all producers to FastAPI
// + Celery. Drain-and-switch: keep these ON until `python -m app.ops.bullmq_drain` reports
// every queue empty, then set RUN_BULLMQ_WORKERS=0. Set it back to 1 only if you roll the
// write routes back to Express (otherwise their jobs would sit in Redis unprocessed).
if (process.env.RUN_BULLMQ_WORKERS !== '0') {
    require('./workers');
} else {
    console.log('[workers] BullMQ workers disabled (RUN_BULLMQ_WORKERS=0): queues are served by Celery');
}

// global error handler (must be last)
app.use((err, req, res, next) => {
    console.error(JSON.stringify({
        level: 'error',
        requestId: req.requestId,
        message: err.message,
        stack: err.stack,
        path: req.originalUrl,
        timestamp: new Date().toISOString(),
    }));
    res.status(err.status || 500).json({
        success: false,
        message: err.message || 'Internal server error',
        requestId: req.requestId,   // lets the merchant quote this back to you for support
    });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`NexPay running on port ${PORT}`);
});