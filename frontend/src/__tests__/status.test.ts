import { describe, expect, it } from 'vitest'
import { codePointSlice, formatCountdown } from '../format'
import { keySteps, statusBanner } from '../status'
import type { AuditEventView } from '../types/api'

const base = {
  workflow_state: 'COLLECTING',
  provider_status: 'NEW',
  deadline_expired: false,
  evidence_ready: false,
  blocking_contradiction: false,
}

describe('statusBanner', () => {
  it('never presents a verified upload as a win', () => {
    const b = statusBanner({ ...base, workflow_state: 'MONITORING', provider_status: 'POD_UPLOAD' })
    expect(b.title).toBe('Submission verified — dispute outcome pending')
    expect(`${b.title} ${b.detail}`).not.toMatch(/\bwon\b/i)
    expect(b.detail).toContain('not a win')
  })

  it('labels a provider WON as a simulated outcome only when closed', () => {
    expect(statusBanner({ ...base, workflow_state: 'CLOSED', provider_status: 'WON' }).title).toContain('simulated')
  })

  it('distinguishes blocking contradictions from plain review', () => {
    expect(statusBanner({ ...base, workflow_state: 'NEEDS_HUMAN_REVIEW', blocking_contradiction: true }).title).toBe(
      'Submission blocked: contradiction found',
    )
    expect(statusBanner({ ...base, workflow_state: 'NEEDS_HUMAN_REVIEW' }).title).toBe('Needs human review')
  })

  it('reports an expired deadline over collecting states', () => {
    expect(statusBanner({ ...base, deadline_expired: true }).tone).toBe('block')
  })

  it('shows reported debit only when present', () => {
    const lost = statusBanner({ ...base, workflow_state: 'CLOSED', provider_status: 'LOST', debit_display: '₹18,500.00' })
    expect(lost.detail).toContain('₹18,500.00')
    expect(statusBanner({ ...base, workflow_state: 'CLOSED', provider_status: 'LOST' }).detail).toContain('none reported')
  })
})

const ev = (seq: number, event_type: string, data: Record<string, unknown> = {}, actor_type = 'system'): AuditEventView => ({
  seq,
  event_type,
  summary: event_type,
  actor_type,
  data,
  created_at: '2030-01-02T04:30:00Z',
})

describe('keySteps', () => {
  it('maps stored events to the PRD step names, each linked to its event', () => {
    const steps = keySteps([
      ev(1, 'checklist.updated', { requirement_id: 'delivery_record', status: 'missing' }),
      ev(2, 'checklist.updated', { requirement_id: 'delivery_record', status: 'missing' }),
      ev(3, 'evidence.requested'),
      ev(4, 'evidence.uploaded', {}, 'user'),
      ev(5, 'evidence.uploaded', {}, 'system'),
      ev(6, 'validation.finding_opened', { severity: 'blocking' }),
      ev(7, 'validation.finding_opened', { severity: 'info' }),
      ev(8, 'pack.built'),
      ev(9, 'submission.requested'),
      ev(10, 'submission.verified'),
      ev(11, 'tool.ok'),
    ])
    expect(steps.map((s) => [s.seq, s.label])).toEqual([
      [1, 'Observed gap'],
      [3, 'Evidence requested'],
      [4, 'Staff response'],
      [6, 'Contradiction detected'],
      [8, 'Pack built'],
      [9, 'Submission requested'],
      [10, 'Receipt verified'],
    ])
  })
})

describe('formatting', () => {
  it('formats countdowns and expiry in words', () => {
    expect(formatCountdown(48 * 3600)).toBe('48h 0m left')
    expect(formatCountdown(3725, true)).toBe('1h 2m 05s left')
    expect(formatCountdown(0)).toBe('Deadline passed')
    expect(formatCountdown(-10, true)).toBe('Deadline passed')
  })

  it('slices by code points, not UTF-16 units', () => {
    const text = 'पावती 😀 ORD-1'
    const start = Array.from(text).length - 5
    expect(codePointSlice(text, start)).toBe('ORD-1')
    expect(text.slice(start)).not.toBe('ORD-1') // naive UTF-16 slicing is off by the emoji's surrogate pair
  })
})
