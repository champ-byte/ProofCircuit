"""Bounded POD self-healing: one correction round after a recognized rejection (PRD 8.6, C07).

On an authoritative read of `POD_REJECT` with a nonempty `comment`, for the latest verified DEFEND:
- the raw status/comment is stored on that submission as a handled-rejection marker (once only);
- if the deadline is open, the rejected pack is the latest one and the repair budget remains, the
  backend opens one correction round: a staff task carrying the provider's exact reason (quoted,
  untrusted text), MONITORING -> WAITING_FOR_EVIDENCE;
- otherwise (no reason, expired deadline, repeat rejection, older pack) a person reviews it.
Resubmission then needs new evidence, a new pack and the normal policy gate (see policy.check_defense).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Case, EvidencePack, StaffTask, Submission
from app.domain.clock import get_clock
from app.services import messaging
from app.services.audit import audit

MAX_REASON_CHARS = 246  # the Status API documents `comment` as string(246)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_reason(comment: str | None) -> str:
    """Provider text is untrusted: strip control characters, collapse whitespace, cap the length."""
    return " ".join(_CONTROL.sub(" ", comment or "").split())[:MAX_REASON_CHARS]


def rejected_submission(session: Session, case: Case) -> Submission | None:
    """The latest verified DEFEND: the pack a POD_REJECT refers to. Ordered by pack version, which is
    strictly increasing per case (timestamps can tie)."""
    return session.scalar(
        select(Submission)
        .join(EvidencePack, EvidencePack.id == Submission.pack_id)
        .where(
            Submission.case_id == case.id,
            Submission.action == "DEFEND",
            Submission.verification_state == "verified",
        )
        .order_by(EvidencePack.version.desc())
    )


def open_repair(session: Session, case: Case) -> Submission | None:
    """The rejected submission whose correction round is in progress, if any."""
    sub = rejected_submission(session, case)
    marker = (sub.provider_rejection or {}) if sub else {}
    if sub is not None and marker.get("handled") == "repair" and marker.get("repair_round") == case.pod_repair_count:
        return sub
    return None


def original_document_hashes(pack: EvidencePack | None) -> set[str]:
    """Supporting originals in a pack (the generated cover is excluded: it changes with any case edit)."""
    if pack is None:
        return set()
    return {f["sha256"] for f in pack.upload_files if f.get("role") != "summary"}


def handle_pod_rejection(session: Session, settings: Settings, case: Case, read_body: dict[str, Any]) -> dict[str, Any]:
    from app.runner import enqueue  # runner imports services; keep this import local
    from app.services import reminders

    sub = rejected_submission(session, case)
    if sub is None:
        messaging.request_human_review(
            session,
            case,
            reason_code="pod_rejection_unmatched",
            question="The provider reports POD_REJECT, but no verified submission of this case matches it.",
            source_ids=[],
            actor_type="system",
            actor_id=None,
        )
        return {"status": "review", "reason": "no verified submission"}
    if sub.provider_rejection is not None:
        return {"status": "already_handled", "handled": sub.provider_rejection.get("handled")}  # duplicate/stale

    reason = clean_reason(read_body.get("comment"))
    problems = []
    if not reason:
        problems.append("the rejection has no reason")
    if get_clock().now() >= case.deadline_utc:  # policy imports this module, so no deadline_open here
        problems.append("the response deadline has passed")
    if case.pod_repair_count >= settings.max_pod_repair_rounds:
        problems.append(f"the correction budget ({settings.max_pod_repair_rounds} round) is used: repeat rejection")
    if sub.pack_id != case.latest_pack_id:
        problems.append("the rejected pack is not the latest pack")

    marker: dict[str, Any] = {
        "comment": reason,
        "status_raw": read_body.get("disputeStatus"),
        "at": get_clock().now().isoformat(),
        "pack_id": sub.pack_id,
    }
    if problems:
        sub.provider_rejection = {**marker, "handled": "review", "problems": problems}
        messaging.request_human_review(
            session,
            case,
            reason_code="pod_rejection",
            question=f"Provider rejected the proof (“{reason or 'no reason given'}”); no automatic correction: "
            + "; ".join(problems)
            + ".",
            source_ids=[],
            actor_type="system",
            actor_id=None,
        )
        audit(
            session,
            event_type="repair.not_started",
            summary="POD rejection needs a person: " + "; ".join(problems) + ".",
            actor_type="system",
            case_id=case.id,
            merchant_id=case.merchant_id,
            data={"submission_id": sub.id, **marker, "problems": problems},
        )
        return {"status": "review", "problems": problems}

    case.pod_repair_count += 1
    sub.provider_rejection = {**marker, "handled": "repair", "repair_round": case.pod_repair_count}
    case.version += 1  # the correction round is a new case state; earlier packs are stale
    task, created = messaging.request_evidence(
        session,
        case,
        "delivery_record",
        actor_type="system",
        actor_id=None,
        provider_reason=reason,
    )
    audit(
        session,
        event_type="repair.started",
        summary=f"POD rejected: “{reason}”. Correction round {case.pod_repair_count} of "
        f"{settings.max_pod_repair_rounds}: corrected delivery proof requested.",
        actor_type="system",
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"submission_id": sub.id, "staff_task_id": task.id, **marker, "round": case.pod_repair_count},
    )
    if created:
        enqueue(session, case, "deliver_outbox", {"staff_task_id": task.id})
        trigger = reminders.create_trigger(session, settings, case, task)
        if trigger is not None:
            enqueue(session, case, "dispatch_reminder_trigger", {"outbox_event_id": trigger.id})
    return {"status": "repair_started", "staff_task_id": task.id, "round": case.pod_repair_count}


def repair_task(session: Session, case: Case) -> StaffTask | None:
    """The staff task opened for the current correction round (carries the provider reason)."""
    return session.scalar(
        select(StaffTask)
        .where(StaffTask.case_id == case.id, StaffTask.kind == "evidence", StaffTask.provider_reason.is_not(None))
        .order_by(StaffTask.request_round.desc())
    )
