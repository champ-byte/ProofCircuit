from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def audit(
    session: Session,
    *,
    event_type: str,
    summary: str,
    actor_type: str,
    actor_id: str | None = None,
    case_id: str | None = None,
    merchant_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        summary=summary,
        actor_type=actor_type,
        actor_id=actor_id,
        case_id=case_id,
        merchant_id=merchant_id,
        data=data or {},
    )
    session.add(event)
    return event
