import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../lib/axios'

const STATUS_STYLES = {
  CREATED: 'bg-blue-500/20 text-blue-300',
  PROCESSING: 'bg-yellow-500/20 text-yellow-300',
  SUCCESS: 'bg-green-500/20 text-green-300',
  FAILED: 'bg-red-500/20 text-red-300',
  PARTIALLY_REFUNDED: 'bg-orange-500/20 text-orange-300',
  REFUNDED: 'bg-purple-500/20 text-purple-300',
}

const STATUSES = ['ALL', ...Object.keys(STATUS_STYLES)]

const paise = (n) => `₹${(n / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`

function StatusChip({ status }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[status] ?? 'bg-gray-500/20 text-gray-300'}`}>
      {status}
    </span>
  )
}

export default function Transactions() {
  const [intents, setIntents] = useState([])
  const [meta, setMeta] = useState({ total: 0, limit: 20, offset: 0 })
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [loading, setLoading] = useState(true)
  const [processingId, setProcessingId] = useState(null)
  const [error, setError] = useState(null)
  const navigate = useNavigate()

  const fetchIntents = useCallback(async (offset = 0) => {
    setLoading(true)
    setError(null)
    try {
      const params = { limit: meta.limit, offset }
      if (statusFilter !== 'ALL') params.status = statusFilter
      const res = await api.get('/payments/intents', { params })
      setIntents(res.data.data)
      setMeta(res.data.meta)
    } catch (err) {
      setError(err.response?.data?.message ?? 'Failed to load payments')
    } finally {
      setLoading(false)
    }
  }, [statusFilter, meta.limit])

  useEffect(() => { fetchIntents(0) }, [fetchIntents])

  async function handleProcess(e, intentId) {
    e.stopPropagation()               // don't trigger the row click
    setProcessingId(intentId)
    try {
      await api.post(`/payments/intents/${intentId}/process`)
      await fetchIntents(meta.offset) // re-fetch: status, gateway, fee all changed
    } catch (err) {
      setError(err.response?.data?.message ?? 'Processing failed')
    } finally {
      setProcessingId(null)
    }
  }

  return (
    <div className="p-8 text-white">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Payments</h1>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm"
        >
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {error && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-gray-800">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 text-gray-400 text-left">
            <tr>
              <th className="px-4 py-3">Intent</th>
              <th className="px-4 py-3">Amount</th>
              <th className="px-4 py-3">Method</th>
              <th className="px-4 py-3">Gateway</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">Loading…</td></tr>
            ) : intents.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">No payments found</td></tr>
            ) : intents.map((intent) => {
              const latestTxn = intent.transactions?.[0]
              return (
                <tr
                  key={intent.id}
                  onClick={() => navigate(`/transactions/${intent.id}`)}
                  className="border-t border-gray-800 hover:bg-gray-900/50 cursor-pointer"
                >
                  <td className="px-4 py-3 font-mono text-xs text-gray-400">{intent.id.slice(0, 8)}…</td>
                  <td className="px-4 py-3">{paise(intent.amount)}</td>
                  <td className="px-4 py-3 text-gray-300">{intent.method}</td>
                  <td className="px-4 py-3 text-gray-300">{latestTxn?.gateway ?? '—'}</td>
                  <td className="px-4 py-3"><StatusChip status={intent.status} /></td>
                  <td className="px-4 py-3 text-gray-400">{new Date(intent.createdAt).toLocaleString('en-IN')}</td>
                  <td className="px-4 py-3 text-right">
                    {intent.status === 'CREATED' && (
                      <button
                        onClick={(e) => handleProcess(e, intent.id)}
                        disabled={processingId === intent.id}
                        className="px-3 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs font-medium"
                      >
                        {processingId === intent.id ? 'Processing…' : 'Process'}
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-4 text-sm text-gray-400">
        <span>{meta.total} total</span>
        <div className="flex gap-2">
          <button
            onClick={() => fetchIntents(Math.max(0, meta.offset - meta.limit))}
            disabled={meta.offset === 0}
            className="px-3 py-1 rounded-lg border border-gray-700 disabled:opacity-40"
          >Prev</button>
          <button
            onClick={() => fetchIntents(meta.offset + meta.limit)}
            disabled={meta.offset + meta.limit >= meta.total}
            className="px-3 py-1 rounded-lg border border-gray-700 disabled:opacity-40"
          >Next</button>
        </div>
      </div>
    </div>
  )
}