/**
 * RazorX — the reliable one. Strong on cards, 2% fee.
 * All adapters share this interface: processPayment, processRefund.
 */
const BASE = { successRate: 0.95, minLatency: 200, maxLatency: 800, feePercent: 2.0 };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rand = (min, max) => Math.floor(Math.random() * (max - min) + min);

async function processPayment({ amount, method, intentId }) {
    const latencyMs = rand(BASE.minLatency, BASE.maxLatency);
    await sleep(latencyMs);

    // method affinity: cards are RazorX's home turf
    const effectiveRate = method === 'CARD' ? 0.97 : BASE.successRate - 0.05;

    if (Math.random() > effectiveRate) {
        return {
            success: false,
            latencyMs,
            error: ['insufficient_funds', 'bank_timeout', 'card_declined'][rand(0, 3)],
            retryable: Math.random() < 0.5,
        };
    }

    return {
        success: true,
        latencyMs,
        gatewayTxnId: `rzx_${Date.now()}_${rand(1000, 9999)}`,
        feeAmount: Math.round(amount * (BASE.feePercent / 100)),
    };
}

async function processRefund({ gatewayTxnId, amount, refundId }) {
    await sleep(rand(300, 1000));
    if (Math.random() > 0.97) {
        return { success: false, error: 'gateway_timeout', retryable: true };
    }
    return { success: true, gatewayRefundRef: `rzx_rf_${Date.now()}_${rand(1000, 9999)}` };
}

module.exports = { name: 'RAZORX', processPayment, processRefund };