import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { StaffInbox } from '../components/StaffInbox'
import { useSession } from '../session'
import type { CaseSummary } from '../types/api'

/**
 * The staff member's own screen (phone-sized): every open dispute in their shop with the requests
 * addressed to them, in their language. Uses the staff session itself, so the server enforces that
 * they only act as themselves.
 */
export function StaffPage() {
  const { t } = useTranslation()
  const { session, token, users, setIdentity } = useSession()
  const [cases, setCases] = useState<CaseSummary[] | null>(null)
  const [version, setVersion] = useState(0)
  const [message, setMessage] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const isStaff = session?.user.role === 'staff'

  useEffect(() => {
    if (!token || !isStaff) return
    let active = true
    api.cases(token)
      .then((result) => {
        if (active) {
          setCases(result)
          setLoadError(null)
        }
      })
      .catch((err: Error) => {
        if (active) setLoadError(t('staff.failed', { error: err.message }))
      })
    return () => { active = false }
  }, [token, isStaff, version, t])

  const run = useCallback(async (fn: () => Promise<unknown>, ok: string) => {
    setMessage(null)
    try {
      await fn()
      setMessage(ok)
    } catch (err) {
      setMessage(t('staff.failed', { error: (err as Error).message }))
    } finally {
      setVersion((v) => v + 1)
    }
  }, [t])

  if (!session) return <p aria-live="polite">{t('staff.loading')}</p>

  if (!isStaff) {
    const staffUsers = users.filter((u) => u.mid === session.merchant.mid && u.role === 'staff')
    return (
      <section className="staff-page panel" aria-labelledby="staff-choose-h">
        <h1 id="staff-choose-h">{t('staff.chooseTitle')}</h1>
        <p className="sub">{t('staff.chooseBody')}</p>
        <div className="welcome-role-actions">
          {staffUsers.map((u) => (
            <button key={u.handle} type="button" className="button-primary" onClick={() => setIdentity(`${u.mid}/${u.handle}`)}>
              {u.display_name}
            </button>
          ))}
        </div>
      </section>
    )
  }

  const open = (cases ?? []).filter((c) => c.workflow_state !== 'CLOSED')
  return (
    <div className="staff-page" lang={session.user.locale.split('-')[0]}>
      <header className="staff-page-head">
        <p className="eyebrow">{session.user.display_name} · {session.merchant.name}</p>
        <h1>{t('staff.title')}</h1>
        <p>{t('staff.intro')}</p>
      </header>
      {message && <p role="status" className="staff-message">{message}</p>}
      {loadError && <p role="alert" className="error">{loadError}</p>}
      {cases === null && loadError ? null : cases === null ? (
        <p aria-live="polite">{t('staff.loading')}</p>
      ) : open.length === 0 ? (
        <p className="queue-empty">{t('staff.none')}</p>
      ) : (
        open.map((c) => (
          <section key={c.id} className="panel staff-case" aria-label={t('staff.case', { id: c.external_dispute_id, merchant: c.merchant_name })}>
            <h2>{t('staff.case', { id: c.external_dispute_id, merchant: c.merchant_name })}</h2>
            <p className="sub">{c.order_id} · {c.amount_display}</p>
            <StaffInbox caseId={c.id} staff={session} version={version} run={run} />
          </section>
        ))
      )}
    </div>
  )
}
