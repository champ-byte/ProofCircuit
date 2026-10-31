import { useEffect, useMemo, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { api } from '../api/client'
import { useSession } from '../session'
import { STATE_LABELS, formatCountdown, formatIst } from '../format'
import { secondsUntil, useNow } from '../hooks'
import type { CaseSummary } from '../types/api'
import { WorkflowChart } from '../components/WorkflowChart'

type QueueView = 'all' | 'review' | 'action' | 'waiting' | 'closed'
const isClosed = (c: CaseSummary) => c.workflow_state === 'CLOSED'
const isWaiting = (c: CaseSummary) => c.workflow_state === 'WAITING_FOR_EVIDENCE'
const isReview = (c: CaseSummary) => c.workflow_state === 'NEEDS_HUMAN_REVIEW'
const isInProgress = (c: CaseSummary) => !isClosed(c) && !isWaiting(c) && !isReview(c)

function urgency(c: CaseSummary, now: number): 'Deadline passed' | 'Urgent' | 'High' | 'Normal' | 'Done' {
  if (isClosed(c)) return 'Done'
  const left = secondsUntil(c.deadline_utc, now)
  if (left <= 0) return 'Deadline passed'
  if (left < 6 * 3600) return 'Urgent'
  if (left < 24 * 3600 || c.blocker) return 'High'
  return 'Normal'
}

function exportVisibleCases(cases: CaseSummary[], now: number) {
  const safeCell = (value: string) => {
    const text = /^[\s]*[=+@-]/.test(value) ? `'${value}` : value
    return `"${text.replaceAll('"', '""')}"`
  }
  const rows = [
    ['Dispute', 'Merchant', 'Order', 'Reason', 'Amount at risk', 'Urgency', 'Owner', 'Deadline IST', 'Workflow', 'Provider status', 'Blocker', 'Next action'],
    ...cases.map((c) => [c.external_dispute_id, c.merchant_name, c.order_id, c.reason.replaceAll('_', ' '), c.amount_display, urgency(c, now), c.owner ?? '', formatIst(c.deadline_utc), STATE_LABELS[c.workflow_state] ?? c.workflow_state, c.provider_status_raw ?? c.provider_status, c.blocker ?? '', c.next_action]),
  ]
  const csv = rows.map((row) => row.map((value) => safeCell(String(value))).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'proofcircuit-disputes.csv'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

function deadlineClass(seconds: number): string {
  if (seconds <= 0) return 'queue-deadline queue-deadline-danger'
  if (seconds < 6 * 3600) return 'queue-deadline queue-deadline-urgent'
  return 'queue-deadline'
}

export function CasesPage({ cases, showOverview = false }: { cases: CaseSummary[]; showOverview?: boolean }) {
  const now = useNow(1000)
  const [view, setView] = useState<QueueView>('all')
  const [query, setQuery] = useState('')
  const [urgentOnly, setUrgentOnly] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [descending, setDescending] = useState(false)
  const counts = useMemo(() => ({
    all: cases.length,
    action: cases.filter(isInProgress).length,
    review: cases.filter(isReview).length,
    waiting: cases.filter(isWaiting).length,
    closed: cases.filter(isClosed).length,
    blocked: cases.filter((c) => !isClosed(c) && Boolean(c.blocker)).length,
  }), [cases])
  const visible = useMemo(() => {
    const search = query.trim().toLocaleLowerCase()
    return cases
      .filter((c) => view === 'all' || (view === 'review' && isReview(c)) || (view === 'action' && isInProgress(c)) || (view === 'waiting' && isWaiting(c)) || (view === 'closed' && isClosed(c)))
      .filter((c) => !search || [c.external_dispute_id, c.order_id, c.merchant_name, c.owner ?? '', c.reason].some((value) => value.toLocaleLowerCase().includes(search)))
      .filter((c) => !urgentOnly || urgency(c, now) === 'Urgent' || urgency(c, now) === 'Deadline passed')
      .sort((a, b) => {
        if (isClosed(a) !== isClosed(b)) return isClosed(a) ? 1 : -1
        return (Date.parse(a.deadline_utc) - Date.parse(b.deadline_utc)) * (descending ? -1 : 1)
      })
  }, [cases, query, view, urgentOnly, descending, now])
  const maxPage = Math.max(1, Math.ceil(visible.length / pageSize))
  const currentPage = Math.min(page, maxPage)
  const pageCases = visible.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const nextCase = cases.filter((c) => !isClosed(c)).sort((a, b) => Date.parse(a.deadline_utc) - Date.parse(b.deadline_utc))[0]

  return (
    <div className="operations-shell">
      <aside className="operations-sidebar" aria-label="Operations navigation">
        <p>WORKSPACE</p>
        <NavLink to="/dashboard">◫ <span>Dashboard</span></NavLink>
        <NavLink to="/cases">▤ <span>Disputes</span></NavLink>
        <p>INSIGHTS</p>
        <NavLink to="/evaluation">▥ <span>Evaluation</span></NavLink>
        <div className="operations-sidebar-note">Your dispute workspace<br />Every step in one place</div>
      </aside>
      <div className="dashboard">
      {showOverview && <section className="dashboard-hero" aria-labelledby="dashboard-title">
        <div className="dashboard-hero-copy">
          <p className="eyebrow">ProofSaathi / dispute operations</p>
          <h1 id="dashboard-title">Every dispute, clearly in hand.</h1>
          <p>See what needs attention, follow the evidence, and track each response to a verified submission.</p>
        </div>
        <div className="dashboard-hero-guide" aria-hidden="true">
          <span>YOUR RESPONSE PATH</span>
          <strong><b>1</b> Find the missing proof</strong>
          <strong><b>2</b> Review the response</strong>
          <strong><b>3</b> Track the receipt</strong>
        </div>
      </section>}

      {showOverview && <section className="dashboard-overview" aria-label="Case overview">
        <div className="overview-card overview-card-primary">
          <span className="overview-label">Total disputes</span>
          <strong>{counts.all}</strong>
          <span>In this merchant workspace</span>
        </div>
        <div className="overview-card">
          <span className="overview-label">In review</span>
          <strong>{counts.review}</strong>
          <span>Human decision requested</span>
        </div>
        <div className="overview-card">
          <span className="overview-label">Waiting for evidence</span>
          <strong>{counts.waiting}</strong>
          <span>Staff response or document pending</span>
        </div>
        <div className="overview-card">
          <span className="overview-label">Open blockers</span>
          <strong>{counts.blocked}</strong>
          <span>Cases with a reported blocker</span>
        </div>
      </section>}

      {showOverview && <WorkflowChart cases={cases} />}
      {showOverview && <section className="dashboard-flow" aria-labelledby="dashboard-flow-title">
        <div className="dashboard-flow-head">
          <div><p className="eyebrow">Behind every case</p><h2 id="dashboard-flow-title">The full response flow, in view.</h2><p>Open a dispute for the live stage, source evidence, staff messages, tool actions, and recorded result.</p></div>
          {nextCase && <Link className="button-primary" to={`/cases/${nextCase.id}`}>Open next case <span aria-hidden="true">→</span></Link>}
        </div>
        <ol className="dashboard-flow-steps">
          {['Intake', 'Collect proof', 'Validate', 'Human review', 'Build pack', 'Submit', 'Verify'].map((label, index) => <li key={label}><span>{String(index + 1).padStart(2, '0')}</span>{label}</li>)}
        </ol>
      </section>}

      <section className="queue-panel" aria-labelledby="queue-title">
        <div className="queue-heading">
          <div>
            <p className="eyebrow">{showOverview ? 'Case overview' : 'Operations / disputes'}</p>
            {showOverview ? <h2 id="queue-title">Disputes</h2> : <h1 id="queue-title">Disputes</h1>}
            <p>Search and open a case to follow its evidence, decisions, and submission.</p>
          </div>
          <div className="queue-heading-actions">
            <label className="queue-search">
              <span>Search disputes</span>
              <input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1) }} placeholder="Dispute, order, merchant…" type="search" />
            </label>
            <button type="button" className={urgentOnly ? 'queue-toolbar active' : 'queue-toolbar'} aria-pressed={urgentOnly} onClick={() => { setUrgentOnly((u) => !u); setPage(1) }}>Urgent only</button>
            <button type="button" className="queue-toolbar" disabled={visible.length === 0} onClick={() => exportVisibleCases(visible, now)}>Export CSV</button>
          </div>
        </div>
        <div className="queue-filters" role="group" aria-label="Filter cases">
          {([
            ['all', 'All cases', counts.all],
            ['review', 'In review', counts.review],
            ['action', 'In progress', counts.action],
            ['waiting', 'Waiting', counts.waiting],
            ['closed', 'Done', counts.closed],
          ] as const).map(([key, label, count]) => (
            <button key={key} type="button" className={view === key ? 'queue-filter active' : 'queue-filter'} aria-pressed={view === key} onClick={() => { setView(key); setPage(1) }}>
              {label} <span>{count}</span>
            </button>
          ))}
        </div>
        {cases.length === 0 ? (
          <p className="queue-empty">No dispute cases for this merchant.</p>
        ) : visible.length === 0 ? (
          <p className="queue-empty">No cases match this view or search.</p>
        ) : (
          <div className="table-wrap queue-table-wrap">
            <table className="cases queue-table">
              <caption className="visually-hidden">Dispute queue</caption>
              <thead>
                <tr>
                  <th scope="col">Merchant / dispute</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Amount at risk</th>
                  <th scope="col">Urgency</th>
                  <th scope="col">Assigned to</th>
                  <th scope="col"><button type="button" className="table-sort" onClick={() => setDescending((d) => !d)}>Deadline <span aria-hidden="true">{descending ? '↓' : '↑'}</span></button></th>
                  <th scope="col">Status / next step</th>
                </tr>
              </thead>
              <tbody>
                {pageCases.map((c) => {
                  const remaining = secondsUntil(c.deadline_utc, now)
                  const priority = urgency(c, now)
                  return (
                    <tr key={c.id}>
                      <td data-label="Merchant / dispute">
                        <strong>{c.merchant_name}</strong>
                        <span className="queue-meta"><Link className="queue-case-link" to={`/cases/${c.id}`}>{c.external_dispute_id}</Link> · {c.order_id}</span>
                      </td>
                      <td data-label="Reason">{c.reason.replaceAll('_', ' ')}</td>
                      <td data-label="Amount at risk" className="num">{c.amount_display}</td>
                      <td data-label="Urgency"><span className={`urgency urgency-${priority.toLowerCase().replaceAll(' ', '-')}`}>{priority}</span></td>
                      <td data-label="Assigned to">{c.owner ?? 'Unassigned'}</td>
                      <td data-label="Deadline">
                        <span className={deadlineClass(remaining)}>{formatCountdown(remaining)}</span>
                        <span className="queue-meta">{formatIst(c.deadline_utc)}</span>
                      </td>
                      <td data-label="Status / next step">
                        <span className={`queue-state ${isClosed(c) ? 'queue-state-closed' : c.blocker ? 'queue-state-blocked' : 'queue-state-active'}`}>
                          {STATE_LABELS[c.workflow_state] ?? c.workflow_state}
                        </span>
                        <span className="queue-action">{c.next_action}</span>
                        {c.blocker && <span className="queue-blocker">Blocker: {c.blocker}</span>}
                        <Link className="queue-open" to={`/cases/${c.id}`}>Open case <span aria-hidden="true">→</span></Link>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {visible.length > 0 && (
          <div className="queue-pagination">
            <span>Showing {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, visible.length)} of {visible.length}</span>
            <label>Rows per page <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1) }}><option value="10">10</option><option value="25">25</option><option value="50">50</option></select></label>
            <button type="button" disabled={currentPage <= 1} onClick={() => setPage((p) => p - 1)}>Previous</button>
            <button type="button" disabled={currentPage >= maxPage} onClick={() => setPage((p) => p + 1)}>Next</button>
          </div>
        )}
      </section>
      </div>
    </div>
  )
}

export function CasesRoute({ showOverview = false }: { showOverview?: boolean }) {
  const { token, session } = useSession()
  const [cases, setCases] = useState<CaseSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    api.cases(token).then((c) => {
      setCases(c)
      setError(null)
    }).catch((e: Error) => setError(e.message))
  }, [token])

  return (
    <>
      {error && <p role="alert" className="error">{error}</p>}
      {cases === null && !error ? <p aria-live="polite">Loading cases…</p> : null}
      {cases && token && <CasesPage cases={cases} showOverview={showOverview} />}
      {session && <p className="dashboard-merchant">Viewing {session.merchant.name}</p>}
    </>
  )
}
