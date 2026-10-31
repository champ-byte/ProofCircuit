"""Bounded agent loop: observe -> propose -> validate -> authorize -> execute -> re-read (PRD 9).

Bounds: AGENT_MAX_STEPS proposals per run, AGENT_MAX_SCHEMA_REPAIRS re-asks per response,
AGENT_TIMEOUT_SECONDS per run, and a stop after repeated denials. Waiting states return control
without further model calls; a new event (staff reply, upload, review, webhook) starts a new run.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select

from app.agent.prompt import SYSTEM_PROMPT, observation, user_prompt
from app.agent.schema import ACTION_JSON_SCHEMA, InvalidModelOutput, parse_action
from app.agent.tools import ToolContext, dispatch
from app.db.models import AgentRun, Case, StaffTask
from app.db.session import session_scope
from app.domain.clock import get_clock
from app.domain.enums import OperationalFlag, WorkflowState
from app.providers.base import Completion, Reasoner, ReasonerError
from app.providers.router import ReasonerUnavailable, build_reasoner, call_once, complete_routed
from app.services.audit import audit
from app.services.messaging import request_human_review
from app.services.policy import deadline_open
from app.services.workflow import add_flag, sync_workflow

IDLE_STATES = {
    WorkflowState.CLOSED: "case closed",
    WorkflowState.MONITORING: "submission verified; waiting for the provider outcome",
    WorkflowState.SUBMITTING: "submission in progress",
    WorkflowState.SUBMISSION_UNCERTAIN: "reconciliation in progress",
}


def idle_reason(session: Any, case: Case) -> str | None:
    """Nothing for a model to decide: return control without spending an inference call."""
    if case.workflow_state in IDLE_STATES:
        return IDLE_STATES[WorkflowState(case.workflow_state)]
    if not deadline_open(case):
        return "deadline passed"
    open_kinds = set(
        session.scalars(select(StaffTask.kind).where(StaffTask.case_id == case.id, StaffTask.status == "open"))
    )
    if "review" in open_kinds:
        return "waiting for human review"
    if "evidence" in open_kinds:
        return "waiting for staff evidence"
    return None


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "status",
        "created",
        "round",
        "reasons",
        "version",
        "order_status",
        "receipt",
        "provider_status",
        "evidence_ready",
        "workflow_state",
        "denied",
        "error",
    )
    return {k: result[k] for k in keep if k in result}


def _finish(run_id: str, status: str, error: str | None = None) -> None:
    with session_scope() as session:
        run = session.get(AgentRun, run_id)
        if run is not None:
            run.status = status
            run.error = error
            run.finished_at = get_clock().now()


def _escalate(settings: Any, case_id: str, reason_code: str, question: str, flag: bool = False) -> None:
    with session_scope() as session:
        case = session.get(Case, case_id)
        assert case is not None
        if flag:
            add_flag(case, OperationalFlag.AGENT_LIMIT_REACHED)
        request_human_review(
            session, case, reason_code=reason_code, question=question, source_ids=[], actor_type="agent", actor_id=None
        )
        sync_workflow(session, settings, case)


async def run_agent(app: Any, case_id: str, *, trigger: str, mode: str = "live") -> dict[str, Any]:
    settings = app.state.settings
    replay: Reasoner | None = build_reasoner(app, "replay") if mode == "fixture_replay" else None
    with session_scope() as session:
        case = session.get(Case, case_id)
        assert case is not None
        reason = idle_reason(session, case)
        if reason is not None:
            audit(
                session,
                event_type="agent.idle",
                summary=f"Agent not run: {reason}.",
                actor_type="agent",
                case_id=case.id,
                merchant_id=case.merchant_id,
                data={"trigger": trigger},
            )
            return {"status": "idle", "reason": reason}
        run = AgentRun(
            case_id=case.id,
            provider=replay.name if replay else settings.reasoner_provider,
            model=None,
            mode=mode,
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id
        audit(
            session,
            event_type="agent.run_started",
            summary=f"Agent run started ({'Fixture replay' if replay else 'live model'}; trigger: {trigger}).",
            actor_type="agent",
            case_id=case.id,
            merchant_id=case.merchant_id,
            data={"run_id": run_id, "mode": mode, "trigger": trigger},
        )

    try:
        return await _steps(app, settings, case_id, run_id, replay)
    except Exception as exc:
        # Never leave a run "running": close it, record why, and let the runner record the failure.
        detail = f"{type(exc).__name__}: {exc}"[:500]
        _finish(run_id, "failed", detail)
        with session_scope() as session:
            audit(
                session,
                event_type="agent.run_failed",
                summary=f"Agent run failed unexpectedly: {detail}",
                actor_type="agent",
                case_id=case_id,
                data={"run_id": run_id},
            )
        raise


async def _steps(app: Any, settings: Any, case_id: str, run_id: str, replay: Reasoner | None) -> dict[str, Any]:
    started = time.monotonic()
    history: list[dict[str, Any]] = []
    denials = 0
    for step in range(1, settings.agent_max_steps + 1):
        if time.monotonic() - started > settings.agent_timeout_seconds:
            _escalate(settings, case_id, "agent_timeout", "Agent run exceeded its time budget.", flag=True)
            _finish(run_id, "limit_reached", "run timeout")
            return {"status": "limit_reached", "run_id": run_id, "reason": "timeout"}
        with session_scope() as session:
            case = session.get(Case, case_id)
            assert case is not None
            if step > 1 and (reason := idle_reason(session, case)) is not None:
                _finish(run_id, "waiting" if "waiting" in reason else "completed", None)
                return {"status": "stopped", "run_id": run_id, "reason": reason, "steps": step - 1}
            ctx, untrusted = observation(session, case)

        proposal = None
        repair: str | None = None
        for _attempt in range(settings.agent_max_schema_repairs + 1):
            prompt = user_prompt(ctx, untrusted, history, repair)
            try:
                completion, reasoner = await _infer(app, replay, prompt, run_id, case_id)
            except ReasonerUnavailable as exc:
                with session_scope() as session:
                    audit(
                        session,
                        event_type="agent.reasoner_unavailable",
                        summary="Reasoner unavailable: " + "; ".join(exc.reasons) + ". Manual operation still works.",
                        actor_type="agent",
                        case_id=case_id,
                        data={"run_id": run_id, "reasons": exc.reasons},
                    )
                _finish(run_id, "paused_reasoner_unavailable", "; ".join(exc.reasons))
                return {"status": "paused_reasoner_unavailable", "run_id": run_id, "reasons": exc.reasons}
            with session_scope() as session:
                run = session.get(AgentRun, run_id)
                assert run is not None
                run.model_calls += 1
                run.provider = reasoner.name
                run.model = completion.model_returned
            try:
                proposal = parse_action(completion.text)
                break
            except InvalidModelOutput as exc:
                repair = str(exc)[:400]
                with session_scope() as session:
                    audit(
                        session,
                        event_type="agent.invalid_output",
                        summary=f"Model output rejected: {repair}",
                        actor_type="agent",
                        case_id=case_id,
                        data={"run_id": run_id, "step": step},
                    )
        if proposal is None:
            _escalate(
                settings,
                case_id,
                "agent_output_invalid",
                "The model did not return a valid action after bounded repairs.",
            )
            _finish(run_id, "failed", "invalid model output after repairs")
            return {"status": "failed", "run_id": run_id, "reason": "invalid output"}

        ctx_tool = ToolContext(case_id=case_id, run_id=run_id, actor_kind="agent")
        outcome = await dispatch(
            app,
            ctx_tool,
            step=step,
            tool_name=proposal.action,
            arguments=proposal.arguments,
            rationale=proposal.reason,
            source_ids=proposal.source_ids,
        )
        history.append(
            {
                "step": step,
                "tool": proposal.action,
                "arguments": proposal.arguments,
                "status": outcome["status"],
                "result": _summary(outcome["result"]),
            }
        )
        if outcome["status"] == "denied":
            denials += 1
            if denials >= settings.agent_max_consecutive_denials:
                _escalate(
                    settings,
                    case_id,
                    "agent_repeated_denials",
                    f"The agent's proposals were denied {denials} times in a row; a person should decide.",
                )
                _finish(run_id, "stopped_denied", "repeated denials")
                return {"status": "stopped_denied", "run_id": run_id, "steps": step}
        else:
            denials = 0
        if proposal.action == "wait_for_event" and outcome["status"] == "ok":
            # A denied wait (e.g. invalid arguments) does not end the run: the model sees the denial
            # in RUN_HISTORY and may correct it, within the proposal and denial budgets.
            _finish(run_id, "waiting")
            return {"status": "waiting", "run_id": run_id, "steps": step}

    _escalate(
        settings,
        case_id,
        "agent_limit_reached",
        f"Agent used its {settings.agent_max_steps}-proposal budget.",
        flag=True,
    )
    _finish(run_id, "limit_reached", "proposal budget exhausted")
    return {"status": "limit_reached", "run_id": run_id}


async def _infer(
    app: Any, replay: Reasoner | None, prompt: str, run_id: str, case_id: str
) -> tuple[Completion, Reasoner]:
    if replay is not None:
        try:
            completion = await call_once(
                app,
                replay,
                system=SYSTEM_PROMPT,
                user=prompt,
                schema=ACTION_JSON_SCHEMA,
                purpose="propose",
                run_id=run_id,
                case_id=case_id,
            )
        except ReasonerError as exc:
            raise ReasonerUnavailable([f"replay: {exc}"]) from exc
        return completion, replay
    completion, reasoner, notes = await complete_routed(
        app,
        system=SYSTEM_PROMPT,
        user=prompt,
        schema=ACTION_JSON_SCHEMA,
        purpose="propose",
        run_id=run_id,
        case_id=case_id,
    )
    if notes:
        with session_scope() as session:
            audit(
                session,
                event_type="agent.reasoner_fallback",
                summary=f"Used {reasoner.name} after: " + "; ".join(notes),
                actor_type="agent",
                case_id=case_id,
                data={"run_id": run_id, "notes": notes, "used": reasoner.name},
            )
    return completion, reasoner
