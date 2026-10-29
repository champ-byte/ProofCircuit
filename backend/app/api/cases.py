from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Identity, current_identity, get_db, get_settings_dep
from app.config import Settings
from app.db.models import AuditEvent, Case, DemoUser, Merchant
from app.domain.clock import get_clock
from app.domain.enums import WorkflowState
from app.domain.money import format_inr
from app.services.validation import assess

router = APIRouter(prefix="/api/cases", tags=["cases"])


class CaseSummary(BaseModel):
    id: str
    merchant_name: str
    mid: str
    external_dispute_id: str
    order_id: str
    transaction_id: str
    reason: str
    amount_paise: int
    amount_display: str
    currency: str
    debit_amount_paise: int | None  # only when the provider reported it
    dispute_utr: str | None
    deadline_utc: datetime
    deadline_local: str
    deadline_raw: str
    timezone_assumption: str
    seconds_to_deadline: int
    deadline_expired: bool
    workflow_state: str
    provider_status: str
    provider_status_raw: str | None
    flags: list[Any]
    version: int
    owner: str | None
    next_action: str
    synthetic: bool
    evidence_ready: bool
    blocker: str | None


class TimelineEvent(BaseModel):
    seq: int
    event_type: str
    summary: str
    actor_type: str
    created_at: datetime


class CaseDetail(CaseSummary):
    timeline: list[TimelineEvent]


def _next_action(case: Case) -> str:
    # Descriptive only; the agent/policy decides real actions from M2/M3 onwards.
    return {
        WorkflowState.NEW: "Start agent to collect evidence",
        WorkflowState.WAITING_FOR_EVIDENCE: "Waiting for staff evidence",
        WorkflowState.NEEDS_HUMAN_REVIEW: "Human review required",
        WorkflowState.READY_TO_SUBMIT: "Submit defense",
        WorkflowState.MONITORING: "Monitor provider status",
    }.get(WorkflowState(case.workflow_state), case.workflow_state)


def _summary(
    db: Session, case: Case, merchant: Merchant, owner: DemoUser | None, settings: Settings
) -> dict[str, Any]:
    now = get_clock().now()
    assessment = assess(db, case)
    remaining = int((case.deadline_utc - now).total_seconds())
    return {
        "id": case.id,
        "merchant_name": merchant.name,
        "mid": case.mid,
        "external_dispute_id": case.external_dispute_id,
        "order_id": case.order_id,
        "transaction_id": case.transaction_id,
        "reason": case.reason,
        "amount_paise": case.amount_paise,
        "amount_display": format_inr(case.amount_paise),
        "currency": case.currency,
        "debit_amount_paise": case.debit_amount_paise,
        "dispute_utr": case.dispute_utr,
        "deadline_utc": case.deadline_utc,
        "deadline_local": case.deadline_utc.astimezone(ZoneInfo(settings.app_timezone)).isoformat(),
        "deadline_raw": case.deadline_raw,
        "timezone_assumption": case.timezone_assumption,
        "seconds_to_deadline": remaining,
        "deadline_expired": remaining <= 0,
        "workflow_state": case.workflow_state,
        "provider_status": case.provider_status,
        "provider_status_raw": case.provider_status_raw,
        "flags": case.flags,
        "version": case.version,
        "owner": owner.display_name if owner else None,
        "next_action": _next_action(case),
        "synthetic": case.synthetic,
        "evidence_ready": assessment["evidence_ready"],
        "blocker": assessment["blockers"][0] if assessment["blockers"] else None,
    }


def _scoped_query(identity: Identity):  # type: ignore[no-untyped-def]
    return (
        select(Case, Merchant, DemoUser)
        .join(Merchant, Case.merchant_id == Merchant.id)
        .outerjoin(DemoUser, Case.owner_user_id == DemoUser.id)
        .where(Case.merchant_id == identity.merchant_id)
    )


@router.get("", response_model=list[CaseSummary])
def list_cases(
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.execute(_scoped_query(identity).order_by(Case.deadline_utc)).all()
    return [_summary(db, c, m, o, settings) for c, m, o in rows]


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(
    case_id: str,
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = db.execute(_scoped_query(identity).where(Case.id == case_id)).first()
    if row is None:
        # Scoped 404: never reveal whether another merchant's case exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    case, merchant, owner = row
    events = db.scalars(select(AuditEvent).where(AuditEvent.case_id == case.id).order_by(AuditEvent.seq)).all()
    return {
        **_summary(db, case, merchant, owner, settings),
        "timeline": [
            {
                "seq": e.seq,
                "event_type": e.event_type,
                "summary": e.summary,
                "actor_type": e.actor_type,
                "created_at": e.created_at,
            }
            for e in events
        ],
    }
