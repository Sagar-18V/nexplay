import { useEffect, useState } from 'react'
import api from '../lib/axios'

const paise = (n) => `₹${(Number(n) / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`

function StatCard({ label, value, sub }) {
  return (
    <div className="rounded-xl border border-gray-800 p-4">
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className="text-2xl font-semibold">{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  )
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.get('/metrics')
      .then((res) => setMetrics(res.data.data))
      .catch((err) => setError(err.response?.data?.message ?? 'Failed to load metrics'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-gray-400">Loading…</div>
  if (error) return <div className="p-8 text-red-300">{error}</div>
  if (!metrics) return null

  const totalSuccess = metrics.gateways.reduce((s, g) => s + g.successCount, 0)
  const totalFailure = metrics.gateways.reduce((s, g) => s + g.failureCount, 0)
  const totalVolume = totalSuccess + totalFailure
  const overallRate = totalVolume > 0 ? ((totalSuccess / totalVolume) * 100).toFixed(1) : '0.0'

  const byGateway = {}
  for (const g of metrics.gateways) {
    if (!byGateway[g.gateway]) byGateway[g.gateway] = { success: 0, failure: 0, latencies: [] }
    byGateway[g.gateway].success += g.successCount
    byGateway[g.gateway].failure += g.failureCount
    byGateway[g.gateway].latencies.push(g.avgLatencyMs)
  }

  return (
    <div className="p-8 text-white">
      <h1 className="text-2xl font-semibold mb-6">Dashboard</h1>

      <div className="grid grid-cols-4 gap-4 mb-8">
        <StatCard label="Total transactions" value={totalVolume} />
        <StatCard label="Overall success rate" value={`${overallRate}%`} />
        <StatCard label="Active gateways" value={Object.keys(byGateway).length} sub="of 4 configured" />
        <StatCard
          label="Reconciliation"
          value={metrics.queues.reconciliation.completed}
          sub={`${metrics.queues.reconciliation.failed} failed jobs`}
        />
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="rounded-xl border border-gray-800 overflow-hidden">
          <div className="bg-gray-900 px-4 py-3 text-sm text-gray-400">Gateway performance</div>
          <table className="w-full text-sm">
            <thead className="text-gray-500 text-left">
              <tr>
                <th className="px-4 py-2">Gateway</th>
                <th className="px-4 py-2">Success</th>
                <th className="px-4 py-2">Failed</th>
                <th className="px-4 py-2">Avg latency</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(byGateway).map(([name, d]) => (
                <tr key={name} className="border-t border-gray-800">
                  <td className="px-4 py-2 font-medium">{name}</td>
                  <td className="px-4 py-2 text-green-300">{d.success}</td>
                  <td className="px-4 py-2 text-red-300">{d.failure || 0}</td>
                  <td className="px-4 py-2 text-gray-400">
                    {Math.round(d.latencies.reduce((a, b) => a + b, 0) / d.latencies.length)}ms
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-gray-800 overflow-hidden">
          <div className="bg-gray-900 px-4 py-3 text-sm text-gray-400">Queue health</div>
          <table className="w-full text-sm">
            <thead className="text-gray-500 text-left">
              <tr>
                <th className="px-4 py-2">Queue</th>
                <th className="px-4 py-2">Completed</th>
                <th className="px-4 py-2">Failed</th>
                <th className="px-4 py-2">Active</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(metrics.queues).map(([name, q]) => (
                <tr key={name} className="border-t border-gray-800">
                  <td className="px-4 py-2 font-medium capitalize">{name}</td>
                  <td className="px-4 py-2 text-green-300">{q.completed}</td>
                  <td className="px-4 py-2 text-red-300">{q.failed}</td>
                  <td className="px-4 py-2 text-gray-400">{q.active}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}