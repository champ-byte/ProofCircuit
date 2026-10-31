import { createContext, useContext } from 'react'
import type { DemoSession, DemoUser } from './types/api'

export interface SessionState {
  session: DemoSession | null
  token: string | null
  /** "MID/handle" of the signed-in person; null until someone signs in. */
  identity: string | null
  users: DemoUser[]
  /** Sign in as this person (the session is issued by the server). */
  setIdentity: (identity: string) => void
  /** Re-issue the demo session (after a reset invalidated it). */
  relogin: () => void
}

export const SessionContext = createContext<SessionState>({
  session: null,
  token: null,
  identity: null,
  users: [],
  setIdentity: () => undefined,
  relogin: () => undefined,
})

export function useSession(): SessionState {
  return useContext(SessionContext)
}
