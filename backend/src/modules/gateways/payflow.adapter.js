const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rand = (min, max) => Math.floor(Math.random() * (max - min) + min);

async function processPayment({ amount, method }) {
    const latencyMs = rand(150, 500);   // domestic rails, fast
    await sleep(latencyMs);

    const affinity = { UPI: 0.96, NET_BANKING: 0.94, CARD: 0.85, WALLET: 0.82 };
    if (Math.random() > (affinity[method] ?? 0.85)) {
        return { success: false, latencyMs, error: ['upi_timeout', 'bank_unavailable'][rand(0, 2)], retryable: Math.random() < 0.6 };
    }
    return {
        success: true, latencyMs,
        gatewayTxnId: `pfl_${Date.now()}_${rand(1000, 9999)}`,
        feeAmount: method === 'UPI' ? 0 : Math.round(amount * 0.012),  // UPI free, else 1.2%
    };
}

async function processRefund({ amount }) {
    await sleep(rand(200, 800));
    if (Math.random() > 0.96) return { success: false, error: 'npci_delay', retryable: true };
    return { success: true, gatewayRefundRef: `pfl_rf_${Date.now()}_${rand(1000, 9999)}` };
}

module.exports = { name: 'PAYFLOW', processPayment, processRefund };