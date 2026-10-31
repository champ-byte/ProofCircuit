"""Backend policy gate (PRD 8.4, 8.5, 14). The model proposes; this decides.

Every check runs immediately before the write; a previously green checklist is not enough.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Approval, Case, EvidencePack, StaffTask, Submission
from app.domain.clock import get_clock
from app.domain.enums import DisputeReason, ProviderDisputeStatus, WorkflowState
from app.services.pack import COMMENTS_MAX_CODE_POINTS, MAX_UPLOAD_FILES, UPLOADABLE
from app.services.repair import open_repair, original_document_hashes
from app.services.validation import revalidate_case

MAX_FILE_BYTES = 5_000_000
IN_FLIGHT = ("pending", "sent", "acknowledged", "uncertain")
OPEN_PROVIDER_STATES = (
    ProviderDisputeStatus.NEW,
    ProviderDisputeStatus.POD_UPLOAD,
    ProviderDisputeStatus.POD_REJECT,
    ProviderDisputeStatus.UNKNOWN,
)


@dataclass
class Decision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reasons": self.reasons, "checks": self.checks}


def deadline_open(case: Case) -> bool:
    return get_clock().now() < case.deadline_utc


def check_defense(
    session: Session,
    settings: Settings,
    case: Case,
    pack: EvidencePack | None,
    *,
    actor_kind: str,
    resend_of: Submission | None = None,
) -> Decision:
    reasons: list[str] = []
    checks: dict[str, Any] = {}

    def need(ok: bool, name: str, reason: str) -> None:
        checks[name] = ok
        if not ok:
            reasons.append(reason)

    need(
        settings.paytm_mode == "simulator" and not settings.paytm_live_enabled,
        "simulator_only",
        "live Paytm writes are disabled",
    )
    need(case.workflow_state != WorkflowState.CLOSED, "case_open", "case is closed")
    need(
        case.reason == DisputeReason.GOODS_NOT_RECEIVED,
        "reason_confirmed",
        "dispute reason is not confirmed as goods-not-received; reviewer confirmation required",
    )
    need(deadline_open(case), "deadline_open", "response deadline has passed (DEADLINE_EXPIRED)")
    if actor_kind == "agent":
        need(settings.auto_submit_simulator, "auto_submit_enabled", "AUTO_SUBMIT_SIMULATOR is disabled")

    need(pack is not None and pack.case_id == case.id, "pack_present", "no evidence pack for this case")
    if pack is not None and pack.case_id == case.id:
        need(pack.id == case.latest_pack_id, "pack_is_latest", "pack is not the latest version")
        need(pack.case_version == case.version, "pack_current", "case changed after this pack was built; rebuild it")
        need(
            pack.order_status == "ORDER_DELIVERED",
            "order_status_delivered",
            "orderStatus is not ORDER_DELIVERED; dispatch alone cannot support an autonomous defense",
        )
        files = pack.upload_files
        need(0 < len(files) <= MAX_UPLOAD_FILES, "file_count", f"pack must have 1–{MAX_UPLOAD_FILES} upload files")
        need(all(f["size"] <= MAX_FILE_BYTES for f in files), "file_size", "a pack file exceeds 5,000,000 bytes")
        need(
            all(f["mime"] in UPLOADABLE for f in files),
            "file_types",
            "a pack file type is outside the simulator allowlist",
        )
        need(len(pack.comments) <= COMMENTS_MAX_CODE_POINTS, "comments_length", "comments exceed 240 code points")

    assessment = revalidate_case(session, settings, case)
    need(assessment["evidence_ready"], "evidence_ready", "evidence is not ready: " + "; ".join(assessment["blockers"]))

    open_review = session.scalar(
        select(StaffTask.id).where(StaffTask.case_id == case.id, StaffTask.kind == "review", StaffTask.status == "open")
    )
    need(open_review is None, "no_open_review", "a human review is open for this case")

    in_flight = session.scalars(
        select(Submission).where(Submission.case_id == case.id, Submission.verification_state.in_(IN_FLIGHT))
    ).all()
    others = [s for s in in_flight if resend_of is None or s.id != resend_of.id]
    need(not others, "no_in_flight_submission", "another submission is in flight; reconcile it first")

    status = ProviderDisputeStatus(case.provider_status)
    if status == ProviderDisputeStatus.POD_REJECT:
        # A resubmission belongs to an open correction round (one per MAX_POD_REPAIR_ROUNDS) and must
        # carry changed evidence: resending the rejected originals is never a repair (PRD 8.6).
        rejected = open_repair(session, case)
        need(
            rejected is not None and case.pod_repair_count <= settings.max_pod_repair_rounds,
            "repair_round_open",
            "no POD correction round is open (budget used or rejection not handled); human review required",
        )
        if rejected is not None and pack is not None:
            before = original_document_hashes(session.get(EvidencePack, rejected.pack_id))
            need(
                original_document_hashes(pack) != before,
                "evidence_changed",
                "the pack resends the rejected evidence unchanged; corrected proof is required",
            )
    else:
        need(
            status == ProviderDisputeStatus.NEW,
            "provider_state_eligible",
            f"provider status {case.provider_status} does not allow an upload",
        )
    return Decision(not reasons, reasons, checks)


def approval_payload_hash(case: Case, action: str) -> str:
    payload = {
        "case_id": case.id,
        "dispute_id": case.external_dispute_id,
        "mid": case.mid,
        "action": action,
        "amount_paise": case.amount_paise,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def check_concession(session: Session, case: Case, approval: Approval | None, reviewer_id: str) -> Decision:
    reasons: list[str] = []
    now = get_clock().now()
    if approval is None or approval.case_id != case.id:
        reasons.append("no approval for this case")
    else:
        if approval.consumed_at is not None:
            reasons.append("approval already used")
        if approval.expires_at <= now:
            reasons.append("approval expired")
        if approval.case_version != case.version:
            reasons.append("case changed since approval; approve again")
        if approval.action != "ACCEPT" or approval.payload_hash != approval_payload_hash(case, "ACCEPT"):
            reasons.append("approval does not match this exact concession")
        if approval.reviewer_user_id != reviewer_id:
            reasons.append("approval belongs to a different reviewer")
    if not deadline_open(case):
        reasons.append("response deadline has passed")
    if ProviderDisputeStatus(case.provider_status) not in (ProviderDisputeStatus.NEW, ProviderDisputeStatus.POD_REJECT):
        reasons.append(f"provider status {case.provider_status} does not allow concession")
    in_flight = session.scalar(
        select(Submission.id).where(Submission.case_id == case.id, Submission.verification_state.in_(IN_FLIGHT))
    )
    if in_flight:
        reasons.append("another submission is in flight; reconcile it first")
    return Decision(not reasons, reasons)


def refund_policy(case: Case) -> dict[str, Any]:
    """Dry run only. No refund provider exists or is ever called (PRD 5.2)."""
    status = ProviderDisputeStatus(case.provider_status)
    if status in OPEN_PROVIDER_STATES:
        return {
            "decision": "DENY_OPEN_DISPUTE",
            "dry_run": True,
            "reason": "Refunds are not allowed while the dispute is open.",
            "provider_status": case.provider_status,
        }
    return {
        "decision": "OUT_OF_SCOPE",
        "dry_run": True,
        "reason": "Refund handling after a dispute outcome is outside this prototype.",
        "provider_status": case.provider_status,
    }
