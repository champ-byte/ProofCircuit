import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import type { DemoSession, ReasoningMode, RunView } from '../types/api'

/**
 * Says plainly whether the AI assistant is working, waiting or off, and offers the two paths:
 * let it check the case, or do the steps yourself (both go through the same policy gate).
 */
export function AssistantCard({
  caseId, token, session, mode, version, closed, onChanged, onDoItMyself,
}: {
  caseId: string
  token: string
  session: DemoSession
  mode: ReasoningMode | null
  version: number
  closed: boolean
  onChanged: () => Promise<void>
  onDoItMyself: () => void
}) {
  const { t } = useTranslation()
  const [runs, setRuns] = useState<RunView[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.runs(token, caseId).then(setRuns).catch(() => setRuns([]))
  }, [token, caseId, version])

  const live = mode?.mode === 'live'
  const last = runs.filter((r) => r.mode !== 'manual').at(-1)
  const canAct = session.user.role === 'owner' || session.user.role === 'operator'
  const state = last?.status === 'running' ? 'working'
    : last?.status === 'paused_reasoner_unavailable' ? 'paused'
      : !live ? 'off'
        : last?.status === 'waiting' ? 'waiting' : 'ready'

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.startRun(token, caseId)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      await onChanged()
      setBusy(false)
    }
  }

  return (
    <section className={`assistant-card assistant-${state}`} aria-labelledby="assistant-card-title">
      <div>
        <p className="eyebrow">{t('assistant.eyebrow')}{mode ? ` · ${mode.label}` : ''}</p>
        <h2 id="assistant-card-title">{state === 'working' && <span className="assistant-pulse" aria-hidden="true" />}{t(`assistant.${state}`)}</h2>
        <p>{t(`assistant.${state}Text`)}</p>
        {last && <p className="sub">{t('assistant.lastRun', { status: t(`assistant.status.${last.status}`, { defaultValue: last.status.replaceAll('_', ' ') }) })}</p>}
        <p className="sub assistant-limits">{t('assistant.limits')}</p>
        {error && <p role="alert" className="error">{error}</p>}
      </div>
      <div className="assistant-actions-row">
        {live && canAct && !closed && (
          <button type="button" className="button-primary" disabled={busy || state === 'working'} onClick={() => void start()}>
            {t('assistant.start')}
          </button>
        )}
        <button type="button" onClick={onDoItMyself}>{t('assistant.myself')}</button>
      </div>
    </section>
  )
}
