import { useEffect, useState } from 'react'
import { api } from '../api'

const PROVIDER_DSP = 'http://provider-cp:8183/protocol'

export default function Agreements() {
  const [agreements, setAgreements] = useState<Record<string, unknown>[]>([])
  const [loading, setLoading]       = useState(true)
  const [trStatus, setTrStatus]     = useState<Record<string, string>>({})

  const load = () => {
    setLoading(true)
    api.consumer.agreements()
      .then(d => { setAgreements(d as Record<string, unknown>[]); setLoading(false) })
      .catch(console.error)
  }
  useEffect(load, [])

  const startTransfer = async (agreementId: string, assetId: string) => {
    setTrStatus(prev => ({ ...prev, [agreementId]: 'starting…' }))
    const tc = assetId.includes('tc1') ? 'tc1' : assetId.includes('tc2') ? 'tc2' : 'tc3'
    try {
      await api.consumer.transfer({
        '@context': { '@vocab': 'https://w3id.org/edc/v0.0.1/ns/' },
        '@type': 'TransferRequestDto',
        connectorId: 'provider',
        counterPartyAddress: PROVIDER_DSP,
        contractId: agreementId,
        protocol: 'dataspace-protocol-http',
        transferType: 'HttpData-PUSH',
        dataDestination: {
          type: 'HttpData',
          baseUrl: `http://receiver:4000/receive/${tc}`,
        },
      })
      setTrStatus(prev => ({ ...prev, [agreementId]: 'started ✓' }))
    } catch (e) {
      setTrStatus(prev => ({ ...prev, [agreementId]: `error: ${e}` }))
    }
  }

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Contract Agreements</h1>
          <p className="text-slate-500 text-sm">Finalized agreements — ready for data transfer</p>
        </div>
        <button onClick={load} className="px-4 py-2 bg-violet-600 text-white text-sm rounded-lg hover:bg-violet-700">Refresh</button>
      </div>

      {loading ? <p className="text-slate-400">Loading…</p> : agreements.length === 0 ? (
        <p className="text-slate-400">No agreements yet. Complete a negotiation first.</p>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-xs uppercase border-b border-slate-200">
              <tr>
                <th className="px-5 py-3 text-left">Agreement ID</th>
                <th className="px-5 py-3 text-left">Asset</th>
                <th className="px-5 py-3 text-left">Provider</th>
                <th className="px-5 py-3 text-center">Transfer</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {agreements.map(a => {
                const id = a['@id'] as string
                const assetId = a['assetId'] as string
                const status  = trStatus[id]
                return (
                  <tr key={id} className="hover:bg-slate-50">
                    <td className="px-5 py-3 font-mono text-xs text-slate-500">{id?.slice(0, 24)}…</td>
                    <td className="px-5 py-3 font-medium text-slate-700">{assetId}</td>
                    <td className="px-5 py-3 text-slate-500">{a['providerId'] as string ?? 'provider'}</td>
                    <td className="px-5 py-3 text-center">
                      <button
                        onClick={() => startTransfer(id, assetId)}
                        disabled={!!status}
                        className="px-3 py-1.5 bg-violet-600 text-white text-xs rounded-lg hover:bg-violet-700 disabled:opacity-60 transition-colors">
                        {status ?? '▶ Start Transfer'}
                      </button>
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
