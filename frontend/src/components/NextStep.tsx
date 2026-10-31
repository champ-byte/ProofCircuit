import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { statusBanner } from '../status'
import type { CaseDetail, EvidenceOverview, PackView } from '../types/api'
import { useView } from '../view'

type Primary = { label: string; tool?: string; args?: Record<string, unknown>; anchor?: string }

/**
 * The one "what now" card on the owner's case page: where the case stands, one short sentence,
 * and one primary button. Replaces the separate status banner and guide card (the test id stays,
 * because the E2E reads the title from it).
 */
export function NextStep({
  caseId, token, detail, evidence, version, onChanged, goTo,
}: {
  caseId: string
  token: string
  detail: CaseDetail
  evidence: EvidenceOverview
  version: number
  onChanged: () => Promise<void>
  goTo: (anchor: string) => void
}) {
  const { t } = useTranslation()
  const { detailed } = useView()
  const [packs, setPacks] = useState<PackView[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.packs(token, caseId).then(setPacks).catch(() => setPacks([]))
  }, [token, caseId, version])

  const { assessment } = evidence
  const debit = detail.debit_amount_paise !== null
    ? `₹${(detail.debit_amount_paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
    : null
  const banner = statusBanner({
    workflow_state: detail.workflow_state,
    provider_status: detail.provider_status,
    deadline_expired: detail.deadline_expired,
    evidence_ready: assessment.evidence_ready,
    blocking_contradiction: assessment.blocking_contradiction,
    debit_display: debit,
  })
  const missing = evidence.checklist.find((item) => item.status === 'missing')
  const what = missing ? t(`requirements.${missing.requirement_id}`, { defaultValue: missing.requirement_id.replaceAll('_', ' ') }) : ''
  const who = missing?.assignee ?? t('guide.yourStaff')
  const currentPack = packs.some((p) => p.is_latest && !p.stale)
  const askAgain = { tool: 'request_evidence', args: { requirement_id: missing?.requirement_id ?? 'delivery_record' } }

  // One sentence and one button per situation.
  let text = banner.detail
  let primary: Primary | null = null
  switch (banner.id) {
    case 'lost': case 'lostNoDebit': case 'won': case 'closed':
      primary = { label: t('next.seeResult'), anchor: 'pack-h' }
      break
    case 'monitoring':
      primary = { label: t('next.seeReceipt'), anchor: 'pack-h' }
      break
    case 'submitting': case 'uncertain':
      primary = { label: t('next.checkStatus'), tool: 'get_submission_status' }
      break
    case 'deadline':
      primary = { label: t('next.seeHistory'), anchor: 'steps-h' }
      break
    case 'contradiction':
      primary = { label: t('next.askAgain'), ...askAgain }
      break
    case 'review':
      primary = { label: t('next.seeProblem'), anchor: 'findings-h' }
      break
    case 'waiting':
      if (missing) text = t('next.waitingText', { who, what })
      primary = { label: t('next.seeChecklist'), anchor: 'checklist-h' }
      break
    case 'ready':
      text = currentPack ? t('next.readySendText') : t('next.readyBuildText')
      primary = currentPack ? { label: t('panels.action.submit_defense'), tool: 'submit_defense' } : { label: t('panels.action.build_evidence_pack'), tool: 'build_evidence_pack' }
      break
    default:
      if (assessment.blocking_contradiction) {
        text = t('banner.contradiction.detail')
        primary = { label: t('next.askAgain'), ...askAgain }
      } else if (missing) {
        text = t('next.missingText', { what })
        primary = { label: t('panels.action.request_evidence'), ...askAgain }
      } else {
        primary = { label: t('next.seeChecklist'), anchor: 'checklist-h' }
      }
  }

  const act = async (p: Primary) => {
    if (p.anchor) return goTo(p.anchor)
    setBusy(true)
    setError(null)
    try {
      await api.action(token, caseId, p.tool!, p.args ?? {})
    } catch (err) {
      setError((err as Error).message)
    } finally {
      await onChanged()
      setBusy(false)
    }
  }

  const showBlockers = detailed && !['MONITORING', 'CLOSED', 'SUBMITTING', 'SUBMISSION_UNCERTAIN'].includes(detail.workflow_state)
  return (
    <section className={`next-step banner banner-${banner.tone}`} aria-labelledby="next-step-title">
      <div className="next-step-main" role="status" aria-live="polite" data-testid="status-banner">
        <p className="eyebrow">{t('guide.eyebrow')}</p>
        <h2 id="next-step-title">{banner.title}</h2>
        {text && <p>{text}</p>}
        {showBlockers && assessment.blockers.length > 0 && (
          <ul className="sub">{assessment.blockers.map((x) => <li key={x}>{x}</li>)}</ul>
        )}
      </div>
      {primary && (
        <div className="next-step-action">
          <button type="button" className="button-primary" disabled={busy} onClick={() => void act(primary)}>{primary.label}</button>
          {error && <p role="alert" className="error">{error}</p>}
        </div>
      )}
    </section>
  )
}
