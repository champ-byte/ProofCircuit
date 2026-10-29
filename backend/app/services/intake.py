"""Create exactly one case per (merchant, external dispute) from a normalized Paytm-shaped event."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Case, Merchant, ProviderEvent
from app.domain.enums import DisputeReason, WorkflowState
from app.domain.paytm import NormalizedDispute
from app.services.audit import audit


def find_case(session: Session, merchant_id: str, dispute_id: str) -> Case | None:
    return session.scalar(select(Case).where(Case.merchant_id == merchant_id, Case.external_dispute_id == dispute_id))


def open_case(
    session: Session,
    *,
    merchant: Merchant,
    dispute: NormalizedDispute,
    raw_body: dict[str, Any],
    source: str,
    reason: DisputeReason,
    owner_user_id: str | None,
    signature_valid: bool | None,
) -> tuple[Case, bool]:
    """Return (case, created). A repeat of the same dispute never creates a second case."""
    if dispute.mid != merchant.mid:
        raise ValueError("dispute MID does not match the resolved merchant")

    existing = find_case(session, merchant.id, dispute.dispute_id)
    event = ProviderEvent(
        source=source,
        raw_payload=raw_body,
        canonical_hash=dispute.payload_hash,
        signature_valid=signature_valid,
        case_id=existing.id if existing else None,
    )
    session.add(event)
    if existing is not None:
        audit(
            session,
            event_type="provider.event_duplicate",
            summary=f"Duplicate dispute event for {dispute.dispute_id}; no new case created.",
            actor_type="provider",
            case_id=existing.id,
            merchant_id=merchant.id,
            data={"canonical_hash": dispute.payload_hash},
        )
        return existing, False

    case = Case(
        merchant_id=merchant.id,
        mid=dispute.mid,
        external_dispute_id=dispute.dispute_id,
        transaction_id=dispute.transaction_id,
        order_id=dispute.order_id,
        customer_ref=dispute.cust_id,
        bank_reference_no=dispute.bank_reference_no,
        amount_paise=dispute.amount_paise,
        transaction_amount_paise=dispute.transaction_amount_paise,
        debit_amount_paise=dispute.debit_amount_paise,
        dispute_utr=dispute.dispute_utr,
        currency="INR",
        reason=reason,
        dispute_type_raw=dispute.dispute_type_raw,
        deadline_utc=dispute.deadline_utc,
        deadline_raw=dispute.deadline_raw,
        timezone_assumption=dispute.timezone_assumption,
        transaction_at_utc=dispute.transaction_at_utc,
        locale=merchant.default_locale,
        owner_user_id=owner_user_id,
        workflow_state=WorkflowState.NEW,
        provider_status=dispute.provider_status,
        provider_status_raw=dispute.provider_status_raw,
        flags=[],
        version=1,
    )
    session.add(case)
    session.flush()
    event.case_id = case.id
    event.applied_case_version = case.version
    audit(
        session,
        event_type="case.opened",
        summary=f"Dispute {dispute.dispute_id} opened for order {dispute.order_id}.",
        actor_type="provider",
        case_id=case.id,
        merchant_id=merchant.id,
        data={"source": source, "canonical_hash": dispute.payload_hash, "reason": reason},
    )
    return case, True


def record_status_callback(
    session: Session,
    *,
    case: Case,
    dispute: NormalizedDispute,
    raw_body: dict[str, Any],
    demo_event_id: str | None,
    demo_sequence: int | None,
) -> tuple[ProviderEvent, bool]:
    """Persist a later webhook for an existing case. Returns (event, duplicate).

    Webhook content is never applied directly: the caller queues an authoritative Status API
    read, so out-of-order or unknown states cannot regress the case (PRD 10.3).
    """
    duplicate = False
    if demo_event_id is not None:
        duplicate = (
            session.scalar(
                select(ProviderEvent.id).where(
                    ProviderEvent.case_id == case.id, ProviderEvent.demo_event_id == demo_event_id
                )
            )
            is not None
        )
    else:
        duplicate = (
            session.scalar(
                select(ProviderEvent.id).where(
                    ProviderEvent.case_id == case.id, ProviderEvent.canonical_hash == dispute.payload_hash
                )
            )
            is not None
        )
    event = ProviderEvent(
        case_id=case.id,
        source="s2s_callback",
        raw_payload=raw_body,
        canonical_hash=dispute.payload_hash,
        demo_event_id=demo_event_id,
        demo_sequence=demo_sequence,
        signature_valid=True,
        applied_case_version=None if duplicate else case.version,
    )
    session.add(event)
    audit(
        session,
        event_type="provider.callback_duplicate" if duplicate else "provider.callback_received",
        summary=(
            f"Duplicate webhook for {dispute.dispute_id} ignored."
            if duplicate
            else f"Webhook reports {dispute.provider_status_raw}; queued an authoritative status read."
        ),
        actor_type="provider",
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"demo_event_id": demo_event_id, "demo_sequence": demo_sequence, "reported": dispute.provider_status_raw},
    )
    return event, duplicate
