from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Identity, current_identity, get_db, get_settings_dep, require_role
from app.api.evidence import scoped_case
from app.config import Settings
from app.db.models import (
    AgentRun,
    Approval,
    AuditEvent,
    DemoUser,
    EvidencePack,
    Review,
    StaffTask,
    Submission,
    ToolCall,
)
from app.domain.clock import get_clock
from app.domain.enums import DisputeReason
from app.domain.money import format_inr
from app.providers.base import AGENT_TOOLS
from app.runner import enqueue, enqueue_continuation, resume_all, schedule
from app.services import messaging
from app.services.audit import audit
from app.services.policy import approval_payload_hash, check_concession, refund_policy
from app.services.submission import concession_submission

router = APIRouter(prefix="/api", tags=["actions"])


def _accepted(response: Response) -> None:
    response.status_code = status.HTTP_202_ACCEPTED


# --- Manual tool execution (same dispatcher the agent will use) ----------------------------


class ActionRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=500)
    source_ids: list[str] = Field(default_factory=list)


@router.post("/cases/{case_id}/actions")
def run_action(
    case_id: str,
    req: ActionRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("owner", "operator")),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    case = scoped_case(db, identity, case_id)
    if req.tool not in AGENT_TOOLS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{req.tool!r} is not an available tool")
    run = AgentRun(case_id=case.id, provider="human", model=None, mode="manual", status="running")
    db.add(run)
    db.flush()
    work = enqueue(
        db,
        case,
        "tool",
        {
            "run_id": run.id,
            "tool": req.tool,
            "arguments": req.arguments,
            "reason": req.reason,
            "source_ids": req.source_ids,
            "actor_kind": "human",
            "actor_id": identity.user_id,
            "step": 1,
        },
    )
    db.commit()
    schedule(background, request.app, case.id)
    _accepted(response)
    return {"run_id": run.id, "pending_work_id": work.id}


class RunRequest(BaseModel):
    mode: Literal["live", "fixture_replay"] = "live"


@router.post("/cases/{case_id}/runs")
def start_run(
    case_id: str,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    req: RunRequest | None = None,
    identity: Identity = Depends(require_role("owner", "operator")),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    """Start/resume. Live runs use the model only after a passing smoke test; otherwise the case is
    re-evaluated deterministically (manual mode). Fixture replay is operator-only and always labelled."""
    case = scoped_case(db, identity, case_id)
    mode = req.mode if req else "live"
    if mode == "fixture_replay" and identity.role != "operator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "fixture replay is an operator demo control")
    work = enqueue_continuation(db, case, "manual_start", mode=mode)
    db.commit()
    schedule(background, request.app, case.id)
    _accepted(response)
    from app.providers.readiness import provider_report

    label = "Fixture replay" if mode == "fixture_replay" else provider_report(settings)["reasoning_mode"]["label"]
    return {"pending_work_id": work.id, "mode": mode, "reasoning_label": label}


@router.post("/providers/smoke")
async def provider_smoke(
    request: Request,
    provider: Literal["gemini", "openrouter"] = "gemini",
    identity: Identity = Depends(require_role("operator")),
) -> dict[str, Any]:
    """Operator-triggered live smoke test (spends 1–4 inference calls)."""
    from app.services.smoke import smoke_test

    return await smoke_test(request.app, provider)


@router.get("/cases/{case_id}/runs")
def list_runs(
    case_id: str, identity: Identity = Depends(current_identity), db: Session = Depends(get_db, scope="function")
) -> list[dict[str, Any]]:
    case = scoped_case(db, identity, case_id)
    runs = db.scalars(select(AgentRun).where(AgentRun.case_id == case.id).order_by(AgentRun.started_at)).all()
    calls = db.scalars(select(ToolCall).where(ToolCall.case_id == case.id).order_by(ToolCall.started_at)).all()
    return [
        {
            "id": r.id,
            "provider": r.provider,
            "model": r.model,
            "mode": r.mode,
            "status": r.status,
            "error": r.error,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "tool_calls": [
                {
                    "step": c.step,
                    "tool": c.tool,
                    "arguments": c.arguments,
                    "rationale": c.rationale,
                    "status": c.status,
                    "result": c.result,
                }
                for c in calls
                if c.run_id == r.id
            ],
        }
        for r in runs
    ]


@router.get("/cases/{case_id}/events")
def case_events(
    case_id: str,
    after: int = 0,
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    case = scoped_case(db, identity, case_id)
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.case_id == case.id, AuditEvent.seq > after)
        .order_by(AuditEvent.seq)
        .limit(500)
    ).all()
    events = [
        {
            "seq": e.seq,
            "event_type": e.event_type,
            "summary": e.summary,
            "actor_type": e.actor_type,
            "data": e.data,
            "created_at": e.created_at,
        }
        for e in rows
    ]
    return {"events": events, "cursor": events[-1]["seq"] if events else after}


# --- Staff inbox -------------------------------------------------------------------------------


class StaffMessage(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


@router.get("/cases/{case_id}/messages")
def get_inbox(
    case_id: str, identity: Identity = Depends(current_identity), db: Session = Depends(get_db, scope="function")
) -> dict[str, Any]:
    return messaging.inbox(db, scoped_case(db, identity, case_id))


@router.post("/cases/{case_id}/messages", status_code=status.HTTP_201_CREATED)
def post_staff_message(
    case_id: str,
    msg: StaffMessage,
    request: Request,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("staff")),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    case = scoped_case(db, identity, case_id)
    staff = db.get(DemoUser, identity.user_id)
    assert staff is not None
    message = messaging.staff_reply(db, case, staff, msg.body)
    enqueue_continuation(db, case, "staff_reply")
    db.commit()
    schedule(background, request.app, case.id)
    return {"message_id": message.id}


# --- Human review, approvals and concession --------------------------------------------------


class ReviewDecision(BaseModel):
    decision: Literal["approve_concession", "resolve_review", "confirm_reason"]
    explanation: str = Field(min_length=5, max_length=1000)
    task_id: str | None = None
    cited_source_ids: list[str] = Field(default_factory=list)


@router.post("/cases/{case_id}/reviews", status_code=status.HTTP_201_CREATED)
def review(
    case_id: str,
    req: ReviewDecision,
    request: Request,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("reviewer")),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    case = scoped_case(db, identity, case_id)
    db.add(
        Review(
            case_id=case.id,
            reviewer_user_id=identity.user_id,
            decision=req.decision,
            cited_source_ids=req.cited_source_ids,
            explanation=req.explanation,
            case_version=case.version,
        )
    )
    result: dict[str, Any] = {"decision": req.decision}
    if req.decision == "approve_concession":
        approval = Approval(
            case_id=case.id,
            reviewer_user_id=identity.user_id,
            action="ACCEPT",
            payload_hash=approval_payload_hash(case, "ACCEPT"),
            case_version=case.version,
            expires_at=get_clock().now() + timedelta(seconds=settings.approval_ttl_seconds),
        )
        db.add(approval)
        db.flush()
        result |= {
            "approval_id": approval.id,
            "expires_at": approval.expires_at,
            "case_version": case.version,
            "consequence": (
                f"Conceding gives up the defense. The dispute becomes LOST and "
                f"{format_inr(case.amount_paise)} (synthetic) may be debited from a later settlement."
            ),
        }
        audit(
            db,
            event_type="review.concession_approved",
            summary="Reviewer approved a single-use concession (not yet executed).",
            actor_type="user",
            actor_id=identity.user_id,
            case_id=case.id,
            merchant_id=case.merchant_id,
            data={"approval_id": approval.id, "expires_at": approval.expires_at.isoformat()},
        )
    elif req.decision == "resolve_review":
        task = db.get(StaffTask, req.task_id or "")
        if task is None or task.case_id != case.id or task.kind != "review" or task.status != "open":
            raise HTTPException(status.HTTP_409_CONFLICT, "no open review task with that id")
        task.status = "resolved"
        task.resolved_at = get_clock().now()
        audit(
            db,
            event_type="review.resolved",
            summary=f"Review resolved: {req.explanation}",
            actor_type="user",
            actor_id=identity.user_id,
            case_id=case.id,
            merchant_id=case.merchant_id,
            data={"task_id": task.id},
        )
    else:
        case.reason = DisputeReason.GOODS_NOT_RECEIVED
        case.version += 1
        audit(
            db,
            event_type="review.reason_confirmed",
            summary="Reviewer confirmed the goods-not-received reason.",
            actor_type="user",
            actor_id=identity.user_id,
            case_id=case.id,
            merchant_id=case.merchant_id,
        )
    if req.decision != "approve_concession":
        enqueue_continuation(db, case, req.decision)
    db.commit()
    schedule(background, request.app, case.id)
    return result


class ConcessionRequest(BaseModel):
    approval_id: str
    confirm: bool


@router.post("/cases/{case_id}/accept-dispute")
def accept_dispute(
    case_id: str,
    req: ConcessionRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("reviewer")),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    """ "Accept the customer's dispute (concede)": human-only, single-use, version-bound approval."""
    case = scoped_case(db, identity, case_id)
    if not req.confirm:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "explicit confirmation required")
    approval = db.get(Approval, req.approval_id)
    decision = check_concession(db, case, approval, identity.user_id)
    if not decision.allowed:
        audit(
            db,
            event_type="policy.denied",
            summary="Concession denied: " + "; ".join(decision.reasons),
            actor_type="user",
            actor_id=identity.user_id,
            case_id=case.id,
            merchant_id=case.merchant_id,
        )
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, {"reasons": decision.reasons})
    assert approval is not None
    approval.consumed_at = get_clock().now()
    sub = concession_submission(db, case, approval.id)
    audit(
        db,
        event_type="concession.requested",
        summary="Reviewer conceded the dispute (ACCEPT queued).",
        actor_type="user",
        actor_id=identity.user_id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"approval_id": approval.id, "submission_id": sub.id},
    )
    enqueue(db, case, "concede", {"submission_id": sub.id})
    db.commit()
    schedule(background, request.app, case.id)
    _accepted(response)
    return {"submission_id": sub.id}


@router.post("/cases/{case_id}/refund-policy-check")
def refund_check(
    case_id: str, identity: Identity = Depends(current_identity), db: Session = Depends(get_db, scope="function")
) -> dict[str, Any]:
    case = scoped_case(db, identity, case_id)
    result = refund_policy(case)
    audit(
        db,
        event_type="policy.refund_checked",
        summary=f"Refund dry-run: {result['decision']} (no refund call).",
        actor_type="user",
        actor_id=identity.user_id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data=result,
    )
    return result


# --- Packs and submissions ---------------------------------------------------------------------


@router.get("/cases/{case_id}/pack")
def list_packs(
    case_id: str, identity: Identity = Depends(current_identity), db: Session = Depends(get_db, scope="function")
) -> list[dict[str, Any]]:
    case = scoped_case(db, identity, case_id)
    packs = db.scalars(select(EvidencePack).where(EvidencePack.case_id == case.id).order_by(EvidencePack.version)).all()
    return [
        {
            "id": p.id,
            "version": p.version,
            "case_version": p.case_version,
            "pack_hash": p.pack_hash,
            "order_status": p.order_status,
            "comments": p.comments,
            "upload_files": p.upload_files,
            "is_latest": p.id == case.latest_pack_id,
            "stale": p.case_version != case.version,
            "created_at": p.created_at,
            "downloads": ["manifest.json", "evidence-index.html", "cover.pdf"],
        }
        for p in packs
    ]


@router.get("/cases/{case_id}/pack/{version}/{filename}")
def download_pack_file(
    case_id: str,
    version: int,
    filename: Literal["manifest.json", "evidence-index.html", "cover.pdf"],
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db, scope="function"),
) -> Response:
    case = scoped_case(db, identity, case_id)
    pack = db.scalar(select(EvidencePack).where(EvidencePack.case_id == case.id, EvidencePack.version == version))
    if pack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pack not found")
    data = (settings.data_path / pack.storage_dir / filename).read_bytes()
    media = {
        "manifest.json": "application/json",
        "evidence-index.html": "text/html; charset=utf-8",
        "cover.pdf": "application/pdf",
    }[filename]
    return Response(
        data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{case.external_dispute_id}-v{version}-{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get("/cases/{case_id}/submissions")
def list_submissions(
    case_id: str, identity: Identity = Depends(current_identity), db: Session = Depends(get_db, scope="function")
) -> list[dict[str, Any]]:
    case = scoped_case(db, identity, case_id)
    subs = db.scalars(select(Submission).where(Submission.case_id == case.id).order_by(Submission.created_at)).all()
    packs = {p.id: p.version for p in db.scalars(select(EvidencePack).where(EvidencePack.case_id == case.id))}
    return [
        {
            "id": s.id,
            "action": s.action,
            "pack_version": packs.get(s.pack_id or ""),
            "state": s.verification_state,
            "attempts": s.attempts,
            "provider_reference": s.provider_reference,
            "intent_digest": s.intent_digest,
            "idempotency_key": s.idempotency_key,
            "last_error": s.last_error,
            "reconciliation": s.reconciliation,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
        for s in subs
    ]


@router.post("/demo/resume-pending")
async def resume_pending(request: Request, identity: Identity = Depends(require_role("operator"))) -> dict[str, Any]:
    """Explicit recovery trigger: reconcile in-flight submissions and drain pending work."""
    return await resume_all(request.app)
