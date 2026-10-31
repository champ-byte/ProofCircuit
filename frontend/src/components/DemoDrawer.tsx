import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { StaffInbox } from './StaffInbox'
import { useSession } from '../session'
import type { DemoSession, ProviderReport, SimulatorState } from '../types/api'

export type TabId = 'inbox' | 'faults' | 'identity' | 'data' | 'providers' | 'resume'
const TABS: { id: TabId; label: string }[] = [
  { id: 'inbox', label: 'Staff inbox' },
  { id: 'faults', label: 'Fault injector' },
  { id: 'identity', label: 'Identity' },
  { id: 'data', label: 'Seed / reset' },
  { id: 'providers', label: 'Providers' },
  { id: 'resume', label: 'Resume' },
]

const ACTION_FAULTS = [
  ['drop_response_after', 'Lose response after accepting (504)'],
  ['system_error_after', '5001 after accepting'],
  ['system_error_before', '5001 before accepting'],
  ['upload_failed', '4010 upload failed'],
  ['ack_variant_a', 'Ack with resultStatus A'],
] as const
const STATUS_FAULTS = [
  ['system_error', 'Status read 5001'],
  ['stale_status', 'Stale status (previous state)'],
] as const

/** Keyboard-operable tab list (ARIA tabs pattern: arrows, Home, End). */
export function Tabs({ active, onChange }: { active: TabId; onChange: (t: TabId) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const onKeyDown = (e: KeyboardEvent, index: number) => {
    let next = index
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (index + 1) % TABS.length
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (index - 1 + TABS.length) % TABS.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = TABS.length - 1
    else return
    e.preventDefault()
    onChange(TABS[next].id)
    refs.current[next]?.focus()
  }
  return (
    <div role="tablist" aria-label="Demo controls" className="tabs">
      {TABS.map((t, i) => (
        <button
          key={t.id}
          ref={(el) => void (refs.current[i] = el)}
          role="tab"
          id={`tab-${t.id}`}
          aria-selected={active === t.id}
          aria-controls={`panel-${t.id}`}
          tabIndex={active === t.id ? 0 : -1}
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => onKeyDown(e, i)}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

function useDemoSession(mid: string, handle: string, key: number): DemoSession | null {
  const [s, setS] = useState<DemoSession | null>(null)
  useEffect(() => {
    api.createSession(mid, handle).then(setS).catch(() => setS(null))
  }, [mid, handle, key])
  return s
}

export function DemoDrawer({
  caseId,
  disputeId,
  mid,
  version,
  requestedTab,
  onChanged,
  onReset,
}: {
  caseId: string
  disputeId: string
  mid: string
  version: number
  requestedTab?: { tab: TabId; nonce: number } | null
  onChanged: () => Promise<void>
  onReset: (newCaseId: string) => void
}) {
  const { users, identity, setIdentity } = useSession()
  const [open, setOpen] = useState(Boolean(requestedTab))
  const [tab, setTab] = useState<TabId>(requestedTab?.tab ?? 'inbox')
  const [loginKey, setLoginKey] = useState(0)
  const [staffHandle, setStaffHandle] = useState('staff-delivery')
  const staff = useDemoSession(mid, staffHandle, loginKey)
  const operator = useDemoSession(mid, 'operator', loginKey)
  const [message, setMessage] = useState<string | null>(null)

  const run = useCallback(
    async (fn: () => Promise<unknown>, ok: string) => {
      setMessage(null)
      try {
        const r = await fn()
        setMessage(typeof r === 'string' ? r : ok)
        await onChanged()
      } catch (err) {
        setMessage(`Failed: ${(err as Error).message}`)
      }
    },
    [onChanged],
  )

  return (
    <aside id="demo-drawer" className={`drawer ${open ? 'drawer-open' : 'drawer-closed'}`} aria-label="Demo drawer">
      <button type="button" className="drawer-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? 'Hide demo drawer' : 'Show demo drawer'}
      </button>
      {open && (
        <div className="drawer-body">
          <p className="sub drawer-note">
            Synthetic demo controls. Every action still goes through server-side role and merchant checks; this is not a
            permission bypass.
          </p>
          <Tabs active={tab} onChange={setTab} />
          <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="tabpanel">
            {tab === 'inbox' && staff && (
              <StaffInbox
                caseId={caseId}
                staff={staff}
                staffHandle={staffHandle}
                setStaffHandle={setStaffHandle}
                version={version}
                run={run}
                operator={operator}
              />
            )}
            {tab === 'faults' && operator && (
              <FaultInjector disputeId={disputeId} operator={operator} version={version} run={run} />
            )}
            {tab === 'identity' && (
              <div>
                <p className="sub">Switch the identity used for the main workspace.</p>
                <ul className="identity-list">
                  {users
                    .filter((u) => u.mid === mid)
                    .map((u) => {
                      const id = `${u.mid}/${u.handle}`
                      return (
                        <li key={id}>
                          <button type="button" aria-pressed={identity === id} onClick={() => setIdentity(id)}>
                            {u.display_name} <span className="sub">({u.role}, {u.locale})</span>
                          </button>
                        </li>
                      )
                    })}
                </ul>
              </div>
            )}
            {tab === 'data' && operator && (
              <SeedReset
                operator={operator}
                onReset={(newCaseId) => {
                  setLoginKey((k) => k + 1)
                  onReset(newCaseId)
                }}
              />
            )}
            {tab === 'providers' && operator && (
              <Providers caseId={caseId} operator={operator} version={version} run={run} />
            )}
            {tab === 'resume' && operator && (
              <div>
                <p className="sub">
                  Explicit recovery: reconcile in-flight submissions and drain pending work. There is no background
                  polling worker.
                </p>
                <button
                  type="button"
                  onClick={() =>
                    run(async () => {
                      const r = await api.resume(operator.token)
                      return `Resume: ${Object.entries(r)
                        .map(([k, v]) => `${k.replaceAll('_', ' ')} ${v}`)
                        .join(', ')}`
                    }, 'Resumed.')
                  }
                >
                  Resume pending work
                </button>
              </div>
            )}
          </div>
          {message && (
            <p role="status" className="sub drawer-message">
              {message}
            </p>
          )}
        </div>
      )}
    </aside>
  )
}

type Runner = (fn: () => Promise<unknown>, ok: string) => Promise<void>

function FaultInjector({
  disputeId,
  operator,
  version,
  run,
}: {
  disputeId: string
  operator: DemoSession
  version: number
  run: Runner
}) {
  const [state, setState] = useState<SimulatorState | null>(null)
  const [comment, setComment] = useState('Signature on the delivery receipt is not legible')
  const [outcome, setOutcome] = useState('WON')
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    api.simState(operator.token, disputeId).then(setState).catch(() => setState(null))
  }, [operator.token, disputeId, version, refresh])
  const inject = (body: Record<string, unknown>, ok: string) =>
    run(async () => {
      await api.simEvent(operator.token, { dispute_id: disputeId, ...body })
      setRefresh((r) => r + 1)
    }, ok)
  return (
    <div>
      {state && (
        <dl className="kv">
          <dt>Simulated dispute status</dt>
          <dd>
            <code>{state.dispute_status}</code>
          </dd>
          <dt>Receipts at provider</dt>
          <dd>{state.receipts.length}</dd>
          <dt>Queued faults</dt>
          <dd>
            {state.queued_faults.length === 0
              ? 'none'
              : state.queued_faults.map((f) => `${f.api}:${f.kind} ×${f.remaining}`).join(', ')}
          </dd>
        </dl>
      )}
      <fieldset>
        <legend>Next Action API call</legend>
        {ACTION_FAULTS.map(([kind, label]) => (
          <button key={kind} type="button" onClick={() => inject({ type: 'fault', api: 'action', kind }, `Queued: ${label}`)}>
            {label}
          </button>
        ))}
      </fieldset>
      <fieldset>
        <legend>Next Status API call</legend>
        {STATUS_FAULTS.map(([kind, label]) => (
          <button key={kind} type="button" onClick={() => inject({ type: 'fault', api: 'status', kind }, `Queued: ${label}`)}>
            {label}
          </button>
        ))}
      </fieldset>
      <fieldset>
        <legend>Provider review events</legend>
        <label className="field">
          POD rejection comment
          <input value={comment} maxLength={246} onChange={(e) => setComment(e.target.value)} />
        </label>
        <button type="button" onClick={() => inject({ type: 'pod_reject', comment }, 'POD rejection injected.')}>
          Reject proof (POD_REJECT)
        </button>
        <label className="field">
          Outcome
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="WON">WON</option>
            <option value="LOST">LOST (with simulated debit)</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() =>
            inject(
              outcome === 'LOST'
                ? { type: 'outcome', outcome, debit_amount: '18500.00', dispute_utr: 'UTR-DEMO-0001', lost_reason: 'Simulated' }
                : { type: 'outcome', outcome },
              `Outcome ${outcome} injected.`,
            )
          }
        >
          Inject outcome
        </button>
        <button type="button" onClick={() => inject({ type: 'resend_callback' }, 'Webhook re-sent (duplicate).')}>
          Re-send last webhook
        </button>
      </fieldset>
    </div>
  )
}

function SeedReset({ operator, onReset }: { operator: DemoSession; onReset: (newCaseId: string) => void }) {
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <div>
      <p className="sub">Deletes all demo data and runtime files, then reseeds the hero case. Sessions are re-issued.</p>
      <label className="check-row">
        <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /> I understand this
        deletes all demo data
      </label>
      <button
        type="button"
        className="danger"
        disabled={!confirm || busy}
        onClick={async () => {
          setBusy(true)
          setError(null)
          try {
            const r = await api.reset(operator.token)
            onReset(r.case_id)
          } catch (err) {
            setError((err as Error).message)
          } finally {
            setBusy(false)
            setConfirm(false)
          }
        }}
      >
        Reset demo data
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function Providers({ caseId, operator, version, run }: { caseId: string; operator: DemoSession; version: number; run: Runner }) {
  const [report, setReport] = useState<ProviderReport | null>(null)
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    api.providers().then(setReport).catch(() => setReport(null))
  }, [version, refresh])
  if (!report) return <p className="sub">Loading…</p>
  return (
    <div>
      <p>
        Reasoning mode: <strong>{report.reasoning_mode.label}</strong>
      </p>
      <p className="sub">
        Model calls in the last 24 h: {report.usage.calls_24h ?? '?'} / {report.usage.cap} cap · minimum{' '}
        {report.usage.min_interval_s}s between calls
      </p>
      <ul className="readiness">
        {[...report.reasoners, ...report.integrations].map((p) => (
          <li key={`${p.role}-${p.name}`}>
            <strong>{p.name}</strong> <span className="sub">({p.role})</span>: <span className={`st st-${p.status}`}>{p.status.replaceAll('_', ' ')}</span>
            {p.model && <span className="sub"> · {p.model}</span>}
            <div className="sub">{p.detail}</div>
          </li>
        ))}
      </ul>
      <div className="fixture-buttons">
        <button
          type="button"
          onClick={() =>
            run(async () => {
              const r = await api.smoke(operator.token)
              setRefresh((x) => x + 1)
              return r.ok ? `Smoke test passed: ${r.model_returned} in ${r.latency_ms} ms` : `Smoke test failed: ${r.detail}`
            }, '')
          }
        >
          Run reasoner smoke test (uses 1–4 model calls)
        </button>
        <button type="button" onClick={() => run(() => api.startRun(operator.token, caseId, 'fixture_replay'), 'Fixture replay started (not AI).')}>
          Run fixture replay (not AI)
        </button>
      </div>
    </div>
  )
}
