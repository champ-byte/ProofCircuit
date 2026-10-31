import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { NextStep } from '../components/NextStep'
import type { CaseDetail, EvidenceOverview, PackView } from '../types/api'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const detail = (workflow_state: string) => ({
  workflow_state, provider_status: 'NEW', deadline_expired: false, debit_amount_paise: null,
}) as CaseDetail

const evidence = (over: Partial<EvidenceOverview['assessment']> = {}, missing = true) => ({
  checklist: missing ? [{ requirement_id: 'delivery_record', label: 'Delivery record', status: 'missing', assignee: 'Sanjay' }] : [],
  assessment: { evidence_ready: false, blocking_contradiction: false, blockers: ['delivery_record: missing'], ...over },
}) as unknown as EvidenceOverview

function show(state: string, ev: EvidenceOverview, packs: PackView[] = []) {
  vi.spyOn(api, 'packs').mockResolvedValue(packs)
  const action = vi.spyOn(api, 'action').mockResolvedValue({ run_id: 'r1' })
  const goTo = vi.fn()
  render(<NextStep caseId="c1" token="t" detail={detail(state)} evidence={ev} version={0} onChanged={vi.fn().mockResolvedValue(undefined)} goTo={goTo} />)
  return { action, goTo }
}

describe('next-step card', () => {
  it('shows one status, one sentence and one button that asks staff for the missing proof', async () => {
    const { action } = show('COLLECTING', evidence())
    expect(screen.getByTestId('status-banner').textContent).toContain('Collecting proof')
    expect(screen.getByText('The delivery record is missing. Ask staff to send it.')).toBeTruthy()
    expect(screen.getAllByRole('button')).toHaveLength(1)
    expect(screen.queryByText(/delivery_record/)).toBeNull() // blockers are detailed-view only
    fireEvent.click(screen.getByRole('button', { name: 'Ask staff for delivery proof' }))
    await waitFor(() => expect(action).toHaveBeenCalledWith('t', 'c1', 'request_evidence', { requirement_id: 'delivery_record' }))
  })

  it('names who was asked while waiting', () => {
    show('WAITING_FOR_EVIDENCE', evidence())
    expect(screen.getByText('Sanjay was asked for the delivery record. The case continues when it arrives.')).toBeTruthy()
  })

  it('prepares the response file first, then sends it', async () => {
    show('READY_TO_SUBMIT', evidence({ evidence_ready: true }, false))
    expect(await screen.findByRole('button', { name: 'Prepare response file' })).toBeTruthy()
    cleanup()
    const pack = { is_latest: true, stale: false } as PackView
    const { action } = show('READY_TO_SUBMIT', evidence({ evidence_ready: true }, false), [pack])
    fireEvent.click(await screen.findByRole('button', { name: 'Send response' }))
    await waitFor(() => expect(action).toHaveBeenCalledWith('t', 'c1', 'submit_defense', {}))
  })

  it('opens the receipt after sending instead of claiming a win', () => {
    const { goTo } = show('MONITORING', evidence({}, false))
    expect(screen.getByTestId('status-banner').textContent).toContain('This is not a win yet')
    fireEvent.click(screen.getByRole('button', { name: 'See the receipt' }))
    expect(goTo).toHaveBeenCalledWith('pack-h')
  })
})
