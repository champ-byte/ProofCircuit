import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { api } from './api/client'
import { BrandMark } from './components/BrandMark'
import { CasesRoute } from './pages/CasesPage'
import { CaseWorkspace } from './pages/CaseWorkspace'
import { EvaluationPage } from './pages/EvaluationPage'
import { LandingPage } from './pages/LandingPage'
import { SessionContext } from './session'
import type { DemoSession, DemoUser } from './types/api'

const DEFAULT_IDENTITY = 'MID-DEMO-001/owner'

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
  const location = useLocation()
  if (location.pathname === '/') return null
  return (
    <label id="demo-identity" className="identity">
      <span>Viewing as</span>
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

function SiteFooter() {
  const location = useLocation()
  return (
    <footer className="site-footer">
      <span>ProofSaathi · A clearer way to handle disputes</span>
      <span>Demo workspace · No real payments or customer messages</span>
      {location.pathname !== '/evaluation' && <Link to="/evaluation">Evaluation tools</Link>}
    </footer>
  )
}

export default function App() {
  const [users, setUsers] = useState<DemoUser[]>([])
  const [identity, setIdentityState] = useState(DEFAULT_IDENTITY)
  const [loginKey, setLoginKey] = useState(0)
  const [session, setSession] = useState<DemoSession | null>(null)
  const [error, setError] = useState<string | null>(null)

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
  }, [])
  const relogin = useCallback(() => {
    setSession(null)
    setLoginKey((k) => k + 1)
  }, [])

  return (
    <BrowserRouter>
      <SessionContext.Provider value={{ session, token: session?.token ?? null, identity, users, setIdentity, relogin }}>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <div className="app">
          <header className="topbar">
            <Link to="/" className="brand">
              <BrandMark className="brand-mark" />
              <span className="brand-copy"><span className="brand-name">ProofSaathi</span><span className="brand-tag">Dispute support for your shop</span></span>
            </Link>
            <nav aria-label="Main" className="mainnav">
              <NavLink to="/" end>Home</NavLink>
              <NavLink to="/dashboard">Dashboard</NavLink>
              <NavLink to="/cases">Disputes</NavLink>
            </nav>
            <div className="header-actions">
              <HeaderIdentity identity={identity} users={users} setIdentity={setIdentity} />
              <Link to="/cases" className="nav-cta">View disputes <span aria-hidden="true">→</span></Link>
            </div>
          </header>
          <main id="main" tabIndex={-1}>
            <SessionError message={error} />
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/dashboard" element={<CasesRoute showOverview />} />
              <Route path="/cases" element={<CasesRoute />} />
              <Route path="/cases/:id" element={<CaseRoute />} />
              <Route path="/evaluation" element={<EvaluationPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            <SiteFooter />
          </main>
        </div>
      </SessionContext.Provider>
    </BrowserRouter>
  )
}
