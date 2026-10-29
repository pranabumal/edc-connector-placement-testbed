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
  const [assets, setAssets]       = useState<unknown[]>([])
  const [transfers, setTransfers] = useState<unknown[]>([])
  const [loading, setLoading]     = useState(true)
  const [setupStatus, setSetupStatus] = useState<'idle' | 'running' | 'ok' | 'error'>('idle')
  const [setupMsg, setSetupMsg]       = useState('')

  useEffect(() => {
    Promise.all([api.provider.assets(), api.provider.transfers()])
      .then(([a, t]) => { setAssets(a); setTransfers(t) })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const runSetup = async () => {
    setSetupStatus('running')
    setSetupMsg('')
    try {
      const res = await api.provider.setup()
      const assetCount = (res['assets'] as unknown[])?.length ?? 0
      setSetupMsg(`Done — ${assetCount} assets, policy, and contract definitions registered.`)
      setSetupStatus('ok')
      // Reload asset count
      api.provider.assets().then(setAssets).catch(console.error)
    } catch (e) {
      setSetupMsg(String(e))
      setSetupStatus('error')
    }
  }

  if (loading) return <p className="p-8 text-slate-400">Loading…</p>

  const recent = (transfers as Record<string, unknown>[]).slice(0, 5)

  return (
    <div className="p-8 max-w-5xl">
      <h1 className="text-2xl font-bold text-slate-800 mb-1">Provider Dashboard</h1>
      <p className="text-slate-500 text-sm mb-6">
        Eclipse Dataspace Connector — Provider Control Plane
      </p>

      {/* One-shot provider setup */}
      {assets.length === 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 mb-6 flex items-start gap-4">
          <div className="flex-1">
            <p className="text-amber-800 font-semibold text-sm">No assets registered</p>
            <p className="text-amber-700 text-xs mt-1">
              The Provider connector is empty. Click "Run Setup" to register the TC-1, TC-2, and TC-3
              assets, an open-access policy, and contract definitions.
            </p>
            {setupMsg && (
              <p className={`text-xs mt-2 ${setupStatus === 'error' ? 'text-red-600' : 'text-emerald-700'}`}>
                {setupMsg}
              </p>
            )}
          </div>
          <button
            onClick={runSetup}
            disabled={setupStatus === 'running'}
            className="shrink-0 px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white text-sm font-semibold rounded-lg transition-colors">
            {setupStatus === 'running' ? 'Setting up…' : 'Run Setup'}
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 mb-8 sm:grid-cols-4">
        <StatCard label="Assets"           value={assets.length}    sub="registered in catalog" />
        <StatCard label="Transfer Processes" value={transfers.length} sub="total on provider side" />
        <StatCard label="Provider port"    value="8182"             sub="Management API" />
        <StatCard label="Protocol port"    value="8183"             sub="DSP endpoint" />
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm mb-6">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
          <h2 className="font-semibold text-slate-700">Recent Transfer Processes</h2>
          <Link to="/transfers" className="text-xs text-blue-600 hover:underline">View all →</Link>
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
                  <td className="px-5 py-2 font-mono text-xs text-slate-500 truncate max-w-xs">{(t['@id'] as string)?.slice(0, 16)}…</td>
                  <td className="px-5 py-2">{t['assetId'] as string ?? '—'}</td>
                  <td className="px-5 py-2"><StatusBadge state={t['state'] as string} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-xl p-5">
        <p className="text-blue-800 font-semibold text-sm mb-3">Run a Test Case</p>
        <div className="flex gap-3">
          {['tc1', 'tc2', 'tc3'].map(tc => (
            <Link key={tc} to={`/tests/${tc}`}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors">
              Run {tc.toUpperCase()}
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}
