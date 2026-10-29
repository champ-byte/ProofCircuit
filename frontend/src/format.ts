export function formatIst(utc: string): string {
  const local = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(utc) ? utc : `${utc}Z`)
  const text = local.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })
  return `${text} IST`
}

export function formatCountdown(seconds: number): string {
  if (seconds <= 0) return 'Deadline passed'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m left`
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
