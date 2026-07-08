const express = require('express');
const crypto = require('crypto');
const app = express();

const API_KEY = '922eb9e6-1a4a-4bcd-b9bb-6afd9f180dab'; // your merchant's apiKey

app.use(express.raw({ type: 'application/json' }));  // raw body — sign what arrived

app.post('/webhook', (req, res) => {
    const expected = crypto.createHmac('sha256', API_KEY).update(req.body).digest('hex');
    const received = req.headers['x-nexpay-signature'];
    const valid = crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(received || ''.padEnd(64, '0')));

    const body = JSON.parse(req.body);
    console.log(`[${new Date().toISOString()}] ${body.event} | signature ${valid ? 'VALID ✓' : 'INVALID ✗'}`);
    console.log(JSON.stringify(body.payload, null, 2));
    res.json({ received: true });
});

app.listen(4000, () => console.log('Webhook receiver on :4000'));