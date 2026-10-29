"""Simulator HTTP boundary, mirroring Paytm paths under /api/simulator/v1/dispute/...

No Paytm host is ever called. Receipts and event injection are simulator-only extensions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.api.deps import Identity, get_db, get_settings_dep, require_role
from app.config import Settings
from app.db.models import Merchant, SimulatorDispute, SimulatorFault, SimulatorSubmission
from app.domain.clock import get_clock
from app.domain.paytm import format_naive_time
from app.simulator import service as sim
from app.simulator.signing import sign_body, sign_params, verify

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/simulator", tags=["paytm-simulator"])


def _secret(settings: Settings) -> str:
    return settings.demo_webhook_secret.get_secret_value()


# --- Status API (JSON in, JSON out) -----------------------------------------------------


@router.post("/v1/dispute/status")
async def dispute_status(
    request: Request,
    background: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None
    head = payload.get("head") if isinstance(payload, dict) else None
    body = payload.get("body") if isinstance(payload, dict) else None
    sig_ok = (
        isinstance(body, dict)
        and isinstance(head, dict)
        and verify(sign_body(_secret(settings), body), head.get("signature"))
    )
    resp_body, changed = sim.status_lookup(
        db, head=head, body=body, tz=settings.paytm_naive_timezone, signature_ok=sig_ok
    )
    db.commit()
    if changed and isinstance(body, dict):
        _queue_callback(background, request, settings, str(body.get("mid")), str(body.get("disputeId")))
    client_id = head.get("clientId") if isinstance(head, dict) else None
    return JSONResponse(
        {"head": sim.response_head(client_id, sign_body(_secret(settings), resp_body), ms=False), "body": resp_body}
    )


# --- Action API (multipart in, JSON out) ------------------------------------------------


@router.post("/v1/dispute/action")
async def dispute_action(
    request: Request,
    background: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db),
) -> Response:
    form = await request.form(max_files=50, max_fields=50)
    params: dict[str, str] = {}
    files: list[sim.UploadedFile] = []
    for key, value in form.multi_items():
        if isinstance(value, UploadFile):
            if key == "files":
                data = await value.read(sim.MAX_FILE_BYTES + 1)
                files.append(sim.UploadedFile(value.filename or "file", data, value.content_type))
        else:
            params[key] = str(value)
    sig_ok = verify(sign_params(_secret(settings), params), params.get("signature"))
    outcome = sim.perform_action(db, params=params, files=files, tz=settings.paytm_naive_timezone, signature_ok=sig_ok)
    db.commit()
    if outcome.status_changed:
        _queue_callback(background, request, settings, params["mid"], params["disputeId"])
    if outcome.result is None:
        # Simulated lost response: the effect happened but the caller gets no business response.
        return Response(status_code=504, content=b"", background=background)
    resp_body = {"resultInfo": outcome.result}
    return JSONResponse(
        {
            "head": sim.response_head(params.get("clientId"), sign_body(_secret(settings), resp_body), ms=True),
            "body": resp_body,
        },
        background=background,
    )


# --- Simulator-only receipts --------------------------------------------------------------


def _check_receipt_signature(request: Request, settings: Settings, params: dict[str, str]) -> None:
    if not verify(sign_params(_secret(settings), params), request.headers.get("x-demo-signature")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid demo signature")


@router.get("/receipts")
def list_receipts(
    mid: str,
    disputeId: str,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _check_receipt_signature(request, settings, {"mid": mid, "disputeId": disputeId})
    rows = db.scalars(
        select(SimulatorSubmission)
        .where(SimulatorSubmission.mid == mid, SimulatorSubmission.dispute_id == disputeId)
        .order_by(SimulatorSubmission.sequence)
    ).all()
    return [sim.receipt_view(r) for r in rows]


@router.get("/receipts/{reference}")
def get_receipt(
    reference: str, request: Request, settings: Settings = Depends(get_settings_dep), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _check_receipt_signature(request, settings, {"reference": reference})
    row = db.scalar(select(SimulatorSubmission).where(SimulatorSubmission.reference == reference))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "receipt not found")
    return sim.receipt_view(row)


# --- Demo drawer: event and fault injection ----------------------------------------------


class SimEvent(BaseModel):
    dispute_id: str
    type: str = Field(pattern="^(fault|pod_reject|outcome|resend_callback|create_dispute)$")
    api: str | None = Field(default=None, pattern="^(status|action)$")
    kind: str | None = None
    count: int = Field(default=1, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=246)
    outcome: str | None = None
    debit_amount: str | None = None
    dispute_utr: str | None = None
    lost_reason: str | None = None
    body: dict[str, Any] | None = None  # create_dispute only


@router.post("/events")
def inject_event(
    event: SimEvent,
    request: Request,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    merchant = db.get(Merchant, identity.merchant_id)
    assert merchant is not None
    tz = settings.paytm_naive_timezone
    if event.type == "create_dispute":
        if not event.body:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "body required")
        from app.domain.paytm import PaytmFieldError, normalize_callback_body

        body = {**event.body, "mid": merchant.mid, "disputeId": event.dispute_id, "disputeStatus": "NEW"}
        try:
            normalized = normalize_callback_body(body, tz)
        except PaytmFieldError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        if sim.find_dispute(db, merchant.mid, event.dispute_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "dispute exists")
        now = format_naive_time(get_clock().now(), tz)
        db.add(
            SimulatorDispute(
                mid=merchant.mid,
                dispute_id=event.dispute_id,
                body={**body, "disputeCreateDateTime": now, "disputeUpdateDateTime": now},
                dispute_status="NEW",
                event_sequence=1,
                due_at_utc=normalized.deadline_utc,
            )
        )
        db.commit()
        _queue_callback(background, request, settings, merchant.mid, event.dispute_id)
        return {"created": True}

    dispute = sim.find_dispute(db, merchant.mid, event.dispute_id)
    if dispute is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dispute not found")
    try:
        if event.type == "fault":
            allowed = sim.STATUS_FAULTS if event.api == "status" else sim.ACTION_FAULTS
            if event.api is None or event.kind not in allowed:
                raise ValueError(f"fault kind must be one of {allowed} for api={event.api}")
            db.add(
                SimulatorFault(
                    mid=dispute.mid,
                    dispute_id=dispute.dispute_id,
                    api=event.api,
                    kind=event.kind,
                    remaining=event.count,
                )
            )
            db.commit()
            return {"queued_fault": event.kind, "count": event.count}
        if event.type == "pod_reject":
            sim.inject_pod_reject(db, dispute, (event.comment or "").strip() or "Proof insufficient", tz)
        elif event.type == "outcome":
            fields: dict[str, Any] = {}
            if event.debit_amount:
                fields["debitAmount"] = event.debit_amount
            if event.dispute_utr:
                fields["disputeUtr"] = event.dispute_utr
            if event.lost_reason:
                fields["disputeLostReason"] = event.lost_reason
            sim.inject_outcome(db, dispute, event.outcome or "", tz, **fields)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    _queue_callback(background, request, settings, dispute.mid, dispute.dispute_id)
    return {"dispute_status": dispute.dispute_status, "sequence": dispute.event_sequence}


# --- S2S callbacks to the app ---------------------------------------------------------------


def _queue_callback(
    background: BackgroundTasks, request: Request, settings: Settings, mid: str, dispute_id: str
) -> None:
    background.add_task(send_callback, request.app, settings, mid, dispute_id)


async def send_callback(app: Any, settings: Settings, mid: str, dispute_id: str) -> None:
    """Chargeback Peon-style webhook for the dispute's *current* state. Best effort, like a real
    webhook: the app must still reconcile through the Status API."""
    from app.db.session import session_scope

    with session_scope() as session:
        dispute = sim.find_dispute(session, mid, dispute_id)
        if dispute is None:
            return
        body = sim.callback_body(dispute)
        sequence = dispute.event_sequence
    payload = {"head": {"version": "v1", "signature": sign_body(_secret(settings), body)}, "body": body}
    headers = {"X-Demo-Event-Id": f"{dispute_id}:{sequence}", "X-Demo-Sequence": str(sequence)}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app.internal") as client:
            await client.post("/api/dispute-events", json=payload, headers=headers)
    except Exception:  # webhook delivery is best effort
        log.exception("simulator callback delivery failed")
