import type { CaseSummary, DemoSession, DemoUser, ProviderReport } from '../types/api'

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
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
  return (await resp.json()) as T
}

export const api = {
  providers: () => request<ProviderReport>('/api/providers'),
  demoUsers: () => request<DemoUser[]>('/api/demo/users'),
  createSession: (mid: string, handle: string) =>
    request<DemoSession>('/api/demo/session', { method: 'POST', body: JSON.stringify({ mid, handle }) }),
  cases: (token: string) => request<CaseSummary[]>('/api/cases', {}, token),
}
