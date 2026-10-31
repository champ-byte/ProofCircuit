import { useEffect, useRef, useState } from 'react'
import { api } from './api/client'

/** Current time, re-rendering every `intervalMs` (for live countdowns). */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

export function secondsUntil(utc: string, now: number): number {
  const at = Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(utc) ? utc : `${utc}Z`)
  return Math.floor((at - now) / 1000)
}

/**
 * Background work (runner, agent, simulator webhooks) finishes after HTTP responses return.
 * Follow the persisted event feed every 1.5 s and call `onAdvance` when it moves; the backend never polls.
 */
export function useEventFeed(token: string | null, caseId: string, onAdvance: () => void) {
  const callback = useRef(onAdvance)
  useEffect(() => {
    callback.current = onAdvance
  }, [onAdvance])
  useEffect(() => {
    if (!token) return
    let cursor = -1
    let stopped = false
    const tick = async () => {
      try {
        const res = await api.events(token, caseId, Math.max(cursor, 0))
        if (cursor === -1) cursor = res.cursor
        else if (res.cursor !== cursor) {
          cursor = res.cursor
          callback.current()
        }
      } catch {
        /* transient; next tick retries */
      }
      if (!stopped) timer = window.setTimeout(tick, 1500)
    }
    let timer = window.setTimeout(tick, 0)
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [token, caseId])
}
