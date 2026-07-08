import { useEffect, useState } from 'react'
import api from '../lib/axios'

const RUN_CHIP = {
  PENDING: 'bg-gray-500/20 text-gray-300',
  IN_PROGRESS: 'bg-yellow-500/20 text-yellow-300',
  COMPLETED: 'bg-green-500/20 text-green-300',
  PARTIAL: 'bg-orange-500/20 text-orange-300',
  FAILED: 'bg-red-500/20 text-red-300',
}
const JOB_CHIP = {
  QUEUED: 'bg-gray-500/20 text-gray-300',
  RUNNING: 'bg-yellow-500/20 text-yellow-300',
  COMPLETED: 'bg-green-500/20 text-green-300',
  FAILED: 'bg-red-500/20 text-red-300',
}
const DISC_TYPE_CHIP = {
  MISSING_AT_GATEWAY: 'bg-orange-500/20 text-orange-300',
  MISSING_IN_DB: 'bg-red-500/20 text-red-300',
  AMOUNT_MISMATCH: 'bg-pink-500/20 text-pink-300',
  STATUS_MISMATCH: 'bg-yellow-500/20 text-yellow-300',
}

const paise = (n) => `₹${(Number(n) / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`

function Chip({ map, value }) {
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${map[value] ?? 'bg-gray-500/20 text-gray-300'}`}>{value}</span>
}

export default function Reconciliation() {
  const [runs, setRuns] = useState([])
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState(false)
  const [error, setError] = useState(null)

  async function loadRuns() {
    setLoading(true)
    try {
      const res = await api.get('/reconciliation/runs')
      setRuns(res.data.data)
    } catch (err) {
      setError(err.response?.data?.message ?? 'Failed to load runs')
    } finally { setLoading(false) }
  }

  useEffect(() => { loadRuns() }, [])

  async function openRun(id) {
    setSelected(id)
    setDetail(null)
    const res = await api.get(`/reconciliation/runs/${id}`)
    setDetail(res.data.data)
  }

  async function triggerRun() {
    setTriggering(true)
    setError(null)
    try {
      await api.post('/reconciliation/runs/trigger', {})
      setTimeout(loadRuns, 1500)  // give the flow a moment to create rows
    } catch (err) {
      setError(err.response?.data?.message ?? 'Trigger failed')
    } finally { setTriggering(false) }
  }

  return (
    <div className="p-8 text-white">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Reconciliation</h1>
        <button
          onClick={triggerRun}
          disabled={triggering}
          className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm font-medium"
        >
          {triggering ? 'Starting…' : 'Run Reconciliation'}
        </button>
      </div>

      {error && <div className="mb-4 px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">{error}</div>}

      <div className="grid grid-cols-3 gap-6">
        {/* Runs list */}
        <div className="col-span-1 rounded-xl border border-gray-800 overflow-hidden h-fit">
          <div className="bg-gray-900 px-4 py-3 text-sm text-gray-400">Runs</div>
          {loading ? (
            <div className="px-4 py-6 text-gray-500 text-sm">Loading…</div>
          ) : runs.length === 0 ? (
            <div className="px-4 py-6 text-gray-500 text-sm">No runs yet</div>
          ) : runs.map((run) => (
            <div
              key={run.id}
              onClick={() => openRun(run.id)}
              className={`px-4 py-3 border-t border-gray-800 cursor-pointer hover:bg-gray-900/50 ${selected === run.id ? 'bg-gray-900/70' : ''}`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm">{new Date(run.runDate).toLocaleDateString('en-IN')}</span>
                <Chip map={RUN_CHIP} value={run.status} />
              </div>
              <div className="text-xs text-gray-500">{run.gatewayJobs.length} gateways</div>
            </div>
          ))}
        </div>

        {/* Detail */}
        <div className="col-span-2">
          {!selected ? (
            <div className="text-gray-500 text-sm px-4 py-8 text-center border border-gray-800 rounded-xl">Select a run</div>
          ) : !detail ? (
            <div className="text-gray-500 text-sm px-4 py-8">Loading…</div>
          ) : (
            <>
              <div className="grid grid-cols-4 gap-3 mb-6">
                {detail.gatewayJobs.map((job) => (
                  <div key={job.id} className="rounded-xl border border-gray-800 p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium">{job.gateway}</span>
                      <Chip map={JOB_CHIP} value={job.status} />
                    </div>
                    <div className="text-xs text-gray-400 space-y-1">
                      <div>Matched: <span className="text-white">{job.matchedCount}</span> / {job.totalInDb}</div>
                      <div>Flagged: <span className="text-orange-300">{job.discrepancyCount}</span></div>
                      <div>Expected: {paise(job.expectedAmount)}</div>
                      <div>Reported: {paise(job.reportedAmount)}</div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="rounded-xl border border-gray-800 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-900 text-gray-400 text-left">
                    <tr>
                      <th className="px-4 py-2">Gateway</th>
                      <th className="px-4 py-2">Type</th>
                      <th className="px-4 py-2">Our Amount</th>
                      <th className="px-4 py-2">Gateway Amount</th>
                      <th className="px-4 py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.gatewayJobs.flatMap((job) =>
                      job.discrepancies.map((d) => (
                        <tr key={d.id} className="border-t border-gray-800">
                          <td className="px-4 py-2">{job.gateway}</td>
                          <td className="px-4 py-2"><Chip map={DISC_TYPE_CHIP} value={d.type} /></td>
                          <td className="px-4 py-2 text-gray-400">{d.ourAmount != null ? paise(d.ourAmount) : '—'}</td>
                          <td className="px-4 py-2 text-gray-400">{d.gatewayAmount != null ? paise(d.gatewayAmount) : '—'}</td>
                          <td className="px-4 py-2 text-gray-400">{d.status}</td>
                        </tr>
                      ))
                    )}
                    {detail.gatewayJobs.every((j) => j.discrepancies.length === 0) && (
                      <tr><td colSpan={5} className="px-4 py-6 text-center text-gray-500">No discrepancies</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}