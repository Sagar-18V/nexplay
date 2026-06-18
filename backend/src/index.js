require('dotenv').config();
const express = require('express');
const app = express();

app.use(express.json());

const cookieParser = require('cookie-parser');
app.use(cookieParser());

// health check
app.get('/health', (req, res) => {
    res.json({ status: 'ok', service: 'NexPay API', version: 'v1' });
});

// routes (we'll add more here each day)
app.use('/v1/auth', require('./modules/auth/auth.routes'));

// global error handler
app.use((err, req, res, next) => {
    console.error(err);
    res.status(err.status || 500).json({
        success: false,
        message: err.message || 'Internal server error'
    });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`NexPay running on port ${PORT}`);
});