import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge'

const ACCENT = 'blue'

const TC_META: Record<string, { label: string; desc: string; target: string; payload: string }> = {
  tc1: {
    label:   'TC-1: Real-time Control Signal',
    desc:    'Near-real-time control signal at ~50 Hz. Small payload (~300 B). Tests EDC overhead against a 20 ms target.',
    target:  '≤ 20 ms (50 Hz)',
    payload: '~300 bytes',
  },
  tc2: {
    label:   'TC-2: High-Frequency Sensor Batch',
    desc:    '1 kHz vibration sensor batch — 1 000 samples per request (~50 KB). Tests throughput and batch latency.',
    target:  'Batch every ~1 s',
    payload: '~50 KB',
  },
  tc3: {
    label:   'TC-3: Video Stream',
    desc:    'Simulated 640×480 compressed video frame (~15 KB). Tests maximum frame throughput through EDC.',
    target:  '≤ 41 ms (24 fps)',
    payload: '~15 KB',
  },
  tc4: {
    label:   'TC-4: AAS Control Signal via EDC',
    desc:    'Transfers the live ControlSignal submodel from BaSyx AAS through EDC. Same data domain as TC-1 but routed via the digital twin layer — compare latency to quantify AAS mediation overhead.',
    target:  '≤ 20 ms (compare vs TC-1)',
    payload: 'AAS submodel JSON (~1 KB)',
  },
}

const PHASE_ORDER = ['catalog', 'negotiate', 'transfers', 'metrics'] as const
type Phase = typeof PHASE_ORDER[number]

interface PhaseStatus { catalog: string; negotiate: string; transfers: string; metrics: string }
interface TransferRow { index: number; transfer_id: string; state: string; elapsed_ms: number }

interface HistoryRun {
  id: string
  tc: string
  label: string
  repeats: number
  status: string
  started_at: number
  result?: {
    summary?: Record<string, number>
    transfers?: TransferRow[]
  }
  error?: string
}

// ── Shared sub-components ────────────────────────────────────────────────────

function PhaseRow({ phases, negState, rows, totalTransfers }: {
  phases: PhaseStatus; negState: string; rows: TransferRow[]; totalTransfers: number
}) {
  const icon = (p: string) =>
    p === 'running' ? { sym: '◎', cls: `text-${ACCENT}-500 animate-pulse` } :
    p === 'done'    ? { sym: '✓', cls: 'text-emerald-500' } :
                     { sym: '○', cls: 'text-slate-300' }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {PHASE_ORDER.map((phase, idx) => {
        const st   = phases[phase as Phase]
        const { sym, cls } = icon(st)
        return (
          <div key={phase} className="flex items-center gap-2">
            <div className={`flex items-center gap-1.5 ${cls}`}>
              <span className="text-xl font-mono leading-none">{sym}</span>
              <div>
                <p className="text-xs font-semibold capitalize">
                  {phase === 'negotiate' ? 'Negotiate' : phase.charAt(0).toUpperCase() + phase.slice(1)}
                </p>
                {phase === 'negotiate' && negState && st === 'running' && (
                  <p className="text-xs text-slate-400">{negState}</p>
                )}
                {phase === 'transfers' && rows.length > 0 && (
                  <p className="text-xs text-slate-400">{rows.length}/{totalTransfers}</p>
                )}
              </div>
            </div>
            {idx < PHASE_ORDER.length - 1 && <div className="w-8 h-px bg-slate-200" />}
          </div>
        )
      })}
    </div>
  )
}

function SummaryGrid({ summary, meta }: { summary: Record<string, number>; meta: typeof TC_META[string] }) {
  const avg = summary['latency_ms_avg']
  return (
    <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5">
      <p className="text-emerald-800 font-semibold mb-4">Run Summary</p>
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Avg Latency', value: avg != null ? `${avg} ms` : '—' },
          { label: 'Min Latency', value: summary['latency_ms_min'] != null ? `${summary['latency_ms_min']} ms` : '—' },
          { label: 'Max Latency', value: summary['latency_ms_max'] != null ? `${summary['latency_ms_max']} ms` : '—' },
          { label: 'Completed',   value: `${summary['completed']}/${summary['total_transfers']}` },
        ].map(({ label, value }) => (
          <div key={label} className="bg-white rounded-lg p-3 border border-emerald-100">
            <p className="text-xs text-slate-400 mb-0.5">{label}</p>
            <p className="text-xl font-bold text-slate-800">{value}</p>
          </div>
        ))}
      </div>
      {avg != null && (
        <p className="mt-3 text-sm text-emerald-700">
          EDC overhead: <strong>{avg} ms avg</strong> vs target {meta.target}.
        </p>
      )}
    </div>
  )
}

function TransferTable({ rows, total }: { rows: TransferRow[]; total?: number }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
        <p className="text-sm font-semibold text-slate-700">Transfer Results</p>
        <span className="text-xs text-slate-400">{rows.length} / {total ?? rows.length} transfers</span>
      </div>
      <div className="max-h-72 overflow-y-auto">
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
            {rows.map(r => (
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
  )
}

// ── History card ─────────────────────────────────────────────────────────────

function HistoryCard({ run, meta }: { run: HistoryRun; meta: typeof TC_META[string] }) {
  const [showTransfers, setShowTransfers] = useState(false)
  const transfers = run.result?.transfers ?? []
  const summary   = run.result?.summary

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      {/* Card header */}
      <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="font-mono text-xs text-slate-400">{run.id.slice(0, 8)}…</span>
          <StatusBadge state={run.status} />
          <span className="text-xs text-slate-500">{run.repeats} repeats</span>
          <span className="text-xs text-slate-400">{new Date(run.started_at).toLocaleString()}</span>
        </div>
        <Link
          to={`/tests/runs/${run.id}`}
          className={`text-xs text-${ACCENT}-600 hover:underline font-medium`}>
          Full Details →
        </Link>
      </div>

      {/* Compact summary stats */}
      {summary && (
        <div className="px-5 py-3 bg-slate-50 border-b border-slate-100 grid grid-cols-4 gap-4">
          {[
            { label: 'Avg',  value: `${summary['latency_ms_avg']} ms`,  cls: 'text-slate-800' },
            { label: 'Min',  value: `${summary['latency_ms_min']} ms`,  cls: 'text-emerald-600' },
            { label: 'Max',  value: `${summary['latency_ms_max']} ms`,  cls: 'text-red-500' },
            { label: 'Done', value: `${summary['completed']}/${summary['total_transfers']}`, cls: 'text-slate-700' },
          ].map(({ label, value, cls }) => (
            <div key={label}>
              <p className="text-xs text-slate-400">{label}</p>
              <p className={`font-mono font-bold text-sm ${cls}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Error */}
      {run.error && (
        <div className="px-5 py-3 bg-red-50 border-b border-red-100 text-xs text-red-700">
          <strong>Error:</strong> {run.error}
        </div>
      )}

      {/* Transfer table toggle */}
      {transfers.length > 0 && (
        <div className="px-5 py-2 border-b border-slate-100">
          <button
            onClick={() => setShowTransfers(v => !v)}
            className="text-xs text-slate-500 hover:text-slate-700 hover:underline">
            {showTransfers ? '▲ Hide' : '▼ Show'} {transfers.length} transfers
          </button>
        </div>
      )}
      {showTransfers && transfers.length > 0 && (
        <TransferTable rows={transfers} total={run.repeats} />
      )}
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function TestRunner() {
  const { tc = 'tc1' } = useParams<{ tc: string }>()
  const meta = TC_META[tc] ?? TC_META.tc1

  // Configuration
  const [repeats, setRepeats] = useState(5)

  // Active run (live)
  const [activeRunId,      setActiveRunId]      = useState<string | null>(null)
  const [activeStatus,     setActiveStatus]     = useState<string>('idle')
  const [phases,           setPhases]           = useState<PhaseStatus>({ catalog: 'idle', negotiate: 'idle', transfers: 'idle', metrics: 'idle' })
  const [negState,         setNegState]         = useState('')
  const [rows,             setRows]             = useState<TransferRow[]>([])
  const [totalTransfers,   setTotalTransfers]   = useState(0)
  const [activeSummary,    setActiveSummary]    = useState<Record<string, unknown> | null>(null)
  const [activeError,      setActiveError]      = useState('')
  const sseRef = useRef<EventSource | null>(null)

  // Access / agreement gate
  const [accessStatus, setAccessStatus] = useState<Record<string, unknown> | null>(null)

  const loadAccessStatus = () =>
    api.access.status(tc)
      .then(s => setAccessStatus(s))
      .catch(console.error)

  // Run history for this TC
  const [history, setHistory] = useState<HistoryRun[]>([])

  const loadHistory = () =>
    api.tests.runs()
      .then(runs => setHistory((runs as HistoryRun[]).filter(r => r.tc === tc)))
      .catch(console.error)

  // Reset active run + reload history + access status when TC changes
  useEffect(() => {
    sseRef.current?.close()
    setActiveRunId(null)
    setActiveStatus('idle')
    setAccessStatus(null)
    setPhases({ catalog: 'idle', negotiate: 'idle', transfers: 'idle', metrics: 'idle' })
    setNegState(''); setRows([]); setActiveSummary(null); setActiveError(''); setTotalTransfers(0)
    loadHistory()
    loadAccessStatus()
  }, [tc]) // eslint-disable-line react-hooks/exhaustive-deps

  const startRun = async () => {
    sseRef.current?.close()
    setActiveRunId(null)
    setActiveStatus('starting')
    setPhases({ catalog: 'idle', negotiate: 'idle', transfers: 'idle', metrics: 'idle' })
    setNegState(''); setRows([]); setActiveSummary(null); setActiveError(''); setTotalTransfers(0)

    try {
      const { run_id } = await api.tests.run(tc, repeats)
      setActiveRunId(run_id)
      setActiveStatus('running')

      const src = new EventSource(`/api/tests/stream/${run_id}`)
      sseRef.current = src

      src.onmessage = (e: MessageEvent) => {
        const event = JSON.parse(e.data) as Record<string, unknown>
        const type  = event['type'] as string

        if (type === 'phase') {
          const phase  = event['phase'] as Phase
          const status = event['status'] as string
          setPhases(prev => ({ ...prev, [phase]: status }))
          if (phase === 'transfers' && event['total']) setTotalTransfers(event['total'] as number)
        }
        if (type === 'negotiate_state') setNegState(event['state'] as string)
        if (type === 'transfer_done')   setRows(prev => [...prev, event as unknown as TransferRow])
        if (type === 'completed') {
          setActiveSummary((event['summary'] ?? {}) as Record<string, unknown>)
          setActiveStatus('completed')
          src.close()
          loadHistory()
        }
        if (type === 'failed') {
          setActiveError(event['error'] as string)
          setActiveStatus('failed')
          src.close()
          loadHistory()
        }
      }
      src.onerror = () => {
        setActiveError('SSE connection lost.')
        setActiveStatus('failed')
        src.close()
      }
    } catch (e) {
      setActiveError(String(e)); setActiveStatus('failed')
    }
  }

  const isRunning    = activeStatus === 'running' || activeStatus === 'starting'
  const hasActiveRun = activeStatus !== 'idle'

  const hasAgreement   = !!accessStatus?.['agreement_id']
  const accessApproved = !!accessStatus?.['access_approved']
  const canRun         = hasAgreement || accessApproved
  const accessChecked  = accessStatus !== null

  // History cards exclude the currently active run (it's shown at top)
  const historyCards = history.filter(r => r.id !== activeRunId)

  return (
    <div className="p-8 max-w-5xl space-y-6">

      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-800 mb-1">{meta.label}</h1>
        <p className="text-slate-500 text-sm">{meta.desc}</p>
        <div className="flex gap-6 mt-3 text-sm">
          <span className="text-slate-500">Target: <span className="text-slate-800 font-medium">{meta.target}</span></span>
          <span className="text-slate-500">Payload: <span className="text-slate-800 font-medium">{meta.payload}</span></span>
        </div>
      </div>

      {/* ── Access / agreement gate banner ──────────────────────────────────── */}
      {accessChecked && !hasAgreement && !accessApproved && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
          <p className="font-semibold mb-1">No active agreement for this asset</p>
          <ol className="list-decimal list-inside text-xs space-y-0.5 text-amber-700">
            <li>Consumer: go to Catalog → <strong>Request Access</strong></li>
            <li>Provider: go to <strong>Access Requests</strong> → Approve</li>
            <li>Consumer: Catalog → <strong>Negotiate &amp; Agree</strong></li>
            <li>Return here to run the test</li>
          </ol>
          <div className="flex gap-3 mt-3">
            <Link to="/access" className="text-xs text-blue-600 hover:underline font-medium">
              Go to Access Requests →
            </Link>
            <button onClick={loadAccessStatus} className="text-xs text-slate-500 hover:underline">
              Re-check
            </button>
          </div>
        </div>
      )}

      {accessChecked && hasAgreement && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm text-emerald-700 flex items-center justify-between">
          <div>
            <p className="font-semibold">Active agreement — negotiate phase will be skipped</p>
            <p className="text-xs mt-0.5 font-mono text-emerald-600">
              {(accessStatus!['agreement_id'] as string).slice(0, 36)}…
            </p>
          </div>
          <button onClick={loadAccessStatus} className="text-xs text-emerald-600 hover:underline shrink-0">
            Refresh
          </button>
        </div>
      )}

      {accessChecked && accessApproved && !hasAgreement && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-sm text-blue-700">
          <p className="font-semibold">Access approved — test will negotiate a new agreement</p>
          <p className="text-xs mt-0.5 text-blue-500">
            No existing agreement found. The test will run the full 4-phase flow including EDC negotiation.
          </p>
        </div>
      )}

      {/* Run configuration */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
        <p className="text-sm font-semibold text-slate-700 mb-4">Run Configuration</p>
        <div className="flex items-center gap-6">
          <label className="flex items-center gap-3 text-sm text-slate-600">
            Transfers:
            <input
              type="number" min={1} max={1000} value={repeats}
              onChange={e => setRepeats(Number(e.target.value))}
              disabled={isRunning}
              className={`w-24 border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-${ACCENT}-500 disabled:bg-slate-100`}
            />
          </label>
          <button
            onClick={startRun}
            disabled={isRunning || (accessChecked && !canRun)}
            className={`px-6 py-2 bg-${ACCENT}-600 text-white rounded-lg text-sm font-semibold hover:bg-${ACCENT}-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors`}>
            {isRunning ? '● Running…' : '▶ Run Test'}
          </button>
          {accessChecked && !canRun && !isRunning && (
            <span className="text-xs text-amber-600 font-medium">Requires approval first</span>
          )}
          {activeStatus === 'completed' && <span className="text-emerald-600 font-semibold text-sm">✓ Completed</span>}
          {activeStatus === 'failed'    && <span className="text-red-600    font-semibold text-sm">✗ Failed</span>}
        </div>
      </div>

      {/* ── Active run block ─────────────────────────────────────────────── */}
      {hasActiveRun && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-semibold text-slate-700">Current Run</h2>
            {activeRunId && (
              <span className="font-mono text-xs text-slate-400">{activeRunId.slice(0, 8)}…</span>
            )}
            <StatusBadge state={activeStatus} />
            {activeRunId && (
              <Link to={`/tests/runs/${activeRunId}`} className={`text-xs text-${ACCENT}-600 hover:underline ml-auto`}>
                Full Details →
              </Link>
            )}
          </div>

          {/* Phase progress */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <p className="text-sm font-semibold text-slate-700 mb-4">Phase Progress</p>
            <PhaseRow phases={phases} negState={negState} rows={rows} totalTransfers={totalTransfers} />
          </div>

          {/* Error */}
          {activeError && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">
              <strong>Error:</strong> {activeError}
            </div>
          )}

          {/* Live transfer table */}
          {rows.length > 0 && (
            <TransferTable rows={rows} total={totalTransfers || repeats} />
          )}

          {/* Summary */}
          {activeSummary && (
            <SummaryGrid summary={activeSummary as Record<string, number>} meta={meta} />
          )}
        </div>
      )}

      {/* ── Run history ──────────────────────────────────────────────────── */}
      {historyCards.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-slate-700">
            Previous Runs
            <span className="ml-2 text-slate-400 font-normal">({historyCards.length})</span>
          </h2>
          {historyCards.map(run => (
            <HistoryCard key={run.id} run={run} meta={meta} />
          ))}
        </div>
      )}

      {!hasActiveRun && historyCards.length === 0 && (
        <p className="text-slate-400 text-sm">No runs yet. Click "Run Test" to start.</p>
      )}

    </div>
  )
}
