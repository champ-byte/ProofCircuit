import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CaseProgress } from '../components/CaseProgress'
import { Welcome } from '../components/Welcome'
import { stageIndex, tourPage } from '../guide'
import i18n from '../i18n'
import { SessionContext } from '../session'
import type { DemoUser } from '../types/api'

afterEach(async () => {
  cleanup()
  await i18n.changeLanguage('en')
  localStorage.clear()
})

const users: DemoUser[] = [
  { mid: 'MID-DEMO-001', merchant_name: 'Metro', handle: 'owner', display_name: 'Asha (Owner)', role: 'owner', locale: 'en-IN' },
  { mid: 'MID-DEMO-001', merchant_name: 'Metro', handle: 'staff-delivery', display_name: 'Sanjay (Delivery)', role: 'staff', locale: 'mr-IN' },
  { mid: 'MID-DEMO-001', merchant_name: 'Metro', handle: 'staff-billing', display_name: 'Meera (Billing)', role: 'staff', locale: 'hi-IN' },
  { mid: 'MID-DEMO-001', merchant_name: 'Metro', handle: 'reviewer', display_name: 'Ravi (Reviewer)', role: 'reviewer', locale: 'en-IN' },
]

describe('case progress', () => {
  it('maps nine workflow states onto three stages', () => {
    expect(stageIndex('WAITING_FOR_EVIDENCE')).toBe(0)
    expect(stageIndex('NEEDS_HUMAN_REVIEW')).toBe(0)
    expect(stageIndex('READY_TO_SUBMIT')).toBe(1)
    expect(stageIndex('SUBMISSION_UNCERTAIN')).toBe(1)
    expect(stageIndex('MONITORING')).toBe(2)
    expect(stageIndex('CLOSED')).toBe(3)
  })

  it('marks the current stage for screen readers', () => {
    render(<CaseProgress workflowState="READY_TO_SUBMIT" />)
    const current = document.querySelector('[aria-current=step]')
    expect(current?.textContent).toContain('Check and send')
    expect(screen.getAllByText('Done')).toHaveLength(1)
  })

  it('picks the guide for each page', () => {
    expect(tourPage('/')).toBe('landing')
    expect(tourPage('/dashboard')).toBe('cases')
    expect(tourPage('/cases/abc')).toBe('case')
    expect(tourPage('/staff')).toBe('staff')
    expect(tourPage('/evaluation')).toBeNull()
  })
})

describe('welcome chooser', () => {
  it('switches language first, then signs in as the chosen staff member', async () => {
    const setIdentity = vi.fn()
    const onClose = vi.fn()
    render(
      <MemoryRouter>
        <SessionContext.Provider value={{ session: null, token: null, identity: '', users, setIdentity, relogin: () => undefined }}>
          <Welcome onClose={onClose} />
        </SessionContext.Provider>
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: /मराठी/ }))
    expect(await screen.findByText('तुमची भाषा निवडा')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /पुढे/ }))
    expect(screen.getByText(/Paytm इथे व्यक्ती नाही/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Sanjay (Delivery)' }))
    expect(setIdentity).toHaveBeenCalledWith('MID-DEMO-001/staff-delivery')
    expect(onClose).toHaveBeenCalled()
    expect(localStorage.getItem('proofsaathi.onboarded')).toBe('1')
  })
})
