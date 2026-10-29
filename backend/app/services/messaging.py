"""Staff evidence requests and the local in-app inbox (PRD 8.2, 13.3).

Recipients come from configured staff roles, never from model-supplied contacts. Messages are
delivered to the in-app staff inbox only; nothing here sends WhatsApp/SMS. Templates are demo
starter copy and need native-speaker review before any real use.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, Case, ChecklistItem, DemoUser, Message, OutboxEvent, StaffTask
from app.domain.clock import get_clock
from app.services.audit import audit

LOCALES = ("en-IN", "hi-IN", "mr-IN")
REQUIREMENT_STAFF = {"delivery_record": "delivery", "invoice": "billing", "order_linkage": "billing"}

TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "delivery_record": {
        "missing": {
            "en-IN": "Order {order}: the delivery receipt is not available. Please send the correct receipt.",
            "hi-IN": "ऑर्डर {order}: इस ऑर्डर की डिलीवरी रसीद उपलब्ध नहीं है। कृपया सही रसीद भेजें।",
            "mr-IN": "ऑर्डर {order}: या ऑर्डरची डिलिव्हरी पावती उपलब्ध नाही. कृपया योग्य पावती पाठवा.",
        },
        "wrong": {
            "en-IN": (
                "Order {order}: the receipt sent is for a different order. "
                "Please send the delivery receipt for {order}."
            ),
            "hi-IN": "ऑर्डर {order}: भेजी गई रसीद किसी दूसरे ऑर्डर की है। कृपया {order} की सही डिलीवरी रसीद भेजें।",
            "mr-IN": "ऑर्डर {order}: पाठवलेली पावती दुसऱ्या ऑर्डरची आहे. कृपया {order} ची योग्य डिलिव्हरी पावती पाठवा.",
        },
    },
    "invoice": {
        "missing": {
            "en-IN": "Order {order}: the invoice is not available. Please send the invoice for this order.",
            "hi-IN": "ऑर्डर {order}: इस ऑर्डर का इनवॉइस उपलब्ध नहीं है। कृपया इनवॉइस भेजें।",
            "mr-IN": "ऑर्डर {order}: या ऑर्डरचे इनव्हॉइस उपलब्ध नाही. कृपया इनव्हॉइस पाठवा.",
        },
        "wrong": {
            "en-IN": "Order {order}: the invoice sent does not match this order. Please send the invoice for {order}.",
            "hi-IN": "ऑर्डर {order}: भेजा गया इनवॉइस इस ऑर्डर से मेल नहीं खाता। कृपया {order} का इनवॉइस भेजें।",
            "mr-IN": "ऑर्डर {order}: पाठवलेले इनव्हॉइस या ऑर्डरशी जुळत नाही. कृपया {order} चे इनव्हॉइस पाठवा.",
        },
    },
    "order_linkage": {
        "missing": {
            "en-IN": "Order {order}: please send a document linking transaction {txn} to this order.",
            "hi-IN": "ऑर्डर {order}: कृपया लेनदेन {txn} को इस ऑर्डर से जोड़ने वाला दस्तावेज़ भेजें।",
            "mr-IN": "ऑर्डर {order}: कृपया व्यवहार {txn} या ऑर्डरशी जोडणारे दस्तऐवज पाठवा.",
        },
    },
}


class MessagingError(ValueError):
    pass


def _staff_for(session: Session, case: Case, function: str) -> DemoUser | None:
    return session.scalar(
        select(DemoUser).where(
            DemoUser.merchant_id == case.merchant_id, DemoUser.role == "staff", DemoUser.staff_function == function
        )
    )


def request_evidence(
    session: Session,
    case: Case,
    requirement_id: str,
    *,
    assignee_id: str | None = None,
    locale: str | None = None,
    actor_type: str,
    actor_id: str | None,
) -> tuple[StaffTask, bool]:
    """Create one staff task + one local message per (case, requirement, round). Returns (task, created)."""
    if requirement_id not in REQUIREMENT_STAFF:
        raise MessagingError(f"unknown requirement {requirement_id}")
    staff = _staff_for(session, case, REQUIREMENT_STAFF[requirement_id])
    if staff is None:
        raise MessagingError(f"no configured staff for {requirement_id}")
    if assignee_id is not None and assignee_id not in (staff.id, staff.handle):
        raise MessagingError("assignee must be the configured staff role for this requirement")
    if locale is not None and locale not in LOCALES:
        raise MessagingError(f"locale must be one of {LOCALES}")

    tasks = session.scalars(
        select(StaffTask)
        .where(StaffTask.case_id == case.id, StaffTask.requirement_id == requirement_id, StaffTask.kind == "evidence")
        .order_by(StaffTask.request_round.desc())
    ).all()
    if tasks and tasks[0].status == "open":
        return tasks[0], False  # deduplicated: the open request already covers this round
    round_no = (tasks[0].request_round + 1) if tasks else 1

    item = session.scalar(
        select(ChecklistItem).where(ChecklistItem.case_id == case.id, ChecklistItem.requirement_id == requirement_id)
    )
    situation = "wrong" if item is not None and item.status == "conflicting" else "missing"
    templates = TEMPLATES[requirement_id].get(situation) or TEMPLATES[requirement_id]["missing"]
    use_locale = locale or staff.locale
    body = templates[use_locale].format(order=case.order_id, txn=case.transaction_id)

    task = StaffTask(
        case_id=case.id,
        merchant_id=case.merchant_id,
        assignee_user_id=staff.id,
        requirement_id=requirement_id,
        kind="evidence",
        request_round=round_no,
        locale=use_locale,
        status="open",
        dedup_key=f"{case.id}:{requirement_id}:{round_no}",
    )
    session.add(task)
    session.flush()
    message = Message(
        case_id=case.id,
        staff_task_id=task.id,
        recipient_user_id=staff.id,
        direction="outbound",
        locale=use_locale,
        body=body,
        delivery_state="queued",
        dedup_key=f"msg:{task.dedup_key}",
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
    audit(
        session,
        event_type="evidence.requested",
        summary=(
            f"Requested {requirement_id.replace('_', ' ')} from {staff.display_name} ({use_locale}, round {round_no})."
        ),
        actor_type=actor_type,
        actor_id=actor_id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"staff_task_id": task.id, "message_id": message.id, "situation": situation, "round": round_no},
    )
    return task, True


def deliver_outbox(session: Session, case_id: str) -> int:
    """Deliver queued messages to the local in-app inbox (never an external channel)."""
    delivered = 0
    for event in session.scalars(
        select(OutboxEvent).where(OutboxEvent.case_id == case_id, OutboxEvent.status == "pending")
    ):
        message = session.get(Message, event.payload.get("message_id"))
        if message is not None and message.delivery_state == "queued":
            message.delivery_state = "sent_in_simulator"
            delivered += 1
            audit(
                session,
                event_type="message.delivered_local",
                summary="Message placed in the in-app staff inbox (simulated; no WhatsApp).",
                actor_type="system",
                case_id=case_id,
                data={"message_id": message.id},
            )
        event.status = "completed"
        event.completed_at = get_clock().now()
        event.attempts += 1
    return delivered


def mark_staff_response(session: Session, case: Case, staff_user_id: str) -> list[str]:
    tasks = session.scalars(
        select(StaffTask).where(
            StaffTask.case_id == case.id,
            StaffTask.assignee_user_id == staff_user_id,
            StaffTask.kind == "evidence",
            StaffTask.status == "open",
        )
    ).all()
    for t in tasks:
        t.status = "responded"
        t.resolved_at = get_clock().now()
    return [t.id for t in tasks]


def staff_reply(session: Session, case: Case, staff: DemoUser, body: str) -> Message:
    message = Message(
        case_id=case.id,
        sender_user_id=staff.id,
        direction="inbound",
        locale=staff.locale,
        body=body,
        delivery_state="received",
    )
    session.add(message)
    session.flush()
    responded = mark_staff_response(session, case, staff.id)
    case.version += 1
    audit(
        session,
        event_type="staff.replied",
        summary=f"{staff.display_name} replied in the staff inbox.",
        actor_type="user",
        actor_id=staff.id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"message_id": message.id, "responded_tasks": responded},
    )
    return message


def request_human_review(
    session: Session,
    case: Case,
    *,
    reason_code: str,
    question: str,
    source_ids: list[str],
    actor_type: str,
    actor_id: str | None,
) -> tuple[StaffTask, bool]:
    reviewer = session.scalar(
        select(DemoUser).where(DemoUser.merchant_id == case.merchant_id, DemoUser.role == "reviewer")
    )
    if reviewer is None:
        raise MessagingError("no reviewer configured")
    existing = session.scalar(
        select(StaffTask).where(
            StaffTask.case_id == case.id,
            StaffTask.kind == "review",
            StaffTask.status == "open",
            StaffTask.requirement_id == f"review:{reason_code}",
        )
    )
    if existing is not None:
        return existing, False
    count = len(
        session.scalars(select(StaffTask.id).where(StaffTask.case_id == case.id, StaffTask.kind == "review")).all()
    )
    task = StaffTask(
        case_id=case.id,
        merchant_id=case.merchant_id,
        assignee_user_id=reviewer.id,
        requirement_id=f"review:{reason_code}",
        kind="review",
        request_round=count + 1,
        locale=reviewer.locale,
        status="open",
        dedup_key=f"{case.id}:review:{reason_code}:{count + 1}",
        provider_reason=None,
    )
    session.add(task)
    session.flush()
    audit(
        session,
        event_type="review.requested",
        summary=f"Human review requested: {question}",
        actor_type=actor_type,
        actor_id=actor_id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"staff_task_id": task.id, "reason_code": reason_code, "source_ids": source_ids, "question": question},
    )
    return task, True


def inbox(session: Session, case: Case) -> dict[str, Any]:
    users = {
        u.id: u.display_name for u in session.scalars(select(DemoUser).where(DemoUser.merchant_id == case.merchant_id))
    }
    tasks = session.scalars(select(StaffTask).where(StaffTask.case_id == case.id).order_by(StaffTask.created_at)).all()
    messages = session.scalars(select(Message).where(Message.case_id == case.id).order_by(Message.created_at)).all()
    questions = {
        e.data.get("staff_task_id"): e.data.get("question")
        for e in session.scalars(
            select(AuditEvent).where(AuditEvent.case_id == case.id, AuditEvent.event_type == "review.requested")
        )
    }
    return {
        "tasks": [
            {
                "id": t.id,
                "kind": t.kind,
                "requirement_id": t.requirement_id,
                "round": t.request_round,
                "assignee": users.get(t.assignee_user_id),
                "locale": t.locale,
                "status": t.status,
                "question": questions.get(t.id) if t.kind == "review" else None,
                "created_at": t.created_at,
            }
            for t in tasks
        ],
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "from": users.get(m.sender_user_id or ""),
                "to": users.get(m.recipient_user_id or ""),
                "locale": m.locale,
                "body": m.body,
                "delivery_state": m.delivery_state,
                "created_at": m.created_at,
            }
            for m in messages
        ],
    }
