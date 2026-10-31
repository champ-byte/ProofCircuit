import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CaseProgress } from '../components/CaseProgress'
import { Welcome } from '../components/Welcome'
import { stageIndex, tourPage } from '../guide'
import i18n from '../i18n'

afterEach(async () => {
  cleanup()
  await i18n.changeLanguage('en')
  localStorage.clear()
})

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
  it('switches language, then sends the visitor to sign in', async () => {
    const onClose = vi.fn()
    render(
      <MemoryRouter initialEntries={['/']}>
        <Welcome onClose={onClose} />
        <Routes>
          <Route path="/" element={<p>home</p>} />
          <Route path="/signin" element={<p>sign-in page</p>} />
        </Routes>
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: /मराठी/ }))
    expect(await screen.findByText('तुमची भाषा निवडा')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /पुढे/ }))
    expect(screen.getByText('sign-in page')).toBeTruthy()
    expect(onClose).toHaveBeenCalled()
    expect(localStorage.getItem('proofsaathi.onboarded')).toBe('1')
  })
})
