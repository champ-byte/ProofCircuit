import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { CaseHeader } from '../components/CaseHeader'
import { ChecklistPanel, EvidencePanel, FindingsPanel, type SourceRef } from '../components/Evidence'
import { ReviewerPanel } from '../components/Reviewer'
import { StatusBanner } from '../components/StatusBanner'
import { TestimonyPanel } from '../components/Testimony'
import { formatCountdown } from '../format'
import { secondsUntil, useEventFeed, useNow } from '../hooks'
import { needsReview } from '../roles'
import { useSession } from '../session'
import type { CaseDetail, CaseSummary, EvidenceOverview, InboxView } from '../types/api'

type ReviewItem = { summary: CaseSummary; questions: string[] }

/** The reviewer's home: only the cases waiting for their decision. */
export function ReviewQueue() {
  const { t } = useTranslation()
  const { token } = useSession()
  const now = useNow(1000)
  const [items, setItems] = useState<ReviewItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    let active = true
    api.cases(token)
      .then((cases) => Promise.all(
        cases
          .filter((c) => c.workflow_state !== 'CLOSED')
          .map(async (c) => ({ summary: c, questions: needsReview(c, await api.inbox(token, c.id).catch(() => null)) })),
      ))
      .then((rows) => {
        if (!active) return
        setItems(rows.filter((r): r is ReviewItem => r.questions !== null))
        setError(null)
      })
      .catch((err: Error) => active && setError(err.message))
    return () => { active = false }
  }, [token])

  return (
    <section className="review-queue" aria-labelledby="review-queue-h">
      <p className="eyebrow">{t('review.eyebrow')}</p>
      <h1 id="review-queue-h">{t('review.title')}</h1>
      <p className="sub">{t('review.intro')}</p>
      {error && <p role="alert" className="error">{error}</p>}
      {items === null && !error && <p aria-live="polite">{t('cases.loading')}</p>}
      {items?.length === 0 && <p className="queue-empty">{t('review.none')}</p>}
      <ul className="review-list">
        {items?.map(({ summary, questions }) => (
          <li key={summary.id} className="panel review-item">
            <div>
              <h2>{summary.external_dispute_id} · {summary.amount_display}</h2>
              <p className="sub">{summary.merchant_name} · {summary.order_id} · {formatCountdown(secondsUntil(summary.deadline_utc, now))}</p>
              {questions.map((q) => <p key={q}>{q}</p>)}
            </div>
            <Link className="button-primary" to={`/review/${summary.id}`}>{t('review.open')} <span aria-hidden="true">→</span></Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The reviewer's case view: their decisions first, then the evidence. No owner actions here. */
export function ReviewCase() {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const { token } = useSession()
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [evidence, setEvidence] = useState<EvidenceOverview | null>(null)
  const [inbox, setInbox] = useState<InboxView | null>(null)
  const [source, setSource] = useState<SourceRef | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const refresh = useCallback(async () => setReloadKey((k) => k + 1), [])
  const advance = useCallback(() => setReloadKey((k) => k + 1), [])
  useEventFeed(token, id, advance)

  useEffect(() => {
    if (!token) return
    Promise.all([api.caseDetail(token, id), api.evidence(token, id), api.inbox(token, id)])
      .then(([d, e, ib]) => {
        setDetail(d)
        setEvidence(e)
        setInbox(ib)
        setError(null)
      })
      .catch((err: Error) => setError(err.message))
  }, [token, id, reloadKey])

  const openSource = useCallback((s: SourceRef) => {
    setSource(s)
    window.requestAnimationFrame(() => document.getElementById('evidence-h')?.scrollIntoView({ block: 'start' }))
  }, [])

  if (error) return <p role="alert" className="error">{error} <Link to="/review">{t('review.back')}</Link></p>
  if (!detail || !evidence || !token) return <p aria-live="polite">{t('workspace.loading')}</p>
  return (
    <div className="workspace review-case">
      <div className="workspace-top"><Link to="/review">{t('review.back')}</Link></div>
      <CaseHeader detail={detail} />
      <StatusBanner detail={detail} assessment={evidence.assessment} />
      <ReviewerPanel caseId={id} token={token} detail={detail} evidence={evidence} inbox={inbox} onChanged={refresh} />
      <div className="grid">
        <ChecklistPanel evidence={evidence} onOpen={openSource} />
        <FindingsPanel evidence={evidence} onOpen={openSource} />
      </div>
      <EvidencePanel caseId={id} token={token} evidence={evidence} selected={source} onOpen={openSource} onChanged={refresh} />
      <TestimonyPanel caseId={id} token={token} version={reloadKey} />
    </div>
  )
}
