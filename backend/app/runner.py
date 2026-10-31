"""Event-triggered case runner (PRD Section 7, 10.3).

- Callers persist `PendingWork` in the same short transaction as the triggering event and
  commit *before* scheduling `process_case` (FastAPI BackgroundTasks).
- One in-memory asyncio.Lock per case. If a case is already being processed, a new trigger
  returns immediately: the holder re-checks pending work before releasing the lock, with no
  `await` between that final check and the release, so committed work is never stranded.
- No polling worker, no leases. A single startup recovery scan plus an explicit
  "resume pending work" action. One process only (UVICORN_WORKERS=1).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Case, PendingWork, Submission
from app.db.session import session_scope
from app.domain.clock import get_clock
from app.domain.enums import PendingStatus
from app.services.audit import audit

log = logging.getLogger(__name__)

MAX_ITEMS_PER_PASS = 25
NON_TERMINAL_SUBMISSION_STATES = ("pending", "sent", "acknowledged", "uncertain")

_locks: dict[str, asyncio.Lock] = {}
Handler = Callable[[Any, PendingWork], Awaitable[dict[str, Any] | None]]
_handlers: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn

    return register


def lock_for(case_id: str) -> asyncio.Lock:
    lock = _locks.get(case_id)
    if lock is None:
        lock = _locks[case_id] = asyncio.Lock()
    return lock


def enqueue(session: Session, case: Case, kind: str, payload: dict[str, Any] | None = None) -> PendingWork:
    """Persist pending work inside the caller's transaction. Caller commits, then schedules."""
    work = PendingWork(case_id=case.id, kind=kind, case_version=case.version, payload=payload or {})
    session.add(work)
    session.flush()
    return work


def schedule(background: BackgroundTasks, app: Any, case_id: str) -> None:
    background.add_task(process_case, app, case_id)


def _claim_next(case_id: str) -> str | None:
    with session_scope() as session:
        work = session.scalar(
            select(PendingWork)
            .where(PendingWork.case_id == case_id, PendingWork.status == PendingStatus.PENDING)
            .order_by(PendingWork.created_at, PendingWork.id)
        )
        if work is None:
            return None
        work.status = PendingStatus.RUNNING
        work.attempts += 1
        return work.id


def _finish(work_id: str, status: PendingStatus, result: dict[str, Any] | None, error: str | None) -> None:
    with session_scope() as session:
        work = session.get(PendingWork, work_id)
        if work is None:
            return
        work.status = status
        work.completed_at = get_clock().now()
        work.payload = {**work.payload, "result": result, "error": error}
        if error:
            audit(
                session,
                event_type="runner.work_failed",
                summary=f"{work.kind} failed: {error}",
                actor_type="system",
                case_id=work.case_id,
                data={"pending_work_id": work.id},
            )


async def _execute(app: Any, work_id: str) -> None:
    with session_scope() as session:
        work = session.get(PendingWork, work_id)
        assert work is not None
        session.expunge(work)
    fn = _handlers.get(work.kind)
    if fn is None:
        _finish(work_id, PendingStatus.FAILED, None, f"no handler for {work.kind}")
        return
    try:
        result = await fn(app, work)
    except Exception as exc:  # noqa: BLE001 - recorded, never silently dropped
        log.exception("pending work %s (%s) failed", work_id, work.kind)
        _finish(work_id, PendingStatus.FAILED, None, f"{type(exc).__name__}: {exc}")
        return
    _finish(work_id, PendingStatus.COMPLETED, result, None)


async def process_case(app: Any, case_id: str) -> None:
    lock = lock_for(case_id)
    if lock.locked():
        return  # the current holder re-checks pending work before releasing
    async with lock:
        for _ in range(MAX_ITEMS_PER_PASS):
            work_id = _claim_next(case_id)
            if work_id is None:
                break  # final check; release follows without an intervening await
            await _execute(app, work_id)


def cases_with_pending_work() -> list[str]:
    with session_scope() as session:
        return list(
            session.scalars(select(PendingWork.case_id).where(PendingWork.status == PendingStatus.PENDING).distinct())
        )


def recover_interrupted() -> dict[str, int]:
    """Make interrupted work resumable and queue reconciliation for in-flight submissions.
    Reconciliation always precedes any repeated write (PRD 10.3)."""
    counts = {"requeued_work": 0, "reconcile_submissions": 0}
    with session_scope() as session:
        for work in session.scalars(select(PendingWork).where(PendingWork.status == PendingStatus.RUNNING)):
            work.status = PendingStatus.PENDING
            counts["requeued_work"] += 1
            audit(
                session,
                event_type="runner.work_requeued",
                summary=f"Interrupted {work.kind} re-queued.",
                actor_type="system",
                case_id=work.case_id,
                data={"pending_work_id": work.id},
            )
        for sub in session.scalars(
            select(Submission).where(Submission.verification_state.in_(NON_TERMINAL_SUBMISSION_STATES))
        ):
            already = session.scalar(
                select(PendingWork).where(
                    PendingWork.case_id == sub.case_id,
                    PendingWork.kind == "reconcile_submission",
                    PendingWork.status == PendingStatus.PENDING,
                )
            )
            if already is None:
                case = session.get(Case, sub.case_id)
                assert case is not None
                enqueue(session, case, "reconcile_submission", {"submission_id": sub.id, "reason": "startup_recovery"})
                counts["reconcile_submissions"] += 1
    return counts


async def resume_all(app: Any) -> dict[str, Any]:
    counts: dict[str, Any] = recover_interrupted()
    cases = cases_with_pending_work()
    for case_id in cases:
        await process_case(app, case_id)
    counts["cases_processed"] = len(cases)
    return counts


def enqueue_continuation(session: Session, case: Case, trigger: str, *, mode: str = "live") -> PendingWork:
    """Event-triggered continuation. Coalesced: a still-pending agent run will see the newest state."""
    existing = session.scalar(
        select(PendingWork).where(
            PendingWork.case_id == case.id, PendingWork.kind == "agent_run", PendingWork.status == PendingStatus.PENDING
        )
    )
    if existing is not None and existing.payload.get("mode", "live") == mode:
        existing.payload = {**existing.payload, "coalesced": [*existing.payload.get("coalesced", []), trigger]}
        return existing
    return enqueue(session, case, "agent_run", {"trigger": trigger, "mode": mode})
