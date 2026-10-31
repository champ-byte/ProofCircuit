import { lazy, type ReactNode, Suspense, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { api } from './api/client'
import { BrandMark } from './components/BrandMark'
import { LanguageSwitcher } from './components/LanguageSwitcher'
import { Tour } from './components/Tour'
import { ViewProvider, ViewToggle } from './components/ViewToggle'
import { Welcome } from './components/Welcome'
import { isOnboarded, tourPage } from './guide'
import { firstName, homeFor, type Role, saveIdentity, savedIdentity, signInRole } from './roles'
import { SessionContext, useSession } from './session'
import type { DemoSession, DemoUser } from './types/api'

const CasesRoute = lazy(() => import('./pages/CasesPage').then((module) => ({ default: module.CasesRoute })))
const CaseWorkspace = lazy(() => import('./pages/CaseWorkspace').then((module) => ({ default: module.CaseWorkspace })))
const EvaluationPage = lazy(() => import('./pages/EvaluationPage').then((module) => ({ default: module.EvaluationPage })))
const LandingPage = lazy(() => import('./pages/LandingPage').then((module) => ({ default: module.LandingPage })))
const StaffPage = lazy(() => import('./pages/StaffPage').then((module) => ({ default: module.StaffPage })))

const OperatorPage = lazy(() => import('./pages/OperatorPage').then((module) => ({ default: module.OperatorPage })))
const ReviewCase = lazy(() => import('./pages/ReviewPage').then((module) => ({ default: module.ReviewCase })))
const ReviewQueue = lazy(() => import('./pages/ReviewPage').then((module) => ({ default: module.ReviewQueue })))
const SignInPage = lazy(() => import('./pages/SignInPage').then((module) => ({ default: module.SignInPage })))

/** Remount per case so case-local state (selected source, tab) never leaks across cases. */
function CaseRoute() {
  const { id = '' } = useParams()
  return <CaseWorkspace key={id} />
}

function ReviewRoute() {
  const { id = '' } = useParams()
  return <ReviewCase key={id} />
}

/** Each role sees only its own screens; signed-out visitors go to the sign-in page. */
export function RoleRoute({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { t } = useTranslation()
  const { identity, session } = useSession()
  const role = signInRole(identity)
  if (!role) return <Navigate to="/signin" replace />
  if (!roles.includes(role)) return <Navigate to={homeFor(role)} replace />
  if (!session) return <p aria-live="polite">{t('workspace.loading')}</p>
  return <>{children}</>
}

function SessionError({ message }: { message: string | null }) {
  const location = useLocation()
  if (!message || location.pathname === '/') return null
  return <p role="alert" className="error">{message}</p>
}

const NAV: Record<Role | 'none', { to: string; label: string; end?: boolean }[]> = {
  none: [{ to: '/', label: 'app.home', end: true }],
  owner: [{ to: '/dashboard', label: 'app.dashboard' }, { to: '/cases', label: 'app.disputes' }],
  staff: [{ to: '/staff', label: 'nav.myRequests' }],
  reviewer: [{ to: '/review', label: 'nav.toReview' }],
}

function MainNav() {
  const { t } = useTranslation()
  const { identity } = useSession()
  return (
    <nav aria-label="Main" className="mainnav">
      {NAV[signInRole(identity) ?? 'none'].map((link) => <NavLink key={link.to} to={link.to} end={link.end}>{t(link.label)}</NavLink>)}
    </nav>
  )
}

/** "Asha · Shop owner" and Switch user; a Sign in button when nobody is signed in. */
function HeaderUser() {
  const { t } = useTranslation()
  const { identity, users, session } = useSession()
  const role = signInRole(identity)
  if (!role) return <Link to="/signin" className="nav-cta">{t('signin.signIn')} <span aria-hidden="true">→</span></Link>
  const user = users.find((u) => `${u.mid}/${u.handle}` === identity)
  const name = firstName(user?.display_name ?? session?.user.display_name ?? '')
  return (
    <>
      <span id="signed-in-user" className="header-user">{name ? `${name} · ` : ''}{t(`roles.${role}`)}</span>
      <Link to="/signin" className="header-chip">{t('signin.switchUser')}</Link>
    </>
  )
}

function GuideButton({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation()
  const location = useLocation()
  if (!tourPage(location.pathname)) return null
  return <button type="button" className="header-chip" onClick={onOpen}>? {t('app.guideMe')}</button>
}

/** First visit to the home or sign-in page asks for the language, then goes to sign-in. */
function WelcomeGate() {
  const location = useLocation()
  const [dismissed, setDismissed] = useState(isOnboarded)
  if (dismissed || !['/', '/signin'].includes(location.pathname)) return null
  return <Welcome onClose={() => setDismissed(true)} />
}

function SiteFooter() {
  const { t } = useTranslation()
  const location = useLocation()
  return (
    <footer className="site-footer">
      <span>{t('app.footerTagline')}</span>
      <span>{t('app.footerDemo')}</span>
      {location.pathname !== '/operator' && <Link to="/operator" className="footer-quiet">{t('operator.link')}</Link>}
    </footer>
  )
}

export default function App() {
  const { t } = useTranslation()
  const [users, setUsers] = useState<DemoUser[]>([])
  const [identity, setIdentityState] = useState<string | null>(savedIdentity)
  const [loginKey, setLoginKey] = useState(0)
  const [session, setSession] = useState<DemoSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tour, setTour] = useState(false)

  useEffect(() => {
    api.demoUsers().then(setUsers).catch((e: Error) => setError(e.message))
  }, [loginKey])

  useEffect(() => {
    if (!identity) return
    let active = true
    const [mid, handle] = identity.split('/')
    api
      .createSession(mid, handle)
      .then((s) => {
        if (!active) return
        setSession(s)
        setError(null)
      })
      .catch((e: Error) => active && setError(e.message))
    return () => { active = false }
  }, [identity, loginKey])

  // Always re-issue, so signing in again as the same person still ends with a fresh session.
  const setIdentity = useCallback((next: string) => {
    setSession(null)
    setIdentityState(next)
    setLoginKey((k) => k + 1)
    saveIdentity(next)
  }, [])
  const relogin = useCallback(() => {
    setSession(null)
    setLoginKey((k) => k + 1)
  }, [])

  return (
    <BrowserRouter>
      <ViewProvider>
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
            <MainNav />
            <div className="header-actions">
              <LanguageSwitcher />
              <ViewToggle />
              <GuideButton onOpen={() => setTour(true)} />
              <HeaderUser />
            </div>
          </header>
          <main id="main" tabIndex={-1}>
            <SessionError message={error} />
            <Suspense fallback={<p aria-live="polite">{t('workspace.loading')}</p>}><Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/signin" element={<SignInPage />} />
              <Route path="/dashboard" element={<RoleRoute roles={['owner']}><CasesRoute showOverview /></RoleRoute>} />
              <Route path="/cases" element={<RoleRoute roles={['owner']}><CasesRoute /></RoleRoute>} />
              <Route path="/cases/:id" element={<RoleRoute roles={['owner']}><CaseRoute /></RoleRoute>} />
              <Route path="/staff" element={<RoleRoute roles={['staff']}><StaffPage /></RoleRoute>} />
              <Route path="/review" element={<RoleRoute roles={['reviewer']}><ReviewQueue /></RoleRoute>} />
              <Route path="/review/:id" element={<RoleRoute roles={['reviewer']}><ReviewRoute /></RoleRoute>} />
              <Route path="/operator" element={<OperatorPage />} />
              <Route path="/evaluation" element={<EvaluationPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes></Suspense>
            <SiteFooter />
          </main>
          <WelcomeGate />
          {tour && <Tour onClose={() => setTour(false)} />}
        </div>
      </SessionContext.Provider>
      </ViewProvider>
    </BrowserRouter>
  )
}
