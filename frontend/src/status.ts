import i18n from './i18n'
import type { AuditEventView } from './types/api'

export type Tone = 'ok' | 'warn' | 'block' | 'info'

export interface BannerInput {
  workflow_state: string
  provider_status: string
  deadline_expired: boolean
  evidence_ready: boolean
  blocking_contradiction: boolean
  debit_display?: string | null
}

export type BannerId =
  | 'lost' | 'lostNoDebit' | 'won' | 'closed' | 'monitoring' | 'uncertain' | 'submitting'
  | 'deadline' | 'contradiction' | 'review' | 'waiting' | 'ready' | 'collecting'

export interface Banner {
  id: BannerId
  tone: Tone
  title: string
  detail: string
}

/**
 * One mapping from case state to plain-language status. The text always carries the meaning
 * (never color alone), and a verified upload is never presented as a dispute win.
 */
export function statusBanner(s: BannerInput): Banner {
  const make = (id: BannerId, tone: Tone): Banner => ({
    id,
    tone,
    title: i18n.t(`banner.${id}.title`),
    detail: i18n.t(`banner.${id}.detail`, { debit: s.debit_display ?? '' }),
  })
  if (s.workflow_state === 'CLOSED') {
    if (s.provider_status === 'LOST') return make(s.debit_display ? 'lost' : 'lostNoDebit', 'block')
    if (s.provider_status === 'WON') return make('won', 'ok')
    return make('closed', 'info')
  }
  if (s.workflow_state === 'MONITORING') return make('monitoring', 'ok')
  if (s.workflow_state === 'SUBMISSION_UNCERTAIN') return make('uncertain', 'warn')
  if (s.workflow_state === 'SUBMITTING') return make('submitting', 'info')
  if (s.deadline_expired) return make('deadline', 'block')
  if (s.workflow_state === 'NEEDS_HUMAN_REVIEW')
    return s.blocking_contradiction ? make('contradiction', 'block') : make('review', 'warn')
  if (s.workflow_state === 'WAITING_FOR_EVIDENCE') return make('waiting', 'info')
  if (s.workflow_state === 'READY_TO_SUBMIT' || s.evidence_ready) return make('ready', 'ok')
  return make('collecting', 'info')
}

export interface KeyStep {
  seq: number
  label: string
  summary: string
  created_at: string
  actor: string
  /** Plain wording for simple view when the server summary carries raw codes. */
  simple?: string
}

/** Paytm's raw dispute status in plain words ("POD_UPLOAD" → "response received"). */
export function paytmStatus(raw: unknown): string {
  const code = String(raw ?? '').trim().replace('POD UPLOADED', 'POD_UPLOAD')
  return i18n.t(`paytmStatus.${code}`, { defaultValue: i18n.t('paytmStatus.other') })
}

/** Concise steps from persisted audit events (PRD 13.2). Every step links to a stored event. */
export function keySteps(events: AuditEventView[]): KeyStep[] {
  const steps: KeyStep[] = []
  const seenGaps = new Set<string>()
  for (const e of events) {
    let label: string | null = null
    switch (e.event_type) {
      case 'checklist.updated': {
        const req = String(e.data.requirement_id ?? '')
        if (e.data.status === 'missing' && !seenGaps.has(req)) {
          seenGaps.add(req)
          label = 'gap'
        }
        break
      }
      case 'evidence.requested':
        label = 'requested'
        break
      case 'staff.replied':
        label = 'staff'
        break
      case 'evidence.uploaded':
        if (e.actor_type === 'user') label = 'staff'
        break
      case 'validation.finding_opened':
        if (e.data.severity === 'blocking') label = 'contradiction'
        break
      case 'evidence.superseded':
        label = 'superseded'
        break
      case 'testimony.received':
        label = 'voice'
        break
      case 'testimony.confirmed':
      case 'testimony.corrected':
      case 'testimony.human_transcribed':
        label = 'testimony'
        break
      case 'review.requested':
        label = 'review'
        break
      case 'pack.built':
        label = 'pack'
        break
      case 'submission.requested':
        label = 'submission'
        break
      case 'submission.verified':
        label = 'verified'
        break
      case 'provider.status_changed':
        label = 'provider'
        break
      case 'concession.requested':
        label = 'concession'
        break
      case 'agent.run_started':
        label = 'agent'
        break
    }
    if (!label) continue
    const simple = e.event_type === 'provider.status_changed'
      ? i18n.t('steps.providerTo', { status: paytmStatus(e.data.to) })
      : i18n.exists(`steps.simple.${label}`) ? i18n.t(`steps.simple.${label}`) : undefined
    steps.push({ seq: e.seq, label: i18n.t(`steps.${label}`), summary: e.summary, created_at: e.created_at, actor: e.actor_type, simple })
  }
  return steps
}
