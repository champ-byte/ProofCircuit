"""Deterministic workflow-state sync (PRD 10.1). Workflow, provider outcome and operational
flags stay separate; provider status is only ever updated from authoritative reads."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Case, StaffTask, Submission
from app.domain.enums import OperationalFlag, ProviderDisputeStatus, WorkflowState
from app.services.audit import audit
from app.services.policy import deadline_open
from app.services.repair import open_repair
from app.services.validation import revalidate_case


def set_state(session: Session, case: Case, state: WorkflowState, reason: str) -> None:
    if case.workflow_state == state:
        return
    previous = case.workflow_state
    case.workflow_state = state
    audit(
        session,
        event_type="workflow.transition",
        summary=f"{previous} → {state}: {reason}",
        actor_type="system",
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"from": previous, "to": state, "reason": reason},
    )


def add_flag(case: Case, flag: OperationalFlag) -> None:
    if flag not in case.flags:
        case.flags = [*case.flags, flag]


def remove_flag(case: Case, flag: OperationalFlag) -> None:
    if flag in case.flags:
        case.flags = [f for f in case.flags if f != flag]


def sync_workflow(session: Session, settings: Settings, case: Case) -> dict[str, Any]:
    assessment = revalidate_case(session, settings, case)
    if not deadline_open(case):
        add_flag(case, OperationalFlag.DEADLINE_EXPIRED)
    if case.workflow_state == WorkflowState.CLOSED:
        return assessment

    latest = session.scalar(
        select(Submission).where(Submission.case_id == case.id).order_by(Submission.created_at.desc())
    )
    provider = ProviderDisputeStatus(case.provider_status)
    if provider in (ProviderDisputeStatus.WON, ProviderDisputeStatus.LOST):
        set_state(session, case, WorkflowState.CLOSED, f"provider reports {case.provider_status_raw}")
        return assessment
    if latest is not None and latest.verification_state in ("pending", "sent", "acknowledged"):
        set_state(session, case, WorkflowState.SUBMITTING, "submission in progress")
        return assessment
    if latest is not None and latest.verification_state == "uncertain":
        set_state(session, case, WorkflowState.SUBMISSION_UNCERTAIN, "provider effect unknown; reconciling")
        return assessment

    open_review = session.scalar(
        select(StaffTask.id).where(StaffTask.case_id == case.id, StaffTask.kind == "review", StaffTask.status == "open")
    )
    if latest is not None and latest.verification_state == "verified" and provider == ProviderDisputeStatus.POD_UPLOAD:
        set_state(session, case, WorkflowState.MONITORING, "submission independently verified; outcome pending")
    elif open_review is not None:
        set_state(session, case, WorkflowState.NEEDS_HUMAN_REVIEW, "human review requested")
    elif provider == ProviderDisputeStatus.POD_REJECT and open_repair(session, case) is None:
        # No open correction round (repeat rejection, no reason, expired, unhandled): a person decides.
        set_state(session, case, WorkflowState.NEEDS_HUMAN_REVIEW, "provider rejected the proof")
    elif provider == ProviderDisputeStatus.POD_UPLOAD:
        set_state(session, case, WorkflowState.NEEDS_HUMAN_REVIEW, "provider reports an upload this case cannot verify")
    elif session.scalar(
        select(StaffTask.id).where(
            StaffTask.case_id == case.id, StaffTask.kind == "evidence", StaffTask.status == "open"
        )
    ):
        set_state(session, case, WorkflowState.WAITING_FOR_EVIDENCE, "waiting for staff evidence")
    elif assessment["evidence_ready"]:
        set_state(session, case, WorkflowState.READY_TO_SUBMIT, "required evidence passes checks")
    elif assessment["blocking_contradiction"]:
        set_state(session, case, WorkflowState.NEEDS_HUMAN_REVIEW, "blocking contradiction")
    else:
        set_state(session, case, WorkflowState.COLLECTING, "collecting evidence")
    return assessment
