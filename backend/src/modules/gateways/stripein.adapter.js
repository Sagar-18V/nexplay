const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rand = (min, max) => Math.floor(Math.random() * (max - min) + min);

async function processPayment({ amount, method }) {
    const latencyMs = rand(400, 1200); // international = slower
    await sleep(latencyMs);

    // StripeIN only does cards — hard reject anything else
    if (method !== 'CARD') {
        return { success: false, latencyMs, error: 'unsupported_method', retryable: false };
    }
    if (Math.random() > 0.93) {
        return { success: false, latencyMs, error: 'issuer_declined', retryable: Math.random() < 0.4 };
    }
    return {
        success: true, latencyMs,
        gatewayTxnId: `str_${Date.now()}_${rand(1000, 9999)}`,
        feeAmount: Math.round(amount * 0.029) + 300,   // 2.9% + ₹3 flat — priciest
    };
}

async function processRefund({ amount }) {
    await sleep(rand(500, 1500));
    if (Math.random() > 0.95) return { success: false, error: 'processing_error', retryable: true };
    return { success: true, gatewayRefundRef: `str_rf_${Date.now()}_${rand(1000, 9999)}` };
}

module.exports = { name: 'STRIPEIN', processPayment, processRefund };