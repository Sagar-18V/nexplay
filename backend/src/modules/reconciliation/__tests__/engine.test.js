const { reconcile } = require('../reconciliationEngine');

const payments = [
    { id: 'p1', amount: 10000n, status: 'CAPTURED' },   // will match
    { id: 'p2', amount: 25000n, status: 'CAPTURED' },   // amount mismatch
    { id: 'p3', amount: 5000n, status: 'FAILED' },     // missing at gateway
];

const file = {
    total_settled_amount: 10000 + 24500 + 7777,
    records: [
        { our_ref: 'p1', gateway_txn_ref: 'RAZ_1', amount: 10000, status: 'settled' },
        { our_ref: 'p2', gateway_txn_ref: 'RAZ_2', amount: 24500, status: 'settled' },
        { our_ref: null, gateway_txn_ref: 'RAZ_ORPH_1', amount: 7777, status: 'settled' },
    ],
};

const { summary, discrepancies } = reconcile(payments, file);
console.log(summary);
// matchedCount: 1, discrepancyCount: 3
console.log(discrepancies.map((d) => d.type));
// ['AMOUNT_MISMATCH', 'MISSING_AT_GATEWAY', 'MISSING_IN_DB']