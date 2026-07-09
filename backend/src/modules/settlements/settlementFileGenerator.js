const prisma = require('../../config/prisma');

/**
 * Discrepancy injection rates per gateway — personalities carry through.
 * SwiftPay is the sloppiest (it's weak on high-value anyway),
 * RazorX is the cleanest.
 */
const GATEWAY_PROFILES = {
    RAZORX: { dropRate: 0.02, orphanRate: 0.01, amountRate: 0.02, statusRate: 0.02 },
    STRIPEIN: { dropRate: 0.03, orphanRate: 0.02, amountRate: 0.03, statusRate: 0.02 },
    PAYFLOW: { dropRate: 0.04, orphanRate: 0.02, amountRate: 0.03, statusRate: 0.03 },
    SWIFTPAY: { dropRate: 0.06, orphanRate: 0.04, amountRate: 0.05, statusRate: 0.05 },
};

// Gateway's view of status — deliberately different vocab than ours,
// so the recon engine must normalize (real gateways never share your enum)
const STATUS_MAP = { SUCCESS: 'settled', FAILED: 'failure' };

/**
 * Deterministic PRNG (mulberry32) seeded from gateway+date.
 * Same date + gateway => same file every time. Crucial for:
 *  - retries reprocessing identical data (idempotent reconciliation)
 *  - demo repeatability
 */
function seededRandom(seedStr) {
    let h = 1779033703 ^ seedStr.length;
    for (let i = 0; i < seedStr.length; i++) {
        h = Math.imul(h ^ seedStr.charCodeAt(i), 3432918353);
        h = (h << 13) | (h >>> 19);
    }
    let a = h >>> 0;
    return function () {
        a |= 0; a = (a + 0x6d2b79f5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

/**
 * Generates a settlement file for one gateway for one settlement date.
 * Returns the gateway's "report": what THEY claim happened.
 */
async function generateSettlementFile(gateway, runDate) {
    const dayStart = new Date(runDate);
    dayStart.setUTCHours(0, 0, 0, 0);
    const dayEnd = new Date(dayStart);
    dayEnd.setUTCDate(dayEnd.getUTCDate() + 1);

    // Our side of the truth: terminal-state payments routed to this gateway
    const payments = await prisma.transaction.findMany({
        where: {
            gateway,
            status: { in: ['SUCCESS', 'FAILED'] },
            createdAt: { gte: dayStart, lt: dayEnd },
        },
        orderBy: { createdAt: 'asc' },
    });

    const profile = GATEWAY_PROFILES[gateway];
    const rand = seededRandom(`${gateway}:${dayStart.toISOString().slice(0, 10)}`);
    const records = [];

    for (const p of payments) {
        const roll = rand();

        // 1. Drop => MISSING_AT_GATEWAY (we have it, their file doesn't)
        if (roll < profile.dropRate) continue;

        let amountPaise = Number(p.amount);
        let status = STATUS_MAP[p.status];

        // 2. Amount corruption => AMOUNT_MISMATCH
        if (roll < profile.dropRate + profile.amountRate) {
            // realistic corruptions: off-by-small (fee deducted wrongly) or paise/rupee slip
            amountPaise = rand() < 0.5
                ? amountPaise - Math.floor(rand() * 500)   // small unexplained deduction
                : Math.round(amountPaise / 100);           // classic paise-vs-rupee bug
        }
        // 3. Status disagreement => STATUS_MISMATCH
        else if (roll < profile.dropRate + profile.amountRate + profile.statusRate) {
            status = status === 'settled' ? 'failure' : 'settled';
        }

        records.push({
            gateway_txn_ref: `${gateway.slice(0, 3)}_${p.gatewayReferenceId || p.id}`,
            our_ref: p.id,                    // gateways echo back merchant reference
            amount: amountPaise,
            currency: 'INR',
            status,
            settled_at: p.updatedAt.toISOString(),
        });
    }

    // 4. Orphans => MISSING_IN_DB (their file has txns we never recorded)
    const orphanCount = Math.floor(payments.length * profile.orphanRate) || (rand() < 0.3 ? 1 : 0);
    for (let i = 0; i < orphanCount; i++) {
        records.push({
            gateway_txn_ref: `${gateway.slice(0, 3)}_ORPH_${dayStart.getTime()}_${i}`,
            our_ref: null,                    // no merchant reference — we never saw this
            amount: Math.floor(rand() * 500000) + 10000,  // ₹100–₹5100 in paise
            currency: 'INR',
            status: 'settled',
            settled_at: new Date(dayStart.getTime() + rand() * 86400000).toISOString(),
        });
    }

    return {
        gateway,
        settlement_date: dayStart.toISOString().slice(0, 10),
        record_count: records.length,
        total_settled_amount: records
            .filter((r) => r.status === 'settled')
            .reduce((sum, r) => sum + r.amount, 0),
        records,
    };
}

module.exports = { generateSettlementFile, GATEWAY_PROFILES };