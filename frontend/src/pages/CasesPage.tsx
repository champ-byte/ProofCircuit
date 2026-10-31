import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink } from 'react-router-dom'
import { api } from '../api/client'
import { useSession } from '../session'
import { formatCountdown, formatIst, reasonLabel, stateLabel } from '../format'
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
    ...cases.map((c) => [c.external_dispute_id, c.merchant_name, c.order_id, c.reason.replaceAll('_', ' '), c.amount_display, urgency(c, now), c.owner ?? '', formatIst(c.deadline_utc), stateLabel(c.workflow_state), c.provider_status_raw ?? c.provider_status, c.blocker ?? '', c.next_action]),
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
  const { t } = useTranslation()
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
        <p>{t('cases.workspace')}</p>
        <NavLink to="/dashboard">◫ <span>{t('app.dashboard')}</span></NavLink>
        <NavLink to="/cases">▤ <span>{t('app.disputes')}</span></NavLink>
        <div className="operations-sidebar-note">{t('cases.sidebarNote')}</div>
      </aside>
      <div className="dashboard">
      {showOverview && <section className="dashboard-hero" aria-labelledby="dashboard-title">
        <div className="dashboard-hero-copy">
          <p className="eyebrow">{t('cases.heroEyebrow')}</p>
          <h1 id="dashboard-title">{t('cases.heroTitle')}</h1>
          <p>{t('cases.heroBody')}</p>
        </div>
        <div className="dashboard-hero-guide" aria-hidden="true">
          <span>{t('cases.pathTitle')}</span>
          <strong><b>1</b> {t('cases.path1')}</strong>
          <strong><b>2</b> {t('cases.path2')}</strong>
          <strong><b>3</b> {t('cases.path3')}</strong>
        </div>
      </section>}

      {showOverview && <section className="dashboard-overview" aria-label={t('cases.overviewEyebrow')}>
        <div className="overview-card overview-card-primary">
          <span className="overview-label">{t('cases.total')}</span>
          <strong>{counts.all}</strong>
          <span>{t('cases.totalSub')}</span>
        </div>
        <div className="overview-card">
          <span className="overview-label">{t('cases.inReview')}</span>
          <strong>{counts.review}</strong>
          <span>{t('cases.inReviewSub')}</span>
        </div>
        <div className="overview-card">
          <span className="overview-label">{t('cases.waitingEvidence')}</span>
          <strong>{counts.waiting}</strong>
          <span>{t('cases.waitingEvidenceSub')}</span>
        </div>
        <div className="overview-card">
          <span className="overview-label">{t('cases.blockers')}</span>
          <strong>{counts.blocked}</strong>
          <span>{t('cases.blockersSub')}</span>
        </div>
      </section>}

      {showOverview && <WorkflowChart cases={cases} />}
      {showOverview && <section className="dashboard-flow" aria-labelledby="dashboard-flow-title">
        <div className="dashboard-flow-head">
          <div><p className="eyebrow">{t('cases.flowEyebrow')}</p><h2 id="dashboard-flow-title">{t('cases.flowTitle')}</h2><p>{t('cases.flowBody')}</p></div>
          {nextCase && <Link className="button-primary" to={`/cases/${nextCase.id}`}>{t('cases.openNext')} <span aria-hidden="true">→</span></Link>}
        </div>
        <ol className="dashboard-flow-steps">
          {(t('cases.flowSteps', { returnObjects: true }) as string[]).map((label, index) => <li key={label}><span>{String(index + 1).padStart(2, '0')}</span>{label}</li>)}
        </ol>
      </section>}

      <section className="queue-panel" aria-labelledby="queue-title">
        <div className="queue-heading">
          <div>
            <p className="eyebrow">{showOverview ? t('cases.overviewEyebrow') : t('cases.listEyebrow')}</p>
            {showOverview ? <h2 id="queue-title">{t('cases.title')}</h2> : <h1 id="queue-title">{t('cases.title')}</h1>}
            <p>{t('cases.intro')}</p>
          </div>
          <div className="queue-heading-actions">
            <label className="queue-search">
              <span>{t('cases.search')}</span>
              <input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1) }} placeholder={t('cases.searchPlaceholder')} type="search" />
            </label>
            <button type="button" className={urgentOnly ? 'queue-toolbar active' : 'queue-toolbar'} aria-pressed={urgentOnly} onClick={() => { setUrgentOnly((u) => !u); setPage(1) }}>{t('cases.urgentOnly')}</button>
            <button type="button" className="queue-toolbar" disabled={visible.length === 0} onClick={() => exportVisibleCases(visible, now)}>{t('cases.export')}</button>
          </div>
        </div>
        <div className="queue-filters" role="group" aria-label={t('cases.filterLabel')}>
          {([
            ['all', t('cases.filterAll'), counts.all],
            ['review', t('cases.filterReview'), counts.review],
            ['action', t('cases.filterProgress'), counts.action],
            ['waiting', t('cases.filterWaiting'), counts.waiting],
            ['closed', t('cases.filterDone'), counts.closed],
          ] as const).map(([key, label, count]) => (
            <button key={key} type="button" className={view === key ? 'queue-filter active' : 'queue-filter'} aria-pressed={view === key} onClick={() => { setView(key); setPage(1) }}>
              {label} <span>{count}</span>
            </button>
          ))}
        </div>
        {cases.length === 0 ? (
          <p className="queue-empty">{t('cases.empty')}</p>
        ) : visible.length === 0 ? (
          <p className="queue-empty">{t('cases.noMatch')}</p>
        ) : (
          <div className="table-wrap queue-table-wrap">
            <table className="cases queue-table">
              <caption className="visually-hidden">{t('cases.title')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('cases.colMerchant')}</th>
                  <th scope="col">{t('cases.colReason')}</th>
                  <th scope="col">{t('cases.colAmount')}</th>
                  <th scope="col">{t('cases.colUrgency')}</th>
                  <th scope="col">{t('cases.colAssigned')}</th>
                  <th scope="col"><button type="button" className="table-sort" onClick={() => setDescending((d) => !d)}>{t('cases.colDeadline')} <span aria-hidden="true">{descending ? '↓' : '↑'}</span></button></th>
                  <th scope="col">{t('cases.colStatus')}</th>
                </tr>
              </thead>
              <tbody>
                {pageCases.map((c) => {
                  const remaining = secondsUntil(c.deadline_utc, now)
                  const priority = urgency(c, now)
                  return (
                    <tr key={c.id}>
                      <td data-label={t('cases.colMerchant')}>
                        <strong>{c.merchant_name}</strong>
                        <span className="queue-meta"><Link className="queue-case-link" to={`/cases/${c.id}`}>{c.external_dispute_id}</Link> · {c.order_id}</span>
                      </td>
                      <td data-label={t('cases.colReason')}>{reasonLabel(c.reason)}</td>
                      <td data-label={t('cases.colAmount')} className="num">{c.amount_display}</td>
                      <td data-label={t('cases.colUrgency')}><span className={`urgency urgency-${priority.toLowerCase().replaceAll(' ', '-')}`}>{t(`cases.urgency.${priority}`)}</span></td>
                      <td data-label={t('cases.colAssigned')}>{c.owner ?? t('cases.unassigned')}</td>
                      <td data-label={t('cases.colDeadline')}>
                        <span className={deadlineClass(remaining)}>{formatCountdown(remaining)}</span>
                        <span className="queue-meta">{formatIst(c.deadline_utc)}</span>
                      </td>
                      <td data-label={t('cases.colStatus')}>
                        <span className={`queue-state ${isClosed(c) ? 'queue-state-closed' : c.blocker ? 'queue-state-blocked' : 'queue-state-active'}`}>
                          {stateLabel(c.workflow_state)}
                        </span>
                        <span className="queue-action">{c.next_action}</span>
                        {c.blocker && <span className="queue-blocker">{t('cases.blocker', { text: c.blocker })}</span>}
                        <Link className="queue-open" to={`/cases/${c.id}`}>{t('cases.openCase')} <span aria-hidden="true">→</span></Link>
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
            <span>{t('cases.showing', { from: (currentPage - 1) * pageSize + 1, to: Math.min(currentPage * pageSize, visible.length), total: visible.length })}</span>
            <label>{t('cases.rowsPerPage')} <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1) }}><option value="10">10</option><option value="25">25</option><option value="50">50</option></select></label>
            <button type="button" disabled={currentPage <= 1} onClick={() => setPage((p) => p - 1)}>{t('cases.previous')}</button>
            <button type="button" disabled={currentPage >= maxPage} onClick={() => setPage((p) => p + 1)}>{t('cases.next')}</button>
          </div>
        )}
      </section>
      </div>
    </div>
  )
}

export function CasesRoute({ showOverview = false }: { showOverview?: boolean }) {
  const { t } = useTranslation()
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
      {cases === null && !error ? <p aria-live="polite">{t('cases.loading')}</p> : null}
      {cases && token && <CasesPage cases={cases} showOverview={showOverview} />}
      {session && <p className="dashboard-merchant">{t('cases.viewingMerchant', { name: session.merchant.name })}</p>}
    </>
  )
}
