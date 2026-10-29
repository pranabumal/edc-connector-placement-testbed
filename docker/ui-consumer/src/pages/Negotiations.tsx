import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge'

const STATE_ORDER = ['REQUESTING', 'OFFERED', 'ACCEPTED', 'AGREED', 'VERIFIED', 'FINALIZED']

function StateTimeline({ state }: { state: string }) {
  const idx = STATE_ORDER.indexOf(state)
  return (
    <div className="flex items-center gap-1 mt-2">
      {STATE_ORDER.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <div className={`w-2 h-2 rounded-full ${
            i < idx ? 'bg-emerald-500' :
            i === idx ? 'bg-blue-500 ring-2 ring-blue-200' :
            'bg-slate-200'
          }`} />
          {i < STATE_ORDER.length - 1 && <div className={`w-4 h-px ${i < idx ? 'bg-emerald-300' : 'bg-slate-200'}`} />}
        </div>
      ))}
      <span className="ml-2 text-xs text-slate-400">{state}</span>
    </div>
  )
}

export default function Negotiations() {
  const [negs, setNegs]           = useState<Record<string, unknown>[]>([])
  const [loading, setLoading]     = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = () => {
    api.consumer.negotiations()
      .then(d => { setNegs((d as Record<string, unknown>[]).reverse()); setLoading(false) })
      .catch(console.error)
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    if (autoRefresh) timerRef.current = setInterval(load, 2000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [autoRefresh])

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Contract Negotiations</h1>
          <p className="text-slate-500 text-sm">All negotiations initiated from the Consumer connector</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} className="rounded" />
            Auto-refresh (2s)
          </label>
          <button onClick={load} className="px-4 py-2 bg-violet-600 text-white text-sm rounded-lg hover:bg-violet-700">Refresh</button>
        </div>
      </div>

      {loading ? <p className="text-slate-400">Loading…</p> : negs.length === 0 ? (
        <p className="text-slate-400">No negotiations yet. Go to Catalog to start one.</p>
      ) : (
        <div className="space-y-3">
          {negs.map(n => (
            <div key={n['@id'] as string} className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-slate-400">{(n['@id'] as string)?.slice(0, 24)}…</span>
                    <StatusBadge state={n['state'] as string} />
                  </div>
                  {n['contractAgreementId'] && (
                    <p className="text-xs text-emerald-600 mt-1">
                      Agreement: <code>{(n['contractAgreementId'] as string)?.slice(0, 24)}…</code>
                    </p>
                  )}
                  <StateTimeline state={n['state'] as string} />
                </div>
                <div className="text-right text-xs text-slate-400">
                  <p>Counter party:</p>
                  <p className="text-slate-600">{n['counterPartyId'] as string ?? 'provider'}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
