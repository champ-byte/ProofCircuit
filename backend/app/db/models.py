"""Persistent entities (PRD Section 10.2). Money is integer paise; times are aware UTC."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_id
from app.domain.clock import get_clock
from app.domain.enums import PendingStatus, ProviderDisputeStatus, WorkflowState


def _now() -> datetime:
    return get_clock().now()


def _id_col() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[str] = _id_col()
    name: Mapped[str] = mapped_column(String(200))
    mid: Mapped[str] = mapped_column(String(32), unique=True)
    default_locale: Mapped[str] = mapped_column(String(16), default="en-IN")
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class DemoUser(Base):
    __tablename__ = "demo_users"
    __table_args__ = (UniqueConstraint("merchant_id", "handle"),)
    id: Mapped[str] = _id_col()
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    handle: Mapped[str] = mapped_column(String(64))  # stable fixture handle, e.g. "staff-delivery"
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    staff_function: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. "delivery"
    locale: Mapped[str] = mapped_column(String(16), default="en-IN")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("merchant_id", "external_dispute_id"),)
    id: Mapped[str] = _id_col()
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    mid: Mapped[str] = mapped_column(String(32))
    external_dispute_id: Mapped[str] = mapped_column(String(64))
    transaction_id: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(String(64))
    customer_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_reference_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_paise: Mapped[int] = mapped_column(Integer)  # from disputeAmount
    transaction_amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    debit_amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)  # only when reported
    dispute_utr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    reason: Mapped[str] = mapped_column(String(64))
    dispute_type_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline_utc: Mapped[datetime]
    deadline_raw: Mapped[str] = mapped_column(String(32))
    timezone_assumption: Mapped[str] = mapped_column(String(64))
    transaction_at_utc: Mapped[datetime | None] = mapped_column(nullable=True)
    locale: Mapped[str] = mapped_column(String(16), default="en-IN")
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("demo_users.id"), nullable=True)
    workflow_state: Mapped[str] = mapped_column(String(32), default=WorkflowState.NEW)
    provider_status: Mapped[str] = mapped_column(String(32), default=ProviderDisputeStatus.NEW)
    provider_status_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    flags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    latest_pack_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pod_repair_count: Mapped[int] = mapped_column(Integer, default=0)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class EvidenceDocument(Base):
    __tablename__ = "evidence_documents"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))  # server-generated, never user-supplied
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    extraction_status: Mapped[str] = mapped_column(String(32), default="pending")
    extraction_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    # invoice | delivery_record | dispatch_record | other | unknown (deterministic classification)
    doc_type: Mapped[str] = mapped_column(String(32), default="unknown")
    uploaded_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("demo_users.id"), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)
    id: Mapped[str] = _id_col()
    document_id: Mapped[str] = mapped_column(ForeignKey("evidence_documents.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))


class ExtractedFact(Base):
    __tablename__ = "extracted_facts"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("evidence_documents.id"))
    page_number: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(64))
    raw_value: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)  # e.g. "paise:INR", "date"
    span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)  # code points, end-exclusive
    span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str] = mapped_column(String(64))
    verification: Mapped[str] = mapped_column(String(32))  # span_verified | invalid_span | ambiguous
    confirmation_state: Mapped[str] = mapped_column(String(32), default="automatic")
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    __table_args__ = (UniqueConstraint("case_id", "requirement_id"),)
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))  # missing | supported | conflicting | review_required
    source_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("demo_users.id"), nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class ValidationFinding(Base):
    __tablename__ = "validation_findings"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))  # blocking | review | info
    status: Mapped[str] = mapped_column(String(16), default="open")
    source_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)  # rule + sources + values
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # side-by-side values
    case_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class StaffTask(Base):
    __tablename__ = "staff_tasks"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    assignee_user_id: Mapped[str] = mapped_column(ForeignKey("demo_users.id"))
    requirement_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="evidence")  # evidence | review
    request_round: Mapped[int] = mapped_column(Integer, default=1)
    locale: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="open")
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True)  # (case, requirement, round)
    provider_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # escaped POD rejection text
    created_at: Mapped[datetime] = mapped_column(default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    staff_task_id: Mapped[str | None] = mapped_column(ForeignKey("staff_tasks.id"), nullable=True)
    sender_user_id: Mapped[str | None] = mapped_column(ForeignKey("demo_users.id"), nullable=True)
    recipient_user_id: Mapped[str | None] = mapped_column(ForeignKey("demo_users.id"), nullable=True)
    direction: Mapped[str] = mapped_column(String(16))  # outbound | inbound
    locale: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    delivery_state: Mapped[str] = mapped_column(String(32), default="queued")
    dedup_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class StaffReminder(Base):
    """One n8n reminder callback per (merchant, case, task, round, reminder number) (PRD 12.1).

    `queued` until the runner rechecks cancellation under the case lock, then `sent` (local inbox)
    or `skipped` with a reason. Never a claim of external delivery.
    """

    __tablename__ = "staff_reminders"
    id: Mapped[str] = _id_col()
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    staff_task_id: Mapped[str] = mapped_column(ForeignKey("staff_tasks.id"))
    request_round: Mapped[int] = mapped_column(Integer)
    reminder_number: Mapped[int] = mapped_column(Integer)
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | sent | skipped
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    actor: Mapped[str] = mapped_column(String(64))  # authenticated service identity
    created_at: Mapped[datetime] = mapped_column(default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class VoiceNote(Base):
    """Original staff voice-note audio (PRD 8.3 P0+). Testimony, never a delivery document."""

    __tablename__ = "voice_notes"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    staff_user_id: Mapped[str] = mapped_column(ForeignKey("demo_users.id"))  # speaker and uploader
    staff_task_id: Mapped[str | None] = mapped_column(ForeignKey("staff_tasks.id"), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))  # server-generated, never user-supplied
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(16))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # only when a decoder reported it
    # awaiting_transcription | transcribed | stt_failed | stt_unavailable
    stt_status: Mapped[str] = mapped_column(String(32))
    stt_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stt_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Transcript(Base):
    """One transcript version. Corrections create a new version; earlier versions are kept."""

    __tablename__ = "transcripts"
    __table_args__ = (UniqueConstraint("voice_note_id", "version"),)
    id: Mapped[str] = _id_col()
    voice_note_id: Mapped[str] = mapped_column(ForeignKey("voice_notes.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(32))  # stt | staff_correction | human_transcription
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)  # as reported by the provider
    language_probability: Mapped[float | None] = mapped_column(nullable=True)
    # [{start, end, audio_start_ms, audio_end_ms}]: code-point spans into `text`; empty when unknown
    segments: Mapped[list[Any]] = mapped_column(JSON, default=list)
    author_user_id: Mapped[str | None] = mapped_column(ForeignKey("demo_users.id"), nullable=True)  # human text
    confirmation_state: Mapped[str] = mapped_column(String(16))  # unconfirmed | confirmed | superseded
    confirmed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("demo_users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("demo_users.id"))
    decision: Mapped[str] = mapped_column(String(64))
    cited_source_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    case_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("demo_users.id"))
    action: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    case_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class EvidencePack(Base):
    __tablename__ = "evidence_packs"
    __table_args__ = (UniqueConstraint("case_id", "version"),)
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    case_version: Mapped[int] = mapped_column(Integer)
    document_hashes: Mapped[list[Any]] = mapped_column(JSON)  # ordered upload file hashes
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    pack_hash: Mapped[str] = mapped_column(String(64))
    upload_files: Mapped[list[Any]] = mapped_column(JSON, default=list)  # ordered {name, sha256, size, mime}
    intent_digest: Mapped[str] = mapped_column(String(64))  # DEFEND intent identity (see domain/intent.py)
    order_status: Mapped[str] = mapped_column(String(32))
    comments: Mapped[str] = mapped_column(Text)
    storage_dir: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    pack_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_packs.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(16))  # DEFEND | ACCEPT
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provider_ack: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # pending | sent | acknowledged | verified | uncertain | failed | review_required
    verification_state: Mapped[str] = mapped_column(String(32), default="pending")
    intent_digest: Mapped[str] = mapped_column(String(64), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciliation: Mapped[list[Any]] = mapped_column(JSON, default=list)  # evidence trail of reads/receipts
    # Handled-rejection marker for this submitted pack (PRD 8.6, 10.3): set once, so a repeated or stale
    # POD_REJECT delivery can never start a second repair. {comment, status_raw, at, handled, repair_round}
    provider_rejection: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)  # model actually returned
    mode: Mapped[str] = mapped_column(String(32))  # live | manual | fixture_replay
    status: Mapped[str] = mapped_column(String(32), default=PendingStatus.RUNNING)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = _id_col()
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    step: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rationale: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class PendingWork(Base):
    """Persisted 'something needs processing' marker. No leases, no polling (PRD 10.3)."""

    __tablename__ = "pending_work"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))  # e.g. agent_run, reconcile_submission
    case_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=PendingStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=PendingStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ProviderEvent(Base):
    __tablename__ = "provider_events"
    id: Mapped[str] = _id_col()
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32))  # s2s_callback | status_read | seed
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    canonical_hash: Mapped[str] = mapped_column(String(64), index=True)
    demo_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # harness header, not Paytm
    demo_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signature_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    applied_case_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_at: Mapped[datetime] = mapped_column(default=_now)


class AuditEvent(Base):
    """Append-only timeline. Integer seq doubles as the UI cursor. Not tamper-proof."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_case_seq", "case_id", "seq"),)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), nullable=True)
    merchant_id: Mapped[str | None] = mapped_column(ForeignKey("merchants.id"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32))  # system | agent | user | provider | service
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_now)


# --- Independent simulator provider store (never written by app-side code paths) ---------


class SimulatorDispute(Base):
    __tablename__ = "sim_disputes"
    __table_args__ = (UniqueConstraint("mid", "dispute_id"),)
    id: Mapped[str] = _id_col()
    mid: Mapped[str] = mapped_column(String(32))
    dispute_id: Mapped[str] = mapped_column(String(64))
    body: Mapped[dict[str, Any]] = mapped_column(JSON)  # Paytm-shaped fields (raw strings)
    dispute_status: Mapped[str] = mapped_column(String(32), default="NEW")
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    due_at_utc: Mapped[datetime]
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class SimulatorSubmission(Base):
    """Independent simulator receipt. Verification must read this, not app-side Submission rows."""

    __tablename__ = "sim_submissions"
    id: Mapped[str] = _id_col()
    reference: Mapped[str] = mapped_column(String(64), unique=True)
    sim_dispute_id: Mapped[str] = mapped_column(ForeignKey("sim_disputes.id"), index=True)
    mid: Mapped[str] = mapped_column(String(32))
    dispute_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16))
    pack_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_hashes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    order_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_digest: Mapped[str] = mapped_column(String(64), default="")  # computed from received bytes
    files_meta: Mapped[list[Any]] = mapped_column(JSON, default=list)
    timestamp_unit: Mapped[str] = mapped_column(String(8), default="s")
    sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class SimulatorFault(Base):
    """Operator-injected simulator fault, consumed when triggered (demo drawer / tests)."""

    __tablename__ = "sim_faults"
    id: Mapped[str] = _id_col()
    mid: Mapped[str] = mapped_column(String(32))
    dispute_id: Mapped[str] = mapped_column(String(64))
    api: Mapped[str] = mapped_column(String(16))  # status | action
    kind: Mapped[str] = mapped_column(String(48))
    remaining: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ReasonerCall(Base):
    """One inference request (quota accounting and audit). Never stores prompts' secrets or thoughts."""

    __tablename__ = "reasoner_calls"
    id: Mapped[str] = _id_col()
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    model_requested: Mapped[str] = mapped_column(String(128))
    model_returned: Mapped[str | None] = mapped_column(String(128), nullable=True)
    purpose: Mapped[str] = mapped_column(String(32))  # propose | repair | smoke
    status: Mapped[str] = mapped_column(String(32))  # ok | invalid_output | rate_limited | error | timeout
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)


class ProviderCheck(Base):
    """Persisted live smoke-test result; readiness is `ready` only while a passing check is fresh."""

    __tablename__ = "provider_checks"
    id: Mapped[str] = _id_col()
    provider: Mapped[str] = mapped_column(String(32), index=True)
    model_requested: Mapped[str] = mapped_column(String(128))
    model_returned: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str] = mapped_column(Text)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # e.g. schema field that worked
    checked_at: Mapped[datetime] = mapped_column(default=_now)
