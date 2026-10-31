import { useState } from 'react'
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
      setMessage(`${action.label} requested${runId ? ` · run ${runId}` : ''}. The case will refresh from recorded events.`)
      await onChanged()
    } catch (error) {
      setMessage(`${action.label} was not completed: ${(error as Error).message}`)
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
      number: '01', title: 'Check the case',
      description: 'Ask the case assistant to check the record and suggest the next safe action. You can also use the controls below yourself.',
      types: ['agent.run_started'],
      actions: [{ label: 'Check case with assistant', run: () => api.startRun(token, caseId), disabled: !canAct || closed }],
      links: [{ label: 'See agent runs', href: '#actions-h' }],
      demo: { label: 'View assistant setup', tab: 'providers' },
    },
    {
      number: '02', title: 'Collect missing evidence',
      description: missing ? `The checklist still needs ${missing.label.toLowerCase()}.` : 'Inspect the checklist and ask staff for a document when a required item is missing.',
      types: ['evidence.requested', 'staff.replied'],
      actions: [{ label: 'Request missing proof', run: () => api.action(token, caseId, 'request_evidence', { requirement_id: missing?.requirement_id ?? 'delivery_record' }), disabled: !canAct || closed || !missing, hint: !missing ? 'No missing checklist item' : undefined }],
      links: [{ label: 'Upload / inspect evidence', href: '#evidence-h' }, { label: 'View checklist', href: '#checklist-h' }],
      demo: { label: 'Open staff inbox', tab: 'inbox' },
    },
    {
      number: '03', title: 'Validate and resolve mismatches',
      description: evidence.assessment.blocking_contradiction ? 'A blocking contradiction needs corrected proof or a reviewer decision.' : 'Check the order, invoice, and delivery record against each other.',
      types: ['validation.finding_opened', 'evidence.superseded'],
      actions: [{ label: 'Re-run validation', run: () => api.action(token, caseId, 'validate_evidence'), disabled: !canAct || closed }],
      links: [{ label: 'View findings', href: '#findings-h' }, { label: 'Compare sources', href: '#evidence-h' }],
    },
    {
      number: '04', title: 'Ask for human review',
      description: 'Ask a person to decide when documents disagree or the next step is uncertain.',
      types: ['review.requested'],
      actions: [{ label: 'Request review', run: () => api.action(token, caseId, 'request_human_review', { reason: 'owner_request', question: 'Please review the evidence and decide the next safe step.' }), disabled: !canAct || closed }],
      links: [{ label: session.user.role === 'reviewer' ? 'Reviewer decisions' : 'Switch to reviewer above', href: session.user.role === 'reviewer' ? '#reviewer-h' : '#demo-identity' }, { label: 'View findings', href: '#findings-h' }],
    },
    {
      number: '05', title: 'Build a source-linked pack',
      description: 'Freeze the validated documents and citations into a versioned evidence pack.',
      types: ['pack.built'],
      actions: [{ label: 'Build evidence pack', run: () => api.action(token, caseId, 'build_evidence_pack'), disabled: !canAct || closed || !packReady, hint: !packReady ? 'Complete the evidence checks first' : undefined }],
      links: [{ label: 'Inspect pack', href: '#pack-h' }],
    },
    {
      number: '06', title: 'Submit the defense',
      description: 'Send the reviewed response. The app checks the pack, your role, and the deadline first.',
      types: ['submission.requested'],
      actions: [{ label: 'Submit defense', run: () => api.action(token, caseId, 'submit_defense'), disabled: !canAct || closed || !packReady || !hasPack, hint: !packReady ? 'Complete evidence checks first' : !hasPack ? 'Build an evidence pack first' : undefined }],
      links: [{ label: 'See submission', href: '#pack-h' }],
    },
    {
      number: '07', title: 'Verify the receipt and outcome',
      description: 'Check that the response arrived. The final dispute decision may come later.',
      types: ['submission.verified'],
      actions: [{ label: 'Check provider status', run: () => api.action(token, caseId, 'get_submission_status'), disabled: !canAct || (!hasSubmitted && !closed), hint: !hasSubmitted && !closed ? 'Submit a response first' : undefined }],
      links: [{ label: 'View audit timeline', href: '#steps-h' }, { label: 'See receipt', href: '#pack-h' }],
      demo: { label: 'Simulate outcome', tab: 'faults' },
    },
  ]

  const recordedSteps = steps.filter((step) => latest(events, step.types)).length

  return (
    <section className="journey-panel" aria-labelledby="journey-title">
      <div className="journey-heading">
        <div><p className="eyebrow">Your case, step by step</p><h2 id="journey-title">What happens next?</h2><p>These steps follow recorded case activity. Open any step to see its source and available action.</p></div>
        <span className="journey-mode">{session.user.role} view</span>
      </div>
      {!canAct && <p className="journey-role-note">Agent and manual tool buttons require the owner or operator identity. Use the demo identity selector above to switch roles.</p>}
      <nav className="journey-map" aria-label="Case process map">
        <p>{recordedSteps} of {steps.length} stages have related activity. Human review may be skipped when it is not needed.</p>
        <ol>{steps.map((step) => <li key={step.number} className={latest(events, step.types) ? 'visited' : ''}><a href={`#journey-step-${step.number}`}><span>{step.number}</span>{step.title}</a></li>)}</ol>
      </nav>
      <div className="journey-grid">
        {steps.map((step) => {
          const recorded = latest(events, step.types)
          return (
            <article className="journey-step" key={step.number} id={`journey-step-${step.number}`}>
              <div className="journey-step-top"><span className="journey-number">{step.number}</span><span className={recorded ? 'journey-record recorded' : 'journey-record'}>{recorded ? 'Activity recorded' : 'Waiting for this step'}</span></div>
              <h3>{step.title}</h3>
              <p>{step.description}</p>
              {recorded && <p className="journey-event"><strong>What happened:</strong> {recorded.summary} <a href="#steps-h">Open timeline (event #{recorded.seq})</a><span>{formatIst(recorded.created_at)}</span></p>}
              <div className="journey-step-actions">
                {step.actions.map((action) => <span className="journey-action" key={action.label}><button type="button" disabled={busy || action.disabled} onClick={() => void execute(action)}>{action.label}</button>{action.hint && <small>{action.hint}</small>}</span>)}
                {step.demo && <button key={step.demo.label} type="button" className="journey-secondary" onClick={() => openDemo(step.demo!.tab)}>{step.demo.label}</button>}
              </div>
              <div className="journey-links">{step.links.map((link) => <a key={link.label} href={link.href}>{link.label} <span aria-hidden="true">↗</span></a>)}</div>
            </article>
          )
        })}
      </div>
      <div className="journey-branches">
        <h3>When the case takes another path</h3>
        <div>
          <section><strong>Staff reply, voice note or reminder</strong><p>Follow the request in the staff inbox. Testimony is labelled separately from documentary proof.</p><button type="button" onClick={() => openDemo('inbox')}>Open staff tools</button></section>
          <section><strong>Provider rejection or uncertain response</strong><p>Inspect the simulator event, correct the document if needed, then reconcile the provider status.</p><button type="button" onClick={() => openDemo('faults')}>Open simulator controls</button></section>
          <section><strong>Reviewer decision or concession</strong><p>A reviewer records the reason and confirms any concession through the protected two-step flow.</p><a href={session.user.role === 'reviewer' ? '#reviewer-h' : '#demo-identity'}>{session.user.role === 'reviewer' ? 'Open reviewer decisions' : 'Switch to reviewer identity'} →</a></section>
        </div>
      </div>
      {message && <p role="status" className="journey-message">{message}</p>}
    </section>
  )
}
