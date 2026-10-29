export function formatIst(utc: string): string {
  const local = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(utc) ? utc : `${utc}Z`)
  const text = local.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })
  return `${text} IST`
}

/** "47h 59m left" (or with seconds). Never negative: at/after the deadline it says so in words. */
export function formatCountdown(seconds: number, withSeconds = false): string {
  if (seconds <= 0) return 'Deadline passed'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return withSeconds ? `${h}h ${m}m ${String(s).padStart(2, '0')}s left` : `${h}h ${m}m left`
}

export const STATE_LABELS: Record<string, string> = {
  NEW: 'New',
  COLLECTING: 'Collecting evidence',
  WAITING_FOR_EVIDENCE: 'Waiting for evidence',
  NEEDS_HUMAN_REVIEW: 'Needs human review',
  READY_TO_SUBMIT: 'Ready to submit',
  SUBMITTING: 'Submitting',
  SUBMISSION_UNCERTAIN: 'Submission uncertain',
  MONITORING: 'Submission verified — outcome pending',
  CLOSED: 'Closed',
}

/** Slice a string by Unicode code points (backend offsets are code points, not UTF-16 units). */
export function codePointSlice(text: string, start: number, end?: number): string {
  return Array.from(text).slice(start, end).join('')
}
