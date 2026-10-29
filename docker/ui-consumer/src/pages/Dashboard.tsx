import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge'

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="text-3xl font-bold text-slate-800 mt-1">{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
    </div>
  )
}

export default function Dashboard() {
  const [negotiations, setNegotiations] = useState<unknown[]>([])
  const [agreements,   setAgreements]   = useState<unknown[]>([])
  const [transfers,    setTransfers]     = useState<unknown[]>([])
  const [loading, setLoading]           = useState(true)

  useEffect(() => {
    Promise.all([api.consumer.negotiations(), api.consumer.agreements(), api.consumer.transfers()])
      .then(([n, a, t]) => { setNegotiations(n); setAgreements(a); setTransfers(t) })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="p-8 text-slate-400">Loading…</p>

  const recent = (transfers as Record<string, unknown>[]).slice(0, 5)

  return (
    <div className="p-8 max-w-5xl">
      <h1 className="text-2xl font-bold text-slate-800 mb-1">Consumer Dashboard</h1>
      <p className="text-slate-500 text-sm mb-6">Eclipse Dataspace Connector — Consumer Side</p>

      <div className="grid grid-cols-2 gap-4 mb-8 sm:grid-cols-4">
        <StatCard label="Negotiations"  value={negotiations.length} sub="contract negotiations" />
        <StatCard label="Agreements"    value={agreements.length}   sub="finalized contracts" />
        <StatCard label="Transfers"     value={transfers.length}    sub="transfer processes" />
        <StatCard label="Consumer port" value="9192"               sub="Management API" />
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm mb-6">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
          <h2 className="font-semibold text-slate-700">Recent Transfer Processes</h2>
          <Link to="/transfers" className="text-xs text-violet-600 hover:underline">View all →</Link>
        </div>
        {recent.length === 0 ? (
          <p className="px-5 py-6 text-slate-400 text-sm">No transfers yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
              <tr>
                <th className="px-5 py-2 text-left">ID</th>
                <th className="px-5 py-2 text-left">Asset</th>
                <th className="px-5 py-2 text-left">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {recent.map((t: Record<string, unknown>) => (
                <tr key={t['@id'] as string}>
                  <td className="px-5 py-2 font-mono text-xs text-slate-500">{(t['@id'] as string)?.slice(0, 16)}…</td>
                  <td className="px-5 py-2">{t['assetId'] as string ?? '—'}</td>
                  <td className="px-5 py-2"><StatusBadge state={t['state'] as string} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="bg-violet-50 border border-violet-200 rounded-xl p-5">
        <p className="text-violet-800 font-semibold text-sm mb-3">Start a Test Run</p>
        <div className="flex gap-3">
          {['tc1', 'tc2', 'tc3'].map(tc => (
            <Link key={tc} to={`/tests/${tc}`}
              className="px-4 py-2 bg-violet-600 text-white rounded-lg text-sm font-medium hover:bg-violet-700 transition-colors">
              Run {tc.toUpperCase()}
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}
