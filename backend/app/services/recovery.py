"""Single startup recovery scan (PRD Section 7). No polling worker.

M0 scope: count interrupted/pending work and record it. Actual resume/reconciliation of
runs, outbox messages and uncertain submissions is implemented with the runner in M2.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AgentRun, OutboxEvent, PendingWork, Submission
from app.domain.enums import PendingStatus
from app.services.audit import audit

_ACTIVE = (PendingStatus.PENDING, PendingStatus.RUNNING)


def scan_pending(session: Session) -> dict[str, int]:
    def count(stmt) -> int:  # type: ignore[no-untyped-def]
        return int(session.scalar(stmt) or 0)

    return {
        "pending_work": count(select(func.count()).select_from(PendingWork).where(PendingWork.status.in_(_ACTIVE))),
        "outbox": count(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status.in_(_ACTIVE))),
        "interrupted_runs": count(
            select(func.count()).select_from(AgentRun).where(AgentRun.status == PendingStatus.RUNNING)
        ),
        "uncertain_submissions": count(
            select(func.count()).select_from(Submission).where(Submission.verification_state == "uncertain")
        ),
    }


def startup_recovery_scan(session: Session) -> dict[str, int]:
    counts = scan_pending(session)
    if any(counts.values()):
        audit(
            session,
            event_type="system.recovery_scan",
            summary="Startup recovery scan found pending work (resume is implemented in M2).",
            actor_type="system",
            data=counts,
        )
    return counts
