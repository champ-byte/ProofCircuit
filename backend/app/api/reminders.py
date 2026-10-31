"""n8n reminder command and trigger retry (PRD 11, 12.1). Our app API, not a Paytm endpoint."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Identity, get_db, get_settings_dep, require_role
from app.api.evidence import scoped_case
from app.config import Settings
from app.runner import enqueue, schedule
from app.services import reminders

router = APIRouter(prefix="/api", tags=["reminders"])

# Serializes check-then-insert for duplicate callbacks in this single process (UVICORN_WORKERS=1);
# the unique dedup key is the backstop.
_callback_lock = threading.Lock()


class ReminderCommand(BaseModel):
    staff_task_id: str = Field(min_length=1, max_length=64)
    request_round: int = Field(ge=1)
    reminder_number: int = Field(ge=1)


@router.post("/cases/{case_id}/reminders")
def reminder_command(
    case_id: str,
    cmd: ReminderCommand,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    """Called by n8n with N8N_SERVICE_TOKEN. Recipient, locale and text always come from the stored task."""
    try:
        actor = reminders.authenticate_service(settings, request.headers.get("authorization"))
        with _callback_lock:
            case = reminders.scoped_case_for_service(db, settings, case_id)
            status_code, body = reminders.handle_callback(
                db,
                settings,
                case,
                staff_task_id=cmd.staff_task_id,
                request_round=cmd.request_round,
                reminder_number=cmd.reminder_number,
                actor=actor,
            )
            if status_code == 202:
                enqueue(db, case, "send_reminder", {"reminder_id": body["reminder_id"]})
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                status_code, body = reminders.handle_callback(
                    db,
                    settings,
                    case,
                    staff_task_id=cmd.staff_task_id,
                    request_round=cmd.request_round,
                    reminder_number=cmd.reminder_number,
                    actor=actor,
                )
                db.commit()
    except reminders.ReminderError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    if status_code == 202:
        schedule(background, request.app, case.id)
    response.status_code = status_code
    return body


@router.post("/cases/{case_id}/reminder-triggers/{event_id}/retry", status_code=202)
def retry_reminder_trigger(
    case_id: str,
    event_id: str,
    request: Request,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("owner", "operator")),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    case = scoped_case(db, identity, case_id)
    try:
        event = reminders.retry_trigger(db, case, event_id, identity.user_id)
    except reminders.ReminderError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    enqueue(db, case, "dispatch_reminder_trigger", {"outbox_event_id": event.id})
    db.commit()
    schedule(background, request.app, case.id)
    return {"outbox_event_id": event.id, "status": event.status}
