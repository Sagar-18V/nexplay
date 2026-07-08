require('dotenv').config();
const express = require('express');
const app = express();

app.use(express.json());

const cookieParser = require('cookie-parser');
app.use(cookieParser());

// health check
app.get('/', (req, res) => res.json({ service: 'NexPay API', docs: '/api/health' }));


// routes (we'll add more here each day)
app.use('/v1/auth', require('./modules/auth/auth.routes'));
app.use('/v1/payments', require('./modules/payments/payments.routes'));
app.use('/v1/refunds', require('./modules/refunds/refund.routes'));

// Start BullMQ workers (refund + reconciliation)
require('./workers');

// global error handler
app.use((err, req, res, next) => {
    console.error(err);
    res.status(err.status || 500).json({
        success: false,
        message: err.message || 'Internal server error'
    });
});

app.use('/v1/reconciliation', require('./modules/reconciliation/reconciliation.routes'));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`NexPay running on port ${PORT}`);
});