"""Optional n8n staff reminders (PRD 12.1, P0+).

n8n is only a scheduler. The backend starts it: when `request_evidence` creates a new request round,
a `staff.evidence_requested` trigger is persisted as an OutboxEvent in the same transaction and
dispatched to the n8n webhook by the event-triggered runner. n8n waits until `remind_at` and calls
`POST /api/cases/{id}/reminders`. The backend keeps all authority: it rechecks cancellation, picks
the recipient and template from the stored task, and delivers to the local in-app inbox only.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Case, Message, OutboxEvent, StaffReminder, StaffTask, VoiceNote
from app.db.session import session_scope
from app.domain.clock import get_clock
from app.domain.enums import PendingStatus, WorkflowState
from app.services import messaging
from app.services.audit import audit

log = logging.getLogger(__name__)

TRIGGER_EVENT = "staff.evidence_requested"
SERVICE_ACTOR = "n8n-reminder-service"
UNAVAILABLE_LABEL = "Reminder scheduling unavailable"

# Demo starter copy; needs native-speaker review before any real use (same caveat as messaging).
REMINDER_TEMPLATES: dict[str, dict[str, str]] = {
    "delivery_record": {
        "en-IN": "Reminder — order {order}: we are still waiting for the delivery receipt. Please send it.",
        "hi-IN": "रिमाइंडर — ऑर्डर {order}: डिलीवरी रसीद अभी तक नहीं मिली है। कृपया रसीद भेजें।",
        "mr-IN": "स्मरणपत्र — ऑर्डर {order}: डिलिव्हरी पावती अजून मिळालेली नाही. कृपया पावती पाठवा.",
    },
    "invoice": {
        "en-IN": "Reminder — order {order}: we are still waiting for the invoice. Please send it.",
        "hi-IN": "रिमाइंडर — ऑर्डर {order}: इनवॉइस अभी तक नहीं मिला है। कृपया इनवॉइस भेजें।",
        "mr-IN": "स्मरणपत्र — ऑर्डर {order}: इनव्हॉइस अजून मिळालेले नाही. कृपया इनव्हॉइस पाठवा.",
    },
    "order_linkage": {
        "en-IN": "Reminder — order {order}: we are still waiting for the document linking transaction {txn}.",
        "hi-IN": "रिमाइंडर — ऑर्डर {order}: लेनदेन {txn} से जोड़ने वाला दस्तावेज़ अभी तक नहीं मिला है।",
        "mr-IN": "स्मरणपत्र — ऑर्डर {order}: व्यवहार {txn} शी जोडणारे दस्तऐवज अजून मिळालेले नाही.",
    },
}


class ReminderError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def availability(settings: Settings) -> tuple[bool, str]:
    missing = [
        name
        for name, ok in (
            ("REMINDERS_ENABLED", settings.reminders_enabled),
            ("N8N_REMINDER_WEBHOOK_URL", bool(settings.n8n_reminder_webhook_url)),
            ("N8N_WEBHOOK_TOKEN", settings.n8n_webhook_token is not None),
            ("N8N_SERVICE_TOKEN", settings.n8n_service_token is not None),
        )
        if not ok
    ]
    if missing:
        return False, f"Reminders unavailable: set {', '.join(missing)}."
    return True, (
        f"n8n reminder trigger configured ({settings.n8n_reminder_webhook_url}); "
        f"one reminder {settings.reminder_delay_seconds}s after each staff request."
    )


def _iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


# --- Trigger: backend -> n8n -------------------------------------------------------------------


def create_trigger(session: Session, settings: Settings, case: Case, task: StaffTask) -> OutboxEvent | None:
    """Persist one trigger per task/round, in the caller's transaction. None when the feature is off."""
    if not availability(settings)[0] or task.kind != "evidence":
        return None
    dedup_key = f"n8n:{TRIGGER_EVENT}:{task.id}:{task.request_round}:1"
    existing = session.scalar(select(OutboxEvent).where(OutboxEvent.dedup_key == dedup_key))
    if existing is not None:
        return None
    event = OutboxEvent(case_id=case.id, event_type=TRIGGER_EVENT, dedup_key=dedup_key, payload={})
    session.add(event)
    session.flush()
    requested_at = task.created_at
    event.payload = {
        "trigger": {
            "event_id": event.id,  # stable: reused verbatim on every retry
            "event_type": TRIGGER_EVENT,
            "case_id": case.id,
            "staff_task_id": task.id,
            "request_round": task.request_round,
            "reminder_number": 1,
            "requested_at": _iso(requested_at),
            "remind_at": _iso(requested_at + timedelta(seconds=settings.reminder_delay_seconds)),
            "deadline_at": _iso(case.deadline_utc),
        }
    }
    audit(
        session,
        event_type="reminder.trigger_created",
        summary=f"Reminder trigger queued for n8n (due {event.payload['trigger']['remind_at']}).",
        actor_type="system",
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"outbox_event_id": event.id, "staff_task_id": task.id, "round": task.request_round},
    )
    return event


def _staff_replied_since(session: Session, task: StaffTask) -> bool:
    reply = session.scalar(
        select(Message.id).where(
            Message.case_id == task.case_id,
            Message.direction == "inbound",
            Message.sender_user_id == task.assignee_user_id,
            Message.created_at >= task.created_at,
        )
    )
    note = session.scalar(
        select(VoiceNote.id).where(
            VoiceNote.case_id == task.case_id,
            VoiceNote.staff_user_id == task.assignee_user_id,
            VoiceNote.created_at >= task.created_at,
        )
    )
    return reply is not None or note is not None


def cancellation_reason(session: Session, case: Case, task: StaffTask, request_round: int | None = None) -> str | None:
    """None while the task/round is still unresolved and remindable (PRD 12.1 cancellation rules)."""
    if request_round is not None and request_round != task.request_round:
        return "round_changed"
    if task.status != "open":
        return f"task_{task.status}"  # responded (reply/upload), resolved, ...
    latest_round = session.scalar(
        select(StaffTask.request_round)
        .where(
            StaffTask.case_id == case.id, StaffTask.requirement_id == task.requirement_id, StaffTask.kind == "evidence"
        )
        .order_by(StaffTask.request_round.desc())
    )
    if latest_round != task.request_round:
        return "superseded"
    if _staff_replied_since(session, task):
        return "staff_replied"
    if case.workflow_state != WorkflowState.WAITING_FOR_EVIDENCE:
        return f"case_{case.workflow_state.lower()}"
    if case.deadline_utc is None or get_clock().now() >= case.deadline_utc:
        return "deadline_passed"
    return None


def _http_client(app: Any, settings: Settings) -> httpx.AsyncClient:
    transport = getattr(app.state, "n8n_transport", None)  # tests inject httpx.MockTransport
    return httpx.AsyncClient(transport=transport, timeout=settings.n8n_trigger_timeout_seconds)


def _finish_trigger(event_id: str, status: str, error: str | None, summary: str, data: dict[str, Any]) -> None:
    with session_scope() as session:
        event = session.get(OutboxEvent, event_id)
        assert event is not None
        event.status = status
        event.last_error = error
        if status in ("delivered", "skipped"):
            event.completed_at = get_clock().now()
        audit(
            session,
            event_type=f"reminder.trigger_{status}",
            summary=summary,
            actor_type="system",
            case_id=event.case_id,
            data={"outbox_event_id": event_id, **data},
        )


async def dispatch_trigger(app: Any, event_id: str) -> dict[str, Any]:
    """POST the persisted trigger to n8n. Retries only transient failures, with the same event ID."""
    settings: Settings = app.state.settings
    with session_scope() as session:
        event = session.get(OutboxEvent, event_id)
        if event is None or event.status != PendingStatus.PENDING:
            return {"skipped": True, "status": getattr(event, "status", None)}
        trigger = dict(event.payload["trigger"])
        case = session.get(Case, event.case_id)
        task = session.get(StaffTask, trigger["staff_task_id"])
        reason = "case_or_task_missing" if case is None or task is None else cancellation_reason(session, case, task)
    if reason is not None:
        _finish_trigger(event_id, "skipped", reason, f"Reminder trigger not sent: {reason}.", {"reason": reason})
        return {"status": "skipped", "reason": reason}
    ok, detail = availability(settings)
    if not ok:
        _finish_trigger(event_id, "paused", detail, f"{UNAVAILABLE_LABEL}: {detail}", {})
        return {"status": "paused", "error": detail}

    assert settings.n8n_webhook_token is not None
    headers = {"Authorization": f"Bearer {settings.n8n_webhook_token.get_secret_value()}"}
    attempts, error = 0, ""
    async with _http_client(app, settings) as client:
        for attempt in range(settings.n8n_trigger_retries + 1):
            attempts += 1
            if attempt:
                await asyncio.sleep(settings.provider_retry_backoff_seconds * attempt)
            try:
                resp = await client.post(settings.n8n_reminder_webhook_url, json=trigger, headers=headers)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                error = f"{type(exc).__name__}: {exc}"
                continue
            if 200 <= resp.status_code < 300:
                error = ""
                break
            error = f"HTTP {resp.status_code}"
            if resp.status_code < 500:
                break  # authentication/configuration: never retried
    with session_scope() as session:
        event = session.get(OutboxEvent, event_id)
        assert event is not None
        event.attempts += attempts
    data = {"attempts": attempts, "event_id": trigger["event_id"]}
    if not error:
        # An acknowledgement means n8n received the trigger, not that a reminder was sent.
        _finish_trigger(event_id, "delivered", None, "n8n acknowledged the reminder trigger (scheduled).", data)
        return {"status": "delivered", "attempts": attempts}
    if error.startswith("HTTP 4"):
        _finish_trigger(event_id, "paused", error, f"{UNAVAILABLE_LABEL}: n8n rejected the trigger ({error}).", data)
        return {"status": "paused", "error": error, "attempts": attempts}
    _finish_trigger(event_id, "failed", error, f"{UNAVAILABLE_LABEL}: {error} after {attempts} attempts.", data)
    return {"status": "failed", "error": error, "attempts": attempts}


def retry_trigger(session: Session, case: Case, event_id: str, actor_id: str) -> OutboxEvent:
    """Explicit retry of an exhausted/paused trigger, with the same event identity (no new ID)."""
    event = session.get(OutboxEvent, event_id)
    if event is None or event.case_id != case.id or event.event_type != TRIGGER_EVENT:
        raise ReminderError(404, "reminder trigger not found")
    if event.status not in ("failed", "paused"):
        raise ReminderError(409, f"reminder trigger is {event.status}")
    event.status = PendingStatus.PENDING
    event.last_error = None
    audit(
        session,
        event_type="reminder.trigger_retry",
        summary="Reminder trigger retry requested.",
        actor_type="user",
        actor_id=actor_id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"outbox_event_id": event.id},
    )
    return event


# --- Callback: n8n -> backend ------------------------------------------------------------------


def authenticate_service(settings: Settings, authorization: str | None) -> str:
    ok, detail = availability(settings)
    if not ok:
        raise ReminderError(503, detail)
    assert settings.n8n_service_token is not None
    expected = f"Bearer {settings.n8n_service_token.get_secret_value()}"
    if not authorization or not hmac.compare_digest(authorization.strip().encode(), expected.encode()):
        raise ReminderError(401, "invalid or missing service credential")
    return SERVICE_ACTOR


def scoped_case_for_service(session: Session, settings: Settings, case_id: str) -> Case:
    allowed = {m.strip() for m in settings.reminder_merchant_mids.split(",") if m.strip()}
    case = session.get(Case, case_id)
    if case is None or case.mid not in allowed:
        raise ReminderError(404, "case not found")
    return case


def _view(reminder: StaffReminder) -> dict[str, Any]:
    return {
        "reminder_id": reminder.id,
        "status": reminder.status,
        "reason": reminder.reason,
        "message_id": reminder.message_id,
    }


def handle_callback(
    session: Session,
    settings: Settings,
    case: Case,
    *,
    staff_task_id: str,
    request_round: int,
    reminder_number: int,
    actor: str,
) -> tuple[int, dict[str, Any]]:
    """Persist one reminder intent per key. 202 queued | 200 already_processed | 200 skipped."""
    task = session.get(StaffTask, staff_task_id)
    if task is None or task.case_id != case.id or task.kind != "evidence":
        raise ReminderError(404, "staff task not found")
    if not 1 <= reminder_number <= settings.max_reminders_per_request_round:
        raise ReminderError(422, f"reminder_number must be 1..{settings.max_reminders_per_request_round}")
    key = f"{case.merchant_id}:{case.id}:{task.id}:{request_round}:{reminder_number}"
    existing = session.scalar(select(StaffReminder).where(StaffReminder.dedup_key == key))
    if existing is not None:
        return 200, {"result": "already_processed", **_view(existing)}

    reason = cancellation_reason(session, case, task, request_round)
    due = task.created_at + timedelta(seconds=settings.reminder_delay_seconds - settings.reminder_due_tolerance_seconds)
    if reason is None and get_clock().now() < due:
        reason = "not_due"
    if reason is not None:
        # Not persisted: cancellation is permanent and a not-due call may legitimately come again later.
        audit(
            session,
            event_type="reminder.skipped",
            summary=f"Reminder callback skipped: {reason}.",
            actor_type="service",
            actor_id=actor,
            case_id=case.id,
            merchant_id=case.merchant_id,
            data={"staff_task_id": task.id, "round": request_round, "reminder_number": reminder_number},
        )
        return 200, {"result": "skipped", "reason": reason}

    reminder = StaffReminder(
        merchant_id=case.merchant_id,
        case_id=case.id,
        staff_task_id=task.id,
        request_round=request_round,
        reminder_number=reminder_number,
        dedup_key=key,
        status="queued",
        actor=actor,
    )
    session.add(reminder)
    session.flush()  # the unique key backs up the caller's lock against concurrent duplicates
    audit(
        session,
        event_type="reminder.queued",
        summary="n8n reminder callback accepted; delivery rechecked before sending.",
        actor_type="service",
        actor_id=actor,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"reminder_id": reminder.id, "staff_task_id": task.id, "round": request_round},
    )
    return 202, {"result": "queued", **_view(reminder)}


def send_reminder(session: Session, reminder_id: str) -> dict[str, Any]:
    """Under the case lock: recheck cancellation, then place the reminder in the local inbox once."""
    reminder = session.get(StaffReminder, reminder_id)
    if reminder is None or reminder.status != "queued":
        return {"skipped": True, "status": getattr(reminder, "status", None)}
    case = session.get(Case, reminder.case_id)
    task = session.get(StaffTask, reminder.staff_task_id)
    assert case is not None and task is not None
    reason = cancellation_reason(session, case, task, reminder.request_round)
    reminder.completed_at = get_clock().now()
    if reason is not None:
        reminder.status, reminder.reason = "skipped", reason
        audit(
            session,
            event_type="reminder.skipped",
            summary=f"Reminder not sent: {reason}.",
            actor_type="service",
            actor_id=reminder.actor,
            case_id=case.id,
            merchant_id=case.merchant_id,
            data={"reminder_id": reminder.id, "staff_task_id": task.id},
        )
        return {"status": "skipped", "reason": reason}
    templates = REMINDER_TEMPLATES[task.requirement_id]
    message = Message(
        case_id=case.id,
        staff_task_id=task.id,
        recipient_user_id=task.assignee_user_id,
        direction="outbound",
        locale=task.locale,
        body=templates[task.locale].format(order=case.order_id, txn=case.transaction_id),
        delivery_state="queued",
        dedup_key=f"reminder:{reminder.dedup_key}",
    )
    session.add(message)
    session.flush()
    session.add(
        OutboxEvent(
            case_id=case.id,
            event_type="staff_message",
            dedup_key=f"outbox:{message.id}",
            payload={"message_id": message.id},
        )
    )
    session.flush()
    messaging.deliver_outbox(session, case.id)
    reminder.status, reminder.message_id = "sent", message.id
    audit(
        session,
        event_type="reminder.sent",
        summary=f"Reminder placed in the staff inbox ({task.locale}, round {task.request_round}; no WhatsApp).",
        actor_type="service",
        actor_id=reminder.actor,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"reminder_id": reminder.id, "message_id": message.id, "staff_task_id": task.id},
    )
    return {"status": "sent", "message_id": message.id}


def task_reminders(session: Session, case: Case) -> dict[str, dict[str, Any]]:
    """Per staff task: trigger delivery state and reminder results, for the inbox view."""
    out: dict[str, dict[str, Any]] = {}
    for event in session.scalars(
        select(OutboxEvent).where(OutboxEvent.case_id == case.id, OutboxEvent.event_type == TRIGGER_EVENT)
    ):
        trigger = event.payload.get("trigger", {})
        out.setdefault(trigger.get("staff_task_id", ""), {"reminders": []})["trigger"] = {
            "id": event.id,
            "status": event.status,
            "remind_at": trigger.get("remind_at"),
            "attempts": event.attempts,
            "error": event.last_error,
            "label": UNAVAILABLE_LABEL if event.status in ("failed", "paused") else None,
        }
    for r in session.scalars(select(StaffReminder).where(StaffReminder.case_id == case.id)):
        out.setdefault(r.staff_task_id, {"reminders": []})["reminders"].append(
            {**_view(r), "reminder_number": r.reminder_number, "created_at": r.created_at}
        )
    return out
