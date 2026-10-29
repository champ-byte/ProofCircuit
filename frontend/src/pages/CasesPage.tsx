import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useSession } from '../session'
import { STATE_LABELS, formatCountdown, formatIst } from '../format'
import type { CaseSummary } from '../types/api'

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
            <th scope="col">Blocker</th>
            <th scope="col">Next action</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.id}>
              <td>
                <Link to={`/cases/${c.id}`}>
                  <strong>{c.external_dispute_id}</strong>
                </Link>
                <div className="sub">Order {c.order_id}</div>
                <div className="sub">{c.reason.replaceAll('_', ' ')}</div>
              </td>
              <td className="num">{c.amount_display}</td>
              <td>
                {formatIst(c.deadline_utc)}
                <div className={c.deadline_expired ? 'sub warn' : 'sub'}>{formatCountdown(c.seconds_to_deadline)}</div>
              </td>
              <td>{STATE_LABELS[c.workflow_state] ?? c.workflow_state}</td>
              <td>
                <code>{c.provider_status_raw ?? c.provider_status}</code>
              </td>
              <td className="sub">{c.blocker ?? 'None'}</td>
              <td>{c.next_action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function CasesRoute() {
  const { token, session } = useSession()
  const [cases, setCases] = useState<CaseSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    api
      .cases(token)
      .then((c) => {
        setCases(c)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [token])

  return (
    <>
      <h1>Cases{session ? ` · ${session.merchant.name}` : ''}</h1>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {cases === null && !error ? <p aria-live="polite">Loading cases…</p> : null}
      {cases && token && <CasesPage cases={cases} />}
    </>
  )
}
