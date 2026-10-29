import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, LineChart, Line,
} from 'recharts'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge'

interface Run {
  id: string
  tc: string
  label: string
  repeats: number
  status: string
  started_at: number
  result?: {
    summary?: Record<string, number>
    transfers?: Array<{ index: number; elapsed_ms: number; state: string }>
  }
}

export default function Reports() {
  const [runs, setRuns]     = useState<Run[]>([])
  const [selected, setSelected] = useState<Run | null>(null)
  const [loading, setLoading]   = useState(true)

  const load = () => {
    setLoading(true)
    api.tests.runs()
      .then(d => { setRuns(d as Run[]); setLoading(false) })
      .catch(console.error)
  }
  useEffect(load, [])

  const completedRuns = runs.filter(r => r.status === 'completed')

  const barData = completedRuns.map(r => ({
    name: `${r.tc.toUpperCase()} #${r.id.slice(0, 4)}`,
    avg: r.result?.summary?.['latency_ms_avg'] ?? 0,
    min: r.result?.summary?.['latency_ms_min'] ?? 0,
    max: r.result?.summary?.['latency_ms_max'] ?? 0,
    tc:  r.tc,
  }))

  const TC_COLORS: Record<string, string> = { tc1: '#3b82f6', tc2: '#8b5cf6', tc3: '#f59e0b', tc4: '#10b981' }

  return (
    <div className="p-8 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Reports</h1>
          <p className="text-slate-500 text-sm">Test run history and latency analysis</p>
        </div>
        <button onClick={load} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">Refresh</button>
      </div>

      {loading ? (
        <p className="text-slate-400">Loading…</p>
      ) : runs.length === 0 ? (
        <p className="text-slate-400">No test runs yet. Go to a TC page and run a test.</p>
      ) : (
        <>
          {/* Latency comparison chart */}
          {completedRuns.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 mb-6">
              <p className="text-sm font-semibold text-slate-700 mb-4">Latency Comparison (ms) — All Completed Runs</p>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={barData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis unit=" ms" tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v) => `${v} ms`} />
                  <Legend />
                  <Bar dataKey="min" name="Min" fill="#86efac" radius={[3,3,0,0]} />
                  <Bar dataKey="avg" name="Avg" fill="#60a5fa" radius={[3,3,0,0]} />
                  <Bar dataKey="max" name="Max" fill="#f87171" radius={[3,3,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Per-transfer latency line for selected run */}
          {selected?.result?.transfers && (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 mb-6">
              <p className="text-sm font-semibold text-slate-700 mb-1">
                Transfer-by-transfer: {selected.label}
              </p>
              <p className="text-xs text-slate-400 mb-4">Run ID: {selected.id}</p>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={selected.result.transfers}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="index" label={{ value: 'Transfer #', position: 'insideBottom', offset: -2, fontSize: 11 }} />
                  <YAxis unit=" ms" tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v) => `${v} ms`} />
                  <Line type="monotone" dataKey="elapsed_ms" name="Elapsed"
                    stroke={TC_COLORS[selected.tc] ?? '#3b82f6'} strokeWidth={2} dot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Run history table */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-100">
              <p className="text-sm font-semibold text-slate-700">Run History</p>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500 text-xs uppercase border-b border-slate-100">
                <tr>
                  <th className="px-5 py-2 text-left">Run ID</th>
                  <th className="px-5 py-2 text-left">Test Case</th>
                  <th className="px-5 py-2 text-left">Status</th>
                  <th className="px-5 py-2 text-right">Repeats</th>
                  <th className="px-5 py-2 text-right">Avg (ms)</th>
                  <th className="px-5 py-2 text-right">Min (ms)</th>
                  <th className="px-5 py-2 text-right">Max (ms)</th>
                  <th className="px-5 py-2 text-center">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {runs.map(r => (
                  <tr key={r.id} className={`hover:bg-slate-50 ${selected?.id === r.id ? 'bg-blue-50' : ''}`}>
                    <td className="px-5 py-2 font-mono text-xs">
                      <Link to={`/tests/runs/${r.id}`} className="text-blue-600 hover:underline">
                        {r.id.slice(0, 8)}…
                      </Link>
                    </td>
                    <td className="px-5 py-2">
                      <span style={{ color: TC_COLORS[r.tc] ?? '#64748b' }} className="font-semibold text-xs">
                        {r.tc.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-5 py-2"><StatusBadge state={r.status} /></td>
                    <td className="px-5 py-2 text-right text-slate-600">{r.repeats}</td>
                    <td className="px-5 py-2 text-right font-mono font-semibold text-slate-700">
                      {r.result?.summary?.['latency_ms_avg'] ?? '—'}
                    </td>
                    <td className="px-5 py-2 text-right font-mono text-emerald-600">
                      {r.result?.summary?.['latency_ms_min'] ?? '—'}
                    </td>
                    <td className="px-5 py-2 text-right font-mono text-red-500">
                      {r.result?.summary?.['latency_ms_max'] ?? '—'}
                    </td>
                    <td className="px-5 py-2 text-center">
                      <div className="flex items-center justify-center gap-2">
                        {r.status === 'completed' && (
                          <button onClick={() => setSelected(selected?.id === r.id ? null : r)}
                            className="text-xs text-blue-600 hover:underline">
                            {selected?.id === r.id ? 'Hide' : 'Chart'}
                          </button>
                        )}
                        <Link to={`/tests/runs/${r.id}`} className="text-xs text-slate-500 hover:underline">
                          Detail
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
