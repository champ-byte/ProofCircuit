import { createContext, useContext } from 'react'
import type { DemoSession } from './types/api'

export interface SessionState {
  session: DemoSession | null
  token: string | null
}

export const SessionContext = createContext<SessionState>({ session: null, token: null })

export function useSession(): SessionState {
  return useContext(SessionContext)
}
