import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { api } from '../api/client'
import type { CaseDetail, EvidenceOverview, InboxView } from '../types/api'

const CONFIRM_WORD = 'ACCEPT'

/**
 * "Accept the customer's dispute (concede)" — a human-only action, distinct from submitting
 * evidence. Step 1 records a reviewer approval (single-use, 15 min, bound to the case version);
 * step 2 requires typing CONCEDE before the backend executes it.
 */
export function ConcessionModal({
  caseId,
  token,
  amount,
  onClose,
  onDone,
}: {
  caseId: string
  token: string
  amount: string
  onClose: () => void
  onDone: () => Promise<void>
}) {
  const { t } = useTranslation()
  const [explanation, setExplanation] = useState('')
  const [approval, setApproval] = useState<{ id: string; expires: string; consequence: string } | null>(null)
  const [typed, setTyped] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const dialog = useRef<HTMLDivElement>(null)

  useEffect(() => {
    dialog.current?.querySelector<HTMLElement>('textarea, input')?.focus()
  }, [approval])

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose()
    if (e.key !== 'Tab' || !dialog.current) return
    const focusable = Array.from(
      dialog.current.querySelectorAll<HTMLElement>('button:not([disabled]), input, textarea'),
    )
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="modal-backdrop">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="concede-title"
        ref={dialog}
        onKeyDown={onKeyDown}
      >
        <h2 id="concede-title">{t('reviewer.modalTitle')}</h2>
        <p>
          <Trans i18nKey="reviewer.modalBody" values={{ amount }} components={{ b: <strong /> }} />
        </p>
        {!approval ? (
          <>
            <label className="field">
              {t('reviewer.modalExplain')}
              <textarea value={explanation} onChange={(e) => setExplanation(e.target.value)} rows={3} />
            </label>
            <div className="modal-actions">
              <button type="button" onClick={onClose}>
                {t('reviewer.cancel')}
              </button>
              <button
                type="button"
                className="danger"
                disabled={busy || explanation.trim().length < 5}
                onClick={async () => {
                  setBusy(true)
                  setError(null)
                  try {
                    const r = await api.review(token, caseId, { decision: 'approve_concession', explanation })
                    setApproval({ id: r.approval_id!, expires: r.expires_at!, consequence: r.consequence ?? '' })
                  } catch (err) {
                    setError((err as Error).message)
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                {t('reviewer.step1')}
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="sub">
              {t('reviewer.approval', { expires: approval.expires })} {approval.consequence}
            </p>
            <label className="field">
              {t('reviewer.typeConfirm', { word: CONFIRM_WORD })}
              <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
            </label>
            <div className="modal-actions">
              <button type="button" onClick={onClose}>
                {t('reviewer.cancel')}
              </button>
              <button
                type="button"
                className="danger"
                disabled={busy || typed !== CONFIRM_WORD}
                onClick={async () => {
                  setBusy(true)
                  setError(null)
                  try {
                    await api.concede(token, caseId, approval.id)
                    await onDone()
                    onClose()
                  } catch (err) {
                    setError((err as Error).message)
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                {t('reviewer.step2')}
              </button>
            </div>
          </>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}

export function ReviewerPanel({
  caseId,
  token,
  detail,
  evidence,
  inbox,
  onChanged,
}: {
  caseId: string
  token: string
  detail: CaseDetail
  evidence: EvidenceOverview
  inbox: InboxView | null
  onChanged: () => Promise<void>
}) {
  const { t } = useTranslation()
  const [concede, setConcede] = useState(false)
  const [note, setNote] = useState('')
  const [excludeDoc, setExcludeDoc] = useState('')
  const [excludeReason, setExcludeReason] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const reviews = (inbox?.tasks ?? []).filter((t) => t.kind === 'review' && t.status === 'open')
  const active = evidence.documents.filter((d) => d.active)
  const closed = detail.workflow_state === 'CLOSED'

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMessage(null)
    try {
      await fn()
      setMessage(ok)
      await onChanged()
    } catch (err) {
      setMessage(t('reviewer.notDone', { error: (err as Error).message }))
    }
  }

  return (
    <section aria-labelledby="reviewer-h" className="panel reviewer">
      <h2 id="reviewer-h">{t('reviewer.title')}</h2>
      <p className="sub">{t('reviewer.intro')}</p>
      <label className="field">
        {t('reviewer.explanation')}
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('reviewer.placeholder')} />
      </label>
      {reviews.length === 0 ? (
        <p className="sub">{t('reviewer.none')}</p>
      ) : (
        <ul className="findings">
          {reviews.map((task) => (
            <li key={task.id} className="finding finding-review finding-open">
              <strong>{task.requirement_id.replace('review:', '').replaceAll('_', ' ')}</strong>
              {task.question && <p>{task.question}</p>}
              <button
                type="button"
                disabled={note.trim().length < 5}
                onClick={() =>
                  run(
                    () => api.review(token, caseId, { decision: 'resolve_review', task_id: task.id, explanation: note }),
                    t('reviewer.resolved'),
                  )
                }
              >
                {t('reviewer.resolve')}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="reviewer-actions">
        {detail.reason === 'requires_review' && (
          <button
            type="button"
            disabled={note.trim().length < 5}
            onClick={() =>
              run(() => api.review(token, caseId, { decision: 'confirm_reason', explanation: note }), t('reviewer.reasonConfirmed'))
            }
          >
            {t('reviewer.confirmReason')}
          </button>
        )}
        <fieldset className="inline">
          <legend>{t('reviewer.exclude')}</legend>
          <select value={excludeDoc} onChange={(e) => setExcludeDoc(e.target.value)} aria-label={t('reviewer.docLabel')}>
            <option value="">{t('reviewer.chooseDoc')}</option>
            {active.map((d) => (
              <option key={d.id} value={d.id}>
                {d.original_filename}
              </option>
            ))}
          </select>
          <input
            value={excludeReason}
            onChange={(e) => setExcludeReason(e.target.value)}
            placeholder={t('reviewer.reasonPlaceholder')}
            aria-label={t('reviewer.reasonLabel')}
          />
          <button
            type="button"
            disabled={!excludeDoc || excludeReason.trim().length < 10}
            onClick={() => run(() => api.exclude(token, excludeDoc, excludeReason), t('reviewer.excludedDone'))}
          >
            {t('reviewer.excludeBtn')}
          </button>
        </fieldset>
        <button type="button" className="danger" disabled={closed} onClick={() => setConcede(true)}>
          {t('reviewer.concede')}
        </button>
      </div>
      {message && (
        <p role="status" className="sub">
          {message}
        </p>
      )}
      {concede && (
        <ConcessionModal
          caseId={caseId}
          token={token}
          amount={detail.amount_display}
          onClose={() => setConcede(false)}
          onDone={onChanged}
        />
      )}
    </section>
  )
}
