/**
 * Reconciliation Engine — pure function, no DB, no queue.
 * Input:  our payments + gateway settlement file
 * Output: { summary, discrepancies }
 *
 * Being pure makes it unit-testable and reusable
 * (same engine could recon a re-uploaded file, an API pull, etc.)
 */

// Normalize gateway dialect -> our vocabulary (inverse of generator's STATUS_MAP)
const GATEWAY_STATUS_MAP = {
    settled: 'SUCCESS',
    failure: 'FAILED',
    reversed: 'REFUNDED',
};

/**
 * @param {Array} payments  - our DB records for this gateway+window
 *                            [{ id, amount (BigInt|number, paise), status }]
 * @param {Object} settlementFile - output of generateSettlementFile
 * @returns {{ summary: Object, discrepancies: Array }}
 */
function reconcile(payments, settlementFile) {
    const discrepancies = [];

    // Index both sides by the shared key: our payment id (their `our_ref`)
    const dbById = new Map(payments.map((p) => [p.id, p]));

    const fileByRef = new Map();
    const orphanRecords = [];
    for (const rec of settlementFile.records) {
        if (rec.our_ref === null) {
            orphanRecords.push(rec);        // no key to match on — orphan by definition
        } else {
            fileByRef.set(rec.our_ref, rec);
        }
    }

    let matchedCount = 0;

    // Pass 1: walk OUR records, look them up in THEIR file
    for (const payment of payments) {
        const fileRec = fileByRef.get(payment.id);

        if (!fileRec) {
            discrepancies.push({
                type: 'MISSING_AT_GATEWAY',
                paymentId: payment.id,
                gatewayTxnRef: null,
                ourAmount: BigInt(payment.amount),
                gatewayAmount: null,
                ourStatus: payment.status,
                gatewayStatus: null,
            });
            continue;
        }

        const ourAmount = BigInt(payment.amount);
        const gwAmount = BigInt(fileRec.amount);
        const gwStatus = GATEWAY_STATUS_MAP[fileRec.status] ?? `UNKNOWN(${fileRec.status})`;

        const amountMatches = ourAmount === gwAmount;
        const statusMatches = gwStatus === payment.status;

        if (amountMatches && statusMatches) {
            matchedCount++;
        } else if (!amountMatches) {
            // Amount wins classification priority — money errors outrank status errors
            discrepancies.push({
                type: 'AMOUNT_MISMATCH',
                paymentId: payment.id,
                gatewayTxnRef: fileRec.gateway_txn_ref,
                ourAmount,
                gatewayAmount: gwAmount,
                ourStatus: payment.status,
                gatewayStatus: gwStatus,
            });
        } else {
            discrepancies.push({
                type: 'STATUS_MISMATCH',
                paymentId: payment.id,
                gatewayTxnRef: fileRec.gateway_txn_ref,
                ourAmount,
                gatewayAmount: gwAmount,
                ourStatus: payment.status,
                gatewayStatus: gwStatus,
            });
        }

        fileByRef.delete(payment.id);     // consumed — leftovers are file-side extras
    }

    // Pass 2: leftovers in their file + explicit orphans => MISSING_IN_DB
    const unmatchedFileRecords = [...fileByRef.values(), ...orphanRecords];
    for (const rec of unmatchedFileRecords) {
        discrepancies.push({
            type: 'MISSING_IN_DB',
            paymentId: null,
            gatewayTxnRef: rec.gateway_txn_ref,
            ourAmount: null,
            gatewayAmount: BigInt(rec.amount),
            ourStatus: null,
            gatewayStatus: GATEWAY_STATUS_MAP[rec.status] ?? `UNKNOWN(${rec.status})`,
        });
    }

    // Summary — the "reconciliation is a report, not a boolean" payload
    const expectedAmount = payments
        .filter((p) => p.status === 'SUCCESS')
        .reduce((sum, p) => sum + BigInt(p.amount), 0n);

    const summary = {
        totalInDb: payments.length,
        totalInFile: settlementFile.records.length,
        matchedCount,
        discrepancyCount: discrepancies.length,
        expectedAmount,                                   // what we think should settle
        reportedAmount: BigInt(settlementFile.total_settled_amount),
    };

    return { summary, discrepancies };
}

module.exports = { reconcile, GATEWAY_STATUS_MAP };