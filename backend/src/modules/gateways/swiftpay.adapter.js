const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rand = (min, max) => Math.floor(Math.random() * (max - min) + min);

async function processPayment({ amount, method }) {
    const latencyMs = rand(100, 400);   // fastest when it works
    await sleep(latencyMs);

    let rate = method === 'WALLET' ? 0.95 : 0.88;
    if (amount > 5_000_000) rate -= 0.25;        // > ₹50k: falls apart
    else if (amount > 1_000_000) rate -= 0.10;   // > ₹10k: shaky

    if (Math.random() > rate) {
        return { success: false, latencyMs, error: ['wallet_limit_exceeded', 'gateway_overloaded', 'timeout'][rand(0, 3)], retryable: Math.random() < 0.7 };
    }
    return {
        success: true, latencyMs,
        gatewayTxnId: `swp_${Date.now()}_${rand(1000, 9999)}`,
        feeAmount: Math.round(amount * 0.008),      // cheapest: 0.8%
    };
}

async function processRefund({ amount }) {
    await sleep(rand(300, 2000));
    if (Math.random() > 0.90) {                   // the flaky refunder — your retry demo
        return { success: false, error: 'refund_queue_full', retryable: true };
    }
    return { success: true, gatewayRefundRef: `swp_rf_${Date.now()}_${rand(1000, 9999)}` };
}

module.exports = { name: 'SWIFTPAY', processPayment, processRefund };