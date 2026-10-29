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


@handler("agent_run")
async def agent_run(app: Any, work: PendingWork) -> dict[str, Any]:
    """Deterministic re-evaluation first; then the model loop only when a reasoner is ready."""
    from app.agent.loop import run_agent
    from app.providers.router import ready_candidates
    from app.services.audit import audit

    settings = app.state.settings
    base = await evaluate(app, work)
    trigger = work.payload.get("trigger", "event")
    mode = work.payload.get("mode", "live")
    if mode == "fixture_replay":
        return {**base, "agent": await run_agent(app, work.case_id, trigger=trigger, mode="fixture_replay")}
    reason = None
    if not settings.agent_autorun and trigger != "manual_start":
        reason = "AGENT_AUTORUN=false"
    elif not ready_candidates(settings):
        reason = "no reasoner has passed a live smoke test (manual mode)"
    if reason:
        with session_scope() as session:
            audit(
                session,
                event_type="agent.not_run",
                summary=f"Agent not run: {reason}.",
                actor_type="system",
                case_id=work.case_id,
                data={"trigger": trigger},
            )
        return {**base, "agent": {"status": "not_run", "reason": reason}}
    return {**base, "agent": await run_agent(app, work.case_id, trigger=trigger, mode="live")}


@handler("transcribe_voice_note")
async def transcribe_voice_note(app: Any, work: PendingWork) -> dict[str, Any]:
    """Speech-to-text for one stored voice note. Idempotent: only an `awaiting_transcription` note runs."""
    from app.db.models import VoiceNote
    from app.providers.speech import SpeechError, build_speech_provider
    from app.services import testimony
    from app.services.storage import read_original

    note_id = work.payload["voice_note_id"]
    with session_scope() as session:
        note = session.get(VoiceNote, note_id)
        if note is None or note.stt_status != "awaiting_transcription":
            return {"skipped": True, "stt_status": getattr(note, "stt_status", None)}
        audio = read_original(app.state.settings, note.storage_key)
        locale = note.locale
    try:
        result = await build_speech_provider(app).transcribe(audio, locale)
    except SpeechError as exc:
        with session_scope() as session:
            note = session.get(VoiceNote, note_id)
            assert note is not None
            testimony.record_failure(session, note, exc.kind, str(exc))
            return {"stt_status": note.stt_status, "error": exc.kind}
    with session_scope() as session:
        note = session.get(VoiceNote, note_id)
        assert note is not None
        if note.stt_status != "awaiting_transcription":
            return {"skipped": True, "stt_status": note.stt_status}
        transcript = testimony.record_transcription(session, note, result)
        return {"stt_status": note.stt_status, "transcript_id": transcript.id if transcript else None}
