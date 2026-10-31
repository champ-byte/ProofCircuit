import i18n from './i18n'

export function formatIst(utc: string): string {
  const local = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(utc) ? utc : `${utc}Z`)
  const text = local.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })
  return `${text} IST`
}

/** "47h 59m left" (or with seconds). Never negative: at/after the deadline it says so in words. */
export function formatCountdown(seconds: number, withSeconds = false): string {
  if (seconds <= 0) return i18n.t('time.deadlinePassed')
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return withSeconds ? i18n.t('time.leftSeconds', { h, m, s: String(s).padStart(2, '0') }) : i18n.t('time.left', { h, m })
}

const STATES = ['NEW', 'COLLECTING', 'WAITING_FOR_EVIDENCE', 'NEEDS_HUMAN_REVIEW', 'READY_TO_SUBMIT', 'SUBMITTING', 'SUBMISSION_UNCERTAIN', 'MONITORING', 'CLOSED']

/** Workflow state in the current language; unknown states fall back to the raw code. */
export function stateLabel(state: string): string {
  return STATES.includes(state) ? i18n.t(`states.${state}`) : state
}

/** Dispute reason in the current language; unknown reasons fall back to words. */
export function reasonLabel(reason: string): string {
  return i18n.exists(`reasons.${reason}`) ? i18n.t(`reasons.${reason}`) : reason.replaceAll('_', ' ')
}

/** Slice a string by Unicode code points (backend offsets are code points, not UTF-16 units). */
export function codePointSlice(text: string, start: number, end?: number): string {
  return Array.from(text).slice(start, end).join('')
}

/**
 * Server-written summaries are English and can end in technical detail ("… (mr-IN, round 1).",
 * "… (live model; trigger: evidence_uploaded)."). Simple view keeps the first sentence without
 * a trailing bracket; detailed view shows the full text.
 */
export function plainSummary(text: string): string {
  const first = (text.split(/(?<=\.)\s+/)[0] ?? text).replace(/\s*\([^()]*\)\.?$/, '')
  const trimmed = first.replace(/\s*\([a-z]{2}-[A-Z]{2}\)/g, '').split(';')[0].replace(/\.$/, '')
  return trimmed ? `${trimmed}.` : text
}
