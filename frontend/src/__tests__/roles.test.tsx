import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RoleRoute } from '../App'
import { SignInPage } from '../pages/SignInPage'
import { homeFor, needsReview, savedIdentity, signInRole, signInUsers } from '../roles'
import { SessionContext, type SessionState } from '../session'
import type { CaseSummary, DemoSession, DemoUser, InboxView } from '../types/api'

afterEach(() => {
  cleanup()
  localStorage.clear()
})

const user = (mid: string, handle: string, display_name: string, role: string): DemoUser => ({
  mid, merchant_name: mid === 'MID-DEMO-001' ? 'Metro Furniture Demo' : 'Other', handle, display_name, role, locale: 'en-IN',
})

// The real /api/demo/users list, test accounts included.
const users: DemoUser[] = [
  user('MID-DEMO-001', 'owner', 'Asha (Owner)', 'owner'),
  user('MID-DEMO-001', 'reviewer', 'Ravi (Reviewer)', 'reviewer'),
  user('MID-DEMO-001', 'operator', 'Demo Operator', 'operator'),
  user('MID-DEMO-001', 'staff-delivery', 'Sanjay (Delivery)', 'staff'),
  user('MID-DEMO-001', 'staff-billing', 'Meera (Billing)', 'staff'),
  user('MID-DEMO-002', 'owner', 'Other Owner', 'owner'),
  user('MID-EVAL-001', 'owner', 'Eval Owner', 'owner'),
  user('MID-EVAL-001', 'reviewer', 'Eval Reviewer', 'reviewer'),
  user('MID-EVAL-001', 'staff-delivery', 'Eval Delivery Staff', 'staff'),
]

const sessionFor = (handle: string, role: string): DemoSession => ({
  token: `token-${handle}`,
  user: { handle, display_name: handle, role, locale: 'en-IN' },
  merchant: { name: 'Metro Furniture Demo', mid: 'MID-DEMO-001' },
})

function state(identity: string | null, session: DemoSession | null, setIdentity = vi.fn()): SessionState {
  return { session, token: session?.token ?? null, identity, users, setIdentity, relogin: () => undefined }
}

/** Every guarded route, each rendering its own marker, so a test can see where a role ends up. */
function renderAt(path: string, value: SessionState) {
  return render(
    <SessionContext.Provider value={value}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/signin" element={<p>sign-in page</p>} />
          <Route path="/cases" element={<RoleRoute roles={['owner']}><p>owner cases</p></RoleRoute>} />
          <Route path="/cases/:id" element={<RoleRoute roles={['owner']}><p>owner case</p></RoleRoute>} />
          <Route path="/staff" element={<RoleRoute roles={['staff']}><p>staff requests</p></RoleRoute>} />
          <Route path="/review" element={<RoleRoute roles={['reviewer']}><p>review queue</p></RoleRoute>} />
          <Route path="/review/:id" element={<RoleRoute roles={['reviewer']}><p>review case</p></RoleRoute>} />
        </Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
  )
}

describe('who can sign in', () => {
  it('offers only the four MID-DEMO-001 people, never test accounts or the operator', () => {
    expect(signInUsers(users).map((u) => u.display_name)).toEqual(['Asha (Owner)', 'Ravi (Reviewer)', 'Sanjay (Delivery)', 'Meera (Billing)'])
    expect(signInRole('MID-DEMO-001/operator')).toBeNull()
    expect(signInRole('MID-EVAL-001/owner')).toBeNull()
    expect(signInRole('MID-DEMO-001/staff-billing')).toBe('staff')
  })

  it('forgets a saved operator or test identity', () => {
    localStorage.setItem('proofsaathi.identity', 'MID-DEMO-001/operator')
    expect(savedIdentity()).toBeNull()
    localStorage.setItem('proofsaathi.identity', 'MID-DEMO-001/reviewer')
    expect(savedIdentity()).toBe('MID-DEMO-001/reviewer')
  })

  it('sends each role to its own home', () => {
    expect(homeFor('owner')).toBe('/cases')
    expect(homeFor('staff')).toBe('/staff')
    expect(homeFor('reviewer')).toBe('/review')
    expect(homeFor(null)).toBe('/signin')
  })
})

describe('sign-in page', () => {
  it('shows three role cards and signs Sanjay in to the staff screen', () => {
    const setIdentity = vi.fn()
    render(
      <SessionContext.Provider value={state(null, null, setIdentity)}>
        <MemoryRouter initialEntries={['/signin']}>
          <Routes>
            <Route path="/signin" element={<SignInPage />} />
            <Route path="/staff" element={<p>staff requests</p>} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>,
    )
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Shop owner', 'Staff member', 'Reviewer'])
    const buttons = screen.getAllByRole('button').map((b) => b.textContent)
    expect(buttons).toEqual(['Sign in as Asha', 'Sign in as Sanjay', 'Sign in as Meera', 'Sign in as Ravi'])
    expect(screen.queryByText(/Eval|Other Owner|Operator/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Sign in as Sanjay' }))
    expect(setIdentity).toHaveBeenCalledWith('MID-DEMO-001/staff-delivery')
    expect(screen.getByText('staff requests')).toBeTruthy()
  })
})

describe('route guards', () => {
  it('sends signed-out visitors to sign in', () => {
    renderAt('/cases', state(null, null))
    expect(screen.getByText('sign-in page')).toBeTruthy()
  })

  it('lets the owner see owner screens only', () => {
    const owner = state('MID-DEMO-001/owner', sessionFor('owner', 'owner'))
    renderAt('/cases/abc', owner)
    expect(screen.getByText('owner case')).toBeTruthy()
    cleanup()
    renderAt('/review', owner)
    expect(screen.getByText('owner cases')).toBeTruthy()
    cleanup()
    renderAt('/staff', owner)
    expect(screen.getByText('owner cases')).toBeTruthy()
  })

  it('redirects staff away from the case pages', () => {
    const staff = state('MID-DEMO-001/staff-delivery', sessionFor('staff-delivery', 'staff'))
    renderAt('/cases/abc', staff)
    expect(screen.getByText('staff requests')).toBeTruthy()
    cleanup()
    renderAt('/review/abc', staff)
    expect(screen.getByText('staff requests')).toBeTruthy()
  })

  it('keeps the reviewer on the review screens', () => {
    const reviewer = state('MID-DEMO-001/reviewer', sessionFor('reviewer', 'reviewer'))
    renderAt('/cases', reviewer)
    expect(screen.getByText('review queue')).toBeTruthy()
    cleanup()
    renderAt('/review/abc', reviewer)
    expect(screen.getByText('review case')).toBeTruthy()
  })

  it('waits for the session before showing a page', () => {
    renderAt('/staff', state('MID-DEMO-001/staff-billing', null))
    expect(screen.queryByText('staff requests')).toBeNull()
    expect(screen.getByText('Loading case…')).toBeTruthy()
  })
})

describe('review queue filter', () => {
  const summary = (workflow_state: string) => ({ workflow_state }) as CaseSummary
  const inbox = (status: string): InboxView => ({
    tasks: [{ id: 't1', kind: 'review', requirement_id: 'review:owner_request', round: 1, assignee: null, locale: 'en-IN', status, question: 'Please decide.', reminder: null }],
    messages: [],
  })

  it('lists cases in human review or with an open review task', () => {
    expect(needsReview(summary('NEEDS_HUMAN_REVIEW'), null)).toEqual([])
    expect(needsReview(summary('COLLECTING'), inbox('open'))).toEqual(['Please decide.'])
    expect(needsReview(summary('COLLECTING'), inbox('completed'))).toBeNull()
    expect(needsReview(summary('WAITING_FOR_EVIDENCE'), null)).toBeNull()
  })
})
