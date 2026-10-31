"""Evidence ingestion: store original bytes first, extract text, cite fields, revalidate the case."""

from __future__ import annotations

import hashlib
from pathlib import PurePath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Case, DocumentPage, EvidenceDocument, ExtractedFact
from app.domain.citations import locate_span, text_sha256
from app.domain.fields import normalize_field
from app.services.audit import audit
from app.services.extraction import extract, sniff
from app.services.field_rules import classify_document, propose_json_fields, propose_text_fields
from app.services.storage import save_original
from app.services.validation import revalidate_case


def _safe_filename(name: str) -> str:
    base = PurePath(name.replace("\\", "/")).name or "upload"
    return "".join(ch for ch in base if ch.isprintable())[:255]


def ingest_document(
    session: Session,
    settings: Settings,
    case: Case,
    *,
    filename: str,
    declared_mime: str | None,
    data: bytes,
    uploaded_by_user_id: str | None,
    actor_type: str = "user",
) -> tuple[EvidenceDocument, bool, dict[str, Any]]:
    """Return (document, created, assessment). Identical bytes on the same case are not duplicated.

    Raises UploadRejected for unsupported/mismatched content before anything is stored.
    """
    mime, ext = sniff(filename, declared_mime, data)
    sha = hashlib.sha256(data).hexdigest()
    existing = session.scalar(
        select(EvidenceDocument).where(EvidenceDocument.case_id == case.id, EvidenceDocument.sha256 == sha)
    )
    if existing is not None:
        return existing, False, revalidate_case(session, settings, case)

    doc = EvidenceDocument(
        case_id=case.id,
        merchant_id=case.merchant_id,
        original_filename=_safe_filename(filename),
        storage_key="",
        mime_type=mime,
        size_bytes=len(data),
        sha256=sha,
        uploaded_by_user_id=uploaded_by_user_id,
    )
    session.add(doc)
    session.flush()
    # Original bytes are persisted before any parsing.
    doc.storage_key = save_original(settings, case.id, doc.id, ext, data)

    outcome = extract(mime, data)
    doc.extraction_status = outcome.status
    doc.extraction_method = outcome.method
    doc.extraction_error = outcome.error
    doc.page_count = len(outcome.pages)
    page_hashes: dict[int, str] = {}
    for number, text in enumerate(outcome.pages, start=1):
        page_hashes[number] = text_sha256(text)
        session.add(DocumentPage(document_id=doc.id, page_number=number, text=text, text_sha256=page_hashes[number]))

    verified_fields: set[str] = set()
    if outcome.status == "extracted":
        proposals = (
            propose_json_fields(outcome.pages[0]) if mime == "application/json" else propose_text_fields(outcome.pages)
        )
        for p in proposals:
            page_text = outcome.pages[p.page_number - 1]
            span = locate_span(page_text, p.raw_value, p.anchor)
            normalized = normalize_field(p.field, p.raw_value) if span.verification == "span_verified" else None
            if normalized is not None and normalized.value is not None:
                verified_fields.add(p.field)
            session.add(
                ExtractedFact(
                    case_id=case.id,
                    document_id=doc.id,
                    page_number=p.page_number,
                    field=p.field,
                    raw_value=p.raw_value,
                    normalized_value=normalized.value if normalized else None,
                    unit=normalized.unit if normalized else None,
                    span_start=span.start,
                    span_end=span.end,
                    page_text_sha256=page_hashes[p.page_number],
                    quote=p.anchor,
                    method=f"{outcome.method}+label_rules",
                    verification=span.verification,
                )
            )
    doc.doc_type = classify_document(outcome.pages, verified_fields) if outcome.status == "extracted" else "unknown"
    case.version += 1
    audit(
        session,
        event_type="evidence.uploaded",
        summary=f"{doc.original_filename} uploaded ({doc.doc_type.replace('_', ' ')}, {outcome.status}).",
        actor_type=actor_type,
        actor_id=uploaded_by_user_id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={
            "document_id": doc.id,
            "sha256": sha,
            "mime_type": mime,
            "extraction_status": outcome.status,
            "extraction_method": outcome.method,
            "doc_type": doc.doc_type,
        },
    )
    session.flush()
    return doc, True, revalidate_case(session, settings, case)


def exclude_document(
    session: Session, settings: Settings, case: Case, doc: EvidenceDocument, reason: str, actor_id: str
) -> dict[str, Any]:
    """Explicit, reasoned exclusion. The original stays stored and visible in history."""
    doc.exclusion_reason = reason
    for fact in session.scalars(select(ExtractedFact).where(ExtractedFact.document_id == doc.id)):
        fact.stale = True
    case.version += 1
    audit(
        session,
        event_type="evidence.excluded",
        summary=f"{doc.original_filename} excluded: {reason}",
        actor_type="user",
        actor_id=actor_id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"document_id": doc.id, "reason": reason},
    )
    session.flush()
    return revalidate_case(session, settings, case)
