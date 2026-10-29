import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, DbNegotiation } from '../api'

const PROVIDER_DSP = 'http://provider-cp:8183/protocol'
const STATE_ORDER  = ['REQUESTING', 'OFFERED', 'AGREED', 'VERIFIED', 'FINALIZED']

function timeAgo(ms: number): string {
  const diff = Date.now() - ms
  if (diff < 60_000)    return `${Math.floor(diff / 1000)}s ago`
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  return `${Math.floor(diff / 3_600_000)}h ago`
}

// ── Policy panel ──────────────────────────────────────────────────────────────

function PolicyPanel({ policy }: { policy: Record<string, unknown> }) {
  const perms   = (policy['odrl:permission']  as unknown[] ?? [])
  const prohibs = (policy['odrl:prohibition'] as unknown[] ?? [])
  const obligs  = (policy['odrl:obligation']  as unknown[] ?? [])
  const isOpen  = perms.length === 0 && prohibs.length === 0 && obligs.length === 0

  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
      <p className="font-semibold text-slate-600 mb-2">
        Policy Terms
        <span className="ml-2 font-normal text-slate-400">
          (you must agree to these before data can transfer)
        </span>
      </p>
      {isOpen ? (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded-full font-medium">
          Open access — no restrictions
        </span>
      ) : (
        <div className="space-y-1 text-slate-700">
          {perms.length   > 0 && <p><span className="font-medium text-blue-700">Permissions:</span> {perms.length} rule(s)</p>}
          {prohibs.length > 0 && <p><span className="font-medium text-red-700">Prohibitions:</span> {prohibs.length} rule(s)</p>}
          {obligs.length  > 0 && <p><span className="font-medium text-amber-700">Obligations:</span> {obligs.length} rule(s)</p>}
        </div>
      )}
      <p className="text-slate-400 mt-2">
        Offer ID: <code className="text-slate-500">{(policy['@id'] as string)?.slice(0, 28)}…</code>
      </p>
    </div>
  )
}

// ── Negotiation timeline ──────────────────────────────────────────────────────

function NegTimeline({ state }: { state: string }) {
  const idx          = STATE_ORDER.indexOf(state)
  const isTerminated = state === 'TERMINATED'

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {STATE_ORDER.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <div title={s} className={`w-2.5 h-2.5 rounded-full transition-all ${
            isTerminated ? 'bg-red-400' :
            i < idx      ? 'bg-emerald-500' :
            i === idx    ? 'bg-violet-500 ring-2 ring-violet-200' :
            'bg-slate-200'
          }`} />
          {i < STATE_ORDER.length - 1 && (
            <div className={`w-5 h-px ${i < idx ? 'bg-emerald-300' : 'bg-slate-200'}`} />
          )}
        </div>
      ))}
      <span className={`ml-2 text-xs font-semibold ${
        isTerminated ? 'text-red-600' :
        state === 'FINALIZED' ? 'text-emerald-600' : 'text-violet-600'
      }`}>{state}</span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface NegTrack {
  negId:          string
  state:          string
  agreementId?:   string
  transferStatus?: string
}

interface AccessTrack {
  requestId: string
  status:    string   // 'pending' | 'approved' | 'rejected'
}

export default function Catalog() {
  const [catalog, setCatalog]       = useState<Record<string, unknown> | null>(null)
  const [cacheTime, setCacheTime]   = useState<number | null>(null)
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState('')
  const [negTrack,    setNegTrack]    = useState<Record<string, NegTrack>>({})
  const [accessTrack, setAccessTrack] = useState<Record<string, AccessTrack>>({})
  const [restored, setRestored]     = useState(false)
  const pollRefs    = useRef<Record<string, ReturnType<typeof setInterval>>>({})
  const accessPolls = useRef<Record<string, ReturnType<typeof setInterval>>>({})

  // ── On mount: restore state from DB ─────────────────────────────────────────
  useEffect(() => {
    api.consumer.catalogCached()
      .then(cached => { if (cached) { setCatalog(cached.data); setCacheTime(cached.fetched_at) } })
      .catch(console.error)

    // Restore negotiations
    api.consumer.dbNegotiations()
      .then(negs => {
        const track: Record<string, NegTrack> = {}
        for (const neg of negs) {
          track[neg.asset_id] = { negId: neg.neg_id, state: neg.state, agreementId: neg.agreement_id ?? undefined }
          if (neg.state !== 'FINALIZED' && neg.state !== 'TERMINATED' && neg.neg_id) {
            pollNeg(neg.asset_id, neg.neg_id)
          }
        }
        setNegTrack(track)
        setRestored(true)
      })
      .catch(() => setRestored(true))

    // Restore access requests
    api.access.requests()
      .then(reqs => {
        const track: Record<string, AccessTrack> = {}
        for (const r of reqs as any[]) {
          // Keep the most recent request per asset
          if (!track[r.asset_id] || r.requested_at > (track[r.asset_id] as any).requested_at) {
            track[r.asset_id] = { requestId: r.request_id, status: r.status }
          }
        }
        setAccessTrack(track)
        // Resume polling for pending requests
        for (const [assetId, at] of Object.entries(track)) {
          if (at.status === 'pending') pollAccess(assetId, at.requestId)
        }
      })
      .catch(console.error)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Fetch fresh catalog ──────────────────────────────────────────────────────
  const fetchCatalog = () => {
    setLoading(true); setError('')
    api.consumer.catalog()
      .then(d => { setCatalog(d); setCacheTime(Date.now()) })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }

  const datasets = catalog
    ? (Array.isArray(catalog['dcat:dataset'])
        ? catalog['dcat:dataset']
        : catalog['dcat:dataset'] ? [catalog['dcat:dataset']] : []) as Record<string, unknown>[]
    : []

  const getPolicy = (ds: Record<string, unknown>): Record<string, unknown> | null => {
    const p = ds['odrl:hasPolicy']
    if (!p) return null
    return (Array.isArray(p) ? p[0] : p) as Record<string, unknown>
  }

  // ── Poll access request status ───────────────────────────────────────────────
  const pollAccess = (assetId: string, requestId: string) => {
    if (accessPolls.current[assetId]) clearInterval(accessPolls.current[assetId])
    accessPolls.current[assetId] = setInterval(async () => {
      try {
        const all  = await api.access.requests() as any[]
        const mine = all.find((r: any) => r.request_id === requestId)
        if (!mine) return
        setAccessTrack(prev => ({ ...prev, [assetId]: { requestId, status: mine.status } }))
        if (mine.status !== 'pending') clearInterval(accessPolls.current[assetId])
      } catch { /* transient */ }
    }, 3000)
  }

  // ── Request access ────────────────────────────────────────────────────────────
  const requestAccess = async (assetId: string, assetName: string) => {
    setAccessTrack(prev => ({ ...prev, [assetId]: { requestId: '', status: 'pending' } }))
    try {
      const res = await api.access.request(assetId, assetName) as any
      const requestId = res.request_id as string
      setAccessTrack(prev => ({ ...prev, [assetId]: { requestId, status: 'pending' } }))
      pollAccess(assetId, requestId)
    } catch (e) {
      setError(`Access request failed: ${e}`)
      setAccessTrack(prev => { const n = { ...prev }; delete n[assetId]; return n })
    }
  }

  // ── Poll EDC negotiation state ────────────────────────────────────────────────
  const pollNeg = (assetId: string, negId: string) => {
    if (pollRefs.current[assetId]) clearInterval(pollRefs.current[assetId])
    pollRefs.current[assetId] = setInterval(async () => {
      try {
        const data        = await api.consumer.negotiationStatus(negId)
        const state       = data['state'] as string
        const agreementId = data['contractAgreementId'] as string | undefined
        setNegTrack(prev => ({ ...prev, [assetId]: { ...prev[assetId], state, agreementId } }))
        if (state === 'FINALIZED' || state === 'TERMINATED') clearInterval(pollRefs.current[assetId])
      } catch { /* transient */ }
    }, 2000)
  }

  // ── Start EDC negotiation (only after access approved) ────────────────────────
  const negotiate = async (assetId: string, policy: Record<string, unknown>) => {
    setNegTrack(prev => ({ ...prev, [assetId]: { negId: '', state: 'REQUESTING' } }))
    try {
      const res = await api.consumer.negotiate({
        '@context': { '@vocab': 'https://w3id.org/edc/v0.0.1/ns/' },
        '@type':    'ContractRequest',
        counterPartyAddress: PROVIDER_DSP,
        protocol:   'dataspace-protocol-http',
        policy: {
          '@context': 'http://www.w3.org/ns/odrl.jsonld',
          '@id':       policy['@id'],
          '@type':    'Offer',
          assigner:   'provider',
          target:      assetId,
        },
      })
      const negId = res['@id'] as string
      setNegTrack(prev => ({ ...prev, [assetId]: { negId, state: 'REQUESTING' } }))
      pollNeg(assetId, negId)
    } catch (e) {
      setNegTrack(prev => ({ ...prev, [assetId]: { negId: '', state: 'TERMINATED' } }))
      setError(`Negotiation failed: ${e}`)
    }
  }

  // ── Start transfer ────────────────────────────────────────────────────────────
  const startTransfer = async (assetId: string, agreementId: string) => {
    const tc = assetId.includes('tc1') ? 'tc1' : assetId.includes('tc2') ? 'tc2' : assetId.includes('tc3') ? 'tc3' : 'tc4'
    setNegTrack(prev => ({ ...prev, [assetId]: { ...prev[assetId], transferStatus: 'starting…' } }))
    try {
      await api.consumer.transfer({
        '@context': { '@vocab': 'https://w3id.org/edc/v0.0.1/ns/' },
        '@type':    'TransferRequestDto',
        connectorId: 'provider',
        counterPartyAddress: PROVIDER_DSP,
        contractId:  agreementId,
        protocol:    'dataspace-protocol-http',
        transferType: 'HttpData-PUSH',
        dataDestination: { type: 'HttpData', baseUrl: `http://receiver:4000/receive/${tc}` },
      })
      setNegTrack(prev => ({
        ...prev,
        [assetId]: { ...prev[assetId], transferStatus: 'Transfer started — check Transfers page' },
      }))
    } catch (e) {
      setNegTrack(prev => ({ ...prev, [assetId]: { ...prev[assetId], transferStatus: `error: ${e}` } }))
    }
  }

  const hasCachedData = !!catalog && !!cacheTime

  return (
    <div className="p-8 max-w-5xl">

      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Provider Catalog</h1>
          <p className="text-slate-500 text-sm">Assets offered by the Provider connector</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <button
            onClick={fetchCatalog}
            disabled={loading}
            className="px-4 py-2 bg-violet-600 text-white text-sm rounded-lg hover:bg-violet-700 disabled:opacity-50">
            {loading ? 'Fetching…' : hasCachedData ? 'Re-fetch Catalog' : 'Request Catalog'}
          </button>
          {cacheTime && (
            <p className="text-xs text-slate-400">Loaded from cache — fetched {timeAgo(cacheTime)}</p>
          )}
        </div>
      </div>

      {/* Workflow steps */}
      <div className="mb-6 flex items-center gap-2 text-xs text-slate-500 flex-wrap">
        <span className="px-2 py-0.5 bg-violet-100 text-violet-700 rounded font-medium">1 Request Catalog</span>
        <span>→</span>
        <span className="px-2 py-0.5 bg-slate-100 rounded">2 Request Access</span>
        <span>→</span>
        <span className="px-2 py-0.5 bg-slate-100 rounded">3 Provider Approves</span>
        <span>→</span>
        <span className="px-2 py-0.5 bg-slate-100 rounded">4 Negotiate &amp; Agree</span>
        <span>→</span>
        <span className="px-2 py-0.5 bg-slate-100 rounded">5 Transfer Data</span>
      </div>

      {error && (
        <p className="text-red-500 text-sm mb-4 bg-red-50 border border-red-200 rounded-lg p-3">{error}</p>
      )}

      {!catalog && !loading && (
        <div className="bg-slate-100 rounded-xl p-10 text-center text-slate-400">
          <p className="text-lg mb-2">No catalog loaded</p>
          <p className="text-sm">Click "Request Catalog" to fetch available assets from the Provider</p>
        </div>
      )}

      {/* Asset cards */}
      {datasets.length > 0 && (
        <div className="space-y-4">
          {datasets.map((ds) => {
            const assetId    = ds['@id'] as string
            const assetName  = (ds['name'] as string) ?? assetId
            const policy     = getPolicy(ds)
            const access     = accessTrack[assetId]
            const track      = negTrack[assetId]
            const isFinal    = track?.state === 'FINALIZED'
            const isNegInProgress = !!track && !isFinal && track.state !== 'TERMINATED'

            return (
              <div key={assetId}
                className={`bg-white rounded-xl border shadow-sm transition-colors ${
                  isFinal ? 'border-emerald-300' :
                  access?.status === 'approved' ? 'border-violet-200' :
                  'border-slate-200'
                }`}>
                <div className="p-5">

                  {/* Asset header */}
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-slate-800">{assetName}</p>
                      <p className="text-sm text-slate-500 mt-0.5">{ds['description'] as string ?? 'No description'}</p>
                      <p className="text-xs text-slate-400 mt-1">Asset ID: <code className="text-slate-600">{assetId}</code></p>
                    </div>

                    {/* Action button area */}
                    <div className="ml-4 shrink-0 flex flex-col items-end gap-2">

                      {/* Step 2: No access request yet */}
                      {!access && !track && (
                        <button
                          onClick={() => requestAccess(assetId, assetName)}
                          className="px-4 py-2 bg-violet-600 text-white text-sm rounded-lg hover:bg-violet-700 font-medium">
                          Request Access
                        </button>
                      )}

                      {/* Step 3: Pending approval */}
                      {access?.status === 'pending' && !track && (
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-xs px-3 py-1.5 bg-amber-50 text-amber-700 rounded-full border border-amber-200 animate-pulse font-medium">
                            Awaiting Provider Approval…
                          </span>
                          <button
                            onClick={() => setAccessTrack(prev => { const n = { ...prev }; delete n[assetId]; return n })}
                            className="text-xs text-slate-400 hover:underline">
                            Cancel request
                          </button>
                        </div>
                      )}

                      {/* Step 3a: Rejected */}
                      {access?.status === 'rejected' && !track && (
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-xs px-3 py-1.5 bg-red-50 text-red-600 rounded-full border border-red-200 font-medium">
                            Access Rejected
                          </span>
                          <button
                            onClick={() => { setAccessTrack(prev => { const n = { ...prev }; delete n[assetId]; return n }) }}
                            className="text-xs text-violet-600 hover:underline">
                            Request again
                          </button>
                        </div>
                      )}

                      {/* Step 4: Approved — start negotiation */}
                      {access?.status === 'approved' && !track && (
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-xs px-2.5 py-0.5 bg-emerald-100 text-emerald-700 rounded-full font-semibold border border-emerald-200 mb-1">
                            ✓ Access Approved
                          </span>
                          {policy && (
                            <button
                              onClick={() => negotiate(assetId, policy)}
                              className="px-4 py-2 bg-violet-600 text-white text-sm rounded-lg hover:bg-violet-700 font-medium">
                              Negotiate &amp; Agree
                            </button>
                          )}
                        </div>
                      )}

                      {/* Step 4 in progress */}
                      {isNegInProgress && (
                        <span className="text-xs px-3 py-1.5 bg-blue-50 text-blue-600 rounded-full border border-blue-100 animate-pulse">
                          Negotiating…
                        </span>
                      )}

                      {/* Step 5: Agreement active */}
                      {isFinal && (
                        <span className="text-xs px-3 py-1.5 bg-emerald-100 text-emerald-700 rounded-full font-semibold border border-emerald-200">
                          Agreement Active
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Policy — shown only before access is requested */}
                  {policy && !access && !track && <PolicyPanel policy={policy} />}

                  {/* Approved banner with policy reminder */}
                  {access?.status === 'approved' && !track && (
                    <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
                      Provider approved your access request. Click "Negotiate &amp; Agree" to create a contract agreement via the EDC protocol.
                    </div>
                  )}

                  {/* Inline negotiation tracker */}
                  {track && (
                    <div className={`mt-3 rounded-lg border p-4 ${
                      isFinal ? 'border-emerald-200 bg-emerald-50' :
                      track.state === 'TERMINATED' ? 'border-red-200 bg-red-50' :
                      'border-blue-100 bg-blue-50'
                    }`}>
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-xs font-semibold text-slate-600">Negotiation Progress</p>
                        <Link to="/negotiations" className="text-xs text-blue-600 hover:underline">View all →</Link>
                      </div>

                      <NegTimeline state={track.state} />

                      {track.state === 'TERMINATED' && (
                        <p className="text-xs text-red-600 mt-2">
                          Negotiation terminated.{' '}
                          <button
                            onClick={() => setNegTrack(prev => { const n = { ...prev }; delete n[assetId]; return n })}
                            className="underline">Retry</button>
                        </p>
                      )}

                      {track.agreementId && (
                        <p className="text-xs text-emerald-700 mt-2">
                          Agreement ID: <code className="font-mono">{track.agreementId.slice(0, 32)}…</code>
                        </p>
                      )}

                      {isFinal && !track.transferStatus && (
                        <div className="mt-3 flex items-center gap-3">
                          <button
                            onClick={() => startTransfer(assetId, track.agreementId!)}
                            className="px-4 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700 font-semibold">
                            Transfer Data Now
                          </button>
                          <Link to="/agreements" className="text-xs text-slate-500 hover:underline">
                            View Agreements →
                          </Link>
                        </div>
                      )}

                      {track.transferStatus && (
                        <p className={`text-xs mt-3 font-medium ${track.transferStatus.startsWith('error') ? 'text-red-600' : 'text-emerald-700'}`}>
                          {track.transferStatus}
                          {!track.transferStatus.startsWith('error') && (
                            <>{' '}<Link to="/transfers" className="underline ml-1">View Transfers →</Link></>
                          )}
                        </p>
                      )}
                    </div>
                  )}

                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Restored negotiations when catalog isn't loaded */}
      {restored && Object.keys(negTrack).length > 0 && datasets.length === 0 && (
        <div className="mt-6">
          <p className="text-sm font-semibold text-slate-600 mb-3">Previously negotiated assets</p>
          <div className="space-y-2">
            {Object.entries(negTrack).map(([assetId, track]) => (
              <div key={assetId} className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-medium text-slate-700 text-sm">{assetId}</p>
                    <div className="mt-2"><NegTimeline state={track.state} /></div>
                    {track.agreementId && (
                      <p className="text-xs text-emerald-700 mt-1">
                        Agreement: <code>{track.agreementId.slice(0, 28)}…</code>
                      </p>
                    )}
                  </div>
                  {track.state === 'FINALIZED' && !track.transferStatus && (
                    <button
                      onClick={() => startTransfer(assetId, track.agreementId!)}
                      className="ml-4 px-3 py-1.5 bg-emerald-600 text-white text-xs rounded-lg hover:bg-emerald-700 font-semibold">
                      Transfer Now
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
          <button onClick={fetchCatalog} disabled={loading} className="mt-3 text-xs text-violet-600 hover:underline">
            Load catalog to see full details →
          </button>
        </div>
      )}

    </div>
  )
}
