"""Paytm Chargeback Peon-style S2S callback intake (PRD 8.1, 11.1).

`X-Demo-Event-Id` / `X-Demo-Sequence` are our simulator harness headers, not Paytm fields.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_settings_dep
from app.config import Settings
from app.db.models import Merchant, ProviderEvent
from app.domain.enums import DisputeReason, ProviderDisputeStatus
from app.domain.paytm import PaytmFieldError, canonical_hash, normalize_callback_body
from app.runner import enqueue, enqueue_continuation, schedule
from app.services.audit import audit
from app.services.intake import find_case, open_case, record_status_callback
from app.simulator.signing import sign_body, verify

router = APIRouter(prefix="/api", tags=["intake"])


@router.post("/dispute-events")
async def dispute_event(
    request: Request,
    background: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    try:
        payload = json.loads(await request.body())
        head, body = payload["head"], payload["body"]
        if not isinstance(head, dict) or not isinstance(body, dict):
            raise TypeError
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "expected {head, body} JSON") from exc

    demo_event_id = request.headers.get("x-demo-event-id")
    seq_header = request.headers.get("x-demo-sequence")
    demo_sequence = int(seq_header) if seq_header and seq_header.isdigit() else None
    secret = settings.demo_webhook_secret.get_secret_value()
    if not verify(sign_body(secret, body), head.get("signature")):
        db.add(
            ProviderEvent(
                source="s2s_callback",
                raw_payload=body,
                canonical_hash=canonical_hash(body),
                demo_event_id=demo_event_id,
                demo_sequence=demo_sequence,
                signature_valid=False,
            )
        )
        audit(
            db,
            event_type="provider.callback_rejected",
            summary="Webhook with invalid demo signature rejected.",
            actor_type="provider",
            data={"demo_event_id": demo_event_id},
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid signature")

    merchant = db.scalar(select(Merchant).where(Merchant.mid == str(body.get("mid"))))
    if merchant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown merchant")
    try:
        dispute = normalize_callback_body(body, settings.paytm_naive_timezone)
    except PaytmFieldError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    case = find_case(db, merchant.id, dispute.dispute_id)
    if case is None:
        if dispute.provider_status is not ProviderDisputeStatus.NEW:
            raise HTTPException(status.HTTP_409_CONFLICT, "first event for an unknown dispute must be NEW")
        # Paytm's broad disputeType never establishes "goods not received": a reviewer must confirm.
        case, _ = open_case(
            db,
            merchant=merchant,
            dispute=dispute,
            raw_body=body,
            source="s2s_callback",
            reason=DisputeReason.REQUIRES_REVIEW,
            owner_user_id=None,
            signature_valid=True,
        )
        db.flush()
        event = db.scalar(select(ProviderEvent).where(ProviderEvent.case_id == case.id))
        if event is not None:
            event.demo_event_id, event.demo_sequence = demo_event_id, demo_sequence
        enqueue_continuation(db, case, "case_opened")
        db.commit()
        schedule(background, request.app, case.id)
        return {"accepted": True, "case_id": case.id, "created": True, "duplicate": False}

    _, duplicate = record_status_callback(
        db, case=case, dispute=dispute, raw_body=body, demo_event_id=demo_event_id, demo_sequence=demo_sequence
    )
    if not duplicate:
        enqueue(db, case, "reconcile_status", {"trigger": "webhook", "demo_event_id": demo_event_id})
    db.commit()
    if not duplicate:
        schedule(background, request.app, case.id)
    return {"accepted": True, "case_id": case.id, "created": False, "duplicate": duplicate}
