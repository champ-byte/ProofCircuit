from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Identity, current_identity, get_db, get_settings_dep, require_role
from app.config import Settings
from app.db.models import (
    Case,
    ChecklistItem,
    DemoUser,
    DocumentPage,
    EvidenceDocument,
    ExtractedFact,
    ValidationFinding,
)
from app.domain.citations import snippet, verify_span
from app.runner import enqueue_continuation, schedule
from app.services.evidence import exclude_document, ingest_document
from app.services.extraction import MAX_UPLOAD_BYTES, UploadRejected
from app.services.fixtures import HERO_DOCUMENTS, render_hero_document
from app.services.messaging import mark_staff_response
from app.services.storage import read_original
from app.services.validation import REQUIREMENTS, assess, is_active

router = APIRouter(prefix="/api", tags=["evidence"])


def scoped_case(db: Session, identity: Identity, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if case is None or case.merchant_id != identity.merchant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    return case


def scoped_document(db: Session, identity: Identity, doc_id: str) -> EvidenceDocument:
    doc = db.get(EvidenceDocument, doc_id)
    if doc is None or doc.merchant_id != identity.merchant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return doc


def _doc_summary(doc: EvidenceDocument, uploader: str | None) -> dict[str, Any]:
    return {
        "id": doc.id,
        "original_filename": doc.original_filename,
        "mime_type": doc.mime_type,
        "size_bytes": doc.size_bytes,
        "sha256": doc.sha256,
        "doc_type": doc.doc_type,
        "extraction_status": doc.extraction_status,
        "extraction_method": doc.extraction_method,
        "extraction_error": doc.extraction_error,
        "page_count": doc.page_count,
        "uploaded_by": uploader,
        "active": is_active(doc),
        "superseded_by_id": doc.superseded_by_id,
        "exclusion_reason": doc.exclusion_reason,
        "created_at": doc.created_at,
    }


def _fact_view(fact: ExtractedFact, page_text: str | None) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": fact.id,
        "document_id": fact.document_id,
        "page": fact.page_number,
        "field": fact.field,
        "raw_value": fact.raw_value,
        "normalized_value": fact.normalized_value,
        "unit": fact.unit,
        "method": fact.method,
        "verification": fact.verification,
        "stale": fact.stale,
        "source": None,
    }
    if fact.span_start is not None and fact.span_end is not None and page_text is not None:
        intact = verify_span(page_text, fact.page_text_sha256 or "", fact.span_start, fact.span_end, fact.raw_value)
        view["source"] = {**snippet(page_text, fact.span_start, fact.span_end), "recheck_ok": intact}
    return view


def evidence_overview(db: Session, case: Case) -> dict[str, Any]:
    docs = db.scalars(
        select(EvidenceDocument).where(EvidenceDocument.case_id == case.id).order_by(EvidenceDocument.created_at)
    ).all()
    users = {u.id: u.display_name for u in db.scalars(select(DemoUser).where(DemoUser.merchant_id == case.merchant_id))}
    pages = {
        (p.document_id, p.page_number): p.text
        for p in db.scalars(select(DocumentPage).join(EvidenceDocument).where(EvidenceDocument.case_id == case.id))
    }
    facts = db.scalars(select(ExtractedFact).where(ExtractedFact.case_id == case.id)).all()
    checklist = db.scalars(select(ChecklistItem).where(ChecklistItem.case_id == case.id)).all()
    findings = db.scalars(
        select(ValidationFinding).where(ValidationFinding.case_id == case.id).order_by(ValidationFinding.created_at)
    ).all()
    order = list(REQUIREMENTS)
    return {
        "documents": [
            {
                **_doc_summary(d, users.get(d.uploaded_by_user_id or "")),
                "facts": [
                    _fact_view(f, pages.get((f.document_id, f.page_number))) for f in facts if f.document_id == d.id
                ],
            }
            for d in docs
        ],
        "checklist": [
            {
                "requirement_id": c.requirement_id,
                "label": REQUIREMENTS[c.requirement_id]["label"],
                "status": c.status,
                "source_ids": c.source_ids,
                "assignee": users.get(c.assignee_user_id or ""),
                "explanation": c.explanation,
            }
            for c in sorted(checklist, key=lambda c: order.index(c.requirement_id))
        ],
        "findings": [
            {
                "id": f.id,
                "rule_id": f.rule_id,
                "severity": f.severity,
                "status": f.status,
                "source_ids": f.source_ids,
                "explanation": f.explanation,
                "details": f.details,
                "case_version": f.case_version,
                "created_at": f.created_at,
                "resolved_at": f.resolved_at,
            }
            for f in findings
        ],
        "assessment": assess(db, case),
    }


@router.get("/cases/{case_id}/evidence")
def get_case_evidence(
    case_id: str, identity: Identity = Depends(current_identity), db: Session = Depends(get_db, scope="function")
) -> dict[str, Any]:
    return evidence_overview(db, scoped_case(db, identity, case_id))


@router.post("/cases/{case_id}/evidence", status_code=status.HTTP_201_CREATED)
def upload_evidence(
    case_id: str,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    case = scoped_case(db, identity, case_id)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        doc, created, assessment = ingest_document(
            db,
            settings,
            case,
            filename=file.filename or "upload",
            declared_mime=file.content_type,
            data=data,
            uploaded_by_user_id=identity.user_id,
        )
    except UploadRejected as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    else:
        uploader = db.get(DemoUser, identity.user_id)
        if uploader is not None and uploader.role == "staff":
            mark_staff_response(db, case, uploader.id)
        enqueue_continuation(db, case, "evidence_uploaded")
        db.commit()
        schedule(background, request.app, case.id)
    return {"document": _doc_summary(doc, None), "created": created, "assessment": assessment}


@router.get("/evidence/{doc_id}")
def get_document(
    doc_id: str, identity: Identity = Depends(current_identity), db: Session = Depends(get_db, scope="function")
) -> dict[str, Any]:
    doc = scoped_document(db, identity, doc_id)
    pages = db.scalars(
        select(DocumentPage).where(DocumentPage.document_id == doc.id).order_by(DocumentPage.page_number)
    ).all()
    texts = {p.page_number: p.text for p in pages}
    facts = db.scalars(select(ExtractedFact).where(ExtractedFact.document_id == doc.id)).all()
    return {
        **_doc_summary(doc, None),
        "pages": [{"page": p.page_number, "text": p.text, "text_sha256": p.text_sha256} for p in pages],
        "facts": [_fact_view(f, texts.get(f.page_number)) for f in facts],
    }


@router.get("/evidence/{doc_id}/content")
def get_document_content(
    doc_id: str,
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db, scope="function"),
) -> Response:
    doc = scoped_document(db, identity, doc_id)
    data = read_original(settings, doc.storage_key)
    media = "text/plain; charset=utf-8" if doc.mime_type in ("text/plain", "application/json") else doc.mime_type
    ascii_name = "".join(c if c.isascii() and (c.isalnum() or c in "._-") else "_" for c in doc.original_filename)
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'inline; filename="{ascii_name}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )


class ExcludeRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


@router.post("/evidence/{doc_id}/exclude")
def exclude(
    doc_id: str,
    req: ExcludeRequest,
    request: Request,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("owner", "reviewer")),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    doc = scoped_document(db, identity, doc_id)
    if not is_active(doc):
        raise HTTPException(status.HTTP_409_CONFLICT, "document is already superseded or excluded")
    case = scoped_case(db, identity, doc.case_id)
    assessment = exclude_document(db, settings, case, doc, req.reason.strip(), identity.user_id)
    enqueue_continuation(db, case, "evidence_excluded")
    db.commit()
    schedule(background, request.app, case.id)
    return {"assessment": assessment}


@router.get("/demo/cases/{case_id}/fixtures")
def list_fixtures(
    case_id: str, identity: Identity = Depends(current_identity), db: Session = Depends(get_db, scope="function")
) -> list[dict[str, str]]:
    scoped_case(db, identity, case_id)
    return [
        {"name": name, "filename": filename.removesuffix(".txt") + ".pdf"} for name, filename in HERO_DOCUMENTS.items()
    ]


@router.get("/demo/cases/{case_id}/fixtures/{name}")
def download_fixture(
    case_id: str,
    name: str,
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db, scope="function"),
) -> Response:
    """Synthetic demo documents for staff to upload. Rendering is not an upload."""
    if not settings.demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "demo endpoints are disabled")
    case = scoped_case(db, identity, case_id)
    try:
        filename, data = render_hero_document(name, case, settings)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown fixture") from exc
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Content-Type-Options": "nosniff"},
    )
