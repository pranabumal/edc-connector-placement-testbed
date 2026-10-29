import { useEffect, useState } from 'react'
import { api } from '../api'

interface AccessRequest {
  request_id:   string
  asset_id:     string
  asset_name:   string
  status:       string   // 'pending' | 'approved' | 'rejected'
  requested_at: number
  decided_at:   number | null
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending:  'bg-amber-100 text-amber-700 border-amber-200',
    approved: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    rejected: 'bg-red-100 text-red-600 border-red-200',
  }
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${map[status] ?? 'bg-slate-100 text-slate-500'}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  )
}

function timeAgo(ms: number) {
  const d = Date.now() - ms
  if (d < 60_000)    return `${Math.floor(d / 1000)}s ago`
  if (d < 3_600_000) return `${Math.floor(d / 60_000)}m ago`
  return `${Math.floor(d / 3_600_000)}h ago`
}

export default function AccessRequests() {
  const [requests, setRequests] = useState<AccessRequest[]>([])
  const [loading,  setLoading]  = useState(true)
  const [acting,   setActing]   = useState<string | null>(null)

  const load = () =>
    api.access.requests()
      .then(d => { setRequests(d as AccessRequest[]); setLoading(false) })
      .catch(console.error)

  useEffect(() => {
    load()
    const id = setInterval(load, 4000)   // auto-refresh every 4 s
    return () => clearInterval(id)
  }, [])

  const decide = async (requestId: string, action: 'approve' | 'reject') => {
    setActing(requestId)
    try {
      if (action === 'approve') await api.access.approve(requestId)
      else                      await api.access.reject(requestId)
      await load()
    } finally {
      setActing(null)
    }
  }

  const pending  = requests.filter(r => r.status === 'pending')
  const decided  = requests.filter(r => r.status !== 'pending')

  return (
    <div className="p-8 max-w-4xl space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Access Requests</h1>
          <p className="text-slate-500 text-sm">
            Consumer must request access here before data can be negotiated or transferred.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {pending.length > 0 && (
            <span className="px-2.5 py-0.5 bg-amber-100 text-amber-700 text-xs font-bold rounded-full border border-amber-200">
              {pending.length} pending
            </span>
          )}
          <button onClick={load} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
            Refresh
          </button>
        </div>
      </div>

      {/* Workflow guide */}
      <div className="flex items-center gap-2 text-xs text-slate-500 flex-wrap">
        <span className="px-2 py-0.5 bg-slate-100 rounded">Consumer: Request Access</span>
        <span>→</span>
        <span className="px-2 py-0.5 bg-amber-100 text-amber-700 rounded font-medium">Provider: Approve / Reject ← you are here</span>
        <span>→</span>
        <span className="px-2 py-0.5 bg-slate-100 rounded">Consumer: Negotiate Agreement</span>
        <span>→</span>
        <span className="px-2 py-0.5 bg-slate-100 rounded">Consumer: Transfer / Run Tests</span>
      </div>

      {loading && <p className="text-slate-400 text-sm">Loading…</p>}

      {/* Pending requests */}
      {!loading && pending.length === 0 && decided.length === 0 && (
        <div className="bg-slate-50 rounded-xl border border-slate-200 p-10 text-center text-slate-400">
          <p className="text-lg mb-1">No requests yet</p>
          <p className="text-sm">When the Consumer requests access to an asset, it will appear here.</p>
        </div>
      )}

      {pending.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm font-semibold text-slate-700">Pending — awaiting your decision</p>
          {pending.map(req => (
            <div key={req.request_id}
              className="bg-white rounded-xl border border-amber-200 shadow-sm p-5 flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-slate-800">{req.asset_name || req.asset_id}</p>
                <p className="text-xs text-slate-400 mt-0.5 font-mono">{req.asset_id}</p>
                <div className="flex items-center gap-3 mt-2">
                  <StatusChip status={req.status} />
                  <span className="text-xs text-slate-400">Requested {timeAgo(req.requested_at)}</span>
                  <span className="text-xs text-slate-300 font-mono">{req.request_id.slice(0, 12)}…</span>
                </div>
              </div>
              <div className="flex gap-2 shrink-0">
                <button
                  onClick={() => decide(req.request_id, 'approve')}
                  disabled={acting === req.request_id}
                  className="px-4 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700 disabled:opacity-50 font-medium">
                  {acting === req.request_id ? '…' : 'Approve'}
                </button>
                <button
                  onClick={() => decide(req.request_id, 'reject')}
                  disabled={acting === req.request_id}
                  className="px-4 py-2 bg-red-50 text-red-600 border border-red-200 text-sm rounded-lg hover:bg-red-100 disabled:opacity-50">
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Decided requests */}
      {decided.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-semibold text-slate-700">Decision history</p>
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500 text-xs uppercase border-b border-slate-100">
                <tr>
                  <th className="px-5 py-2 text-left">Asset</th>
                  <th className="px-5 py-2 text-left">Status</th>
                  <th className="px-5 py-2 text-left">Requested</th>
                  <th className="px-5 py-2 text-left">Decided</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {decided.map(req => (
                  <tr key={req.request_id} className="hover:bg-slate-50">
                    <td className="px-5 py-2">
                      <p className="font-medium text-slate-700">{req.asset_name || req.asset_id}</p>
                      <p className="text-xs text-slate-400 font-mono">{req.asset_id}</p>
                    </td>
                    <td className="px-5 py-2"><StatusChip status={req.status} /></td>
                    <td className="px-5 py-2 text-xs text-slate-500">{timeAgo(req.requested_at)}</td>
                    <td className="px-5 py-2 text-xs text-slate-500">
                      {req.decided_at ? timeAgo(req.decided_at) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

    </div>
  )
}
