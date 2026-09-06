import { useEffect, useState } from 'react'
import api from '../lib/axios'

const METHOD_COLOR = {
  CARD: 'bg-blue-500/20 text-blue-300',
  UPI: 'bg-teal-500/20 text-teal-300',
  NET_BANKING: 'bg-purple-500/20 text-purple-300',
  WALLET: 'bg-orange-500/20 text-orange-300',
}

export default function Routing() {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.get('/metrics')
      .then((res) => setMetrics(res.data.data))
      .catch((err) => setError(err.response?.data?.message ?? 'Failed to load routing data'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-gray-400">Loading…</div>
  if (error) return <div className="p-8 text-red-300">{error}</div>
  if (!metrics) return null

  const maxCount = Math.max(...metrics.gateways.map((g) => g.successCount + g.failureCount), 1)

  return (
    <div className="p-8 text-white">
      <h1 className="text-2xl font-semibold mb-2">Routing engine</h1>
      <p className="text-sm text-gray-400 mb-6">
        Live gateway performance by payment method — the same data the weighted routing algorithm would consult in a stats-driven upgrade.
      </p>

      <div className="space-y-3">
        {metrics.gateways
          .sort((a, b) => (b.successCount + b.failureCount) - (a.successCount + a.failureCount))
          .map((g) => {
            const total = g.successCount + g.failureCount
            const rate = total > 0 ? ((g.successCount / total) * 100).toFixed(0) : 0
            const barWidth = (total / maxCount) * 100
            return (
              <div key={`${g.gateway}-${g.method}`} className="rounded-xl border border-gray-800 p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <span className="font-medium">{g.gateway}</span>
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${METHOD_COLOR[g.method] ?? 'bg-gray-500/20 text-gray-300'}`}>
                      {g.method}
                    </span>
                  </div>
                  <div className="text-sm text-gray-400">
                    {total} txns · {rate}% success · {g.avgLatencyMs}ms avg
                  </div>
                </div>
                <div className="h-2 rounded-full bg-gray-800 overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 rounded-full"
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
              </div>
            )
          })}
      </div>
    </div>
  )
}
