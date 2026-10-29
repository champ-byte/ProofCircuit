import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { formatIst } from '../format'
import type { DemoSession, InboxView, PackView, RunView, SubmissionView } from '../types/api'

const ACTIONS: { tool: string; label: string; args?: Record<string, unknown> }[] = [
  { tool: 'request_evidence', label: 'Request delivery proof from staff', args: { requirement_id: 'delivery_record' } },
  { tool: 'validate_evidence', label: 'Re-run validation' },
  { tool: 'build_evidence_pack', label: 'Build evidence pack' },
  { tool: 'submit_defense', label: 'Submit defense (simulator)' },
  { tool: 'get_submission_status', label: 'Check provider status' },
]

/** Manual operation through the same tools and policy gate the agent will use (M3). */
export function ActionsPanel({
  caseId,
  token,
  session,
  version,
  onChanged,
}: {
  caseId: string
  token: string
  session: DemoSession
  version: number
  onChanged: () => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [runs, setRuns] = useState<RunView[]>([])
  const canAct = session.user.role === 'owner' || session.user.role === 'operator'

  useEffect(() => {
    api.runs(token, caseId).then(setRuns).catch(() => setRuns([]))
  }, [token, caseId, version])

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
    } finally {
      await onChanged()
      setRuns(await api.runs(token, caseId))
      setBusy(false)
    }
  }
  const last = runs.at(-1)?.tool_calls.at(-1)
  const agentRuns = runs.filter((r) => r.mode !== 'manual').slice(-5).reverse()
  const paused = agentRuns.find((r) => r.status === 'paused_reasoner_unavailable')
  const [smokeMsg, setSmokeMsg] = useState<string | null>(null)

  return (
    <section aria-labelledby="actions-h" className="panel">
      <h2 id="actions-h">Agent and actions</h2>
      <p className="sub">
        The agent runs automatically after each event once a reasoner passes its smoke test. Manual buttons call the same
        backend tools; the policy gate decides either way.
      </p>
      {paused && agentRuns[0]?.id === paused.id && (
        <div className="banner banner-warn" role="status">
          Reasoner unavailable: {paused.error}. Manual operation still works.
        </div>
      )}
      {canAct ? (
        <div className="fixture-buttons">
          <button type="button" disabled={busy} onClick={() => run(() => api.startRun(token, caseId))}>
            Run agent / resume
          </button>
          {session.user.role === 'operator' && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => api.startRun(token, caseId, 'fixture_replay'))}
              >
                Run fixture replay (not AI)
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    const r = await api.smoke(token)
                    setSmokeMsg(r.ok ? `Smoke test passed: ${r.model_returned} in ${r.latency_ms} ms` : `Smoke test failed: ${r.detail}`)
                  })
                }
              >
                Run reasoner smoke test
              </button>
            </>
          )}
          {ACTIONS.map((a) => (
            <button key={a.tool} type="button" disabled={busy} onClick={() => run(() => api.action(token, caseId, a.tool, a.args))}>
              {a.label}
            </button>
          ))}
        </div>
      ) : (
        <p className="sub">Switch to the owner or operator identity to run actions.</p>
      )}
      {smokeMsg && (
        <p role="status" className="sub">
          {smokeMsg}
        </p>
      )}
      {agentRuns.length > 0 && (
        <div className="agent-runs">
          <h3>Agent runs</h3>
          <ol className="timeline">
            {agentRuns.map((r) => (
              <li key={r.id}>
                <span className="tag">{r.mode === 'fixture_replay' ? 'Fixture replay (not AI)' : 'Live model'}</span>{' '}
                {r.provider}
                {r.model ? ` — ${r.model}` : ''} · {r.status.replaceAll('_', ' ')} · {formatIst(r.started_at)}
                <ul>
                  {r.tool_calls.map((c) => (
                    <li key={c.step} className={`tool-${c.status}`}>
                      <strong>
                        {c.step}. {c.tool}
                      </strong>{' '}
                      → {c.status}
                      {c.rationale && <div className="sub">“{c.rationale}”</div>}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </div>
      )}
      {last && (
        <div className={`tool-result tool-${last.status}`} role="status">
          <strong>
            {last.tool} → {last.status}
          </strong>
          <pre>{JSON.stringify(last.result, null, 2)}</pre>
        </div>
      )}
    </section>
  )
}

export function PackPanel({ caseId, token, version }: { caseId: string; token: string; version: number }) {
  const [packs, setPacks] = useState<PackView[]>([])
  const [subs, setSubs] = useState<SubmissionView[]>([])
  useEffect(() => {
    api.packs(token, caseId).then(setPacks).catch(() => setPacks([]))
    api.submissions(token, caseId).then(setSubs).catch(() => setSubs([]))
  }, [token, caseId, version])

  const download = async (v: number, name: string) => {
    const blob = await api.packFile(token, caseId, v, name)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `pack-v${v}-${name}`
    a.click()
    URL.revokeObjectURL(url)
  }
  const verified = subs.find((s) => s.action === 'DEFEND' && s.state === 'verified')

  return (
    <section aria-labelledby="pack-h" className="panel">
      <h2 id="pack-h">Evidence pack and submission</h2>
      {verified && (
        <div className="banner banner-ok" role="status">
          <strong>Submission verified — dispute outcome pending.</strong> Receipt {verified.provider_reference} matches pack v
          {verified.pack_version} (independent simulator receipt plus status read).
        </div>
      )}
      {packs.length === 0 ? (
        <p className="sub">No pack built yet.</p>
      ) : (
        packs
          .slice()
          .reverse()
          .map((p) => (
            <div key={p.id} className="pack">
              <div>
                <strong>Pack v{p.version}</strong> {p.is_latest && <span className="tag">latest</span>}{' '}
                {p.stale && <span className="tag">stale — case changed</span>}
              </div>
              <div className="sub">
                orderStatus <code>{p.order_status}</code> · case version {p.case_version} · hash{' '}
                <code>{p.pack_hash.slice(0, 16)}…</code>
              </div>
              <p>
                <span className="sub">comments:</span> {p.comments}
              </p>
              <ol className="sub">
                {p.upload_files.map((f) => (
                  <li key={f.position}>
                    File {f.position}: {f.name} ({f.role})
                  </li>
                ))}
              </ol>
              <div className="fixture-buttons">
                {['manifest.json', 'evidence-index.html', 'cover.pdf'].map((n) => (
                  <button key={n} type="button" onClick={() => download(p.version, n)}>
                    Download {n}
                  </button>
                ))}
              </div>
            </div>
          ))
      )}
      {subs.length > 0 && (
        <table className="cases">
          <caption>Submissions (simulator only)</caption>
          <thead>
            <tr>
              <th scope="col">Action</th>
              <th scope="col">Pack</th>
              <th scope="col">State</th>
              <th scope="col">Attempts</th>
              <th scope="col">Receipt</th>
              <th scope="col">Reconciliation trail</th>
            </tr>
          </thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s.id}>
                <td>{s.action}</td>
                <td>{s.pack_version ? `v${s.pack_version}` : '—'}</td>
                <td>{s.state}</td>
                <td>{s.attempts}</td>
                <td>{s.provider_reference ?? '—'}</td>
                <td className="sub">
                  {s.reconciliation.map((r) => String(r.step) + (r.kind ? `:${String(r.kind)}` : '')).join(' → ')}
                  {s.last_error && <div className="warn">{s.last_error}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export function InboxPanel({
  caseId,
  token,
  session,
  version,
  onChanged,
}: {
  caseId: string
  token: string
  session: DemoSession
  version: number
  onChanged: () => Promise<void>
}) {
  const [inbox, setInbox] = useState<InboxView | null>(null)
  const [text, setText] = useState('')
  useEffect(() => {
    api.inbox(token, caseId).then(setInbox).catch(() => setInbox(null))
  }, [token, caseId, version])
  if (!inbox) return null
  return (
    <section aria-labelledby="inbox-h" className="panel">
      <h2 id="inbox-h">Staff inbox (in-app simulator; no WhatsApp)</h2>
      {inbox.tasks.length === 0 && <p className="sub">No staff tasks yet.</p>}
      <ul className="timeline">
        {inbox.tasks.map((t) => (
          <li key={t.id}>
            <span className="tag">{t.kind}</span> {t.requirement_id.replaceAll('_', ' ')} · round {t.round} · {t.assignee} ·{' '}
            {t.status}
          </li>
        ))}
      </ul>
      <ul className="messages">
        {inbox.messages.map((m) => (
          <li key={m.id} className={`msg msg-${m.direction}`} lang={m.locale.split('-')[0]}>
            <div className="sub">
              {m.direction === 'outbound' ? `To ${m.to}` : `From ${m.from}`} · {formatIst(m.created_at)} ·{' '}
              {m.delivery_state.replaceAll('_', ' ')}
            </div>
            {m.body}
          </li>
        ))}
      </ul>
      {session.user.role === 'staff' && (
        <form
          className="reply"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!text.trim()) return
            await api.reply(token, caseId, text.trim())
            setText('')
            await onChanged()
          }}
        >
          <label>
            Reply as {session.user.display_name}
            <input value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <button type="submit">Send</button>
        </form>
      )}
    </section>
  )
}
