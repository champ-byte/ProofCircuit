"""Controlled simulator writes and independent verification (PRD 8.6, 10.3, 11.3).

Rules implemented here:
- Intent is persisted (and committed) before any provider call; the same pack always reuses the
  same idempotency key `(merchant_id, dispute_id, action, pack_hash)` and serialized payload.
- An acknowledgement never verifies on its own. Verification requires (a) a successful Status
  read and (b) an independent simulator receipt whose intent digest equals this submission's.
- `4006` is a reconciliation signal, never success. A lost/ambiguous response is
  SUBMISSION_UNCERTAIN: read status and receipts *before* any retry, then resend the same
  payload at most once, and only from an eligible provider state after re-checking policy.
- Provider-model fallback (M3) only repeats inference; nothing here is retried automatically
  beyond that single reconciled resend.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from sqlalchemy import select

from app.db.models import Case, EvidencePack, Submission
from app.db.session import session_scope
from app.domain.clock import get_clock
from app.domain.enums import OperationalFlag, ProviderDisputeStatus, WorkflowState
from app.domain.intent import intent_digest
from app.domain.paytm import PaytmFieldError, parse_optional_amount_paise
from app.providers.paytm import ActionResult, StatusRead, UploadPart, get_provider
from app.services.audit import audit
from app.services.messaging import request_human_review
from app.services.pack import PackBlocked, pack_upload_parts
from app.services.policy import check_defense
from app.services.workflow import add_flag, remove_flag, set_state, sync_workflow

MAX_SENDS = 2  # the original send plus at most one reconciled resend


def idempotency_key(merchant_id: str, dispute_id: str, action: str, identity: str) -> str:
    return hashlib.sha256(f"{merchant_id}|{dispute_id}|{action}|{identity}".encode()).hexdigest()


def _note(sub: Submission, entry: dict[str, Any]) -> None:
    sub.reconciliation = [*sub.reconciliation, {"at": get_clock().now().isoformat(), **entry}]


def apply_status_read(case: Case, read: StatusRead) -> None:
    """Authoritative provider state onto the case: raw string and normalized category."""
    case.provider_status_raw = read.status_raw
    case.provider_status = read.status
    body = read.body
    try:
        debit = parse_optional_amount_paise(body.get("debitAmount"), "debitAmount")
    except PaytmFieldError:
        debit = None
    if debit is not None:
        case.debit_amount_paise = debit
    if body.get("disputeUtr"):
        case.dispute_utr = str(body["disputeUtr"])


async def read_status_bounded(app: Any, case: Case) -> StatusRead:
    settings = app.state.settings
    provider = get_provider(app)
    read = StatusRead(False, True, None, error="not attempted")
    for attempt in range(settings.provider_status_reads):
        read = await provider.get_status(case.mid, case.external_dispute_id)
        if read.ok or not read.retryable:
            return read
        await asyncio.sleep(settings.provider_retry_backoff_seconds * (2**attempt))
    return read


# --- DEFEND ------------------------------------------------------------------------------------


async def submit_defense(
    app: Any, case_id: str, *, pack_id: str | None, actor_kind: str, actor_id: str | None
) -> dict[str, Any]:
    settings = app.state.settings
    with session_scope() as session:
        case = session.get(Case, case_id)
        assert case is not None
        pack = session.get(EvidencePack, pack_id or case.latest_pack_id or "")
        existing: Submission | None = None
        key = ""
        if pack is not None:
            key = idempotency_key(case.merchant_id, case.external_dispute_id, "DEFEND", pack.pack_hash)
            existing = session.scalar(select(Submission).where(Submission.idempotency_key == key))
        if existing is not None and existing.verification_state == "verified":
            return {"status": "already_verified", "submission_id": existing.id}
        resume = existing is not None and existing.verification_state in (
            "pending",
            "sent",
            "acknowledged",
            "uncertain",
        )
        if resume:
            assert existing is not None
            sub_id = existing.id
        decision = check_defense(session, settings, case, pack, actor_kind=actor_kind, resend_of=existing)
        if not resume and not decision.allowed:
            audit(
                session,
                event_type="policy.denied",
                summary="Submission denied: " + "; ".join(decision.reasons),
                actor_type=actor_kind,
                actor_id=actor_id,
                case_id=case.id,
                merchant_id=case.merchant_id,
                data=decision.as_dict(),
            )
            return {"status": "denied", "reasons": decision.reasons}
        if not resume:
            assert pack is not None
            if existing is None:
                existing = Submission(
                    case_id=case.id,
                    pack_id=pack.id,
                    action="DEFEND",
                    idempotency_key=key,
                    intent_digest=pack.intent_digest,
                    verification_state="pending",
                    request_payload={
                        "mid": case.mid,
                        "disputeId": case.external_dispute_id,
                        "action": "DEFEND",
                        "orderStatus": pack.order_status,
                        "comments": pack.comments,
                        "files": [{"name": f["name"], "sha256": f["sha256"]} for f in pack.upload_files],
                    },
                )
                session.add(existing)
            else:  # a definitive failure earlier; same pack, same key, policy re-checked above
                existing.verification_state = "pending"
            session.flush()
            sub_id = existing.id
            set_state(session, case, WorkflowState.SUBMITTING, "policy-authorized simulator write")
            audit(
                session,
                event_type="submission.requested",
                summary=f"DEFEND requested for pack v{pack.version}.",
                actor_type=actor_kind,
                actor_id=actor_id,
                case_id=case.id,
                merchant_id=case.merchant_id,
                data={
                    "submission_id": sub_id,
                    "pack_id": pack.id,
                    "idempotency_key": key,
                    "policy": decision.as_dict(),
                },
            )
    if resume:
        return await reconcile_submission(app, sub_id, allow_resend=True)
    return await _send(app, sub_id)


async def _send(app: Any, sub_id: str) -> dict[str, Any]:
    settings = app.state.settings
    with session_scope() as session:
        sub = session.get(Submission, sub_id)
        assert sub is not None
        case = session.get(Case, sub.case_id)
        assert case is not None
        if sub.attempts >= MAX_SENDS:
            return await _to_review(app, sub_id, "send budget exhausted without verification")
        payload = dict(sub.request_payload)
        parts: list[UploadPart] = []
        if sub.action == "DEFEND":
            pack = session.get(EvidencePack, sub.pack_id)
            assert pack is not None
            try:
                parts = [UploadPart(n, d, m) for n, d, m in pack_upload_parts(settings, pack)]
            except PackBlocked as exc:
                sub.verification_state = "failed"
                sub.last_error = str(exc)
                return {"status": "failed", "error": str(exc)}
        # Persist "sent" before the call: a crash from here on is treated as uncertain.
        sub.verification_state = "sent"
        sub.attempts += 1
    result = await get_provider(app).act(
        action=payload["action"],
        mid=payload["mid"],
        dispute_id=payload["disputeId"],
        order_status=payload.get("orderStatus"),
        comments=payload.get("comments"),
        files=parts,
    )
    return await _handle_action_result(app, sub_id, result)


async def _handle_action_result(app: Any, sub_id: str, result: ActionResult) -> dict[str, Any]:
    with session_scope() as session:
        sub = session.get(Submission, sub_id)
        assert sub is not None
        case = session.get(Case, sub.case_id)
        assert case is not None
        _note(
            sub,
            {
                "step": "action_response",
                "kind": result.kind,
                "code": result.code,
                "result_status": result.result_status,
                "http_status": result.http_status,
            },
        )
        audit(
            session,
            event_type="submission.provider_response",
            summary=f"{sub.action} response: {result.kind} ({result.code or 'no business response'}).",
            actor_type="provider",
            case_id=case.id,
            merchant_id=case.merchant_id,
            data={"submission_id": sub.id, "code": result.code, "kind": result.kind, "raw": result.raw},
        )
        if result.kind == "ack":
            sub.verification_state = "acknowledged"
            sub.provider_ack = result.raw
        elif result.kind == "definitive":
            sub.verification_state = "failed"
            sub.last_error = result.error
            if result.code in ("4005", "4011"):
                add_flag(case, OperationalFlag.DEADLINE_EXPIRED)
            request_human_review(
                session,
                case,
                reason_code="submission_rejected",
                question=f"Simulator rejected the {sub.action}: {result.error}",
                source_ids=[],
                actor_type="system",
                actor_id=None,
            )
            sync_workflow(session, app.state.settings, case)
            return {"status": "failed", "code": result.code, "error": result.error}
        else:
            sub.verification_state = "uncertain"
            sub.last_error = result.error
            set_state(session, case, WorkflowState.SUBMISSION_UNCERTAIN, f"{result.kind}: {result.error}")
    # Ack: verify without resending. 4006/4010/5001/lost: reconcile, resend only if eligible.
    return await reconcile_submission(app, sub_id, allow_resend=result.kind in ("retryable", "unknown"))


async def reconcile_submission(app: Any, sub_id: str, *, allow_resend: bool) -> dict[str, Any]:
    settings = app.state.settings
    provider = get_provider(app)
    with session_scope() as session:
        sub = session.get(Submission, sub_id)
        assert sub is not None
        case = session.get(Case, sub.case_id)
        assert case is not None
        session.expunge(case)
    read = await read_status_bounded(app, case)
    receipts = await provider.list_receipts(case.mid, case.external_dispute_id) if read.ok else None

    with session_scope() as session:
        sub = session.get(Submission, sub_id)
        case = session.get(Case, sub.case_id)  # type: ignore[union-attr]
        assert sub is not None and case is not None
        if not read.ok or receipts is None:
            sub.verification_state = "uncertain"
            add_flag(case, OperationalFlag.PROVIDER_UNAVAILABLE)
            _note(sub, {"step": "status_read", "ok": False, "error": read.error, "receipts": receipts is not None})
            request_human_review(
                session,
                case,
                reason_code="provider_unavailable",
                question="Provider status could not be read after bounded retries; effect unknown.",
                source_ids=[],
                actor_type="system",
                actor_id=None,
            )
            set_state(session, case, WorkflowState.SUBMISSION_UNCERTAIN, "status unreadable after bounded retries")
            return {"status": "uncertain", "reason": "status unavailable"}
        remove_flag(case, OperationalFlag.PROVIDER_UNAVAILABLE)
        apply_status_read(case, read)
        matching = [r for r in receipts if r["action"] == sub.action and r["intentDigest"] == sub.intent_digest]
        _note(
            sub,
            {
                "step": "reconcile",
                "status": read.status_raw,
                "receipts": len(receipts),
                "matching_receipt": matching[0]["reference"] if matching else None,
            },
        )
        status = read.status
        expected = ProviderDisputeStatus.POD_UPLOAD if sub.action == "DEFEND" else ProviderDisputeStatus.LOST

        if matching and status != ProviderDisputeStatus.UNKNOWN:
            sub.verification_state = "verified"
            sub.provider_reference = matching[0]["reference"]
            sub.last_error = None  # the earlier failure stays in the reconciliation trail
            audit(
                session,
                event_type="submission.verified",
                summary=(
                    f"Submission verified — receipt {matching[0]['reference']} matches this exact pack; "
                    f"provider reports {read.status_raw}. Dispute outcome pending."
                    if sub.action == "DEFEND"
                    else f"Concession verified — receipt {matching[0]['reference']}; provider: {read.status_raw}."
                ),
                actor_type="system",
                case_id=case.id,
                merchant_id=case.merchant_id,
                data={
                    "submission_id": sub.id,
                    "receipt": matching[0],
                    "status": read.status_raw,
                    "expected_status": expected,
                    "status_matches_expected": status == expected,
                },
            )
            sync_workflow(session, settings, case)
            return {"status": "verified", "receipt": matching[0]["reference"], "provider_status": read.status_raw}

        eligible = status == ProviderDisputeStatus.NEW or (
            status == ProviderDisputeStatus.POD_REJECT and sub.action == "DEFEND"
        )
        if eligible and allow_resend and sub.attempts < MAX_SENDS:
            pack = session.get(EvidencePack, sub.pack_id) if sub.pack_id else None
            if sub.action == "DEFEND":
                decision = check_defense(session, settings, case, pack, actor_kind="system", resend_of=sub)
                if not decision.allowed:
                    sub.verification_state = "failed"
                    sub.last_error = "resend denied: " + "; ".join(decision.reasons)
                    request_human_review(
                        session,
                        case,
                        reason_code="resend_denied",
                        question=sub.last_error,
                        source_ids=[],
                        actor_type="system",
                        actor_id=None,
                    )
                    sync_workflow(session, settings, case)
                    return {"status": "failed", "reasons": decision.reasons}
            _note(sub, {"step": "resend", "reason": "no matching receipt and provider state is eligible"})
            audit(
                session,
                event_type="submission.resend",
                summary="No matching receipt and the dispute is still eligible: resending the same payload once.",
                actor_type="system",
                case_id=case.id,
                merchant_id=case.merchant_id,
                data={"submission_id": sub.id},
            )
            resend = True
        else:
            resend = False
    if resend:
        return await _send(app, sub_id)
    reason = (
        "provider reports an upload, but no receipt matches this exact pack"
        if status == ProviderDisputeStatus.POD_UPLOAD
        else f"no matching receipt; provider state {read.status_raw} does not permit a resend"
    )
    return await _to_review(app, sub_id, reason)


async def _to_review(app: Any, sub_id: str, reason: str) -> dict[str, Any]:
    with session_scope() as session:
        sub = session.get(Submission, sub_id)
        assert sub is not None
        case = session.get(Case, sub.case_id)
        assert case is not None
        sub.verification_state = "uncertain"
        sub.last_error = reason
        request_human_review(
            session,
            case,
            reason_code="submission_unverified",
            question=reason,
            source_ids=[],
            actor_type="system",
            actor_id=None,
        )
        set_state(session, case, WorkflowState.SUBMISSION_UNCERTAIN, reason)
    return {"status": "uncertain", "reason": reason}


# --- ACCEPT (human-only concession) ------------------------------------------------------------


def concession_submission(session: Any, case: Case, approval_id: str) -> Submission:
    sub = Submission(
        case_id=case.id,
        pack_id=None,
        action="ACCEPT",
        idempotency_key=idempotency_key(case.merchant_id, case.external_dispute_id, "ACCEPT", approval_id),
        intent_digest=intent_digest(
            mid=case.mid,
            dispute_id=case.external_dispute_id,
            action="ACCEPT",
            order_status=None,
            comments=None,
            file_sha256s=[],
        ),
        verification_state="pending",
        request_payload={"mid": case.mid, "disputeId": case.external_dispute_id, "action": "ACCEPT"},
    )
    session.add(sub)
    session.flush()
    return sub


async def send_concession(app: Any, sub_id: str) -> dict[str, Any]:
    return await _send(app, sub_id)


# --- Provider-state refresh (webhook-triggered or manual) ---------------------------------------


async def refresh_status(app: Any, case_id: str) -> dict[str, Any]:
    settings = app.state.settings
    with session_scope() as session:
        case = session.get(Case, case_id)
        assert case is not None
        pending = session.scalar(
            select(Submission).where(
                Submission.case_id == case.id,
                Submission.verification_state.in_(("pending", "sent", "acknowledged", "uncertain")),
            )
        )
        pending_id = pending.id if pending else None
        session.expunge(case)
    if pending_id is not None:
        return await reconcile_submission(app, pending_id, allow_resend=False)
    read = await read_status_bounded(app, case)
    with session_scope() as session:
        case = session.get(Case, case_id)
        assert case is not None
        if not read.ok:
            add_flag(case, OperationalFlag.PROVIDER_UNAVAILABLE)
            audit(
                session,
                event_type="provider.status_unavailable",
                summary=f"Status read failed: {read.error}",
                actor_type="system",
                case_id=case.id,
                merchant_id=case.merchant_id,
            )
            return {"status": "unavailable", "error": read.error}
        remove_flag(case, OperationalFlag.PROVIDER_UNAVAILABLE)
        before = case.provider_status_raw
        apply_status_read(case, read)
        if before != read.status_raw:
            audit(
                session,
                event_type="provider.status_changed",
                summary=f"Provider status {before} → {read.status_raw} (authoritative read).",
                actor_type="provider",
                case_id=case.id,
                merchant_id=case.merchant_id,
                data={
                    "from": before,
                    "to": read.status_raw,
                    "comment": read.body.get("comment"),
                    "disputeLostReason": read.body.get("disputeLostReason"),
                },
            )
        if read.status == ProviderDisputeStatus.UNKNOWN:
            request_human_review(
                session,
                case,
                reason_code="unknown_provider_status",
                question=f"Unknown provider status {read.status_raw!r}",
                source_ids=[],
                actor_type="system",
                actor_id=None,
            )
        sync_workflow(session, settings, case)
        return {"status": "ok", "provider_status": read.status_raw}
