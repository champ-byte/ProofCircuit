import type { EvidenceOverview, Fact } from './types/api'

export interface SourceRef {
  docId: string
  factId?: string
}

export function factIndex(evidence: EvidenceOverview): Map<string, Fact & { filename: string }> {
  const map = new Map<string, Fact & { filename: string }>()
  for (const d of evidence.documents) for (const f of d.facts) map.set(f.id, { ...f, filename: d.original_filename })
  return map
}

/** Resolve a source id (fact or document) to something openable. */
export function resolveSource(id: string, evidence: EvidenceOverview): (SourceRef & { label: string }) | null {
  const fact = factIndex(evidence).get(id)
  if (fact) return { docId: fact.document_id, factId: fact.id, label: `${fact.filename} · ${fact.field.replaceAll('_', ' ')}` }
  const doc = evidence.documents.find((d) => d.id === id)
  return doc ? { docId: doc.id, label: doc.original_filename } : null
}
