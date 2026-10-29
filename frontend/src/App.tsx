import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { api } from './api/client'
import { StatusBadges } from './components/StatusBadges'
import { CasesRoute } from './pages/CasesPage'
import { CaseWorkspace } from './pages/CaseWorkspace'
import { EvaluationPage } from './pages/EvaluationPage'
import { SessionContext } from './session'
import type { DemoSession, DemoUser, ReasoningMode } from './types/api'

const DEFAULT_IDENTITY = 'MID-DEMO-001/owner'

/** Remount per case so case-local state (selected source, drawer tab) never leaks across cases. */
function CaseRoute() {
  const { id = '' } = useParams()
  return <CaseWorkspace key={id} />
}

export default function App() {
  const [mode, setMode] = useState<ReasoningMode | null>(null)
  const [users, setUsers] = useState<DemoUser[]>([])
  const [identity, setIdentityState] = useState(DEFAULT_IDENTITY)
  const [loginKey, setLoginKey] = useState(0)
  const [session, setSession] = useState<DemoSession | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = () => api.providers().then((p) => setMode(p.reasoning_mode)).catch(() => undefined)
    load()
    const id = window.setInterval(load, 20000)
    return () => window.clearInterval(id)
  }, [])

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
            <Link to="/cases" className="brand">
              <span className="brand-name">ProofCircuit</span>
              <span className="brand-tag">Dispute evidence teammate</span>
            </Link>
            <nav aria-label="Main" className="mainnav">
              <NavLink to="/cases">Cases</NavLink>
              <NavLink to="/evaluation">Evaluation</NavLink>
            </nav>
            <StatusBadges mode={mode} />
            <label className="identity">
              <span>Demo identity</span>
              <select value={identity} onChange={(e) => setIdentity(e.target.value)}>
                {users.map((u) => (
                  <option key={`${u.mid}/${u.handle}`} value={`${u.mid}/${u.handle}`}>
                    {u.display_name} — {u.merchant_name}
                  </option>
                ))}
              </select>
            </label>
          </header>
          <main id="main" tabIndex={-1}>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <Routes>
              <Route path="/" element={<Navigate to="/cases" replace />} />
              <Route path="/cases" element={<CasesRoute />} />
              <Route path="/cases/:id" element={<CaseRoute />} />
              <Route path="/evaluation" element={<EvaluationPage />} />
            </Routes>
            <p className="footnote">
              Synthetic hackathon prototype. Simulated Paytm provider; no real money movement or messages.
            </p>
          </main>
        </div>
      </SessionContext.Provider>
    </BrowserRouter>
  )
}
