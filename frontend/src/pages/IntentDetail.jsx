import { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../lib/axios'

const CHIP = {
    CREATED: 'bg-blue-500/20 text-blue-300',
    PROCESSING: 'bg-yellow-500/20 text-yellow-300',
    SUCCESS: 'bg-green-500/20 text-green-300',
    FAILED: 'bg-red-500/20 text-red-300',
    PARTIALLY_REFUNDED: 'bg-orange-500/20 text-orange-300',
    REFUNDED: 'bg-purple-500/20 text-purple-300',
    PENDING: 'bg-yellow-500/20 text-yellow-300',
    SUCCEEDED: 'bg-green-500/20 text-green-300',
}

const paise = (n) => `₹${(n / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`

function Chip({ status }) {
    return (
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${CHIP[status] ?? 'bg-gray-500/20 text-gray-300'}`}>
            {status}
        </span>
    )
}

function Section({ title, children }) {
    return (
        <div className="mb-8">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">{title}</h2>
            {children}
        </div>
    )
}

export default function IntentDetail() {
    const { id } = useParams()
    const [intent, setIntent] = useState(null)
    const [refunds, setRefunds] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    // refund form state
    const [refundAmount, setRefundAmount] = useState('')
    const [refundReason, setRefundReason] = useState('customer_request')
    const [submitting, setSubmitting] = useState(false)
    const [formMsg, setFormMsg] = useState(null)

    const successTxn = intent?.transactions?.find((t) => t.status === 'SUCCESS')
    const remaining = successTxn ? successTxn.amount - (successTxn.refundedAmount ?? 0) : 0

    const load = useCallback(async () => {
        setError(null)
        try {
            const res = await api.get(`/payments/intents/${id}`)
            setIntent(res.data.data)

            const txn = res.data.data.transactions?.find((t) => t.status === 'SUCCESS')
            if (txn) {
                // GET /v1/refunds?transactionId=... — see backend note below
                const r = await api.get('/refunds', { params: { transactionId: txn.id } })
                setRefunds(r.data.data)
            }
        } catch (err) {
            setError(err.response?.data?.message ?? 'Failed to load intent')
        } finally {
            setLoading(false)
        }
    }, [id])

    useEffect(() => { load() }, [load])

    async function handleRefund(e) {
        e.preventDefault()
        setFormMsg(null)

        const amt = Math.round(Number(refundAmount) * 100)   // rupees input -> paise
        if (!Number.isInteger(amt) || amt <= 0) {
            setFormMsg({ type: 'error', text: 'Enter a valid amount' })
            return
        }
        if (amt > remaining) {
            setFormMsg({ type: 'error', text: `Max refundable is ${paise(remaining)}` })
            return
        }

        setSubmitting(true)
        try {
            await api.post(
                `/refunds/transactions/${successTxn.id}`,
                { amount: amt, reason: refundReason },
                { headers: { 'Idempotency-Key': crypto.randomUUID() } }
            )
            setRefundAmount('')
            setFormMsg({ type: 'ok', text: 'Refund accepted — processing' })
            // refund is async (202); poll shortly so SUCCEEDED shows up
            setTimeout(load, 2500)
            await load()
        } catch (err) {
            setFormMsg({ type: 'error', text: err.response?.data?.message ?? 'Refund failed' })
        } finally {
            setSubmitting(false)
        }
    }

    if (loading) return <div className="p-8 text-gray-400">Loading…</div>
    if (error) return <div className="p-8 text-red-300">{error}</div>
    if (!intent) return null

    return (
        <div className="p-8 text-white max-w-4xl">
            <Link to="/transactions" className="text-sm text-gray-400 hover:text-white">← Payments</Link>

            {/* Header */}
            <div className="flex items-center justify-between mt-4 mb-8">
                <div>
                    <h1 className="text-2xl font-semibold">{paise(intent.amount)} <span className="text-gray-400 text-base">{intent.currency}</span></h1>
                    <p className="font-mono text-xs text-gray-500 mt-1">{intent.id}</p>
                </div>
                <Chip status={intent.status} />
            </div>

            {/* Transactions */}
            <Section title="Transactions">
                <div className="rounded-xl border border-gray-800 overflow-hidden">
                    <table className="w-full text-sm">
                        <thead className="bg-gray-900 text-gray-400 text-left">
                            <tr>
                                <th className="px-4 py-2">Gateway</th>
                                <th className="px-4 py-2">Status</th>
                                <th className="px-4 py-2">Gateway Ref</th>
                                <th className="px-4 py-2">Latency</th>
                                <th className="px-4 py-2">Fee</th>
                                <th className="px-4 py-2">Refunded</th>
                            </tr>
                        </thead>
                        <tbody>
                            {intent.transactions.map((t) => (
                                <tr key={t.id} className="border-t border-gray-800">
                                    <td className="px-4 py-2">{t.gateway}</td>
                                    <td className="px-4 py-2"><Chip status={t.status} /></td>
                                    <td className="px-4 py-2 font-mono text-xs text-gray-400">{t.gatewayTxnId ?? t.failureReason ?? '—'}</td>
                                    <td className="px-4 py-2 text-gray-400">{t.latencyMs ? `${t.latencyMs}ms` : '—'}</td>
                                    <td className="px-4 py-2 text-gray-400">{t.feeAmount != null ? paise(t.feeAmount) : '—'}</td>
                                    <td className="px-4 py-2 text-gray-400">{t.refundedAmount ? paise(t.refundedAmount) : '—'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </Section>

            {/* Refund form — only when there's refundable money */}
            {successTxn && remaining > 0 && (
                <Section title={`Create Refund — ${paise(remaining)} refundable`}>
                    <div className="rounded-xl border border-gray-800 bg-gray-900/40 p-4 flex items-end gap-3">
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Amount (₹)</label>
                            <input
                                type="number" step="0.01" min="0.01" max={remaining / 100}
                                value={refundAmount}
                                onChange={(e) => setRefundAmount(e.target.value)}
                                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm w-36"
                                placeholder="0.00"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-400 mb-1">Reason</label>
                            <select
                                value={refundReason}
                                onChange={(e) => setRefundReason(e.target.value)}
                                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
                            >
                                <option value="customer_request">Customer request</option>
                                <option value="duplicate">Duplicate</option>
                                <option value="fraud">Fraud</option>
                            </select>
                        </div>
                        <button
                            onClick={handleRefund}
                            disabled={submitting}
                            className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm font-medium"
                        >
                            {submitting ? 'Submitting…' : 'Refund'}
                        </button>
                        {formMsg && (
                            <span className={`text-sm ${formMsg.type === 'ok' ? 'text-green-300' : 'text-red-300'}`}>
                                {formMsg.text}
                            </span>
                        )}
                    </div>
                </Section>
            )}

            {/* Refund history */}
            {refunds.length > 0 && (
                <Section title="Refunds">
                    <div className="rounded-xl border border-gray-800 overflow-hidden">
                        <table className="w-full text-sm">
                            <thead className="bg-gray-900 text-gray-400 text-left">
                                <tr>
                                    <th className="px-4 py-2">Amount</th>
                                    <th className="px-4 py-2">Status</th>
                                    <th className="px-4 py-2">Reason</th>
                                    <th className="px-4 py-2">Gateway Ref</th>
                                    <th className="px-4 py-2">Attempts</th>
                                    <th className="px-4 py-2">Created</th>
                                </tr>
                            </thead>
                            <tbody>
                                {refunds.map((r) => (
                                    <tr key={r.id} className="border-t border-gray-800">
                                        <td className="px-4 py-2">{paise(r.amount)}</td>
                                        <td className="px-4 py-2"><Chip status={r.status} /></td>
                                        <td className="px-4 py-2 text-gray-400">{r.reason ?? '—'}</td>
                                        <td className="px-4 py-2 font-mono text-xs text-gray-400">{r.gatewayRefundRef ?? r.failureReason ?? '—'}</td>
                                        <td className="px-4 py-2 text-gray-400">{r.attempts}</td>
                                        <td className="px-4 py-2 text-gray-400">{new Date(r.createdAt).toLocaleString('en-IN')}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </Section>
            )}
        </div>
    )
}