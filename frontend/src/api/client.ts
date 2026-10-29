import type {
  CaseDetail,
  CaseSummary,
  DemoSession,
  DemoUser,
  DocumentDetail,
  EvidenceOverview,
  FixtureInfo,
  InboxView,
  PackView,
  RunView,
  SubmissionView,
  ProviderReport,
} from '../types/api'

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function send(path: string, init: RequestInit = {}, token?: string): Promise<Response> {
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (typeof init.body === 'string' && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const resp = await fetch(path, { ...init, headers })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      detail = (await resp.json()).detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, String(detail))
  }
  return resp
}

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  return (await (await send(path, init, token)).json()) as T
}

export const api = {
  providers: () => request<ProviderReport>('/api/providers'),
  demoUsers: () => request<DemoUser[]>('/api/demo/users'),
  createSession: (mid: string, handle: string) =>
    request<DemoSession>('/api/demo/session', { method: 'POST', body: JSON.stringify({ mid, handle }) }),
  cases: (token: string) => request<CaseSummary[]>('/api/cases', {}, token),
  caseDetail: (token: string, id: string) => request<CaseDetail>(`/api/cases/${id}`, {}, token),
  evidence: (token: string, id: string) => request<EvidenceOverview>(`/api/cases/${id}/evidence`, {}, token),
  document: (token: string, id: string) => request<DocumentDetail>(`/api/evidence/${id}`, {}, token),
  upload: (token: string, caseId: string, file: File | Blob, filename: string) => {
    const form = new FormData()
    form.append('file', file, filename)
    return request<{ created: boolean }>(`/api/cases/${caseId}/evidence`, { method: 'POST', body: form }, token)
  },
  exclude: (token: string, docId: string, reason: string) =>
    request<unknown>(`/api/evidence/${docId}/exclude`, { method: 'POST', body: JSON.stringify({ reason }) }, token),
  fixtures: (token: string, caseId: string) => request<FixtureInfo[]>(`/api/demo/cases/${caseId}/fixtures`, {}, token),
  action: (token: string, caseId: string, tool: string, args: Record<string, unknown> = {}) =>
    request<{ run_id: string }>(
      `/api/cases/${caseId}/actions`,
      { method: 'POST', body: JSON.stringify({ tool, arguments: args, reason: 'Manual operator action' }) },
      token,
    ),
  events: (token: string, caseId: string, after: number) =>
    request<{ events: { seq: number }[]; cursor: number }>(`/api/cases/${caseId}/events?after=${after}`, {}, token),
  startRun: (token: string, caseId: string) => request<unknown>(`/api/cases/${caseId}/runs`, { method: 'POST' }, token),
  runs: (token: string, caseId: string) => request<RunView[]>(`/api/cases/${caseId}/runs`, {}, token),
  packs: (token: string, caseId: string) => request<PackView[]>(`/api/cases/${caseId}/pack`, {}, token),
  packFile: async (token: string, caseId: string, version: number, name: string) =>
    (await send(`/api/cases/${caseId}/pack/${version}/${name}`, {}, token)).blob(),
  submissions: (token: string, caseId: string) => request<SubmissionView[]>(`/api/cases/${caseId}/submissions`, {}, token),
  inbox: (token: string, caseId: string) => request<InboxView>(`/api/cases/${caseId}/messages`, {}, token),
  reply: (token: string, caseId: string, body: string) =>
    request<unknown>(`/api/cases/${caseId}/messages`, { method: 'POST', body: JSON.stringify({ body }) }, token),
  fixtureFile: async (token: string, caseId: string, name: string) =>
    (await send(`/api/demo/cases/${caseId}/fixtures/${name}`, {}, token)).blob(),
}
