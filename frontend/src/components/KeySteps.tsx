import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatIst } from '../format'
import { keySteps } from '../status'
import type { AuditEventView } from '../types/api'

/** Concise case story; every step links to the stored audit event in the full log. */
export function KeySteps({ events }: { events: AuditEventView[] }) {
  const { t } = useTranslation()
  const [full, setFull] = useState(false)
  const steps = keySteps(events)
  return (
    <section aria-labelledby="steps-h" className="panel">
      <div className="panel-head">
        <h2 id="steps-h">{t('steps.title')}</h2>
        <button type="button" className="link" aria-expanded={full} onClick={() => setFull((f) => !f)}>
          {full ? t('steps.hideLog') : t('steps.showLog', { count: events.length })}
        </button>
      </div>
      <ol className="steps">
        {steps.map((s) => (
          <li key={s.seq}>
            <span className="step-label">{s.label}</span>{' '}
            <a href={`#event-${s.seq}`} onClick={() => setFull(true)} className="sub">
              {t('steps.event', { seq: s.seq })}
            </a>
            <div>{s.summary}</div>
            <div className="sub">
              {formatIst(s.created_at)} · {s.actor}
            </div>
          </li>
        ))}
      </ol>
      {full && (
        <ol className="timeline" aria-label={t('steps.fullLog')}>
          {events.map((e) => (
            <li key={e.seq} id={`event-${e.seq}`}>
              <span className="sub">
                #{e.seq} · {formatIst(e.created_at)} · {e.actor_type}
              </span>{' '}
              <code>{e.event_type}</code> {e.summary}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
