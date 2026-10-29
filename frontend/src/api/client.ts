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
  AuditEventView,
  EvaluationResults,
  SimulatorState,
  ProviderReport,
  VoiceNotesResponse,
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
    request<{ events: AuditEventView[]; cursor: number }>(`/api/cases/${caseId}/events?after=${after}`, {}, token),
  evidenceContent: async (token: string, docId: string) => (await send(`/api/evidence/${docId}/content`, {}, token)).blob(),
  review: (token: string, caseId: string, body: Record<string, unknown>) =>
    request<{ approval_id?: string; expires_at?: string; consequence?: string }>(
      `/api/cases/${caseId}/reviews`,
      { method: 'POST', body: JSON.stringify(body) },
      token,
    ),
  concede: (token: string, caseId: string, approvalId: string) =>
    request<{ submission_id: string }>(
      `/api/cases/${caseId}/accept-dispute`,
      { method: 'POST', body: JSON.stringify({ approval_id: approvalId, confirm: true }) },
      token,
    ),
  refundCheck: (token: string, caseId: string) =>
    request<{ decision: string; reason: string }>(`/api/cases/${caseId}/refund-policy-check`, { method: 'POST' }, token),
  simState: (token: string, disputeId: string) =>
    request<SimulatorState>(`/api/simulator/state?dispute_id=${encodeURIComponent(disputeId)}`, {}, token),
  simEvent: (token: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/simulator/events', { method: 'POST', body: JSON.stringify(body) }, token),
  reset: (token: string) =>
    request<{ case_id: string }>('/api/demo/reset', { method: 'POST', body: JSON.stringify({ confirm: true }) }, token),
  resume: (token: string) => request<Record<string, number>>('/api/demo/resume-pending', { method: 'POST' }, token),
  evaluation: () => request<EvaluationResults>('/api/evaluation/results'),
  startRun: (token: string, caseId: string, mode: 'live' | 'fixture_replay' = 'live') =>
    request<{ reasoning_label: string }>(
      `/api/cases/${caseId}/runs`,
      { method: 'POST', body: JSON.stringify({ mode }) },
      token,
    ),
  smoke: (token: string) =>
    request<{ ok: boolean; model_returned?: string; detail?: string; latency_ms?: number }>(
      '/api/providers/smoke?provider=gemini',
      { method: 'POST' },
      token,
    ),
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
  voiceNotes: (token: string, caseId: string) => request<VoiceNotesResponse>(`/api/cases/${caseId}/voice-notes`, {}, token),
  uploadVoiceNote: (token: string, caseId: string, file: File | Blob, filename: string) => {
    const form = new FormData()
    form.append('file', file, filename)
    return request<{ voice_note_id: string; created: boolean; stt_status: string }>(
      `/api/cases/${caseId}/voice-notes`,
      { method: 'POST', body: form },
      token,
    )
  },
  voiceAudio: async (token: string, noteId: string) => (await send(`/api/voice-notes/${noteId}/audio`, {}, token)).blob(),
  voiceFixture: async (token: string, caseId: string) =>
    (await send(`/api/demo/cases/${caseId}/voice-fixture`, {}, token)).blob(),
  confirmTranscript: (token: string, noteId: string, version: number) =>
    request<unknown>(`/api/voice-notes/${noteId}/confirm`, { method: 'POST', body: JSON.stringify({ version }) }, token),
  correctTranscript: (token: string, noteId: string, baseVersion: number, text: string) =>
    request<unknown>(
      `/api/voice-notes/${noteId}/correct`,
      { method: 'POST', body: JSON.stringify({ base_version: baseVersion, text }) },
      token,
    ),
  transcribeManually: (token: string, noteId: string, text: string) =>
    request<unknown>(
      `/api/voice-notes/${noteId}/transcribe-manually`,
      { method: 'POST', body: JSON.stringify({ text }) },
      token,
    ),
  retryTranscription: (token: string, noteId: string) =>
    request<unknown>(`/api/voice-notes/${noteId}/retry-transcription`, { method: 'POST' }, token),
}
