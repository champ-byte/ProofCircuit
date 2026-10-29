import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { EvaluationResults } from '../types/api'

export function EvaluationPage() {
  const [res, setRes] = useState<EvaluationResults | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.evaluation().then(setRes).catch((e: Error) => setError(e.message))
  }, [])
  if (error) return <p role="alert" className="error">{error}</p>
  if (!res) return <p aria-live="polite">Loading evaluation…</p>
  return (
    <section aria-labelledby="eval-h">
      <h1 id="eval-h">Evaluation</h1>
      <div className={`banner ${res.executed === 0 ? 'banner-warn' : 'banner-info'}`} role="status">
        <strong>{res.label}</strong>
        <div>{res.note}</div>
      </div>
      <dl className="kv">
        <dt>Planned corpus</dt>
        <dd>{res.planned} synthetic cases (variants from templates, not independent merchant histories)</dd>
        <dt>Split</dt>
        <dd>
          {res.split.development} development · {res.split.held_out} held-out · first pass {res.split.first_pass} (
          {res.split.first_pass_selection})
        </dd>
        <dt>Mode</dt>
        <dd>{res.mode ?? 'Not run'}</dd>
        <dt>Metrics</dt>
        <dd>{res.metrics ? 'See export' : 'None: no case has been executed, so no results are claimed.'}</dd>
      </dl>
      <div className="table-wrap">
        <table className="cases">
          <caption>Categories</caption>
          <thead>
            <tr>
              <th scope="col">Category</th>
              <th scope="col">Planned</th>
              <th scope="col">Executed</th>
              <th scope="col">Not run</th>
            </tr>
          </thead>
          <tbody>
            {res.categories.map((c) => (
              <tr key={c.category}>
                <td>{c.category.replaceAll('_', ' ')}</td>
                <td className="num">{c.planned}</td>
                <td className="num">{c.executed}</td>
                <td className="num">{c.planned - c.executed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
