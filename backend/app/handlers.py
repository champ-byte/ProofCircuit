"""Pending-work handlers executed by the runner under the per-case lock."""

from __future__ import annotations

from typing import Any

from app.agent.tools import ToolContext, dispatch
from app.db.models import AgentRun, Case, PendingWork
from app.db.session import session_scope
from app.domain.clock import get_clock
from app.domain.enums import PendingStatus, WorkflowState
from app.runner import handler
from app.services import messaging, submission
from app.services.workflow import set_state, sync_workflow


@handler("evaluate")
async def evaluate(app: Any, work: PendingWork) -> dict[str, Any]:
    """Deterministic re-evaluation after an event. The model-driven run replaces this in M3."""
    with session_scope() as session:
        case = session.get(Case, work.case_id)
        assert case is not None
        if case.workflow_state == WorkflowState.NEW:
            set_state(session, case, WorkflowState.COLLECTING, "case opened; collecting evidence")
        assessment = sync_workflow(session, app.state.settings, case)
        return {"workflow_state": case.workflow_state, "evidence_ready": assessment["evidence_ready"]}


@handler("tool")
async def run_tool(app: Any, work: PendingWork) -> dict[str, Any]:
    p = work.payload
    ctx = ToolContext(
        case_id=work.case_id, run_id=p["run_id"], actor_kind=p.get("actor_kind", "human"), actor_id=p.get("actor_id")
    )
    outcome = await dispatch(
        app,
        ctx,
        step=int(p.get("step", 1)),
        tool_name=p["tool"],
        arguments=p.get("arguments", {}),
        rationale=p.get("reason", ""),
        source_ids=p.get("source_ids"),
    )
    with session_scope() as session:
        run = session.get(AgentRun, p["run_id"])
        if run is not None and run.mode == "manual":
            run.status = PendingStatus.COMPLETED if outcome["status"] == "ok" else PendingStatus.FAILED
            run.finished_at = get_clock().now()
            run.error = None if outcome["status"] == "ok" else str(outcome["result"].get("reasons"))
    return outcome


@handler("deliver_outbox")
async def deliver(app: Any, work: PendingWork) -> dict[str, Any]:
    with session_scope() as session:
        return {"delivered": messaging.deliver_outbox(session, work.case_id)}


@handler("reconcile_submission")
async def reconcile(app: Any, work: PendingWork) -> dict[str, Any]:
    return await submission.reconcile_submission(app, work.payload["submission_id"], allow_resend=True)


@handler("reconcile_status")
async def reconcile_status(app: Any, work: PendingWork) -> dict[str, Any]:
    return await submission.refresh_status(app, work.case_id)


@handler("concede")
async def concede(app: Any, work: PendingWork) -> dict[str, Any]:
    return await submission.send_concession(app, work.payload["submission_id"])
