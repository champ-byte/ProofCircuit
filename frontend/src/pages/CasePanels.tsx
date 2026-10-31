import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { formatIst } from '../format'
import type { AuditEventView, DemoSession, PackView, RunView, SubmissionView } from '../types/api'
import { useView } from '../view'

const ACTIONS: { tool: string; args?: Record<string, unknown> }[] = [
  { tool: 'request_evidence', args: { requirement_id: 'delivery_record' } },
  { tool: 'validate_evidence' },
  { tool: 'build_evidence_pack' },
  { tool: 'submit_defense' },
  { tool: 'get_submission_status' },
  { tool: 'request_human_review', args: { reason: 'owner_request', question: 'The owner asked a reviewer to look at this case.' } },
]
const KNOWN_TOOLS = new Set(ACTIONS.map((a) => a.tool))

/** Manual operation through the same tools and policy gate the agent will use (M3). */
export function ActionsPanel({
  caseId,
  token,
  session,
  version,
  onChanged,
  events,
}: {
  caseId: string
  token: string
  session: DemoSession
  version: number
  onChanged: () => Promise<void>
  events: AuditEventView[]
}) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [runs, setRuns] = useState<RunView[]>([])
  const { detailed } = useView()
  const toolLabel = (tool: string) => (KNOWN_TOOLS.has(tool) ? t(`panels.action.${tool}`) : tool)
  const result = (status: string) => t(`panels.result.${status}`, { defaultValue: status })
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

  return (
    <section aria-labelledby="actions-h" className="panel">
      <h2 id="actions-h">{t('panels.actionsTitle')}</h2>
      <p className="sub">{t('panels.actionsIntro')}</p>
      {paused && agentRuns[0]?.id === paused.id && (
        <div className="banner banner-warn" role="status">
          {t('panels.reasonerUnavailable', { error: paused.error })}
        </div>
      )}
      {canAct ? (
        <div className="assistant-actions">
          <button type="button" disabled={busy} onClick={() => run(() => api.startRun(token, caseId))}>{t('panels.checkWithAssistant')}</button>
          <h3 id="do-it-yourself">{t('panels.doItYourself')}</h3>
          <div className="fixture-buttons">
            {ACTIONS.map((a) => <button key={a.tool} type="button" disabled={busy} onClick={() => run(() => api.action(token, caseId, a.tool, a.args))}>{toolLabel(a.tool)}</button>)}
          </div>
        </div>
      ) : (
        <p className="sub">{t('panels.switchRole')}</p>
      )}
      {agentRuns.length > 0 && (
        <div className="agent-runs">
          <h3>{t('panels.runsTitle')}</h3>
          <p className="sub">{t('panels.runsIntro')}</p>
          <ol className="timeline">
            {agentRuns.map((r) => (
              <li key={r.id}>
                <span className="tag">{r.mode === 'fixture_replay' ? t('panels.fixtureReplay') : t('panels.liveModel')}</span>{' '}
                {detailed && <>{r.provider}{r.model ? ` — ${r.model}` : ''} · </>}
                {t(`assistant.status.${r.status}`, { defaultValue: r.status.replaceAll('_', ' ') })} · {formatIst(r.started_at)}
                <ul>
                  {r.tool_calls.map((c) => (
                    <li key={c.step} className={`tool-${c.status}`}>
                      <strong>
                        {c.step}. {toolLabel(c.tool)}
                      </strong>{' '}
                      → {result(c.status)}
                      <div className="sub">{KNOWN_TOOLS.has(c.tool) ? t(`panels.explain.${c.tool}`) : t('panels.explainDefault')}</div>
                      {c.rationale && <div className="sub">“{c.rationale}”</div>}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </div>
      )}
      {agentRuns.length === 0 && <p className="sub">{events.some((event) => event.event_type === 'agent.run_started') ? t('panels.runNoLog') : t('panels.noRuns')}</p>}
      {last && (
        <div className={`tool-result tool-${last.status}`} role="status">
          <strong>
            {detailed ? last.tool : toolLabel(last.tool)} → {result(last.status)}
          </strong>
          {detailed && <details><summary>{t('panels.technical')}</summary><pre>{JSON.stringify(last.result, null, 2)}</pre></details>}
        </div>
      )}
    </section>
  )
}

export function PackPanel({ caseId, token, version }: { caseId: string; token: string; version: number }) {
  const { t } = useTranslation()
  const { detailed } = useView()
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
      <h2 id="pack-h">{t('panels.packTitle')}</h2>
      {verified && (
        <div className="banner banner-ok" role="status">
          <strong>{t('panels.verified')}</strong> {t('panels.verifiedDetail', { receipt: verified.provider_reference, version: verified.pack_version })}
        </div>
      )}
      {packs.length === 0 ? (
        <p className="sub">{t('panels.noPack')}</p>
      ) : (
        packs
          .slice()
          .reverse()
          .map((p) => (
            <div key={p.id} className="pack">
              <div>
                <strong>{t('panels.pack', { version: p.version })}</strong> {p.is_latest && <span className="tag">{t('panels.latest')}</span>}{' '}
                {p.stale && <span className="tag">{t('panels.stale')}</span>}
              </div>
              {detailed && <div className="sub">
                orderStatus <code>{p.order_status}</code> · case version {p.case_version} · hash{' '}
                <code>{p.pack_hash.slice(0, 16)}…</code>
              </div>}
              <p>
                <span className="sub">{t(detailed ? 'panels.comments' : 'panels.message')}</span> {p.comments}
              </p>
              {detailed && <ol className="sub">
                {p.upload_files.map((f) => (
                  <li key={f.position}>
                    {t('panels.file', { position: f.position, name: f.name, role: f.role })}
                  </li>
                ))}
              </ol>}
              <div className="fixture-buttons">
                {(detailed ? ['manifest.json', 'evidence-index.html', 'cover.pdf'] : ['cover.pdf']).map((n) => (
                  <button key={n} type="button" onClick={() => download(p.version, n)}>
                    {detailed ? t('panels.download', { name: n }) : t('panels.coverLetter')}
                  </button>
                ))}
              </div>
            </div>
          ))
      )}
      {subs.length > 0 && (
        <table className="cases">
          <caption>{t('panels.subsCaption')}</caption>
          <thead>
            <tr>
              {detailed && <th scope="col">{t('panels.colAction')}</th>}
              <th scope="col">{t('panels.colPack')}</th>
              <th scope="col">{t('panels.colState')}</th>
              {detailed && <th scope="col">{t('panels.colAttempts')}</th>}
              <th scope="col">{t('panels.colReceipt')}</th>
              {detailed && <th scope="col">{t('panels.colTrail')}</th>}
            </tr>
          </thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s.id}>
                {detailed && <td>{s.action}</td>}
                <td>{s.pack_version ? `v${s.pack_version}` : '—'}</td>
                <td>{detailed ? s.state : t(`panels.subState.${s.state}`, { defaultValue: s.state.replaceAll('_', ' ') })}</td>
                {detailed && <td>{s.attempts}</td>}
                <td>{s.provider_reference ?? '—'}</td>
                {detailed && <td className="sub">
                  {s.reconciliation.map((r) => String(r.step) + (r.kind ? `:${String(r.kind)}` : '')).join(' → ')}
                  {s.last_error && <div className="warn">{s.last_error}</div>}
                </td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
