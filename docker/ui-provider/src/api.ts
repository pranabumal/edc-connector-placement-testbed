const BASE = '/api'

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
  provider: {
    assets:           () => get<unknown[]>('/provider/assets'),
    policies:         () => get<unknown[]>('/provider/policies'),
    contractdefs:     () => get<unknown[]>('/provider/contractdefinitions'),
    transfers:        () => get<unknown[]>('/provider/transfers'),
    setup:            () => post<Record<string, unknown>>('/provider/setup'),
    setupAas:         () => post<Record<string, unknown>>('/provider/setup-aas'),
  },
  access: {
    requests:  () => get<unknown[]>('/access/requests'),
    approve:   (id: string) => post<Record<string, unknown>>(`/access/${id}/approve`),
    reject:    (id: string) => post<Record<string, unknown>>(`/access/${id}/reject`),
    status:    (tc: string) => get<Record<string, unknown>>(`/access/status/${tc}`),
  },
  aas: {
    health:          () => get<Record<string, unknown>>('/aas/health'),
    submodelValues:  (tc: string) => get<Record<string, string>>(`/aas/submodels/${tc}/values`),
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
