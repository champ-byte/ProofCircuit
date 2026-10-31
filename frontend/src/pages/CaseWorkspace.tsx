import { type KeyboardEvent, type MouseEvent, useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { AssistantCard } from '../components/Assistant'
import { CaseHeader } from '../components/CaseHeader'
import { CaseGuide } from '../components/CaseGuide'
import { CaseJourney } from '../components/CaseJourney'
import { CaseProgress } from '../components/CaseProgress'
import { DemoDrawer } from '../components/DemoDrawer'
import type { TabId } from '../components/DemoDrawer'
import { ChecklistPanel, EvidencePanel, FindingsPanel, type SourceRef } from '../components/Evidence'
import { KeySteps } from '../components/KeySteps'
import { ReviewerPanel } from '../components/Reviewer'
import { StatusBadges } from '../components/StatusBadges'
import { StatusBanner } from '../components/StatusBanner'
import { TestimonyPanel } from '../components/Testimony'
import { useSession } from '../session'
import type { AuditEventView, CaseDetail, EvidenceOverview, InboxView, ReasoningMode } from '../types/api'
import { ActionsPanel, PackPanel } from './CasePanels'

type CaseTab = 'next' | 'proof' | 'respond' | 'history'
const CASE_TABS: CaseTab[] = ['next', 'proof', 'respond', 'history']

/** Which tab holds an in-page anchor, so existing "#…" links keep working across tabs. */
function tabFor(anchor: string): CaseTab | null {
  if (['case-guide-title', 'checklist-h', 'findings-h', 'reviewer-h', 'assistant-card-title'].includes(anchor)) return 'next'
  if (['evidence-h', 'testimony-h'].includes(anchor)) return 'proof'
  if (['actions-h', 'pack-h', 'do-it-yourself'].includes(anchor)) return 'respond'
  if (anchor === 'steps-h' || anchor === 'journey-title' || anchor.startsWith('journey-step-') || anchor.startsWith('event-')) return 'history'
  return null
}

function CaseTabs({ active, onChange }: { active: CaseTab; onChange: (tab: CaseTab) => void }) {
  const { t } = useTranslation()
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const onKeyDown = (e: KeyboardEvent, index: number) => {
    let next = index
    if (e.key === 'ArrowRight') next = (index + 1) % CASE_TABS.length
    else if (e.key === 'ArrowLeft') next = (index - 1 + CASE_TABS.length) % CASE_TABS.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = CASE_TABS.length - 1
    else return
    e.preventDefault()
    onChange(CASE_TABS[next])
    refs.current[next]?.focus()
  }
  return (
    <div role="tablist" aria-label={t('tabs.label')} className="case-tabs">
      {CASE_TABS.map((tab, i) => (
        <button
          key={tab}
          ref={(el) => void (refs.current[i] = el)}
          role="tab"
          id={`case-tab-${tab}`}
          aria-selected={active === tab}
          aria-controls="case-tabpanel"
          tabIndex={active === tab ? 0 : -1}
          onClick={() => onChange(tab)}
          onKeyDown={(e) => onKeyDown(e, i)}
        >
          {t(`tabs.${tab}`)}
        </button>
      ))}
    </div>
  )
}

export function CaseWorkspace() {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { token, session, relogin } = useSession()
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [evidence, setEvidence] = useState<EvidenceOverview | null>(null)
  const [events, setEvents] = useState<AuditEventView[]>([])
  const [inbox, setInbox] = useState<InboxView | null>(null)
  const [mode, setMode] = useState<ReasoningMode | null>(null)
  const [source, setSource] = useState<SourceRef | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [tab, setTab] = useState<CaseTab>('next')
  const [requestedTab, setRequestedTab] = useState<{ tab: TabId; nonce: number } | null>(null)
  const [pendingAnchor, setPendingAnchor] = useState<string | null>(null)
  const refresh = useCallback(async () => setReloadKey((k) => k + 1), [])
  const openDemo = useCallback((demoTab: TabId) => {
    setRequestedTab((current) => ({ tab: demoTab, nonce: (current?.nonce ?? 0) + 1 }))
    window.requestAnimationFrame(() => document.getElementById('demo-drawer')?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
  }, [])

  /** Switch to the tab that holds an anchor, then scroll to it once it is rendered. */
  const goTo = useCallback((anchor: string) => {
    const target = tabFor(anchor)
    if (target) setTab(target)
    setPendingAnchor(anchor)
  }, [])

  useEffect(() => {
    if (!pendingAnchor) return
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(pendingAnchor)?.scrollIntoView({ block: 'start' })
      setPendingAnchor(null)
    })
    return () => window.cancelAnimationFrame(frame)
  }, [tab, pendingAnchor])

  useEffect(() => {
    api.providers().then((r) => setMode(r.reasoning_mode)).catch(() => setMode(null))
  }, [reloadKey])

  useEffect(() => {
    if (!token) return
    Promise.all([api.caseDetail(token, id), api.evidence(token, id), api.events(token, id, 0), api.inbox(token, id)])
      .then(([d, e, ev, ib]) => {
        setDetail(d)
        setEvidence(e)
        setEvents(ev.events)
        setInbox(ib)
        setError(null)
      })
      .catch((err: Error) => setError(err.message))
  }, [token, id, reloadKey])

  // Background work (runner, agent, simulator webhooks) finishes after HTTP responses return.
  // Follow the persisted event feed and refresh when it advances; the backend never polls.
  useEffect(() => {
    if (!token) return
    let cursor = -1
    let stopped = false
    const tick = async () => {
      try {
        const res = await api.events(token, id, Math.max(cursor, 0))
        if (cursor === -1) cursor = res.cursor
        else if (res.cursor !== cursor) {
          cursor = res.cursor
          setReloadKey((k) => k + 1)
        }
      } catch {
        /* transient; next tick retries */
      }
      if (!stopped) timer = window.setTimeout(tick, 1500)
    }
    let timer = window.setTimeout(tick, 0)
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [token, id])

  const openSource = useCallback((s: SourceRef) => {
    setSource(s)
    goTo('evidence-h')
  }, [goTo])

  // In-page links ("#pack-h", "#journey-step-04", …) live in different tabs now.
  const onClickCapture = (e: MouseEvent) => {
    const link = (e.target as HTMLElement).closest('a[href^="#"]')
    const anchor = link?.getAttribute('href')?.slice(1)
    if (!anchor || !tabFor(anchor)) return
    e.preventDefault()
    goTo(anchor)
  }

  if (error) {
    return (
      <p role="alert" className="error">
        {error} <Link to="/cases">{t('workspace.backToCases')}</Link>
      </p>
    )
  }
  if (!detail || !evidence || !token || !session) return <p aria-live="polite">{t('workspace.loading')}</p>
  const closed = detail.workflow_state === 'CLOSED'

  return (
    <div className="workspace-layout">
      <div className="workspace" onClickCapture={onClickCapture}>
        <div className="workspace-top">
          <Link to="/cases">{t('workspace.back')}</Link>
          <StatusBadges mode={mode} />
        </div>
        <CaseHeader detail={detail} />
        <CaseProgress workflowState={detail.workflow_state} />
        <StatusBanner detail={detail} assessment={evidence.assessment} />
        <CaseTabs active={tab} onChange={setTab} />
        <div role="tabpanel" id="case-tabpanel" aria-labelledby={`case-tab-${tab}`} className="case-tabpanel">
          {tab === 'next' && (
            <>
              <CaseGuide detail={detail} evidence={evidence} onOpenStaff={() => openDemo('inbox')} />
              <AssistantCard
                caseId={id}
                token={token}
                session={session}
                mode={mode}
                version={reloadKey}
                closed={closed}
                onChanged={refresh}
                onDoItMyself={() => goTo('do-it-yourself')}
              />
              {session.user.role === 'reviewer' && (
                <ReviewerPanel caseId={id} token={token} detail={detail} evidence={evidence} inbox={inbox} onChanged={refresh} />
              )}
              <div className="grid">
                <ChecklistPanel evidence={evidence} onOpen={openSource} />
                <FindingsPanel evidence={evidence} onOpen={openSource} />
              </div>
            </>
          )}
          {tab === 'proof' && (
            <>
              <EvidencePanel caseId={id} token={token} evidence={evidence} selected={source} onOpen={openSource} onChanged={refresh} />
              <TestimonyPanel caseId={id} token={token} version={reloadKey} />
            </>
          )}
          {tab === 'respond' && (
            <>
              <ActionsPanel
                caseId={id}
                token={token}
                session={session}
                version={detail.version + evidence.findings.length + reloadKey}
                onChanged={refresh}
                events={events}
              />
              <PackPanel caseId={id} token={token} version={reloadKey} />
            </>
          )}
          {tab === 'history' && (
            <>
              <CaseJourney caseId={id} token={token} session={session} detail={detail} evidence={evidence} events={events} onChanged={refresh} openDemo={openDemo} />
              <KeySteps events={events} />
            </>
          )}
        </div>
      </div>
      <DemoDrawer
        key={requestedTab?.nonce ?? 0}
        caseId={id}
        disputeId={detail.external_dispute_id}
        mid={detail.mid}
        version={reloadKey}
        requestedTab={requestedTab}
        onChanged={refresh}
        onReset={(newCaseId) => {
          relogin()
          navigate(`/cases/${newCaseId}`)
        }}
      />
    </div>
  )
}
