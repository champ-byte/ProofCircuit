import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { DemoControls, type TabId } from '../components/DemoControls'
import { DEMO_MID } from '../roles'
import { useSession } from '../session'
import type { CaseSummary } from '../types/api'

const TAB_IDS: TabId[] = ['inbox', 'faults', 'data', 'providers', 'resume']
const HERO_DISPUTE = 'DSP-DEMO-001'

/**
 * Presenter-only page ("Demo controls" in the footer). Not part of any role's screens: it uses a
 * separate operator session, so whoever is signed in stays signed in. Tools stay in English.
 */
export function OperatorPage() {
  const { t } = useTranslation()
  const { relogin } = useSession()
  const [params, setParams] = useSearchParams()
  const [operatorToken, setOperatorToken] = useState<string | null>(null)
  const [cases, setCases] = useState<CaseSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loginKey, setLoginKey] = useState(0)
  const [version, setVersion] = useState(0)
  const [resetDone, setResetDone] = useState(false)
  const requestedTab = params.get('tab') as TabId | null
  const tab: TabId = requestedTab && TAB_IDS.includes(requestedTab) ? requestedTab : 'inbox'

  useEffect(() => {
    let active = true
    api.createSession(DEMO_MID, 'operator')
      .then((s) => api.cases(s.token).then((list) => {
        if (!active) return
        setOperatorToken(s.token)
        setCases(list)
        setError(null)
      }))
      .catch((err: Error) => active && setError(err.message))
    return () => { active = false }
  }, [loginKey])

  const selected = cases?.find((c) => c.id === params.get('case'))
    ?? cases?.find((c) => c.external_dispute_id === HERO_DISPUTE)
    ?? cases?.[0]

  const update = useCallback((next: { case?: string; tab?: TabId }) => {
    setParams((current) => {
      const merged = new URLSearchParams(current)
      if (next.case) merged.set('case', next.case)
      if (next.tab) merged.set('tab', next.tab)
      return merged
    }, { replace: true })
  }, [setParams])
  const onChanged = useCallback(async () => setVersion((v) => v + 1), [])

  return (
    <div className="operator-page">
      <header className="operator-head">
        <p className="eyebrow">{t('operator.eyebrow')}</p>
        <h1>{t('operator.title')}</h1>
        <p className="sub">{t('operator.intro')}</p>
      </header>
      {error && <p role="alert" className="error">{error}</p>}
      {resetDone && <p role="status" className="operator-reset" data-testid="reset-done">{t('operator.resetDone')}</p>}
      {!cases && !error && <p aria-live="polite">{t('workspace.loading')}</p>}
      {cases && cases.length === 0 && <p className="queue-empty">{t('cases.empty')}</p>}
      {cases && selected && operatorToken && (
        <section className="panel" aria-labelledby="operator-case-h">
          <h2 id="operator-case-h" className="visually-hidden">{t('operator.caseLabel')}</h2>
          <label className="field operator-case">
            {t('operator.caseLabel')}
            <select value={selected.id} onChange={(e) => update({ case: e.target.value })}>
              {cases.map((c) => <option key={c.id} value={c.id}>{c.external_dispute_id} · {c.order_id}</option>)}
            </select>
          </label>
          <DemoControls
            key={selected.id}
            caseId={selected.id}
            disputeId={selected.external_dispute_id}
            mid={selected.mid}
            version={version}
            tab={tab}
            onTab={(next) => update({ tab: next })}
            onChanged={onChanged}
            onReset={(newCaseId) => {
              relogin()
              setResetDone(true)
              setCases(null)
              setLoginKey((k) => k + 1)
              update({ case: newCaseId })
            }}
          />
        </section>
      )}
      <p className="operator-links">
        <Link to="/evaluation">{t('app.footerEvaluation')}</Link>
        <Link to="/signin">{t('signin.switchUser')}</Link>
      </p>
    </div>
  )
}
