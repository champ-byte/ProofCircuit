import { type ReactNode, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { codePointSlice, formatIst } from '../format'
import { factIndex, resolveSource, type SourceRef } from '../sources'
import type { DocumentDetail, EvidenceDocumentSummary, EvidenceOverview, Fact, Finding } from '../types/api'

export type { SourceRef }


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

function SourceLinks({ ids, evidence, onOpen }: { ids: string[]; evidence: EvidenceOverview; onOpen: (s: SourceRef) => void }) {
  const all = ids.map((id) => resolveSource(id, evidence)).filter((r): r is SourceRef & { label: string } => r !== null)
  // Prefer exact citations: drop a bare document link when a cited fact in that document exists.
  const refs = all.filter((r) => r.factId || !all.some((o) => o.factId && o.docId === r.docId))
  if (refs.length === 0) return null
  return (
    <ul className="source-links">
      {refs.map((r, i) => (
        <li key={`${r.docId}-${r.factId ?? i}`}>
          <button type="button" className="link" onClick={() => onOpen(r)}>
            Open source: {r.label}
          </button>
        </li>
      ))}
    </ul>
  )
}

export function ChecklistPanel({ evidence, onOpen }: { evidence: EvidenceOverview; onOpen: (s: SourceRef) => void }) {
  return (
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
              <SourceLinks ids={c.source_ids.slice(0, 3)} evidence={evidence} onOpen={onOpen} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Side-by-side values for a contradiction: what the dispute says vs what the cited document says. */
export function CompareView({ finding, evidence }: { finding: Finding; evidence: EvidenceOverview }) {
  const facts = factIndex(evidence)
  const cited = finding.source_ids.map((id) => facts.get(id)).filter((f): f is Fact & { filename: string } => !!f)
  const d = finding.details
  const caseSide = Object.entries(d).filter(([k]) => /^(case_|disputed_|order_date)/.test(k))
  const docSide = Object.entries(d).filter(([k]) => /^(document_|invoice_|delivered_on|delivery_dates)/.test(k))
  if (caseSide.length === 0 && docSide.length === 0 && cited.length === 0) return null
  const show = (v: unknown) => (Array.isArray(v) ? v.join(', ') : String(v))
  return (
    <div className="compare" role="group" aria-label={`${finding.rule_id} comparison`}>
      <div>
        <div className="compare-head">Dispute record</div>
        {caseSide.map(([k, v]) => (
          <div key={k}>
            <span className="sub">{k.replaceAll('_', ' ')}</span> <code>{show(v)}</code>
          </div>
        ))}
        {caseSide.length === 0 && <div className="sub">—</div>}
      </div>
      <div>
        <div className="compare-head">Cited document</div>
        {docSide
          .filter(([k]) => k !== 'document_id')
          .map(([k, v]) => (
            <div key={k}>
              <span className="sub">{k.replaceAll('_', ' ')}</span> <code>{show(v)}</code>
            </div>
          ))}
        {cited.slice(0, 3).map((f) => (
          <div key={f.id} className="sub">
            {f.filename}, p{f.page}:{' '}
            {f.source ? (
              <span>
                …{f.source.before}
                <mark>{f.source.match}</mark>
                {f.source.after}…
              </span>
            ) : (
              <code>{f.raw_value}</code>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export function FindingsPanel({ evidence, onOpen }: { evidence: EvidenceOverview; onOpen: (s: SourceRef) => void }) {
  const open = evidence.findings.filter((f) => f.status === 'open')
  const resolved = evidence.findings.filter((f) => f.status === 'resolved')
  const render = (f: Finding) => (
    <li key={f.id} className={`finding finding-${f.severity} finding-${f.status}`}>
      <div>
        <span className="tag">{f.severity}</span> <code>{f.rule_id}</code>{' '}
        {f.status === 'resolved' && <span className="tag">resolved</span>}
      </div>
      <p>{f.explanation}</p>
      {f.status === 'open' && <CompareView finding={f} evidence={evidence} />}
      <SourceLinks ids={f.source_ids.slice(0, 4)} evidence={evidence} onOpen={onOpen} />
    </li>
  )
  return (
    <section aria-labelledby="findings-h" className="panel">
      <h2 id="findings-h">Validation findings</h2>
      {open.length === 0 ? <p className="sub">No open findings.</p> : <ul className="findings">{open.map(render)}</ul>}
      {resolved.length > 0 && (
        <details>
          <summary>Resolved ({resolved.length})</summary>
          <ul className="findings">{resolved.map(render)}</ul>
        </details>
      )}
    </section>
  )
}

export function EvidencePanel({
  caseId,
  token,
  evidence,
  selected,
  onOpen,
  onChanged,
}: {
  caseId: string
  token: string
  evidence: EvidenceOverview
  selected: SourceRef | null
  onOpen: (s: SourceRef) => void
  onChanged: () => Promise<void>
}) {
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const upload = async (file: File) => {
    setBusy(true)
    try {
      const res = await api.upload(token, caseId, file, file.name)
      setMessage(res.created ? `Uploaded ${file.name}.` : `${file.name} was already uploaded.`)
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
      <label className="upload">
        Upload evidence (TXT, JSON, PDF; images need OCR)
        <input
          type="file"
          accept=".txt,.json,.pdf,.png,.jpg,.jpeg"
          disabled={busy}
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void upload(f)
            e.target.value = ''
          }}
        />
      </label>
      {message && (
        <p role="status" className="sub">
          {message}
        </p>
      )}
      <div className="table-wrap">
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
            {evidence.documents.map((d: EvidenceDocumentSummary) => (
              <tr key={d.id} className={d.id === selected?.docId ? 'row-selected' : undefined}>
                <td>
                  <button type="button" className="link" onClick={() => onOpen({ docId: d.id })}>
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
      </div>
      {selected && <SourceViewer token={token} source={selected} />}
    </section>
  )
}

export interface Span {
  id: string
  start: number
  end: number
  field: string
}

/** Highlights cited spans by Unicode code points (never UTF-16 indices). The focused span is
 * scrolled into view and receives keyboard focus. */
export function HighlightedPage({ text, spans, focusId }: { text: string; spans: Span[]; focusId?: string }) {
  const chars = Array.from(text)
  const focusRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    focusRef.current?.scrollIntoView?.({ block: 'center' })
    focusRef.current?.focus?.()
  }, [focusId])
  const parts: ReactNode[] = []
  let cursor = 0
  for (const s of [...spans].sort((a, b) => a.start - b.start)) {
    if (s.start < cursor || s.end > chars.length) continue
    parts.push(codePointSlice(text, cursor, s.start))
    const focused = s.id === focusId
    parts.push(
      <mark
        key={s.id}
        title={s.field}
        data-field={s.field}
        className={focused ? 'focus' : undefined}
        tabIndex={focused ? -1 : undefined}
        ref={focused ? (el) => void (focusRef.current = el) : undefined}
      >
        {codePointSlice(text, s.start, s.end)}
      </mark>,
    )
    cursor = s.end
  }
  parts.push(codePointSlice(text, cursor))
  return <pre className="page-text">{parts}</pre>
}

function OriginalPreview({ token, doc }: { token: string; doc: DocumentDetail }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => () => void (url && URL.revokeObjectURL(url)), [url])
  if (!url)
    return (
      <button
        type="button"
        onClick={async () => setUrl(URL.createObjectURL(await api.evidenceContent(token, doc.id)))}
      >
        Show original file ({doc.mime_type})
      </button>
    )
  if (doc.mime_type === 'application/pdf')
    return <iframe className="original" title={`Original: ${doc.original_filename}`} src={url} />
  if (doc.mime_type.startsWith('image/')) return <img className="original" alt={`Original: ${doc.original_filename}`} src={url} />
  return (
    <a href={url} download={doc.original_filename}>
      Download original
    </a>
  )
}

export function SourceViewer({ token, source }: { token: string; source: SourceRef }) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null)
  useEffect(() => {
    api.document(token, source.docId).then(setDoc).catch(() => setDoc(null))
  }, [token, source.docId])
  if (!doc || doc.id !== source.docId) return <p aria-live="polite">Loading source…</p>
  const focusFact = doc.facts.find((f) => f.id === source.factId)
  return (
    <div className="source-viewer" aria-label={`Source: ${doc.original_filename}`}>
      <h3>
        Source: {doc.original_filename} {!doc.active && <span className="tag">excluded</span>}
      </h3>
      {focusFact && (
        <p className="sub" role="status">
          Showing cited {focusFact.field.replaceAll('_', ' ')} on page {focusFact.page}, code points [
          {focusFact.source?.start}, {focusFact.source?.end}){focusFact.source?.recheck_ok ? ' — rechecked against stored text' : ''}
        </p>
      )}
      <div className="source-grid">
        <div>
          {doc.pages.length === 0 ? (
            <p className="sub">No extractable text ({doc.extraction_error}). The original file is preserved.</p>
          ) : (
            doc.pages.map((p) => (
              <div key={p.page}>
                <div className="sub">
                  Extracted text · page {p.page} · sha256 {p.text_sha256.slice(0, 12)}…
                </div>
                <HighlightedPage
                  text={p.text}
                  focusId={focusFact?.page === p.page ? focusFact.id : undefined}
                  spans={doc.facts
                    .filter((f) => f.page === p.page && f.source && f.verification === 'span_verified')
                    .map((f) => ({ id: f.id, start: f.source!.start, end: f.source!.end, field: f.field }))}
                />
              </div>
            ))
          )}
        </div>
        <div>
          <div className="sub">Original bytes (sha256 {doc.sha256.slice(0, 12)}…)</div>
          <OriginalPreview key={doc.id} token={token} doc={doc} />
        </div>
      </div>
      {doc.facts.length > 0 && (
        <details>
          <summary>Extracted facts ({doc.facts.length})</summary>
          <table className="cases">
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
                    {f.normalized_value ?? <span className="warn">unknown</span>}{' '}
                    {f.unit && <span className="sub">{f.unit}</span>}
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
        </details>
      )}
    </div>
  )
}
