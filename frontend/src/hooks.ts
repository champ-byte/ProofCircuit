import { useEffect, useState } from 'react'

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
