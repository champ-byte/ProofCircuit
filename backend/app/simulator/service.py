"""Paytm-shaped dispute simulator (PRD Section 11.2, 11.3).

This module only reads/writes the simulator's own provider store (`sim_*` tables). App-side code
never writes those tables; it can only observe them through the simulator APIs.

Codes, lifecycle and the state-to-error mapping follow the PRD's simulator policy. Where Paytm's
documents are silent (error precedence, ACCEPT outside NEW/POD_REJECT, file-type allowlist),
the choices below are simulator assumptions, not verified Paytm production behavior.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SimulatorDispute, SimulatorFault, SimulatorSubmission
from app.domain.clock import get_clock
from app.domain.intent import intent_digest
from app.domain.paytm import format_naive_time

RESULT_CODES: dict[str, tuple[str, str, str]] = {
    # id: (status, code, message)
    "1001": ("S", "SUCCESS", "Success"),  # Status API lookup success
    "1001_UPLOAD": ("S", "UPLOADED_SUCCESS", "Files uploaded successfully"),
    "1002": ("A", "ACCEPTED_SUCCESS", "Request accepted"),
    "1003": ("S", "DISPUTE_ACCEPTED", "Dispute accepted"),
    "4001": ("F", "INVALID_SIGNATURE", "Invalid signature"),
    "4002": ("F", "MANDATORY_PARAM_MISSING", "Mandatory parameter missing"),
    "4003": ("F", "REQUEST_PARAMS_INVALID", "Request parameters are invalid"),
    "4004": ("F", "DISPUTE_ID_NOT_FOUND", "Dispute id not found"),
    "4005": ("F", "POD_UPLOAD_NOT_ALLOWED", "Upload due date has expired"),
    "4006": ("F", "POD_ALREADY_UPLOADED", "Documents already uploaded"),
    "4007": ("F", "MAX_FILES_EXCEEDED", "Maximum 5 files allowed"),
    "4008": ("F", "MAX_SIZE_EXCEEDED", "File size exceeds 5 MB"),
    "4009": ("F", "FILE_NOT_SUPPORTED", "File type not supported"),
    "4010": ("F", "POD_UPLOAD_FAILED", "POD upload failed"),
    "4011": ("F", "DISPUTE_ACCEPTANCE_NOT_ALLOWED", "Dispute acceptance not allowed after due date"),
    "5001": ("U", "SYSTEM_ERROR", "System error"),
}

MAX_FILES = 5
MAX_FILE_BYTES = 5_000_000  # conservative simulator ceiling; exact Paytm boundary unconfirmed
ORDER_STATUSES = ("ORDER_DELIVERED", "ORDER_IN_TRANSIT")
OPEN_STATES = ("NEW", "POD_REJECT")
STATUS_FAULTS = ("system_error", "stale_status")
ACTION_FAULTS = ("system_error_before", "system_error_after", "drop_response_after", "upload_failed", "ack_variant_a")


def result_info(code_id: str, status_override: str | None = None) -> dict[str, str]:
    status, code, msg = RESULT_CODES[code_id]
    return {
        "resultStatus": status_override or status,
        "resultCodeId": code_id.split("_")[0],
        "resultCode": code,
        "resultMsg": msg,
    }


def sniff_allowed(data: bytes) -> str | None:
    """Simulator allowlist (our assumption; Paytm publishes none): PDF, JPEG, PNG by content."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def timestamp_unit(value: str | None) -> str | None:
    """Docs show seconds in requests and milliseconds in response heads; accept both."""
    if value is None or not value.isdigit():
        return None
    return {10: "s", 13: "ms"}.get(len(value))


def find_dispute(session: Session, mid: str, dispute_id: str) -> SimulatorDispute | None:
    return session.scalar(
        select(SimulatorDispute).where(SimulatorDispute.mid == mid, SimulatorDispute.dispute_id == dispute_id)
    )


def take_fault(session: Session, dispute: SimulatorDispute, api: str) -> str | None:
    fault = session.scalar(
        select(SimulatorFault)
        .where(
            SimulatorFault.mid == dispute.mid,
            SimulatorFault.dispute_id == dispute.dispute_id,
            SimulatorFault.api == api,
            SimulatorFault.remaining > 0,
        )
        .order_by(SimulatorFault.created_at)
    )
    if fault is None:
        return None
    fault.remaining -= 1
    return fault.kind


def _now_naive(tz: str) -> str:
    return format_naive_time(get_clock().now(), tz)


def _set_status(dispute: SimulatorDispute, status: str, tz: str, **fields: Any) -> None:
    body = dict(dispute.body)
    body["_prev_status"] = dispute.dispute_status
    body["disputeStatus"] = status
    body["disputeUpdateDateTime"] = _now_naive(tz)
    body.update(fields)
    dispute.body = body
    dispute.dispute_status = status
    dispute.event_sequence += 1


def apply_expiry(dispute: SimulatorDispute, tz: str) -> bool:
    """Due date passed with no permitted action -> LOST ("Failed to respond")."""
    if dispute.dispute_status in OPEN_STATES and get_clock().now() >= dispute.due_at_utc:
        _set_status(dispute, "LOST", tz, disputeLostReason="Failed to respond", comment=dispute.body.get("comment"))
        return True
    return False


def public_body(dispute: SimulatorDispute, status_override: str | None = None) -> dict[str, Any]:
    body = {k: v for k, v in dispute.body.items() if not k.startswith("_")}
    for optional in ("debitAmount", "disputeLostReason", "comment", "disputeUtr"):
        body.setdefault(optional, None)
    if status_override:
        body["disputeStatus"] = status_override
    return body


@dataclass
class ActionOutcome:
    http_status: int
    result: dict[str, str] | None  # None => response lost (simulated gateway timeout)
    status_changed: bool = False
    receipt: SimulatorSubmission | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class UploadedFile:
    filename: str
    data: bytes
    declared_type: str | None


def perform_action(
    session: Session,
    *,
    params: dict[str, str],
    files: list[UploadedFile],
    tz: str,
    signature_ok: bool,
) -> ActionOutcome:
    """Validate and apply ACCEPT/DEFEND. Validation order is simulator policy (documented in PRD)."""
    for name in ("mid", "disputeId", "action", "requestTimestamp", "signature"):
        if not params.get(name):
            return ActionOutcome(200, result_info("4002"), notes=[f"missing {name}"])
    if not signature_ok:
        return ActionOutcome(200, result_info("4001"))
    unit = timestamp_unit(params.get("requestTimestamp"))
    token_type = params.get("tokenType")
    action = params["action"]
    if unit is None or (token_type is not None and token_type.casefold() != "checksum"):
        return ActionOutcome(200, result_info("4003"), notes=["requestTimestamp/tokenType invalid"])
    if action not in ("ACCEPT", "DEFEND"):
        return ActionOutcome(200, result_info("4003"), notes=["unknown action"])
    dispute = find_dispute(session, params["mid"], params["disputeId"])
    if dispute is None:
        return ActionOutcome(200, result_info("4004"))

    order_status = params.get("orderStatus") or None
    comments = params.get("comments") or None
    if action == "DEFEND":
        if params.get("filesPath") and not files:
            return ActionOutcome(200, result_info("4003"), notes=["filesPath/SFTP upload is deferred in the simulator"])
        if order_status is None:
            return ActionOutcome(200, result_info("4002"), notes=["orderStatus is mandatory for DEFEND"])
        if order_status not in ORDER_STATUSES:
            return ActionOutcome(200, result_info("4003"), notes=["invalid orderStatus"])
        if not files:
            return ActionOutcome(200, result_info("4002"), notes=["files required for DEFEND"])
        if len(files) > MAX_FILES:
            return ActionOutcome(200, result_info("4007"))
        if any(len(f.data) > MAX_FILE_BYTES for f in files):
            return ActionOutcome(200, result_info("4008"))
        if any(sniff_allowed(f.data) is None for f in files):
            return ActionOutcome(200, result_info("4009"))
        if get_clock().now() >= dispute.due_at_utc:
            return ActionOutcome(200, result_info("4005"))
        if dispute.dispute_status in ("POD_UPLOAD", "WON", "LOST"):
            return ActionOutcome(200, result_info("4006"))
        if dispute.dispute_status not in OPEN_STATES:
            return ActionOutcome(200, result_info("4003"), notes=[f"DEFEND not allowed from {dispute.dispute_status}"])
    else:
        if get_clock().now() >= dispute.due_at_utc:
            return ActionOutcome(200, result_info("4011"))
        if dispute.dispute_status not in OPEN_STATES:
            # Undocumented in Paytm's tables; simulator policy.
            return ActionOutcome(200, result_info("4003"), notes=[f"ACCEPT not allowed from {dispute.dispute_status}"])

    fault = take_fault(session, dispute, "action")
    if fault == "system_error_before":
        return ActionOutcome(200, result_info("5001"), notes=["injected: system error before acceptance"])
    if fault == "upload_failed" and action == "DEFEND":
        return ActionOutcome(200, result_info("4010"), notes=["injected: provider-side upload failure"])

    # Apply the effect and write the independent receipt.
    file_hashes = [hashlib.sha256(f.data).hexdigest() for f in files]
    receipt = SimulatorSubmission(
        reference=f"SIMRCPT-{secrets.token_hex(6).upper()}",
        sim_dispute_id=dispute.id,
        mid=dispute.mid,
        dispute_id=dispute.dispute_id,
        action=action,
        pack_hash=None,
        file_hashes=file_hashes,
        files_meta=[
            {"filename": f.filename, "size": len(f.data), "type": sniff_allowed(f.data), "sha256": h}
            for f, h in zip(files, file_hashes, strict=True)
        ],
        order_status=order_status,
        comments=comments,
        intent_digest=intent_digest(
            mid=dispute.mid,
            dispute_id=dispute.dispute_id,
            action=action,
            order_status=order_status,
            comments=comments,
            file_sha256s=file_hashes,
        ),
        timestamp_unit=unit,
        sequence=dispute.event_sequence + 1,
    )
    session.add(receipt)
    if action == "DEFEND":
        _set_status(dispute, "POD_UPLOAD", tz, comment=None)
        success = result_info("1001_UPLOAD", "A" if fault == "ack_variant_a" else None)
    else:
        _set_status(dispute, "LOST", tz, disputeLostReason="Accepted by merchant (simulator)")
        success = result_info("1003")
    session.flush()
    if fault == "system_error_after":
        return ActionOutcome(200, result_info("5001"), True, receipt, ["injected: effect applied, 5001 returned"])
    if fault == "drop_response_after":
        return ActionOutcome(504, None, True, receipt, ["injected: effect applied, response lost"])
    return ActionOutcome(200, success, True, receipt)


def status_lookup(
    session: Session, *, head: Any, body: Any, tz: str, signature_ok: bool
) -> tuple[dict[str, Any], bool]:
    """Return (response body, status_changed_by_lazy_expiry)."""
    if not isinstance(head, dict) or not isinstance(body, dict):
        return {"resultInfo": result_info("4003")}, False
    if (
        not body.get("mid")
        or not body.get("disputeId")
        or not head.get("requestTimestamp")
        or not head.get("signature")
    ):
        return {"resultInfo": result_info("4002")}, False
    if not signature_ok:
        return {"resultInfo": result_info("4001")}, False
    token_type = head.get("tokenType")
    if timestamp_unit(str(head.get("requestTimestamp"))) is None or (
        token_type is not None and str(token_type).casefold() != "checksum"
    ):
        return {"resultInfo": result_info("4003")}, False
    dispute = find_dispute(session, str(body["mid"]), str(body["disputeId"]))
    if dispute is None:
        return {"resultInfo": result_info("4004")}, False
    changed = apply_expiry(dispute, tz)
    fault = take_fault(session, dispute, "status")
    if fault == "system_error":
        return {"resultInfo": result_info("5001")}, changed
    override = dispute.body.get("_prev_status") if fault == "stale_status" else None
    return {"resultInfo": result_info("1001"), **public_body(dispute, override)}, changed


def callback_body(dispute: SimulatorDispute) -> dict[str, Any]:
    """S2S body after a status change. The webhook spells the UTR `disputeutr` (PRD 11.1)."""
    body = public_body(dispute)
    utr = body.pop("disputeUtr", None)
    body["disputeutr"] = utr
    for k in ("disputeCreateDateTime", "disputeUpdateDateTime"):
        body.pop(k, None)
    return body


def inject_pod_reject(session: Session, dispute: SimulatorDispute, comment: str, tz: str) -> None:
    if dispute.dispute_status != "POD_UPLOAD":
        raise ValueError(f"POD rejection requires POD_UPLOAD, dispute is {dispute.dispute_status}")
    _set_status(dispute, "POD_REJECT", tz, comment=comment)


def inject_outcome(session: Session, dispute: SimulatorDispute, outcome: str, tz: str, **fields: Any) -> None:
    if outcome == "WON" and dispute.dispute_status != "POD_UPLOAD":
        raise ValueError("WON requires POD_UPLOAD")
    if outcome == "LOST" and dispute.dispute_status in ("WON", "LOST"):
        raise ValueError(f"dispute already {dispute.dispute_status}")
    if outcome not in ("WON", "LOST"):
        raise ValueError("outcome must be WON or LOST")
    _set_status(dispute, outcome, tz, **fields)


def receipt_view(r: SimulatorSubmission) -> dict[str, Any]:
    return {
        "reference": r.reference,
        "mid": r.mid,
        "disputeId": r.dispute_id,
        "action": r.action,
        "orderStatus": r.order_status,
        "comments": r.comments,
        "fileHashes": r.file_hashes,
        "files": r.files_meta,
        "intentDigest": r.intent_digest,
        "timestampUnit": r.timestamp_unit,
        "sequence": r.sequence,
        "createdAt": r.created_at.isoformat(),
        "_note": "Simulator-only receipt extension; not part of any Paytm API.",
    }


def response_head(client_id: str | None, signature: str, ms: bool) -> dict[str, Any]:
    now: datetime = get_clock().now()
    ts = str(int(now.timestamp() * 1000)) if ms else str(int(now.timestamp()))
    head: dict[str, Any] = {"responseTimestamp": ts, "version": "v1", "signature": signature}
    if client_id:
        head["clientId"] = client_id
    return head
