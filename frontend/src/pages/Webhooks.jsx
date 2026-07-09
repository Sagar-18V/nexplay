import { useEffect, useState } from 'react'
import api from '../lib/axios'

const CHIP = {
    PENDING: 'bg-yellow-500/20 text-yellow-300',
    DELIVERED: 'bg-green-500/20 text-green-300',
    FAILED: 'bg-red-500/20 text-red-300',
}

function Chip({ value }) {
    return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${CHIP[value] ?? 'bg-gray-500/20 text-gray-300'}`}>{value}</span>
}

export default function Webhooks() {
    const [logs, setLogs] = useState([])
    const [loading, setLoading] = useState(true)
    const [redeliveringId, setRedeliveringId] = useState(null)
    const [error, setError] = useState(null)

    async function load() {
        setLoading(true)
        try {
            const res = await api.get('/webhooks/failed')
            setLogs(res.data.data)
        } catch (err) {
            setError(err.response?.data?.message ?? 'Failed to load webhooks')
        } finally { setLoading(false) }
    }

    useEffect(() => { load() }, [])

    async function redeliver(id) {
        setRedeliveringId(id)
        try {
            await api.post(`/webhooks/${id}/redeliver`)
            setTimeout(load, 2000)
        } catch (err) {
            setError(err.response?.data?.message ?? 'Redeliver failed')
        } finally { setRedeliveringId(null) }
    }

    return (
        <div className="p-8 text-white">
            <div className="flex items-center justify-between mb-6">
                <h1 className="text-2xl font-semibold">Failed Webhooks</h1>
                <button onClick={load} className="px-3 py-1.5 rounded-lg border border-gray-700 text-sm">Refresh</button>
            </div>

            {error && <div className="mb-4 px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">{error}</div>}

            <div className="rounded-xl border border-gray-800 overflow-hidden">
                <table className="w-full text-sm">
                    <thead className="bg-gray-900 text-gray-400 text-left">
                        <tr>
                            <th className="px-4 py-3">Event</th>
                            <th className="px-4 py-3">Status</th>
                            <th className="px-4 py-3">Attempts</th>
                            <th className="px-4 py-3">Last Attempted</th>
                            <th className="px-4 py-3">Created</th>
                            <th className="px-4 py-3"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">Loading…</td></tr>
                        ) : logs.length === 0 ? (
                            <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">No failed webhooks 🎉</td></tr>
                        ) : logs.map((log) => (
                            <tr key={log.id} className="border-t border-gray-800">
                                <td className="px-4 py-3 font-mono text-xs">{log.event}</td>
                                <td className="px-4 py-3"><Chip value={log.status} /></td>
                                <td className="px-4 py-3 text-gray-400">{log.attempts}</td>
                                <td className="px-4 py-3 text-gray-400">{log.lastAttemptedAt ? new Date(log.lastAttemptedAt).toLocaleString('en-IN') : '—'}</td>
                                <td className="px-4 py-3 text-gray-400">{new Date(log.createdAt).toLocaleString('en-IN')}</td>
                                <td className="px-4 py-3 text-right">
                                    <button
                                        onClick={() => redeliver(log.id)}
                                        disabled={redeliveringId === log.id}
                                        className="px-3 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs font-medium"
                                    >
                                        {redeliveringId === log.id ? 'Redelivering…' : 'Redeliver'}
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}