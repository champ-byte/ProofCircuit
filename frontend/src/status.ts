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

export interface Banner {
  tone: Tone
  title: string
  detail: string
}

/**
 * One mapping from case state to plain-language status. The text always carries the meaning
 * (never color alone), and a verified upload is never presented as a dispute win.
 */
export function statusBanner(s: BannerInput): Banner {
  if (s.workflow_state === 'CLOSED') {
    if (s.provider_status === 'LOST')
      return {
        tone: 'block',
        title: 'Dispute closed — provider reports LOST',
        detail: s.debit_display
          ? `Reported debit ${s.debit_display} (simulated provider data).`
          : 'Any debit appears on a later settlement; none reported yet.',
      }
    if (s.provider_status === 'WON')
      return { tone: 'ok', title: 'Dispute closed — provider reports WON (simulated outcome)', detail: 'No debit.' }
    return { tone: 'info', title: 'Case closed', detail: '' }
  }
  if (s.workflow_state === 'MONITORING')
    return {
      tone: 'ok',
      title: 'Submission verified — dispute outcome pending',
      detail: 'Verified by an independent simulator receipt and a status read. This is not a win.',
    }
  if (s.workflow_state === 'SUBMISSION_UNCERTAIN')
    return {
      tone: 'warn',
      title: 'Submission uncertain — reconciling with the provider',
      detail: 'The provider effect is unknown; status and receipts are read before any retry.',
    }
  if (s.workflow_state === 'SUBMITTING')
    return { tone: 'info', title: 'Submitting to the Paytm simulator…', detail: 'Policy checks passed for this pack.' }
  if (s.deadline_expired)
    return { tone: 'block', title: 'Deadline passed — submissions are blocked', detail: 'A person must decide next steps.' }
  if (s.workflow_state === 'NEEDS_HUMAN_REVIEW')
    return s.blocking_contradiction
      ? {
          tone: 'block',
          title: 'Submission blocked: contradiction found',
          detail: 'Corrected evidence or a source-backed exclusion is required.',
        }
      : { tone: 'warn', title: 'Needs human review', detail: 'A reviewer must decide before the case continues.' }
  if (s.workflow_state === 'WAITING_FOR_EVIDENCE')
    return { tone: 'info', title: 'Waiting for staff evidence', detail: 'The case resumes when staff reply or upload.' }
  if (s.workflow_state === 'READY_TO_SUBMIT' || s.evidence_ready)
    return { tone: 'ok', title: 'Evidence complete — ready to submit', detail: 'Required evidence passes all checks.' }
  return { tone: 'info', title: 'Collecting evidence', detail: '' }
}

export interface KeyStep {
  seq: number
  label: string
  summary: string
  created_at: string
  actor: string
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
          label = 'Observed gap'
        }
        break
      }
      case 'evidence.requested':
        label = 'Evidence requested'
        break
      case 'staff.replied':
        label = 'Staff response'
        break
      case 'evidence.uploaded':
        if (e.actor_type === 'user') label = 'Staff response'
        break
      case 'validation.finding_opened':
        if (e.data.severity === 'blocking') label = 'Contradiction detected'
        break
      case 'evidence.superseded':
        label = 'Wrong evidence superseded'
        break
      case 'review.requested':
        label = 'Review requested'
        break
      case 'pack.built':
        label = 'Pack built'
        break
      case 'submission.requested':
        label = 'Submission requested'
        break
      case 'submission.verified':
        label = 'Receipt verified'
        break
      case 'provider.status_changed':
        label = 'Provider status changed'
        break
      case 'concession.requested':
        label = 'Concession requested (human)'
        break
      case 'agent.run_started':
        label = 'Agent run'
        break
    }
    if (label) steps.push({ seq: e.seq, label, summary: e.summary, created_at: e.created_at, actor: e.actor_type })
  }
  return steps
}
