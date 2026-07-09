/**
 * Payment routing service — selects the best gateway for a given payment.
 *
 * Current strategy: weighted random selection biased by method.
 * In production this would consult GatewayStat success/latency scores.
 */

const GATEWAY_WEIGHTS = {
    CARD: { RAZORX: 40, STRIPEIN: 35, PAYFLOW: 15, SWIFTPAY: 10 },
    UPI: { RAZORX: 60, PAYFLOW: 30, STRIPEIN: 5, SWIFTPAY: 5 },
    NET_BANKING: { RAZORX: 45, PAYFLOW: 35, STRIPEIN: 10, SWIFTPAY: 10 },
    WALLET: { SWIFTPAY: 40, RAZORX: 30, PAYFLOW: 20, STRIPEIN: 10 },
};

/**
 * Selects a gateway using weighted random sampling.
 * @param {{ method: string, amount: number }} params
 * @returns {string} Gateway enum value
 */
function routePayment({ method, amount, exclude = [] }) {
    const weights = GATEWAY_WEIGHTS[method] ?? GATEWAY_WEIGHTS.CARD;
    const adjusted = { ...weights };
    if (amount > 1_000_000) adjusted.SWIFTPAY = Math.floor((adjusted.SWIFTPAY ?? 0) / 2);
    exclude.forEach((g) => delete adjusted[g]);   // remove failed gateways from consideration

    const entries = Object.entries(adjusted);
    if (entries.length === 0) return null;
    const total = entries.reduce((sum, [, w]) => sum + w, 0);
    let r = Math.random() * total;
    for (const [gateway, weight] of entries) { r -= weight; if (r <= 0) return gateway; }
    return entries[0][0];
}

module.exports = { routePayment };
