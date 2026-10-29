import { useEffect, useState } from 'react'
import { api } from '../api'

export default function Policies() {
  const [policies, setPolicies] = useState<Record<string, unknown>[]>([])
  const [loading, setLoading]   = useState(true)

  const load = () => {
    setLoading(true)
    api.provider.policies()
      .then(d => setPolicies(d as Record<string, unknown>[]))
      .catch(console.error)
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Policy Definitions</h1>
          <p className="text-slate-500 text-sm">ODRL access and usage policies on the Provider</p>
        </div>
        <button onClick={load} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">Refresh</button>
      </div>

      {loading ? <p className="text-slate-400">Loading…</p> : policies.length === 0 ? (
        <p className="text-slate-400">No policies found.</p>
      ) : (
        <div className="space-y-4">
          {policies.map(p => {
            const policy = (p['policy'] ?? {}) as Record<string, unknown>
            const perms = (policy['odrl:permission'] ?? policy['permission'] ?? []) as unknown[]
            const proh  = (policy['odrl:prohibition'] ?? policy['prohibition'] ?? []) as unknown[]
            const oblig = (policy['odrl:obligation'] ?? policy['obligation'] ?? []) as unknown[]
            return (
              <div key={p['@id'] as string} className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="font-semibold text-slate-800">{p['@id'] as string}</span>
                  <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">ODRL Policy</span>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  {[
                    { label: 'Permissions', items: perms, color: 'text-emerald-600' },
                    { label: 'Prohibitions', items: proh, color: 'text-red-600' },
                    { label: 'Obligations', items: oblig, color: 'text-amber-600' },
                  ].map(({ label, items, color }) => (
                    <div key={label}>
                      <p className={`text-xs font-semibold uppercase mb-1 ${color}`}>{label}</p>
                      {items.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">None (open access)</p>
                      ) : (
                        <pre className="text-xs text-slate-600 whitespace-pre-wrap">{JSON.stringify(items, null, 2)}</pre>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
