import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge'

const PHASE_ORDER = ['catalog', 'negotiate', 'transfers', 'metrics'] as const

const TC_META: Record<string, { label: string; target: string }> = {
  tc1: { label: 'TC-1: Real-time Control Signal',    target: '≤ 20 ms (50 Hz)' },
  tc2: { label: 'TC-2: High-Frequency Sensor Batch', target: 'Batch every ~1 s' },
  tc3: { label: 'TC-3: Video Stream',                target: '≤ 41 ms (24 fps)' },
  tc4: { label: 'TC-4: AAS Control Signal via EDC',  target: '≤ 20 ms (compare vs TC-1)' },
}

interface TransferRow { index: number; transfer_id: string; state: string; elapsed_ms: number }
interface Run {
  id: string; tc: string; label: string; repeats: number; status: string; started_at: number
  result?: { summary?: Record<string, number>; transfers?: TransferRow[] }
  error?: string
}

export default function RunDetail() {
  const { run_id } = useParams<{ run_id: string }>()
  const [run, setRun]       = useState<Run | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState('')

  useEffect(() => {
    if (!run_id) return
    api.tests.getRun(run_id)
      .then(r => { setRun(r as Run); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [run_id])

  if (loading) return <div className="p-8 text-slate-400">Loading run…</div>
  if (error || !run) return (
    <div className="p-8">
      <p className="text-red-500 mb-4">{error || 'Run not found.'}</p>
      <Link to="/reports" className="text-blue-600 hover:underline text-sm">← Back to Reports</Link>
    </div>
  )

  const meta      = TC_META[run.tc] ?? { label: run.label, target: '—' }
  const summary   = run.result?.summary
  const transfers = run.result?.transfers ?? []
  const completed = transfers.filter(t => t.state === 'COMPLETED').length

  return (
    <div className="p-8 max-w-5xl space-y-6">

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <Link to="/reports" className="hover:underline text-blue-600">Reports</Link>
        <span>/</span>
        <Link to={`/tests/${run.tc}`} className="hover:underline text-blue-600">{run.tc.toUpperCase()}</Link>
        <span>/</span>
        <span className="font-mono">{run.id.slice(0, 8)}…</span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">{meta.label}</h1>
          <div className="flex items-center gap-3 mt-2">
            <StatusBadge state={run.status} />
            <span className="text-sm text-slate-500">{run.repeats} repeats</span>
            <span className="text-sm text-slate-400">{new Date(run.started_at).toLocaleString()}</span>
          </div>
          <p className="font-mono text-xs text-slate-400 mt-1">Run ID: {run.id}</p>
        </div>
        <Link to={`/tests/${run.tc}`}
          className="text-sm text-blue-600 hover:underline">
          ← Back to {run.tc.toUpperCase()}
        </Link>
      </div>

      {/* Phase summary — static, all phases shown as done/failed */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
        <p className="text-sm font-semibold text-slate-700 mb-4">Phase Progress</p>
        <div className="flex items-center gap-2 flex-wrap">
          {PHASE_ORDER.map((phase, idx) => {
            const isFailed = run.status === 'failed'
            const sym  = run.status === 'completed' ? '✓' : isFailed ? '✗' : '○'
            const cls  = run.status === 'completed' ? 'text-emerald-500' : isFailed ? 'text-red-400' : 'text-slate-300'
            return (
              <div key={phase} className="flex items-center gap-2">
                <div className={`flex items-center gap-1.5 ${cls}`}>
                  <span className="text-xl font-mono leading-none">{sym}</span>
                  <p className="text-xs font-semibold capitalize">
                    {phase === 'negotiate' ? 'Negotiate' : phase.charAt(0).toUpperCase() + phase.slice(1)}
                  </p>
                </div>
                {idx < PHASE_ORDER.length - 1 && <div className="w-8 h-px bg-slate-200" />}
              </div>
            )
          })}
        </div>
      </div>

      {/* Error */}
      {run.error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">
          <strong>Error:</strong> {run.error}
        </div>
      )}

      {/* Transfer results table */}
      {transfers.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
            <p className="text-sm font-semibold text-slate-700">Transfer Results</p>
            <span className="text-xs text-slate-400">{completed} / {transfers.length} completed</span>
          </div>
          <div className="max-h-[480px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500 text-xs uppercase border-b border-slate-100 sticky top-0">
                <tr>
                  <th className="px-5 py-2 text-left">#</th>
                  <th className="px-5 py-2 text-left">Transfer ID</th>
                  <th className="px-5 py-2 text-left">State</th>
                  <th className="px-5 py-2 text-right">Elapsed (ms)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {transfers.map(r => (
                  <tr key={r.index} className="hover:bg-slate-50">
                    <td className="px-5 py-2 text-slate-500">{r.index}</td>
                    <td className="px-5 py-2 font-mono text-xs text-slate-400">{r.transfer_id?.slice(0, 20)}…</td>
                    <td className="px-5 py-2"><StatusBadge state={r.state} /></td>
                    <td className="px-5 py-2 text-right font-mono font-semibold text-slate-700">{r.elapsed_ms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Run summary */}
      {summary && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5">
          <p className="text-emerald-800 font-semibold mb-4">Run Summary</p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { label: 'Avg Latency',    value: summary['latency_ms_avg']    != null ? `${summary['latency_ms_avg']} ms`    : '—' },
              { label: 'Min Latency',    value: summary['latency_ms_min']    != null ? `${summary['latency_ms_min']} ms`    : '—' },
              { label: 'Max Latency',    value: summary['latency_ms_max']    != null ? `${summary['latency_ms_max']} ms`    : '—' },
              { label: 'Median',         value: summary['latency_ms_median'] != null ? `${summary['latency_ms_median']} ms` : '—' },
              { label: 'Std Dev',        value: summary['latency_ms_stdev']  != null ? `${summary['latency_ms_stdev']} ms`  : '—' },
              { label: 'Completed',      value: `${summary['completed']}/${summary['total_transfers']}` },
              { label: 'Failed',         value: String(summary['failed'] ?? 0) },
              { label: 'Target',         value: meta.target },
            ].map(({ label, value }) => (
              <div key={label} className="bg-white rounded-lg p-3 border border-emerald-100">
                <p className="text-xs text-slate-400 mb-0.5">{label}</p>
                <p className="text-base font-bold text-slate-800">{value}</p>
              </div>
            ))}
          </div>
          {summary['latency_ms_avg'] != null && (
            <p className="mt-3 text-sm text-emerald-700">
              EDC overhead: <strong>{summary['latency_ms_avg']} ms avg</strong> vs target {meta.target}.
            </p>
          )}
        </div>
      )}

    </div>
  )
}
