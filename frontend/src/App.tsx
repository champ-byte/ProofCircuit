import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { api } from './api/client'
import { BrandMark } from './components/BrandMark'
import { LanguageSwitcher } from './components/LanguageSwitcher'
import { Tour } from './components/Tour'
import { Welcome } from './components/Welcome'
import { isOnboarded } from './guide'
import { SessionContext } from './session'
import type { DemoSession, DemoUser } from './types/api'

const CasesRoute = lazy(() => import('./pages/CasesPage').then((module) => ({ default: module.CasesRoute })))
const CaseWorkspace = lazy(() => import('./pages/CaseWorkspace').then((module) => ({ default: module.CaseWorkspace })))
const EvaluationPage = lazy(() => import('./pages/EvaluationPage').then((module) => ({ default: module.EvaluationPage })))
const LandingPage = lazy(() => import('./pages/LandingPage').then((module) => ({ default: module.LandingPage })))
const StaffPage = lazy(() => import('./pages/StaffPage').then((module) => ({ default: module.StaffPage })))

const DEFAULT_IDENTITY = 'MID-DEMO-001/owner'
const IDENTITY_KEY = 'proofsaathi.identity'

/** The demo identity survives reloads so a role picked in the welcome chooser sticks. */
function savedIdentity(): string {
  try {
    return localStorage.getItem(IDENTITY_KEY) ?? DEFAULT_IDENTITY
  } catch {
    return DEFAULT_IDENTITY
  }
}

/** Remount per case so case-local state (selected source, drawer tab) never leaks across cases. */
function CaseRoute() {
  const { id = '' } = useParams()
  return <CaseWorkspace key={id} />
}

function SessionError({ message }: { message: string | null }) {
  const location = useLocation()
  if (!message || location.pathname === '/') return null
  return <p role="alert" className="error">{message}</p>
}

function HeaderIdentity({ identity, users, setIdentity }: { identity: string; users: DemoUser[]; setIdentity: (next: string) => void }) {
  const { t } = useTranslation()
  const location = useLocation()
  if (location.pathname === '/') return null
  return (
    <label id="demo-identity" className="identity">
      <span>{t('app.viewingAs')}</span>
      <select value={identity} onChange={(event) => setIdentity(event.target.value)}>
        {users.map((user) => (
          <option key={`${user.mid}/${user.handle}`} value={`${user.mid}/${user.handle}`}>
            {user.display_name} — {user.merchant_name}
          </option>
        ))}
      </select>
    </label>
  )
}

/** First visit to the home page opens the language/role chooser; "Change role" reopens it anywhere. */
function WelcomeGate({ forced, setForced }: { forced: boolean; setForced: (open: boolean) => void }) {
  const location = useLocation()
  const [dismissed, setDismissed] = useState(isOnboarded)
  const open = forced || (!dismissed && location.pathname === '/')
  if (!open) return null
  return <Welcome onClose={() => { setDismissed(true); setForced(false) }} />
}

function SiteFooter() {
  const { t } = useTranslation()
  const location = useLocation()
  return (
    <footer className="site-footer">
      <span>{t('app.footerTagline')}</span>
      <span>{t('app.footerDemo')}</span>
      {location.pathname !== '/evaluation' && <Link to="/evaluation">{t('app.footerEvaluation')}</Link>}
    </footer>
  )
}

export default function App() {
  const { t } = useTranslation()
  const [users, setUsers] = useState<DemoUser[]>([])
  const [identity, setIdentityState] = useState(savedIdentity)
  const [loginKey, setLoginKey] = useState(0)
  const [session, setSession] = useState<DemoSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [welcome, setWelcome] = useState(false)
  const [tour, setTour] = useState(false)

  useEffect(() => {
    api.demoUsers().then(setUsers).catch((e: Error) => setError(e.message))
  }, [loginKey])

  useEffect(() => {
    const [mid, handle] = identity.split('/')
    api
      .createSession(mid, handle)
      .then((s) => {
        setSession(s)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [identity, loginKey])

  const setIdentity = useCallback((next: string) => {
    setSession(null)
    setIdentityState(next)
    try {
      localStorage.setItem(IDENTITY_KEY, next)
    } catch {
      /* private mode: identity resets to the owner on reload */
    }
  }, [])
  const relogin = useCallback(() => {
    setSession(null)
    setLoginKey((k) => k + 1)
  }, [])

  return (
    <BrowserRouter>
      <SessionContext.Provider value={{ session, token: session?.token ?? null, identity, users, setIdentity, relogin }}>
        <a className="skip-link" href="#main">
          {t('app.skip')}
        </a>
        <div className="app">
          <header className="topbar">
            <Link to="/" className="brand">
              <BrandMark className="brand-mark" />
              <span className="brand-copy"><span className="brand-name">ProofSaathi</span><span className="brand-tag">{t('app.brandTag')}</span></span>
            </Link>
            <nav aria-label="Main" className="mainnav">
              <NavLink to="/" end>{t('app.home')}</NavLink>
              <NavLink to="/dashboard">{t('app.dashboard')}</NavLink>
              <NavLink to="/cases">{t('app.disputes')}</NavLink>
              <NavLink to="/staff">{t('app.staffScreen')}</NavLink>
            </nav>
            <div className="header-actions">
              <LanguageSwitcher />
              <button type="button" className="header-chip" onClick={() => setTour(true)}>? {t('app.guideMe')}</button>
              <button type="button" className="header-chip" onClick={() => setWelcome(true)}>{t('app.changeRole')}</button>
              <HeaderIdentity identity={identity} users={users} setIdentity={setIdentity} />
              <Link to="/cases" className="nav-cta">{t('app.viewDisputes')} <span aria-hidden="true">→</span></Link>
            </div>
          </header>
          <main id="main" tabIndex={-1}>
            <SessionError message={error} />
            <Suspense fallback={<p aria-live="polite">{t('workspace.loading')}</p>}><Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/dashboard" element={<CasesRoute showOverview />} />
              <Route path="/cases" element={<CasesRoute />} />
              <Route path="/cases/:id" element={<CaseRoute />} />
              <Route path="/staff" element={<StaffPage />} />
              <Route path="/evaluation" element={<EvaluationPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes></Suspense>
            <SiteFooter />
          </main>
          <WelcomeGate forced={welcome} setForced={setWelcome} />
          {tour && <Tour onClose={() => setTour(false)} />}
        </div>
      </SessionContext.Provider>
    </BrowserRouter>
  )
}
