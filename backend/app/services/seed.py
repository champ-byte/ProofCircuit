"""Demo fixture lifecycle: reset and seed the synthetic hero case relative to the seed clock."""

from __future__ import annotations

import json
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT, Settings
from app.db.base import Base
from app.db.models import Case, DemoUser, Merchant, SimulatorDispute
from app.domain.clock import Clock
from app.domain.enums import DisputeReason
from app.domain.paytm import format_naive_time, normalize_callback_body
from app.services.audit import audit
from app.services.evidence import ingest_document
from app.services.fixtures import render_hero_document
from app.services.intake import open_case

FIXTURES_DIR = REPO_ROOT / "fixtures"
RUNTIME_SUBDIRS = ("evidence", "packs")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def reset_demo(session: Session, settings: Settings) -> None:
    """Delete all demo rows and runtime files. Only ever touches subdirectories of DATA_DIR."""
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    data_root = settings.data_path.resolve()
    for sub in RUNTIME_SUBDIRS:
        target = (data_root / sub).resolve()
        if target.parent == data_root and target.exists():
            shutil.rmtree(target)


def _ensure_merchant(session: Session, spec: dict[str, Any], users: list[dict[str, Any]]) -> Merchant:
    merchant = session.scalar(select(Merchant).where(Merchant.mid == spec["mid"]))
    if merchant is None:
        merchant = Merchant(name=spec["name"], mid=spec["mid"], default_locale=spec["default_locale"])
        session.add(merchant)
        session.flush()
    for user in users:
        exists = session.scalar(
            select(DemoUser).where(DemoUser.merchant_id == merchant.id, DemoUser.handle == user["handle"])
        )
        if exists is None:
            session.add(
                DemoUser(
                    merchant_id=merchant.id,
                    handle=user["handle"],
                    display_name=user["display_name"],
                    role=user["role"],
                    staff_function=user.get("staff_function"),
                    locale=user["locale"],
                )
            )
    session.flush()
    return merchant


def hero_callback(settings: Settings, clock: Clock) -> dict[str, Any]:
    template = load_json(FIXTURES_DIR / "hero" / "dispute_callback.template.json")
    spec = template["seed"]
    now = clock.now().replace(microsecond=0)
    tz = settings.paytm_naive_timezone
    values = {
        "{{DUE_TIME}}": format_naive_time(now + timedelta(hours=spec["due_hours_from_seed"]), tz),
        "{{TXN_TIME}}": format_naive_time(now - timedelta(hours=spec["transaction_hours_before_seed"]), tz),
        "{{CREATE_TIME}}": format_naive_time(now - timedelta(hours=spec["created_hours_before_seed"]), tz),
    }
    body = {k: values.get(v, v) if isinstance(v, str) else v for k, v in template["body"].items()}
    return {"head": template["head"], "body": body, "seed": spec, "create_time": values["{{CREATE_TIME}}"]}


def seed_demo(session: Session, settings: Settings, clock: Clock) -> Case:
    """Idempotent: seeding twice returns the existing hero case rather than a duplicate."""
    org = load_json(FIXTURES_DIR / "demo_org.json")
    merchant = _ensure_merchant(session, org["merchant"], org["users"])
    for other in org.get("other_merchants", []):
        _ensure_merchant(session, other, other.get("users", []))

    callback = hero_callback(settings, clock)
    body = callback["body"]
    dispute = normalize_callback_body(body, settings.paytm_naive_timezone)

    # Independent simulator provider store: the dispute exists "at Paytm".
    sim = session.scalar(
        select(SimulatorDispute).where(
            SimulatorDispute.mid == dispute.mid, SimulatorDispute.dispute_id == dispute.dispute_id
        )
    )
    if sim is None:
        sim_body = {
            **body,
            "debitAmount": None,
            "disputeLostReason": None,
            "comment": None,
            "disputeUtr": None,
            "disputeCreateDateTime": callback["create_time"],
            "disputeUpdateDateTime": callback["create_time"],
        }
        session.add(
            SimulatorDispute(
                mid=dispute.mid,
                dispute_id=dispute.dispute_id,
                body=sim_body,
                dispute_status="NEW",
                due_at_utc=dispute.deadline_utc,
            )
        )

    owner = session.scalar(
        select(DemoUser).where(DemoUser.merchant_id == merchant.id, DemoUser.handle == callback["seed"]["owner_handle"])
    )
    case, created = open_case(
        session,
        merchant=merchant,
        dispute=dispute,
        raw_body=body,
        source="seed",
        # The seeded synthetic event is mapped to goods-not-received by fixture, never inferred
        # from Paytm's broad disputeType (PRD 11.2.1).
        reason=DisputeReason(callback["seed"]["reason"]),
        owner_user_id=owner.id if owner else None,
        signature_valid=None,
    )
    if created:
        audit(
            session,
            event_type="demo.seeded",
            summary="Synthetic hero case seeded relative to the seed clock.",
            actor_type="system",
            case_id=case.id,
            merchant_id=merchant.id,
            data={"deadline_raw": dispute.deadline_raw, "timezone_assumption": dispute.timezone_assumption},
        )
        # Hero starting point: the invoice is present, delivery proof is missing. The invoice goes
        # through the same ingestion/extraction path as any upload.
        filename, data = render_hero_document("invoice", case, settings)
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
    return case
