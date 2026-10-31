import type { CaseDetail, EvidenceOverview } from '../types/api'

export function CaseGuide({ detail, evidence, onOpenStaff }: { detail: CaseDetail; evidence: EvidenceOverview; onOpenStaff: () => void }) {
  const missing = evidence.checklist.find((item) => item.status === 'missing')
  const waiting = detail.workflow_state === 'WAITING_FOR_EVIDENCE'
  const review = detail.workflow_state === 'NEEDS_HUMAN_REVIEW'
  const closed = detail.workflow_state === 'CLOSED'
  const submitted = ['SUBMITTING', 'SUBMISSION_UNCERTAIN', 'MONITORING'].includes(detail.workflow_state)
  const title = closed ? 'This case is complete' : waiting ? 'Waiting for delivery proof' : review ? 'A reviewer needs to decide' : submitted ? 'Your response is being tracked' : missing ? 'One document is still missing' : 'Review the case before responding'
  const explanation = closed
    ? 'The response and outcome are recorded below.'
    : waiting && missing
      ? `${missing.assignee ?? 'Your staff member'} has been asked for ${missing.label.toLowerCase()}. The case can move forward when the right document arrives.`
      : review
        ? 'The evidence needs a human decision. Open the review section to see what needs approval.'
        : submitted
          ? 'The response has been sent or is being reconciled. Check the receipt and provider status below.'
          : missing
            ? `Please add ${missing.label.toLowerCase()} so the response can be checked.`
            : 'The required evidence is available. Check the findings and the response pack before submission.'
  const href = closed || submitted ? '#pack-h' : review ? '#journey-step-04' : missing ? '#checklist-h' : '#findings-h'
  const linkText = closed || submitted ? 'View response and receipt' : review ? 'Open reviewer decision' : missing ? 'See missing proof' : 'Review the evidence'
  return (
    <section className="case-guide" aria-labelledby="case-guide-title">
      <div className="case-guide-main"><p className="eyebrow">Your next step</p><h2 id="case-guide-title">{title}</h2><p>{explanation}</p></div>
      <div className="case-guide-actions">
        {waiting && <button type="button" onClick={onOpenStaff}>Open staff conversation</button>}
        <a href={href}>{linkText} <span aria-hidden="true">→</span></a>
      </div>
    </section>
  )
}
