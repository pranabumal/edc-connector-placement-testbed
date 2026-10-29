const BASE = '/api'

export interface DbNegotiation {
  neg_id:       string
  asset_id:     string
  asset_name:   string
  offer_id:     string
  state:        string
  agreement_id: string | null
  started_at:   number
  updated_at:   number
}

export interface DbAgreement {
  agreement_id: string
  neg_id:       string
  asset_id:     string
  asset_name:   string
  provider_id:  string
  finalized_at: number
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`GET ${path} → ${r.status}`)
  return r.json()
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) throw new Error(`POST ${path} → ${r.status}`)
  return r.json()
}

export const api = {
  access: {
    request: (asset_id: string, asset_name: string) =>
      post<Record<string, unknown>>('/access/request', { asset_id, asset_name }),
    requests: () => get<unknown[]>('/access/requests'),
    status:   (tc: string) => get<Record<string, unknown>>(`/access/status/${tc}`),
  },
  aas: {
    health:         () => get<Record<string, unknown>>('/aas/health'),
    submodelValues: (tc: string) => get<Record<string, string>>(`/aas/submodels/${tc}/values`),
  },
  consumer: {
    catalog:            () => get<Record<string, unknown>>('/consumer/catalog'),
    catalogCached:      () => get<{ fetched_at: number; data: Record<string, unknown> } | null>('/consumer/catalog/cached'),
    negotiations:       () => get<unknown[]>('/consumer/negotiations'),
    negotiationStatus:  (id: string) => get<Record<string, unknown>>(`/consumer/negotiations/${id}`),
    agreements:         () => get<unknown[]>('/consumer/agreements'),
    transfers:          () => get<unknown[]>('/consumer/transfers'),
    negotiate:          (body: unknown) => post<Record<string, unknown>>('/consumer/negotiate', body),
    transfer:           (body: unknown) => post<unknown>('/consumer/transfer', body),
    dbNegotiations:     () => get<DbNegotiation[]>('/consumer/db/negotiations'),
    dbAgreements:       () => get<DbAgreement[]>('/consumer/db/agreements'),
  },
  receiver: {
    metrics:    () => get<Record<string, unknown>>('/receiver/metrics'),
    metricsTc:  (tc: string) => get<Record<string, unknown>>(`/receiver/metrics/${tc}`),
    reset:      () => post<unknown>('/receiver/reset'),
  },
  tests: {
    run:    (tc: string, repeats: number) => post<{ run_id: string }>(`/tests/${tc}/run`, { repeats }),
    runs:   () => get<unknown[]>('/tests/runs'),
    getRun: (id: string) => get<unknown>(`/tests/runs/${id}`),
  },
}
