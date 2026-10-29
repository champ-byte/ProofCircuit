"""Open one corpus case the way the hero is seeded: an independent simulator dispute, the app case and
the invoice through the normal ingestion path. Dates are relative to the seed clock."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Case, DemoUser, Merchant, SimulatorDispute
from app.domain.clock import Clock
from app.domain.enums import DisputeReason
from app.domain.paytm import format_naive_time, normalize_callback_body
from app.evaluation.corpus import render
from app.services.audit import audit
from app.services.evidence import ingest_document
from app.services.intake import open_case


class SeedError(ValueError):
    pass


def seed_eval_case(
    session: Session, settings: Settings, clock: Clock, merchant: Merchant, spec: dict[str, Any], run_tag: str
) -> tuple[Case, date]:
    tz = settings.paytm_naive_timezone
    now = clock.now().replace(microsecond=0)
    d, t = spec["dispute"], spec["timing"]
    dispute_id = f"{d['disputeId']}-{run_tag}"
    if session.scalar(
        select(SimulatorDispute).where(SimulatorDispute.mid == merchant.mid, SimulatorDispute.dispute_id == dispute_id)
    ):
        raise SeedError(f"{dispute_id} already exists; use a new run tag")
    txn_at = now - timedelta(hours=t["transaction_hours_before"])
    body = {
        "transactionId": d["transactionId"],
        "orderId": d["orderId"],
        "disputeAmount": d["amount"],
        "disputeDueDate": format_naive_time(now + timedelta(minutes=t["deadline_minutes_from_seed"]), tz),
        "bankReferenceNo": d["bankReferenceNo"],
        "disputeType": "Successful Order, Service/product delivered",
        "message": "Chargeback dispute has been filed",
        "extSerialNo": d["extSerialNo"],
        "mid": merchant.mid,
        "merchantName": merchant.name,
        "custId": d["custId"],
        "transactionDateTime": format_naive_time(txn_at, tz),
        "transactionAmount": d["amount"],
        "disputeId": dispute_id,
        "disputeStatus": "NEW",
    }
    dispute = normalize_callback_body(body, tz)
    created = format_naive_time(now - timedelta(minutes=5), tz)
    session.add(
        SimulatorDispute(
            mid=merchant.mid,
            dispute_id=dispute_id,
            body={
                **body,
                "debitAmount": None,
                "disputeLostReason": None,
                "comment": None,
                "disputeUtr": None,
                "disputeCreateDateTime": created,
                "disputeUpdateDateTime": created,
            },
            dispute_status="NEW",
            due_at_utc=dispute.deadline_utc,
        )
    )
    owner = session.scalar(select(DemoUser).where(DemoUser.merchant_id == merchant.id, DemoUser.handle == "owner"))
    case, _ = open_case(
        session,
        merchant=merchant,
        dispute=dispute,
        raw_body=body,
        source="seed",
        # Like the hero, the synthetic event is mapped to goods-not-received by fixture, never inferred.
        reason=DisputeReason.GOODS_NOT_RECEIVED,
        owner_user_id=owner.id if owner else None,
        signature_valid=None,
    )
    order_date = txn_at.astimezone(ZoneInfo(tz)).date()
    audit(
        session,
        event_type="evaluation.case_seeded",
        summary=f"Synthetic evaluation case {spec['case_id']} ({spec['category']}, {spec['split']}) seeded.",
        actor_type="system",
        case_id=case.id,
        merchant_id=merchant.id,
        data={"corpus_case": spec["case_id"], "run_tag": run_tag, "category": spec["category"]},
    )
    filename, data = render(spec, "invoice", order_date)
    ingest_document(
        session,
        settings,
        case,
        filename=filename,
        declared_mime="application/pdf",
        data=data,
        uploaded_by_user_id=None,
        actor_type="system",
    )
    return case, order_date
