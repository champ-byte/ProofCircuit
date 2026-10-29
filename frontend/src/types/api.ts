export interface ReasoningMode {
  mode: 'live' | 'manual' | 'fixture_replay'
  label: string
}

export interface ProviderReadiness {
  name: string
  role: string
  status: string
  model: string | null
  detail: string
  notes: string[]
}

export interface ProviderReport {
  reasoning_mode: ReasoningMode
  reasoners: ProviderReadiness[]
  integrations: ProviderReadiness[]
  synthetic_data: boolean
  paytm_mode: string
  usage: { calls_24h: number | null; cap: number; min_interval_s: number }
}

export interface DemoUser {
  mid: string
  merchant_name: string
  handle: string
  display_name: string
  role: string
  locale: string
}

export interface DemoSession {
  token: string
  user: { handle: string; display_name: string; role: string; locale: string }
  merchant: { name: string; mid: string }
}

export interface CaseSummary {
  id: string
  merchant_name: string
  mid: string
  external_dispute_id: string
  order_id: string
  transaction_id: string
  reason: string
  amount_paise: number
  amount_display: string
  currency: string
  debit_amount_paise: number | null
  dispute_utr: string | null
  deadline_utc: string
  deadline_local: string
  deadline_raw: string
  timezone_assumption: string
  seconds_to_deadline: number
  deadline_expired: boolean
  workflow_state: string
  provider_status: string
  provider_status_raw: string | null
  flags: string[]
  version: number
  owner: string | null
  next_action: string
  synthetic: boolean
  evidence_ready: boolean
  blocker: string | null
}

export interface TimelineEvent {
  seq: number
  event_type: string
  summary: string
  actor_type: string
  created_at: string
}

export interface CaseDetail extends CaseSummary {
  timeline: TimelineEvent[]
}

export interface SourceSnippet {
  before: string
  match: string
  after: string
  start: number
  end: number
  recheck_ok: boolean
}

export interface Fact {
  id: string
  document_id: string
  page: number
  field: string
  raw_value: string
  normalized_value: string | null
  unit: string | null
  method: string
  verification: string
  stale: boolean
  source: SourceSnippet | null
}

export interface EvidenceDocumentSummary {
  id: string
  original_filename: string
  mime_type: string
  size_bytes: number
  sha256: string
  doc_type: string
  extraction_status: string
  extraction_method: string | null
  extraction_error: string | null
  page_count: number
  uploaded_by: string | null
  active: boolean
  superseded_by_id: string | null
  exclusion_reason: string | null
  created_at: string
  facts: Fact[]
}

export interface ChecklistEntry {
  requirement_id: string
  label: string
  status: 'missing' | 'supported' | 'conflicting' | 'review_required'
  source_ids: string[]
  assignee: string | null
  explanation: string
}

export interface Finding {
  id: string
  rule_id: string
  severity: 'blocking' | 'review' | 'info'
  status: 'open' | 'resolved'
  source_ids: string[]
  explanation: string
  details: Record<string, unknown>
  case_version: number
  created_at: string
  resolved_at: string | null
}

export interface Assessment {
  evidence_ready: boolean
  blocking_contradiction: boolean
  blockers: string[]
  case_version: number
}

export interface EvidenceOverview {
  documents: EvidenceDocumentSummary[]
  checklist: ChecklistEntry[]
  findings: Finding[]
  assessment: Assessment
}

export interface DocumentDetail extends Omit<EvidenceDocumentSummary, 'facts'> {
  pages: { page: number; text: string; text_sha256: string }[]
  facts: Fact[]
}

export interface FixtureInfo {
  name: string
  filename: string
}

export interface ToolCallView {
  step: number
  tool: string
  arguments: Record<string, unknown>
  rationale: string
  status: 'ok' | 'denied' | 'error'
  result: Record<string, unknown> | null
}

export interface RunView {
  id: string
  provider: string
  model: string | null
  mode: string
  status: string
  error: string | null
  started_at: string
  tool_calls: ToolCallView[]
}

export interface PackView {
  id: string
  version: number
  case_version: number
  pack_hash: string
  order_status: string
  comments: string
  upload_files: { position: number; name: string; sha256: string; size: number; mime: string; role: string }[]
  is_latest: boolean
  stale: boolean
  created_at: string
}

export interface SubmissionView {
  id: string
  action: string
  pack_version: number | null
  state: string
  attempts: number
  provider_reference: string | null
  intent_digest: string
  last_error: string | null
  reconciliation: Record<string, unknown>[]
  created_at: string
}

export interface InboxView {
  tasks: {
    id: string
    kind: string
    requirement_id: string
    round: number
    assignee: string | null
    locale: string
    status: string
    question: string | null
  }[]
  messages: { id: string; direction: string; from: string | null; to: string | null; locale: string; body: string; delivery_state: string; created_at: string }[]
}

export interface AuditEventView {
  seq: number
  event_type: string
  summary: string
  actor_type: string
  data: Record<string, unknown>
  created_at: string
}

export interface SimulatorState {
  dispute_id: string
  dispute_status: string
  comment: string | null
  due_at_utc: string
  event_sequence: number
  queued_faults: { api: string; kind: string; remaining: number }[]
  receipts: { reference: string; action: string; orderStatus: string | null; intentDigest: string; createdAt: string }[]
}

export interface EvaluationResults {
  status: string
  planned: number
  executed: number
  not_run: number
  label: string
  categories: { category: string; planned: number; executed: number }[]
  split: { development: number; held_out: number; first_pass: number; first_pass_selection: string }
  mode: string | null
  metrics: unknown
  note: string
}
