import { useEffect, useState } from 'react'
import { api } from '../api'

const TC_BADGE: Record<string, string> = {
  TC1: 'bg-blue-100 text-blue-700',
  TC2: 'bg-violet-100 text-violet-700',
  TC3: 'bg-amber-100 text-amber-700',
}

export default function Assets() {
  const [assets, setAssets]   = useState<Record<string, unknown>[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  const load = () => {
    setLoading(true)
    api.provider.assets()
      .then(data => setAssets(data as Record<string, unknown>[]))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const props = (a: Record<string, unknown>) =>
    (a['properties'] ?? {}) as Record<string, string>

  const addr = (a: Record<string, unknown>) =>
    (a['dataAddress'] ?? {}) as Record<string, string>

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Assets</h1>
          <p className="text-slate-500 text-sm">Data assets registered on the Provider connector</p>
        </div>
        <button onClick={load}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors">
          Refresh
        </button>
      </div>

      {error && <p className="text-red-500 text-sm mb-4">{error}</p>}
      {loading ? (
        <p className="text-slate-400">Loading…</p>
      ) : assets.length === 0 ? (
        <p className="text-slate-400">No assets registered. Run the provider setup script.</p>
      ) : (
        <div className="space-y-4">
          {assets.map(a => {
            const p = props(a)
            const d = addr(a)
            const tc = p['testcase'] ?? ''
            return (
              <div key={a['@id'] as string} className="bg-white rounded-xl border border-slate-200 shadow-sm">
                <div className="flex items-start justify-between px-5 pt-4 pb-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-slate-800">{p['name'] ?? a['@id'] as string}</span>
                      {tc && (
                        <span className={`text-xs px-2 py-0.5 rounded font-semibold ${TC_BADGE[tc] ?? 'bg-slate-100 text-slate-600'}`}>
                          {tc}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-slate-500 mt-0.5">{p['description']}</p>
                  </div>
                  <span className="font-mono text-xs text-slate-400 mt-0.5">{a['@id'] as string}</span>
                </div>
                <div className="border-t border-slate-100 px-5 py-3 bg-slate-50 rounded-b-xl">
                  <div className="flex flex-wrap gap-x-8 gap-y-1 text-xs text-slate-500">
                    <span><span className="text-slate-400">Type:</span> {d['type']}</span>
                    <span><span className="text-slate-400">Source URL:</span> <code className="text-slate-700">{d['baseUrl']}</code></span>
                    <span><span className="text-slate-400">Content-type:</span> {p['contenttype']}</span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
