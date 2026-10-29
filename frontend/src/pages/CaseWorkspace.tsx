import { type ReactNode, useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useSession } from '../session'
import { ActionsPanel, InboxPanel, PackPanel } from './CasePanels'
import type {
  CaseDetail,
  DocumentDetail,
  EvidenceDocumentSummary,
  EvidenceOverview,
  Fact,
  Finding,
  FixtureInfo,
} from '../types/api'
import { STATE_LABELS, formatCountdown, formatIst } from '../format'

const CHECK_LABEL: Record<string, string> = {
  supported: 'Supported',
  missing: 'Missing',
  conflicting: 'Conflicting',
  review_required: 'Needs review',
}
const DOC_TYPE: Record<string, string> = {
  invoice: 'Invoice',
  delivery_record: 'Delivery record',
  dispatch_record: 'Dispatch record',
  other: 'Other',
  unknown: 'Unknown',
}
const METHOD: Record<string, string> = {
  utf8_text: 'Automatic (text file)',
  json_text: 'Automatic (JSON)',
  pdf_text: 'Automatic (PDF text layer)',
}

export function CaseWorkspace() {
  const { id = '' } = useParams()
  const { token, session } = useSession()
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [evidence, setEvidence] = useState<EvidenceOverview | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [reloadKey, setReloadKey] = useState(0)
  const refresh = useCallback(async () => setReloadKey((k) => k + 1), [])

  // Background work (runner, simulator callbacks) finishes after HTTP responses return. Follow the
  // persisted event feed and refresh when it advances. This is the browser reading deltas; the
  // backend itself never polls.
  useEffect(() => {
    if (!token) return
    let cursor = -1
    let stopped = false
    const tick = async () => {
      try {
        const res = await api.events(token, id, Math.max(cursor, 0))
        if (cursor === -1) cursor = res.cursor
        else if (res.cursor !== cursor) {
          cursor = res.cursor
          setReloadKey((k) => k + 1)
        }
      } catch {
        /* transient; next tick retries */
      }
      if (!stopped) timer = window.setTimeout(tick, 1500)
    }
    let timer = window.setTimeout(tick, 0)
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [token, id])

  useEffect(() => {
    if (!token) return
    Promise.all([api.caseDetail(token, id), api.evidence(token, id)])
      .then(([d, e]) => {
        setDetail(d)
        setEvidence(e)
        setError(null)
      })
      .catch((err: Error) => setError(err.message))
  }, [token, id, reloadKey])

  if (error) {
    return (
      <p role="alert" className="error">
        {error} <Link to="/cases">Back to cases</Link>
      </p>
    )
  }
  if (!detail || !evidence || !token || !session) return <p aria-live="polite">Loading case…</p>

  return (
    <div className="workspace">
      <p>
        <Link to="/cases">← All cases</Link>
      </p>
      <CaseHeader detail={detail} />
      <AssessmentBanner evidence={evidence} />
      <div className="grid">
        <section aria-labelledby="checklist-h" className="panel">
          <h2 id="checklist-h">Evidence checklist</h2>
          <p className="sub">Demo policy for goods-not-received disputes, not a bank guarantee.</p>
          <ul className="checklist">
            {evidence.checklist.map((c) => (
              <li key={c.requirement_id} className={`check check-${c.status}`}>
                <span className="check-status">{CHECK_LABEL[c.status]}</span>
                <div>
                  <strong>{c.label}</strong>
                  <div className="sub">{c.explanation}</div>
                  {c.assignee && <div className="sub">Assignee: {c.assignee}</div>}
                </div>
              </li>
            ))}
          </ul>
        </section>
        <FindingsPanel findings={evidence.findings} documents={evidence.documents} onSelect={setSelected} />
      </div>
      <ActionsPanel caseId={id} token={token} session={session} version={detail.version + evidence.findings.length + reloadKey} onChanged={refresh} />
      <PackPanel caseId={id} token={token} version={reloadKey} />
      <InboxPanel caseId={id} token={token} session={session} version={reloadKey} onChanged={refresh} />
      <EvidencePanel
        caseId={id}
        token={token}
        documents={evidence.documents}
        selected={selected}
        onSelect={setSelected}
        onChanged={refresh}
      />
      <section aria-labelledby="timeline-h" className="panel">
        <h2 id="timeline-h">Timeline</h2>
        <ol className="timeline">
          {detail.timeline.map((e) => (
            <li key={e.seq}>
              <span className="sub">{formatIst(e.created_at)}</span> <code>{e.event_type}</code> {e.summary}
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}

function CaseHeader({ detail }: { detail: CaseDetail }) {
  return (
    <section className="case-header" aria-label="Case summary">
      <div>
        <h1>
          {detail.external_dispute_id} <span className="sub">· {detail.merchant_name}</span>
        </h1>
        <div className="sub">
          Order {detail.order_id} · Transaction {detail.transaction_id} · {detail.reason.replaceAll('_', ' ')}
        </div>
      </div>
      <dl className="facts-row">
        <div>
          <dt>Amount at risk</dt>
          <dd className="num">{detail.amount_display}</dd>
        </div>
        <div>
          <dt>Response deadline</dt>
          <dd>
            {formatIst(detail.deadline_utc)}
            <div className={detail.deadline_expired ? 'sub warn' : 'sub'}>{formatCountdown(detail.seconds_to_deadline)}</div>
          </dd>
        </div>
        <div>
          <dt>Workflow</dt>
          <dd>{STATE_LABELS[detail.workflow_state] ?? detail.workflow_state}</dd>
        </div>
        <div>
          <dt>Provider status</dt>
          <dd>
            <code>{detail.provider_status_raw ?? detail.provider_status}</code>
          </dd>
        </div>
        {detail.debit_amount_paise !== null && (
          <div>
            <dt>Reported debit</dt>
            <dd>{(detail.debit_amount_paise / 100).toFixed(2)} (provider-reported)</dd>
          </div>
        )}
        {detail.flags.length > 0 && (
          <div>
            <dt>Flags</dt>
            <dd>{detail.flags.join(', ')}</dd>
          </div>
        )}
      </dl>
    </section>
  )
}

function AssessmentBanner({ evidence }: { evidence: EvidenceOverview }) {
  const a = evidence.assessment
  if (a.evidence_ready) {
    return (
      <div className="banner banner-ok" role="status">
        Evidence complete and consistent for a pack (case version {a.case_version}).
      </div>
    )
  }
  return (
    <div className={`banner ${a.blocking_contradiction ? 'banner-block' : 'banner-warn'}`} role="status">
      <strong>{a.blocking_contradiction ? 'Submission blocked: contradiction found' : 'Evidence incomplete'}</strong>
      <ul>
        {a.blockers.map((b) => (
          <li key={b}>{b}</li>
        ))}
      </ul>
    </div>
  )
}

function FindingsPanel({
  findings,
  documents,
  onSelect,
}: {
  findings: Finding[]
  documents: EvidenceDocumentSummary[]
  onSelect: (id: string) => void
}) {
  const open = findings.filter((f) => f.status === 'open')
  const resolved = findings.filter((f) => f.status === 'resolved')
  const docIds = new Set(documents.map((d) => d.id))
  const renderFinding = (f: Finding) => (
    <li key={f.id} className={`finding finding-${f.severity} finding-${f.status}`}>
      <div>
        <span className="tag">{f.severity}</span> <code>{f.rule_id}</code>
        {f.status === 'resolved' && <span className="tag">resolved</span>}
      </div>
      <p>{f.explanation}</p>
      {Object.keys(f.details).length > 0 && (
        <table className="details">
          <tbody>
            {Object.entries(f.details).map(([k, v]) => (
              <tr key={k}>
                <th scope="row">{k.replaceAll('_', ' ')}</th>
                <td>
                  <code>{Array.isArray(v) ? v.join(', ') : String(v)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {f.source_ids
        .filter((s) => docIds.has(s))
        .map((s) => (
          <button key={s} type="button" className="link" onClick={() => onSelect(s)}>
            Open source: {documents.find((d) => d.id === s)?.original_filename}
          </button>
        ))}
    </li>
  )
  return (
    <section aria-labelledby="findings-h" className="panel">
      <h2 id="findings-h">Validation findings</h2>
      {open.length === 0 ? <p className="sub">No open findings.</p> : <ul className="findings">{open.map(renderFinding)}</ul>}
      {resolved.length > 0 && (
        <details>
          <summary>Resolved ({resolved.length})</summary>
          <ul className="findings">{resolved.map(renderFinding)}</ul>
        </details>
      )}
    </section>
  )
}

function EvidencePanel({
  caseId,
  token,
  documents,
  selected,
  onSelect,
  onChanged,
}: {
  caseId: string
  token: string
  documents: EvidenceDocumentSummary[]
  selected: string | null
  onSelect: (id: string) => void
  onChanged: () => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [fixtures, setFixtures] = useState<FixtureInfo[]>([])

  useEffect(() => {
    api.fixtures(token, caseId).then(setFixtures).catch(() => setFixtures([]))
  }, [token, caseId])

  const doUpload = async (file: Blob, name: string) => {
    setBusy(true)
    setMessage(null)
    try {
      const res = await api.upload(token, caseId, file, name)
      setMessage(res.created ? `Uploaded ${name}.` : `${name} was already uploaded; no duplicate created.`)
      await onChanged()
    } catch (err) {
      setMessage(`Upload rejected: ${(err as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby="evidence-h" className="panel">
      <h2 id="evidence-h">Evidence</h2>
      <div className="upload-row">
        <label>
          Upload evidence (TXT, JSON, PDF; images need OCR)
          <input
            type="file"
            accept=".txt,.json,.pdf,.png,.jpg,.jpeg"
            disabled={busy}
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void doUpload(f, f.name)
              e.target.value = ''
            }}
          />
        </label>
        {fixtures.length > 0 && (
          <div className="fixture-buttons" aria-label="Synthetic demo documents">
            <span className="sub">Synthetic demo documents (uploaded as the current identity):</span>
            {fixtures
              .filter((f) => f.name !== 'invoice')
              .map((f) => (
                <button
                  key={f.name}
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    const blob = await api.fixtureFile(token, caseId, f.name)
                    await doUpload(blob, f.filename)
                  }}
                >
                  Upload {f.name.replaceAll('_', ' ')}
                </button>
              ))}
          </div>
        )}
      </div>
      {message && (
        <p role="status" className="sub">
          {message}
        </p>
      )}
      <table className="cases">
        <thead>
          <tr>
            <th scope="col">Document</th>
            <th scope="col">Type</th>
            <th scope="col">Extraction</th>
            <th scope="col">Status</th>
            <th scope="col">Uploaded</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((d) => (
            <tr key={d.id} className={d.id === selected ? 'row-selected' : undefined}>
              <td>
                <button type="button" className="link" onClick={() => onSelect(d.id)}>
                  {d.original_filename}
                </button>
                <div className="sub mono">sha256 {d.sha256.slice(0, 12)}…</div>
              </td>
              <td>{DOC_TYPE[d.doc_type] ?? d.doc_type}</td>
              <td>
                {d.extraction_status === 'extracted'
                  ? (METHOD[d.extraction_method ?? ''] ?? d.extraction_method)
                  : d.extraction_status === 'ocr_required'
                    ? 'OCR required (not run)'
                    : `Failed: ${d.extraction_error}`}
              </td>
              <td>{d.active ? 'Active' : <span className="warn">Excluded — {d.exclusion_reason}</span>}</td>
              <td className="sub">
                {d.uploaded_by ?? 'System seed'}
                <div>{formatIst(d.created_at)}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && <SourceViewer token={token} docId={selected} />}
    </section>
  )
}

/** Highlights cited spans. Offsets are Unicode code points, so slice Array.from(text), not the string. */
function HighlightedPage({ text, facts }: { text: string; facts: Fact[] }) {
  const chars = Array.from(text)
  const spans = facts
    .filter((f) => f.source && f.verification === 'span_verified')
    .map((f) => ({ start: f.source!.start, end: f.source!.end, field: f.field }))
    .sort((a, b) => a.start - b.start)
  const parts: ReactNode[] = []
  let cursor = 0
  spans.forEach((s, i) => {
    if (s.start < cursor) return
    parts.push(chars.slice(cursor, s.start).join(''))
    parts.push(
      <mark key={i} title={s.field}>
        {chars.slice(s.start, s.end).join('')}
      </mark>,
    )
    cursor = s.end
  })
  parts.push(chars.slice(cursor).join(''))
  return <pre className="page-text">{parts}</pre>
}

function SourceViewer({ token, docId }: { token: string; docId: string }) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null)
  useEffect(() => {
    api.document(token, docId).then(setDoc).catch(() => setDoc(null))
  }, [token, docId])
  if (!doc) return <p aria-live="polite">Loading source…</p>
  return (
    <div className="source-viewer" aria-label={`Source: ${doc.original_filename}`}>
      <h3>
        Source: {doc.original_filename} {!doc.active && <span className="tag">excluded</span>}
      </h3>
      {doc.pages.length === 0 ? (
        <p className="sub">No extractable text ({doc.extraction_error}). The original file is preserved.</p>
      ) : (
        doc.pages.map((p) => (
          <div key={p.page}>
            <div className="sub">
              Page {p.page} · text sha256 {p.text_sha256.slice(0, 12)}…
            </div>
            <HighlightedPage text={p.text} facts={doc.facts.filter((f) => f.page === p.page)} />
          </div>
        ))
      )}
      {doc.facts.length > 0 && (
        <table className="cases">
          <caption>Extracted facts (spans computed by the backend; values cited from the text above)</caption>
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Raw value</th>
              <th scope="col">Normalized</th>
              <th scope="col">Citation</th>
            </tr>
          </thead>
          <tbody>
            {doc.facts.map((f) => (
              <tr key={f.id}>
                <td>{f.field.replaceAll('_', ' ')}</td>
                <td>
                  <code>{f.raw_value}</code>
                </td>
                <td>
                  {f.normalized_value ?? <span className="warn">unknown</span>} {f.unit && <span className="sub">{f.unit}</span>}
                </td>
                <td className="sub">
                  {f.verification === 'span_verified' && f.source
                    ? `p${f.page} [${f.source.start}, ${f.source.end})${f.source.recheck_ok ? ' ✓ rechecked' : ' ✗ hash mismatch'}`
                    : f.verification}
                  {f.stale && ' · stale'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
