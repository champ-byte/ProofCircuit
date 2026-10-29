import { useEffect, useState } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import { api } from './api/client'
import { StatusBadges } from './components/StatusBadges'
import { CasesRoute } from './pages/CasesPage'
import { CaseWorkspace } from './pages/CaseWorkspace'
import { SessionContext } from './session'
import type { DemoSession, DemoUser, ReasoningMode } from './types/api'

const DEFAULT_IDENTITY = 'MID-DEMO-001/owner'

export default function App() {
  const [mode, setMode] = useState<ReasoningMode | null>(null)
  const [users, setUsers] = useState<DemoUser[]>([])
  const [identity, setIdentity] = useState(DEFAULT_IDENTITY)
  const [session, setSession] = useState<DemoSession | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.providers().then((p) => setMode(p.reasoning_mode)).catch((e: Error) => setError(e.message))
    api.demoUsers().then(setUsers).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    const [mid, handle] = identity.split('/')
    api
      .createSession(mid, handle)
      .then((s) => {
        setSession(s)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [identity])

  return (
    <BrowserRouter>
      <SessionContext.Provider value={{ session, token: session?.token ?? null }}>
        <div className="app">
          <header className="topbar">
            <Link to="/cases" className="brand">
              <span className="brand-name">ProofCircuit</span>
              <span className="brand-tag">Dispute evidence teammate</span>
            </Link>
            <StatusBadges mode={mode} />
            <label className="identity">
              <span>Demo identity</span>
              <select
                value={identity}
                onChange={(e) => {
                  setSession(null)
                  setIdentity(e.target.value)
                }}
              >
                {users.map((u) => (
                  <option key={`${u.mid}/${u.handle}`} value={`${u.mid}/${u.handle}`}>
                    {u.display_name} — {u.merchant_name}
                  </option>
                ))}
              </select>
            </label>
          </header>
          <main>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <Routes>
              <Route path="/" element={<Navigate to="/cases" replace />} />
              <Route path="/cases" element={<CasesRoute />} />
              <Route path="/cases/:id" element={<CaseWorkspace />} />
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
