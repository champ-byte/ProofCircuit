import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { CaseJourney } from '../components/CaseJourney'
import { CasesPage } from '../pages/CasesPage'
import { LandingPage } from '../pages/LandingPage'
import type { AuditEventView, CaseDetail, CaseSummary, DemoSession, EvidenceOverview } from '../types/api'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const caseSummary = (id: string, state: string, deadline: string): CaseSummary => ({
  id, merchant_name: 'Metro Furniture', mid: 'MID-DEMO-001', external_dispute_id: id,
  order_id: `ORDER-${id}`, transaction_id: `TXN-${id}`, reason: 'goods_not_received',
  amount_paise: 1850000, amount_display: '₹18,500.00', currency: 'INR',
  debit_amount_paise: null, dispute_utr: null, deadline_utc: deadline, deadline_local: deadline,
  deadline_raw: deadline, timezone_assumption: 'UTC', seconds_to_deadline: 0,
  deadline_expired: false, workflow_state: state, provider_status: 'POD_UPLOAD',
  provider_status_raw: 'POD_UPLOAD', flags: [], version: 1, owner: 'Asha',
  next_action: 'Review evidence', synthetic: true, evidence_ready: false, blocker: null,
})

describe('navigation and case workflow', () => {
  it('provides direct landing-page routes into disputes and the dashboard', () => {
    render(<MemoryRouter><LandingPage /></MemoryRouter>)
    expect(screen.getByRole('heading', { name: /A payment dispute/ })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'View disputes' }).getAttribute('href')).toBe('/cases')
    expect(screen.getByRole('link', { name: 'Explore dashboard' }).getAttribute('href')).toBe('/dashboard')
  })

  it('filters the dispute queue by recorded workflow state', () => {
    const cases = [
      caseSummary('DSP-REVIEW', 'NEEDS_HUMAN_REVIEW', '2030-01-02T00:00:00Z'),
      caseSummary('DSP-WAIT', 'WAITING_FOR_EVIDENCE', '2030-01-03T00:00:00Z'),
      caseSummary('DSP-DONE', 'CLOSED', '2030-01-04T00:00:00Z'),
    ]
    render(<MemoryRouter><CasesPage cases={cases} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /In review/ }))
    expect(screen.getByRole('link', { name: 'DSP-REVIEW' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'DSP-WAIT' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Done/ }))
    expect(screen.getByRole('link', { name: 'DSP-DONE' })).toBeTruthy()
  })

  it('requests the missing checklist item through the existing action API', async () => {
    const action = vi.spyOn(api, 'action').mockResolvedValue({ run_id: 'run-123' })
    const onChanged = vi.fn().mockResolvedValue(undefined)
    const session = { user: { role: 'owner' } } as DemoSession
    const detail = { workflow_state: 'COLLECTING' } as CaseDetail
    const evidence = {
      checklist: [{ requirement_id: 'delivery_record', label: 'Delivery record', status: 'missing' }],
      assessment: { evidence_ready: false, blocking_contradiction: false },
    } as EvidenceOverview
    const events: AuditEventView[] = [{ seq: 7, event_type: 'evidence.requested', summary: 'Proof asked for', actor_type: 'agent', data: {}, created_at: '2030-01-01T00:00:00Z' }]
    render(<CaseJourney caseId="case-1" token="test-token" session={session} detail={detail} evidence={evidence} events={events} onChanged={onChanged} openDemo={vi.fn()} />)
    expect(screen.getByText('Activity recorded')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Open timeline \(event #7\)/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Submit defense' }).hasAttribute('disabled')).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Request missing proof' }))
    await waitFor(() => expect(action).toHaveBeenCalledWith('test-token', 'case-1', 'request_evidence', { requirement_id: 'delivery_record' }))
    expect(onChanged).toHaveBeenCalled()
  })
})
