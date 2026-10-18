const { Worker } = require('bullmq');
const { safeHandler } = require('../../utils/safeHandler');
const { bullmqConnection } = require('../../config/redis');
const prisma = require('../../config/prisma');
const { getGatewayAdapter } = require('../gateways'); // your adapter registry

const refundWorker = new Worker('refunds', async (job) => {
    const { refundId } = job.data;

    const refund = await prisma.refund.findUnique({
        where: { id: refundId },
        include: { transaction: true },
    });
    if (!refund) throw new Error(`Refund ${refundId} not found`);

    // Idempotent re-entry: retry after partial success must not re-hit gateway
    if (refund.status === 'SUCCEEDED' || refund.status === 'FAILED') return;

    await prisma.refund.update({
        where: { id: refundId },
        data: { status: 'PROCESSING', attempts: { increment: 1 } },
    });

    const adapter = getGatewayAdapter(refund.transaction.gateway);
    const result = await adapter.processRefund({
        gatewayTxnId: refund.transaction.gatewayTxnId,
        amount: refund.amount,
        refundId: refund.id,
    });

    if (!result.success) {
        // Retryable failure -> throw (BullMQ backs off and retries).
        // Terminal rejection -> mark FAILED, no throw.
        if (result.retryable) throw new Error(result.error);

        await prisma.refund.update({
            where: { id: refundId },
            data: { status: 'FAILED', failureReason: result.error, processedAt: new Date() },
        });
        return;
    }

    // SUCCESS: one atomic unit — refund terminal state + ledger reversals
    // + refundedAmount + intent status. All or nothing.
    await prisma.$transaction(async (tx) => {
        await tx.refund.update({
            where: { id: refundId },
            data: {
                status: 'SUCCEEDED',
                gatewayRefundRef: result.gatewayRefundRef,
                processedAt: new Date(),
            },
        });

        // Ledger reversal: mirror of the capture entries, directions flipped.
        // Capture wrote:  DEBIT CUSTOMER_RECEIVABLE / CREDIT MERCHANT_PAYABLE
        // Reversal writes: DEBIT MERCHANT_PAYABLE / CREDIT CUSTOMER_RECEIVABLE
        // Append-only: original entries are never touched.
        await tx.ledgerEntry.createMany({
            data: [
                {
                    txnId: refund.transactionId,
                    refundId: refund.id,
                    entryType: 'DEBIT',
                    account: 'MERCHANT_PAYABLE',
                    amount: refund.amount,
                },
                {
                    txnId: refund.transactionId,
                    refundId: refund.id,
                    entryType: 'CREDIT',
                    account: 'CUSTOMER_RECEIVABLE',
                    amount: refund.amount,
                },
            ],
        });

        const updatedTxn = await tx.transaction.update({
            where: { id: refund.transactionId },
            data: { refundedAmount: { increment: refund.amount } },
        });

        // Intent status: fully vs partially refunded
        await tx.paymentIntent.update({
            where: { id: refund.transaction.intentId },
            data: {
                status: updatedTxn.refundedAmount >= updatedTxn.amount
                    ? 'REFUNDED'
                    : 'PARTIALLY_REFUNDED',
            },
        });
    });
}, { connection: bullmqConnection, concurrency: 5 });

refundWorker.on('failed', safeHandler('refunds:failed', async (job, err) => {
    if (job && job.attemptsMade >= job.opts.attempts) {
        await prisma.refund.update({
            where: { id: job.data.refundId },
            data: { status: 'FAILED', failureReason: err.message, processedAt: new Date() },
        });
    }
}));

module.exports = { refundWorker };