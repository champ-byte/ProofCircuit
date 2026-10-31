import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import i18n from '../i18n'
import { codePointSlice, formatIst, plainSummary } from '../format'
import { factIndex, resolveSource, type SourceRef } from '../sources'
import type { DocumentDetail, EvidenceDocumentSummary, EvidenceOverview, Fact, Finding } from '../types/api'
import { useView } from '../view'

export type { SourceRef }


/** Translated label for a known code, or the raw code when the locale has no entry. */
const label = (group: string, code: string) => i18n.t(`evidence.${group}.${code}`, { defaultValue: code })

function SourceLinks({ ids, evidence, onOpen }: { ids: string[]; evidence: EvidenceOverview; onOpen: (s: SourceRef) => void }) {
  const all = ids.map((id) => resolveSource(id, evidence)).filter((r): r is SourceRef & { label: string } => r !== null)
  // Prefer exact citations: drop a bare document link when a cited fact in that document exists.
  const refs = all.filter((r) => r.factId || !all.some((o) => o.factId && o.docId === r.docId))
  const { t } = useTranslation()
  if (refs.length === 0) return null
  return (
    <ul className="source-links">
      {refs.map((r, i) => (
        <li key={`${r.docId}-${r.factId ?? i}`}>
          <button type="button" className="link" onClick={() => onOpen(r)}>
            {t('evidence.openSource', { label: r.label })}
          </button>
        </li>
      ))}
    </ul>
  )
}

export function ChecklistPanel({ evidence, onOpen }: { evidence: EvidenceOverview; onOpen: (s: SourceRef) => void }) {
  const { t } = useTranslation()
  return (
    <section aria-labelledby="checklist-h" className="panel">
      <h2 id="checklist-h">{t('evidence.checklistTitle')}</h2>
      <p className="sub">{t('evidence.checklistNote')}</p>
      <ul className="checklist">
        {evidence.checklist.map((c) => (
          <li key={c.requirement_id} className={`check check-${c.status}`}>
            <span className="check-status">{label('check', c.status)}</span>
            <div>
              <strong>{t(`checklist.${c.requirement_id}`, { defaultValue: c.label })}</strong>
              <div className="sub">{c.explanation}</div>
              {c.assignee && <div className="sub">{t('evidence.assignee', { name: c.assignee })}</div>}
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
  const { t } = useTranslation()
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
        <div className="compare-head">{t('evidence.disputeRecord')}</div>
        {caseSide.map(([k, v]) => (
          <div key={k}>
            <span className="sub">{k.replaceAll('_', ' ')}</span> <code>{show(v)}</code>
          </div>
        ))}
        {caseSide.length === 0 && <div className="sub">—</div>}
      </div>
      <div>
        <div className="compare-head">{t('evidence.citedDocument')}</div>
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
  const { t } = useTranslation()
  const { detailed } = useView()
  const open = evidence.findings.filter((f) => f.status === 'open')
  const resolved = evidence.findings.filter((f) => f.status === 'resolved')
  const render = (f: Finding) => (
    <li key={f.id} className={`finding finding-${f.severity} finding-${f.status}`}>
      <div>
        <span className="tag">{label('severity', f.severity)}</span> {detailed && <code>{f.rule_id}</code>}{' '}
        {f.status === 'resolved' && <span className="tag">{t('evidence.resolvedTag')}</span>}
      </div>
      <p>{detailed ? f.explanation : plainSummary(f.explanation)}</p>
      {f.status === 'open' && <CompareView finding={f} evidence={evidence} />}
      <SourceLinks ids={f.source_ids.slice(0, 4)} evidence={evidence} onOpen={onOpen} />
    </li>
  )
  return (
    <section aria-labelledby="findings-h" className="panel">
      <h2 id="findings-h">{t('evidence.findingsTitle')}</h2>
      {open.length === 0 ? <p className="sub">{t('evidence.noFindings')}</p> : <ul className="findings">{open.map(render)}</ul>}
      {resolved.length > 0 && (
        <details>
          <summary>{t('evidence.resolvedCount', { count: resolved.length })}</summary>
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
  const { t } = useTranslation()
  const { detailed } = useView()
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const upload = async (file: File) => {
    setBusy(true)
    try {
      const res = await api.upload(token, caseId, file, file.name)
      setMessage(res.created ? t('evidence.uploadedFile', { file: file.name }) : t('evidence.alreadyUploaded', { file: file.name }))
      await onChanged()
    } catch (err) {
      setMessage(t('evidence.rejected', { error: (err as Error).message }))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section aria-labelledby="evidence-h" className="panel">
      <h2 id="evidence-h">{t('evidence.title')}</h2>
      <label className="upload">
        {t('evidence.upload')}
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
              <th scope="col">{t('evidence.colDocument')}</th>
              <th scope="col">{t('evidence.colType')}</th>
              {detailed && <th scope="col">{t('evidence.colExtraction')}</th>}
              <th scope="col">{t('evidence.colStatus')}</th>
              <th scope="col">{t('evidence.colUploaded')}</th>
            </tr>
          </thead>
          <tbody>
            {evidence.documents.map((d: EvidenceDocumentSummary) => (
              <tr key={d.id} className={d.id === selected?.docId ? 'row-selected' : undefined}>
                <td>
                  <button type="button" className="link" onClick={() => onOpen({ docId: d.id })}>
                    {d.original_filename}
                  </button>
                  {detailed && <div className="sub mono">sha256 {d.sha256.slice(0, 12)}…</div>}
                </td>
                <td>{label('docType', d.doc_type)}</td>
                {detailed && <td>
                  {d.extraction_status === 'extracted'
                    ? label('method', d.extraction_method ?? '')
                    : d.extraction_status === 'ocr_required'
                      ? t('evidence.ocrRequired')
                      : t('evidence.extractFailed', { error: d.extraction_error })}
                </td>}
                <td>{d.active ? t('evidence.active') : <span className="warn">{t('evidence.excluded', { reason: d.exclusion_reason })}</span>}</td>
                <td className="sub">
                  {d.uploaded_by ?? t('evidence.systemSeed')}
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
  const { t } = useTranslation()
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => () => void (url && URL.revokeObjectURL(url)), [url])
  if (!url)
    return (
      <button
        type="button"
        onClick={async () => setUrl(URL.createObjectURL(await api.evidenceContent(token, doc.id)))}
      >
        {t('evidence.showOriginal', { type: doc.mime_type })}
      </button>
    )
  if (doc.mime_type === 'application/pdf')
    return <iframe className="original" title={`Original: ${doc.original_filename}`} src={url} />
  if (doc.mime_type.startsWith('image/')) return <img className="original" alt={`Original: ${doc.original_filename}`} src={url} />
  return (
    <a href={url} download={doc.original_filename}>
      {t('evidence.downloadOriginal')}
    </a>
  )
}

export function SourceViewer({ token, source }: { token: string; source: SourceRef }) {
  const { t } = useTranslation()
  const { detailed } = useView()
  const [doc, setDoc] = useState<DocumentDetail | null>(null)
  useEffect(() => {
    api.document(token, source.docId).then(setDoc).catch(() => setDoc(null))
  }, [token, source.docId])
  if (!doc || doc.id !== source.docId) return <p aria-live="polite">{t('evidence.loadingSource')}</p>
  const focusFact = doc.facts.find((f) => f.id === source.factId)
  return (
    <div className="source-viewer" aria-label={`Source: ${doc.original_filename}`}>
      <h3>
        {t('evidence.source', { file: doc.original_filename })} {!doc.active && <span className="tag">{t('evidence.excludedTag')}</span>}
      </h3>
      {focusFact && !detailed && (
        <p className="sub" role="status">{t('evidence.showingField', { field: focusFact.field.replaceAll('_', ' '), page: focusFact.page })}</p>
      )}
      {focusFact && detailed && (
        <p className="sub" role="status">
          Showing cited {focusFact.field.replaceAll('_', ' ')} on page {focusFact.page}, code points [
          {focusFact.source?.start}, {focusFact.source?.end}){focusFact.source?.recheck_ok ? ' — rechecked against stored text' : ''}
        </p>
      )}
      <div className="source-grid">
        <div>
          {doc.pages.length === 0 ? (
            <p className="sub">{t('evidence.noText', { error: doc.extraction_error })}</p>
          ) : (
            doc.pages.map((p) => (
              <div key={p.page}>
                <div className="sub">
                  {detailed ? `Extracted text · page ${p.page} · sha256 ${p.text_sha256.slice(0, 12)}…` : t('evidence.page', { page: p.page })}
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
          <div className="sub">{detailed ? `Original bytes (sha256 ${doc.sha256.slice(0, 12)}…)` : t('evidence.originalFile')}</div>
          <OriginalPreview key={doc.id} token={token} doc={doc} />
        </div>
      </div>
      {detailed && doc.facts.length > 0 && (
        <details>
          <summary>{t('evidence.facts', { count: doc.facts.length })}</summary>
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
