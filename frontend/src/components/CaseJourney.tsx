import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { formatIst } from '../format'
import type { AuditEventView, CaseDetail, DemoSession, EvidenceOverview } from '../types/api'

type DemoTab = 'inbox' | 'faults' | 'providers' | 'resume'
type JourneyAction = { label: string; run: () => Promise<unknown>; disabled?: boolean; hint?: string }

function latest(events: AuditEventView[], types: string[]) {
  return [...events].reverse().find((event) => types.includes(event.event_type))
}

export function CaseJourney({
  caseId, token, session, detail, evidence, events, onChanged, openDemo,
}: {
  caseId: string
  token: string
  session: DemoSession
  detail: CaseDetail
  evidence: EvidenceOverview
  events: AuditEventView[]
  onChanged: () => Promise<void>
  openDemo: (tab: DemoTab) => void
}) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const canAct = session.user.role === 'owner' || session.user.role === 'operator'
  const closed = detail.workflow_state === 'CLOSED'
  const missing = evidence.checklist.find((item) => item.status === 'missing')
  const packReady = evidence.assessment.evidence_ready && !evidence.assessment.blocking_contradiction
  const hasPack = events.some((event) => event.event_type === 'pack.built')
  const hasSubmitted = events.some((event) => event.event_type === 'submission.requested')

  const execute = async (action: JourneyAction) => {
    setBusy(true)
    setMessage(null)
    try {
      const result = await action.run()
      const runId = result && typeof result === 'object' && 'run_id' in result ? String(result.run_id) : null
      setMessage(runId ? t('journey.requestedRun', { action: action.label, run: runId }) : t('journey.requested', { action: action.label }))
      await onChanged()
    } catch (error) {
      setMessage(t('journey.failed', { action: action.label, error: (error as Error).message }))
    } finally {
      setBusy(false)
    }
  }

  const steps: {
    number: string
    title: string
    description: string
    types: string[]
    actions: JourneyAction[]
    links: { label: string; href: string }[]
    demo?: { label: string; tab: DemoTab }
  }[] = [
    {
      number: '01', title: t('journey.s1Title'),
      description: t('journey.s1Text'),
      types: ['agent.run_started'],
      actions: [{ label: t('journey.s1Action'), run: () => api.startRun(token, caseId), disabled: !canAct || closed }],
      links: [{ label: t('journey.s1Link'), href: '#actions-h' }],
      demo: { label: t('journey.s1Demo'), tab: 'providers' },
    },
    {
      number: '02', title: t('journey.s2Title'),
      description: missing ? t('journey.s2TextMissing', { what: t(`checklist.${missing.requirement_id}`, { defaultValue: missing.label }).toLowerCase() }) : t('journey.s2Text'),
      types: ['evidence.requested', 'staff.replied'],
      actions: [{ label: t('journey.s2Action'), run: () => api.action(token, caseId, 'request_evidence', { requirement_id: missing?.requirement_id ?? 'delivery_record' }), disabled: !canAct || closed || !missing, hint: !missing ? t('journey.s2Hint') : undefined }],
      links: [{ label: t('journey.s2Link1'), href: '#evidence-h' }, { label: t('journey.s2Link2'), href: '#checklist-h' }],
      demo: { label: t('journey.s2Demo'), tab: 'inbox' },
    },
    {
      number: '03', title: t('journey.s3Title'),
      description: evidence.assessment.blocking_contradiction ? t('journey.s3TextBlocked') : t('journey.s3Text'),
      types: ['validation.finding_opened', 'evidence.superseded'],
      actions: [{ label: t('journey.s3Action'), run: () => api.action(token, caseId, 'validate_evidence'), disabled: !canAct || closed }],
      links: [{ label: t('journey.s3Link1'), href: '#findings-h' }, { label: t('journey.s3Link2'), href: '#evidence-h' }],
    },
    {
      number: '04', title: t('journey.s4Title'),
      description: t('journey.s4Text'),
      types: ['review.requested'],
      actions: [{ label: t('journey.s4Action'), run: () => api.action(token, caseId, 'request_human_review', { reason: 'owner_request', question: 'Please review the evidence and decide the next safe step.' }), disabled: !canAct || closed }],
      links: [{ label: t('journey.s4LinkSwitch'), href: '/signin' }, { label: t('journey.s3Link1'), href: '#findings-h' }],
    },
    {
      number: '05', title: t('journey.s5Title'),
      description: t('journey.s5Text'),
      types: ['pack.built'],
      actions: [{ label: t('journey.s5Action'), run: () => api.action(token, caseId, 'build_evidence_pack'), disabled: !canAct || closed || !packReady, hint: !packReady ? t('journey.s5Hint') : undefined }],
      links: [{ label: t('journey.s5Link'), href: '#pack-h' }],
    },
    {
      number: '06', title: t('journey.s6Title'),
      description: t('journey.s6Text'),
      types: ['submission.requested'],
      actions: [{ label: t('journey.s6Action'), run: () => api.action(token, caseId, 'submit_defense'), disabled: !canAct || closed || !packReady || !hasPack, hint: !packReady ? t('journey.s6HintChecks') : !hasPack ? t('journey.s6HintPack') : undefined }],
      links: [{ label: t('journey.s6Link'), href: '#pack-h' }],
    },
    {
      number: '07', title: t('journey.s7Title'),
      description: t('journey.s7Text'),
      types: ['submission.verified'],
      actions: [{ label: t('journey.s7Action'), run: () => api.action(token, caseId, 'get_submission_status'), disabled: !canAct || (!hasSubmitted && !closed), hint: !hasSubmitted && !closed ? t('journey.s7Hint') : undefined }],
      links: [{ label: t('journey.s7Link1'), href: '#steps-h' }, { label: t('journey.s7Link2'), href: '#pack-h' }],
      demo: { label: t('journey.s7Demo'), tab: 'faults' },
    },
  ]

  const recordedSteps = steps.filter((step) => latest(events, step.types)).length

  return (
    <section className="journey-panel" aria-labelledby="journey-title">
      <div className="journey-heading">
        <div><p className="eyebrow">{t('journey.eyebrow')}</p><h2 id="journey-title">{t('journey.title')}</h2><p>{t('journey.intro')}</p></div>
        <span className="journey-mode">{t('journey.roleView', { role: t(`roles.${session.user.role}`, { defaultValue: session.user.role }) })}</span>
      </div>
      {!canAct && <p className="journey-role-note">{t('journey.roleNote')}</p>}
      <nav className="journey-map" aria-label={t('journey.mapLabel')}>
        <p>{t('journey.progress', { done: recordedSteps, total: steps.length })}</p>
        <ol>{steps.map((step) => <li key={step.number} className={latest(events, step.types) ? 'visited' : ''}><a href={`#journey-step-${step.number}`}><span>{step.number}</span>{step.title}</a></li>)}</ol>
      </nav>
      <div className="journey-grid">
        {steps.map((step) => {
          const recorded = latest(events, step.types)
          return (
            <article className="journey-step" key={step.number} id={`journey-step-${step.number}`}>
              <div className="journey-step-top"><span className="journey-number">{step.number}</span><span className={recorded ? 'journey-record recorded' : 'journey-record'}>{recorded ? t('journey.recorded') : t('journey.waiting')}</span></div>
              <h3>{step.title}</h3>
              <p>{step.description}</p>
              {recorded && <p className="journey-event"><strong>{t('journey.happened')}</strong> {recorded.summary} <a href="#steps-h">{t('journey.openTimeline', { seq: recorded.seq })}</a><span>{formatIst(recorded.created_at)}</span></p>}
              <div className="journey-step-actions">
                {step.actions.map((action) => <span className="journey-action" key={action.label}><button type="button" disabled={busy || action.disabled} onClick={() => void execute(action)}>{action.label}</button>{action.hint && <small>{action.hint}</small>}</span>)}
                {step.demo && <button key={step.demo.label} type="button" className="journey-secondary" onClick={() => openDemo(step.demo!.tab)}>{step.demo.label}</button>}
              </div>
              <div className="journey-links">{step.links.map((link) => link.href.startsWith('/')
                ? <Link key={link.label} to={link.href}>{link.label} <span aria-hidden="true">↗</span></Link>
                : <a key={link.label} href={link.href}>{link.label} <span aria-hidden="true">↗</span></a>)}</div>
            </article>
          )
        })}
      </div>
      <div className="journey-branches">
        <h3>{t('journey.branches')}</h3>
        <div>
          <section><strong>{t('journey.b1Title')}</strong><p>{t('journey.b1Text')}</p><button type="button" onClick={() => openDemo('inbox')}>{t('journey.b1Action')}</button></section>
          <section><strong>{t('journey.b2Title')}</strong><p>{t('journey.b2Text')}</p><button type="button" onClick={() => openDemo('faults')}>{t('journey.b2Action')}</button></section>
          <section><strong>{t('journey.b3Title')}</strong><p>{t('journey.b3Text')}</p><Link to="/signin">{t('journey.b3Switch')} →</Link></section>
        </div>
      </div>
      {message && <p role="status" className="journey-message">{message}</p>}
    </section>
  )
}
