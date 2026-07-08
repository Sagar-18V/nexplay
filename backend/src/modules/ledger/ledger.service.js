/**
 * Ledger writer — append-only, always balanced.
 * Every write happens inside the CALLER's transaction (tx),
 * so ledger entries commit atomically with the state change that caused them.
 */

/** Capture: customer owes -> merchant is owed (minus platform fee). */
async function writeCaptureEntries(tx, { txnId, amount, feeAmount = 0 }) {
    const merchantNet = amount - feeAmount;
    const entries = [
        { txnId, entryType: 'DEBIT', account: 'CUSTOMER_RECEIVABLE', amount },
        { txnId, entryType: 'CREDIT', account: 'MERCHANT_PAYABLE', amount: merchantNet },
    ];
    if (feeAmount > 0) {
        entries.push({ txnId, entryType: 'CREDIT', account: 'PLATFORM_REVENUE', amount: feeAmount });
    }
    // Invariant: debits === credits (amount = merchantNet + feeAmount)
    await tx.ledgerEntry.createMany({ data: entries });
}



/** Refund reversal: merchant gives back -> customer is owed. Fee NOT refunded. */
async function writeRefundReversalEntries(tx, { txnId, refundId, amount }) {
    await tx.ledgerEntry.createMany({
        data: [
            { txnId, refundId, entryType: 'DEBIT', account: 'MERCHANT_PAYABLE', amount },
            { txnId, refundId, entryType: 'CREDIT', account: 'CUSTOMER_RECEIVABLE', amount },
        ],
    });
}

module.exports = { writeCaptureEntries, writeRefundReversalEntries };