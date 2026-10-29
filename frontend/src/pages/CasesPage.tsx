import type { CaseSummary } from '../types/api'

function formatDeadline(c: CaseSummary): string {
  const local = new Date(c.deadline_utc.endsWith('Z') ? c.deadline_utc : `${c.deadline_utc}Z`)
  const text = local.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })
  return `${text} IST`
}

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return 'Deadline passed'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m left`
}

const STATE_LABELS: Record<string, string> = {
  NEW: 'New',
  COLLECTING: 'Collecting evidence',
  WAITING_FOR_EVIDENCE: 'Waiting for evidence',
  NEEDS_HUMAN_REVIEW: 'Needs human review',
  READY_TO_SUBMIT: 'Ready to submit',
  SUBMITTING: 'Submitting',
  SUBMISSION_UNCERTAIN: 'Submission uncertain',
  MONITORING: 'Submission verified — outcome pending',
  CLOSED: 'Closed',
}

export function CasesPage({ cases }: { cases: CaseSummary[] }) {
  if (cases.length === 0) {
    return <p className="empty">No dispute cases for this merchant.</p>
  }
  return (
    <div className="table-wrap">
      <table className="cases">
        <caption>Dispute queue</caption>
        <thead>
          <tr>
            <th scope="col">Dispute</th>
            <th scope="col">Amount at risk</th>
            <th scope="col">Deadline</th>
            <th scope="col">Workflow</th>
            <th scope="col">Provider status</th>
            <th scope="col">Next action</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.id}>
              <td>
                <strong>{c.external_dispute_id}</strong>
                <div className="sub">Order {c.order_id}</div>
                <div className="sub">{c.reason.replaceAll('_', ' ')}</div>
              </td>
              <td className="num">{c.amount_display}</td>
              <td>
                {formatDeadline(c)}
                <div className={c.deadline_expired ? 'sub warn' : 'sub'}>{formatCountdown(c.seconds_to_deadline)}</div>
              </td>
              <td>{STATE_LABELS[c.workflow_state] ?? c.workflow_state}</td>
              <td>
                <code>{c.provider_status_raw ?? c.provider_status}</code>
              </td>
              <td>{c.next_action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
