import { useTranslation } from 'react-i18next'
import type { CaseDetail, EvidenceOverview } from '../types/api'

export function CaseGuide({ detail, evidence, onOpenStaff }: { detail: CaseDetail; evidence: EvidenceOverview; onOpenStaff: () => void }) {
  const { t } = useTranslation()
  const missing = evidence.checklist.find((item) => item.status === 'missing')
  const missingLabel = missing ? t(`checklist.${missing.requirement_id}`, { defaultValue: missing.label }).toLowerCase() : ''
  const waiting = detail.workflow_state === 'WAITING_FOR_EVIDENCE'
  const review = detail.workflow_state === 'NEEDS_HUMAN_REVIEW'
  const closed = detail.workflow_state === 'CLOSED'
  const submitted = ['SUBMITTING', 'SUBMISSION_UNCERTAIN', 'MONITORING'].includes(detail.workflow_state)
  const title = t(closed ? 'guide.closed' : waiting ? 'guide.waiting' : review ? 'guide.review' : submitted ? 'guide.submitted' : missing ? 'guide.missing' : 'guide.default')
  const explanation = closed
    ? t('guide.closedText')
    : waiting && missing
      ? t('guide.waitingText', { who: missing.assignee ?? t('guide.yourStaff'), what: missingLabel })
      : review
        ? t('guide.reviewText')
        : submitted
          ? t('guide.submittedText')
          : missing
            ? t('guide.missingText', { what: missingLabel })
            : t('guide.defaultText')
  const href = closed || submitted ? '#pack-h' : review ? '#journey-step-04' : missing ? '#checklist-h' : '#findings-h'
  const linkText = t(closed || submitted ? 'guide.linkReceipt' : review ? 'guide.linkReview' : missing ? 'guide.linkMissing' : 'guide.linkEvidence')
  return (
    <section className="case-guide" aria-labelledby="case-guide-title">
      <div className="case-guide-main"><p className="eyebrow">{t('guide.eyebrow')}</p><h2 id="case-guide-title">{title}</h2><p>{explanation}</p></div>
      <div className="case-guide-actions">
        {waiting && <button type="button" onClick={onOpenStaff}>{t('guide.openStaff')}</button>}
        <a href={href}>{linkText} <span aria-hidden="true">→</span></a>
      </div>
    </section>
  )
}
