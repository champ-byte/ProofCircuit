import { createContext, useContext } from 'react'
import type { DemoSession, DemoUser } from './types/api'

export interface SessionState {
  session: DemoSession | null
  token: string | null
  identity: string // "MID/handle"
  users: DemoUser[]
  setIdentity: (identity: string) => void
  /** Re-issue the demo session (after a reset invalidated it). */
  relogin: () => void
}

export const SessionContext = createContext<SessionState>({
  session: null,
  token: null,
  identity: '',
  users: [],
  setIdentity: () => undefined,
  relogin: () => undefined,
})

export function useSession(): SessionState {
  return useContext(SessionContext)
}
