const prisma = require('../../config/prisma');
const { refundQueue } = require('./refund.queue');
const AppError = require('../../utils/AppError'); // your operational-error class

/**
 * Creates a refund with over-refund protection.
 *
 * Concurrency strategy: pessimistic lock (SELECT ... FOR UPDATE) on the
 * transaction row. Two concurrent partial refunds serialize — the second
 * waits for the first's transaction to commit, then sees its refund row
 * and gets correctly rejected if the total would exceed the captured amount.
 */
async function createRefund({ transactionId, merchantId, amount, reason, idempotencyKey }) {
    if (!Number.isInteger(amount) || amount <= 0) {
        throw new AppError('Refund amount must be a positive integer (paise)', 400);
    }

    const refund = await prisma.$transaction(async (tx) => {
        // 1. Lock the transaction row. Prisma has no native FOR UPDATE — raw SQL.
        //    NOWAIT alternative would fail-fast; we prefer brief waiting.
        const rows = await tx.$queryRaw`
      SELECT t.id, t.amount, t.status, t."intentId", t.gateway,
             pi."merchantId"
      FROM transactions t
      JOIN payment_intents pi ON pi.id = t."intentId"
      WHERE t.id = ${transactionId}
      FOR UPDATE OF t
    `;

        if (rows.length === 0) throw new AppError('Transaction not found', 404);
        const txn = rows[0];

        // 2. Ownership + refundability checks
        if (txn.merchantId !== merchantId) {
            throw new AppError('Transaction not found', 404); // don't leak existence
        }
        if (txn.status !== 'SUCCESS') {
            throw new AppError('Only successful transactions can be refunded', 422);
        }

        // 3. THE invariant — inside the lock, counting all non-FAILED refunds.
        //    PENDING/PROCESSING count too: money promised is money committed.
        const agg = await tx.refund.aggregate({
            where: { transactionId, status: { not: 'FAILED' } },
            _sum: { amount: true },
        });
        const alreadyCommitted = agg._sum.amount ?? 0;

        if (alreadyCommitted + amount > txn.amount) {
            throw new AppError(
                `Refund exceeds refundable amount. Captured: ${txn.amount}, ` +
                `already committed: ${alreadyCommitted}, requested: ${amount}`,
                422
            );
        }

        // 4. Create PENDING refund (idempotencyKey unique = DB backstop)
        return tx.refund.create({
            data: { transactionId, merchantId, amount, reason, idempotencyKey },
        });
    });

    // 5. Enqueue AFTER commit — never enqueue inside the transaction:
    //    worker could grab the job before the row is visible.
    await refundQueue.add('process-refund', { refundId: refund.id }, {
        jobId: `refund-${refund.id}`,
        attempts: 3,
        backoff: { type: 'exponential', delay: 3000 },
    });

    return refund;
}

module.exports = { createRefund };