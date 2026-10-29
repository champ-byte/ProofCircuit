import { useState } from 'react'
import { formatIst } from '../format'
import { keySteps } from '../status'
import type { AuditEventView } from '../types/api'

/** Concise case story; every step links to the stored audit event in the full log. */
export function KeySteps({ events }: { events: AuditEventView[] }) {
  const [full, setFull] = useState(false)
  const steps = keySteps(events)
  return (
    <section aria-labelledby="steps-h" className="panel">
      <div className="panel-head">
        <h2 id="steps-h">Key steps</h2>
        <button type="button" className="link" aria-expanded={full} onClick={() => setFull((f) => !f)}>
          {full ? 'Hide full audit log' : `Show full audit log (${events.length} events)`}
        </button>
      </div>
      <ol className="steps">
        {steps.map((s) => (
          <li key={s.seq}>
            <span className="step-label">{s.label}</span>{' '}
            <a href={`#event-${s.seq}`} onClick={() => setFull(true)} className="sub">
              event #{s.seq}
            </a>
            <div>{s.summary}</div>
            <div className="sub">
              {formatIst(s.created_at)} · {s.actor}
            </div>
          </li>
        ))}
      </ol>
      {full && (
        <ol className="timeline" aria-label="Full audit log">
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
