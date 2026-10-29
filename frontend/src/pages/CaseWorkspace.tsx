import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { CaseHeader } from '../components/CaseHeader'
import { DemoDrawer } from '../components/DemoDrawer'
import { ChecklistPanel, EvidencePanel, FindingsPanel, type SourceRef } from '../components/Evidence'
import { KeySteps } from '../components/KeySteps'
import { ReviewerPanel } from '../components/Reviewer'
import { StatusBanner } from '../components/StatusBanner'
import { useSession } from '../session'
import type { AuditEventView, CaseDetail, EvidenceOverview, InboxView } from '../types/api'
import { ActionsPanel, PackPanel } from './CasePanels'

export function CaseWorkspace() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { token, session, relogin } = useSession()
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [evidence, setEvidence] = useState<EvidenceOverview | null>(null)
  const [events, setEvents] = useState<AuditEventView[]>([])
  const [inbox, setInbox] = useState<InboxView | null>(null)
  const [source, setSource] = useState<SourceRef | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const refresh = useCallback(async () => setReloadKey((k) => k + 1), [])

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
    window.setTimeout(() => document.getElementById('evidence-h')?.scrollIntoView({ block: 'start' }), 0)
  }, [])

  if (error) {
    return (
      <p role="alert" className="error">
        {error} <Link to="/cases">Back to cases</Link>
      </p>
    )
  }
  if (!detail || !evidence || !token || !session) return <p aria-live="polite">Loading case…</p>

  return (
    <div className="workspace-layout">
      <div className="workspace">
        <p>
          <Link to="/cases">← All cases</Link>
        </p>
        <CaseHeader detail={detail} />
        <StatusBanner detail={detail} assessment={evidence.assessment} />
        {session.user.role === 'reviewer' && (
          <ReviewerPanel
            caseId={id}
            token={token}
            detail={detail}
            evidence={evidence}
            inbox={inbox}
            onChanged={refresh}
          />
        )}
        <div className="grid">
          <ChecklistPanel evidence={evidence} onOpen={openSource} />
          <FindingsPanel evidence={evidence} onOpen={openSource} />
        </div>
        <ActionsPanel
          caseId={id}
          token={token}
          session={session}
          version={detail.version + evidence.findings.length + reloadKey}
          onChanged={refresh}
        />
        <PackPanel caseId={id} token={token} version={reloadKey} />
        <EvidencePanel
          caseId={id}
          token={token}
          evidence={evidence}
          selected={source}
          onOpen={openSource}
          onChanged={refresh}
        />
        <KeySteps events={events} />
      </div>
      <DemoDrawer
        caseId={id}
        disputeId={detail.external_dispute_id}
        mid={detail.mid}
        version={reloadKey}
        onChanged={refresh}
        onReset={(newCaseId) => {
          relogin()
          navigate(`/cases/${newCaseId}`)
        }}
      />
    </div>
  )
}
