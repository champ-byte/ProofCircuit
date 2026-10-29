import { useEffect, useState } from 'react'
import { api } from './api/client'
import { StatusBadges } from './components/StatusBadges'
import { CasesPage } from './pages/CasesPage'
import type { CaseSummary, DemoSession, DemoUser, ReasoningMode } from './types/api'

const DEFAULT_IDENTITY = 'MID-DEMO-001/owner'

export default function App() {
  const [mode, setMode] = useState<ReasoningMode | null>(null)
  const [users, setUsers] = useState<DemoUser[]>([])
  const [identity, setIdentity] = useState(DEFAULT_IDENTITY)
  const [session, setSession] = useState<DemoSession | null>(null)
  const [cases, setCases] = useState<CaseSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.providers().then((p) => setMode(p.reasoning_mode)).catch((e: Error) => setError(e.message))
    api.demoUsers().then(setUsers).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    const [mid, handle] = identity.split('/')
    api
      .createSession(mid, handle)
      .then(async (s) => {
        setSession(s)
        setCases(await api.cases(s.token))
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [identity])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-name">ProofCircuit</span>
          <span className="brand-tag">Dispute evidence teammate</span>
        </div>
        <StatusBadges mode={mode} />
        <label className="identity">
          <span>Demo identity</span>
          <select
            value={identity}
            onChange={(e) => {
              setCases(null)
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
        <h1>Cases{session ? ` · ${session.merchant.name}` : ''}</h1>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {cases === null && !error ? <p aria-live="polite">Loading cases…</p> : null}
        {cases && <CasesPage cases={cases} />}
        <p className="footnote">
          Synthetic hackathon prototype. Simulated Paytm provider; no real money movement or messages.
        </p>
      </main>
    </div>
  )
}
