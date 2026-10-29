import { useEffect, useState } from 'react'
import { api } from '../api'

export default function ContractDefs() {
  const [defs, setDefs]       = useState<Record<string, unknown>[]>([])
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    api.provider.contractdefs()
      .then(d => setDefs(d as Record<string, unknown>[]))
      .catch(console.error)
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Contract Definitions</h1>
          <p className="text-slate-500 text-sm">Defines which assets are offered under which policies</p>
        </div>
        <button onClick={load} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">Refresh</button>
      </div>

      {loading ? <p className="text-slate-400">Loading…</p> : defs.length === 0 ? (
        <p className="text-slate-400">No contract definitions found.</p>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-xs uppercase border-b border-slate-200">
              <tr>
                <th className="px-5 py-3 text-left">Definition ID</th>
                <th className="px-5 py-3 text-left">Access Policy</th>
                <th className="px-5 py-3 text-left">Contract Policy</th>
                <th className="px-5 py-3 text-left">Asset Selector</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {defs.map(d => {
                const selector = (d['assetsSelector'] ?? []) as Record<string, unknown>[]
                const assetVal = selector[0]?.['operandRight'] as string ?? '—'
                return (
                  <tr key={d['@id'] as string} className="hover:bg-slate-50">
                    <td className="px-5 py-3 font-mono text-xs text-slate-700">{d['@id'] as string}</td>
                    <td className="px-5 py-3 text-slate-600">{d['accessPolicyId'] as string}</td>
                    <td className="px-5 py-3 text-slate-600">{d['contractPolicyId'] as string}</td>
                    <td className="px-5 py-3">
                      <span className="bg-blue-50 text-blue-700 text-xs px-2 py-0.5 rounded font-mono">{assetVal}</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
