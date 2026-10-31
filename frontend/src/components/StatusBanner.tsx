import { useTranslation } from 'react-i18next'
import { statusBanner } from '../status'
import type { Assessment, CaseDetail } from '../types/api'
import { useView } from '../view'

export function StatusBanner({ detail, assessment }: { detail: CaseDetail; assessment: Assessment }) {
  useTranslation()
  const { detailed } = useView()
  const debit =
    detail.debit_amount_paise !== null
      ? `₹${(detail.debit_amount_paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
      : null
  const b = statusBanner({
    workflow_state: detail.workflow_state,
    provider_status: detail.provider_status,
    deadline_expired: detail.deadline_expired,
    evidence_ready: assessment.evidence_ready,
    blocking_contradiction: assessment.blocking_contradiction,
    debit_display: debit,
  })
  const showBlockers = detailed && !['MONITORING', 'CLOSED', 'SUBMITTING', 'SUBMISSION_UNCERTAIN'].includes(detail.workflow_state)
  return (
    <div className={`banner banner-${b.tone}`} role="status" aria-live="polite" data-testid="status-banner">
      <strong>{b.title}</strong>
      {b.detail && <div>{b.detail}</div>}
      {showBlockers && assessment.blockers.length > 0 && (
        <ul>
          {assessment.blockers.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
