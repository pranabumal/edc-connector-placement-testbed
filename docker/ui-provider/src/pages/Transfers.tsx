import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge'

export default function Transfers() {
  const [transfers, setTransfers] = useState<Record<string, unknown>[]>([])
  const [loading, setLoading]     = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = () => {
    api.provider.transfers()
      .then(d => { setTransfers((d as Record<string, unknown>[]).reverse()); setLoading(false) })
      .catch(console.error)
  }

  useEffect(() => {
    load()
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [])

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    if (autoRefresh) timerRef.current = setInterval(load, 3000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [autoRefresh])

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Transfer Processes</h1>
          <p className="text-slate-500 text-sm">All transfer processes on the Provider side</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)}
              className="rounded" />
            Auto-refresh (3s)
          </label>
          <button onClick={load} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">Refresh</button>
        </div>
      </div>

      {loading ? <p className="text-slate-400">Loading…</p> : transfers.length === 0 ? (
        <p className="text-slate-400">No transfer processes yet.</p>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-xs uppercase border-b border-slate-200">
              <tr>
                <th className="px-5 py-3 text-left">Transfer ID</th>
                <th className="px-5 py-3 text-left">Asset</th>
                <th className="px-5 py-3 text-left">Type</th>
                <th className="px-5 py-3 text-left">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {transfers.map(t => (
                <tr key={t['@id'] as string} className="hover:bg-slate-50">
                  <td className="px-5 py-3 font-mono text-xs text-slate-500">{(t['@id'] as string)?.slice(0, 20)}…</td>
                  <td className="px-5 py-3 text-slate-700">{t['assetId'] as string ?? '—'}</td>
                  <td className="px-5 py-3 text-slate-500 text-xs">{t['type'] as string ?? '—'}</td>
                  <td className="px-5 py-3"><StatusBadge state={t['state'] as string ?? 'UNKNOWN'} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
