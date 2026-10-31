import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { formatIst } from '../format'
import type { EvaluationMetrics, EvaluationResults } from '../types/api'

const of = (n: number, d: number) => `${n} of ${d}`

function Metrics({ m }: { m: EvaluationMetrics }) {
  return (
    <dl className="kv">
      <dt>Correct behaviour</dt>
      <dd>
        {of(m.correct, m.executed)} executed cases (development {of(m.by_split.development?.correct ?? 0, m.by_split.development?.executed ?? 0)}, held-out{' '}
        {of(m.by_split.held_out?.correct ?? 0, m.by_split.held_out?.executed ?? 0)})
      </dd>
      <dt>Eligible on-time submissions</dt>
      <dd>{of(m.eligible_on_time_submissions.count, m.eligible_on_time_submissions.eligible)} cases labelled eligible</dd>
      <dt>Contradictions</dt>
      <dd>
        detected in {of(m.contradictions.detected_in_expected_cases, m.contradictions.expected_cases)} cases that contain one;{' '}
        {m.contradictions.false_positive_cases} false-positive cases
      </dd>
      <dt>Checklist complete when submitted</dt>
      <dd>{of(m.checklist_complete_in_submitted_cases.count, m.checklist_complete_in_submitted_cases.submitted)}</dd>
      <dt>Safety</dt>
      <dd>
        {m.unsafe_actions} unsafe actions · {m.duplicate_writes} duplicate provider writes
      </dd>
      <dt>Model usage</dt>
      <dd>
        {m.model_calls} model calls · {m.invalid_model_outputs} invalid outputs (repaired or escalated) · {m.policy_denials}{' '}
        policy denials{m.seconds_per_case !== null ? ` · ${m.seconds_per_case} s per case` : ''}
      </dd>
    </dl>
  )
}

export function EvaluationPage() {
  const [res, setRes] = useState<EvaluationResults | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.evaluation().then(setRes).catch((e: Error) => setError(e.message))
  }, [])
  if (error) return <p role="alert" className="error">{error}</p>
  if (!res) return <p aria-live="polite">Loading evaluation…</p>
  return (
    <section className="evaluation-page" aria-labelledby="eval-h">
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
        <dd>
          {res.mode ? res.mode.label : 'Not run'}
          {res.started_at ? ` · ${res.run_tag}, started ${formatIst(res.started_at)}` : ''}
        </dd>
      </dl>
      {res.metrics ? <Metrics m={res.metrics} /> : <p>No case has been executed, so no results are claimed.</p>}
      <div className="table-wrap">
        <table className="cases">
          <caption>Categories</caption>
          <thead>
            <tr>
              <th scope="col">Category</th>
              <th scope="col">Planned</th>
              <th scope="col">Executed</th>
              <th scope="col">Correct</th>
              <th scope="col">Not run</th>
            </tr>
          </thead>
          <tbody>
            {res.categories.map((c) => (
              <tr key={c.category}>
                <td>{c.category.replaceAll('_', ' ')}</td>
                <td className="num">{c.planned}</td>
                <td className="num">{c.executed}</td>
                <td className="num">{c.correct ?? '—'}</td>
                <td className="num">{c.planned - c.executed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {res.cases && res.cases.length > 0 && (
        <div className="table-wrap">
          <table className="cases">
            <caption>Executed cases (live model; scored after the run against separate ground truth)</caption>
            <thead>
              <tr>
                <th scope="col">Case</th>
                <th scope="col">Category · split</th>
                <th scope="col">Expected</th>
                <th scope="col">Observed</th>
                <th scope="col">Result</th>
                <th scope="col">Model calls</th>
              </tr>
            </thead>
            <tbody>
              {res.cases.map((c) => (
                <tr key={c.corpus_case}>
                  <td>{c.corpus_case}</td>
                  <td>
                    {c.category.replaceAll('_', ' ')} · {c.split.replace('_', '-')}
                  </td>
                  <td>{c.acceptable_outcomes.join(' or ')}</td>
                  <td>
                    {c.outcome}
                    {c.contradictions_detected.length > 0 && <div className="sub">{c.contradictions_detected.join(', ')}</div>}
                  </td>
                  <td>
                    <strong>{c.correct ? 'Correct' : 'Incorrect'}</strong>
                    {c.unsafe.length > 0 && <div className="sub">{c.unsafe.join('; ')}</div>}
                    {c.missing_rules.length > 0 && <div className="sub">missed {c.missing_rules.join(', ')}</div>}
                  </td>
                  <td className="num">{c.model_calls}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {res.superseded_attempts && res.superseded_attempts.length > 0 && (
        <section aria-labelledby="superseded-h">
          <h2 id="superseded-h">Superseded attempts</h2>
          <p className="sub">First attempts replaced by a re-run after fixing the bug they exposed. Kept for the record.</p>
          <ul>
            {res.superseded_attempts.map((a) => (
              <li key={`${a.corpus_case}-${a.run_tag}`}>
                <strong>{a.corpus_case}</strong> (run {a.run_tag}): {a.outcome}, {a.correct ? 'correct' : 'incorrect'}. {a.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
      {res.not_run_cases && res.not_run_cases.length > 0 && (
        <p className="sub">
          Not run in this export: {res.not_run_cases.map((c) => `${c.corpus_case} (${c.reason})`).join('; ')}
        </p>
      )}
    </section>
  )
}
