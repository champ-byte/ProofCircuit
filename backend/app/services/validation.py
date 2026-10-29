"""Deterministic checklist and validators for the goods-not-received demo policy (PRD 8.2, 8.3).

The checklist is *our demo policy*, not a universal list of evidence that satisfies a bank.
Only span-verified, non-stale facts from active (not superseded/excluded) documents count.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    Case,
    ChecklistItem,
    DemoUser,
    DocumentPage,
    EvidenceDocument,
    ExtractedFact,
    ValidationFinding,
)
from app.domain.clock import get_clock
from app.domain.enums import OperationalFlag
from app.domain.money import format_inr
from app.services.audit import audit
from app.services.field_rules import detect_untrusted_instructions

REQUIREMENTS: dict[str, dict[str, str]] = {
    "order_linkage": {"label": "Transaction/order linkage for the disputed order", "staff_function": "billing"},
    "invoice": {"label": "Invoice for the disputed order and amount", "staff_function": "billing"},
    "delivery_record": {"label": "Delivery record linking the order to a delivery date", "staff_function": "delivery"},
}
CRITICAL_FIELDS = {"order_id", "amount", "delivered_on", "transaction_id"}
BLOCKING_SEVERITIES = {"blocking", "review"}


@dataclass
class FindingSpec:
    rule_id: str
    severity: str  # blocking | review | info
    source_ids: list[str]
    explanation: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps([self.rule_id, sorted(self.source_ids), self.details], sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class DocView:
    doc: EvidenceDocument
    facts: list[ExtractedFact]

    def verified(self, name: str) -> list[ExtractedFact]:
        return [
            f
            for f in self.facts
            if f.field == name and f.verification == "span_verified" and not f.stale and f.normalized_value
        ]

    def values(self, name: str) -> set[str]:
        return {f.normalized_value for f in self.verified(name) if f.normalized_value}


def is_active(doc: EvidenceDocument) -> bool:
    return doc.superseded_by_id is None and doc.exclusion_reason is None


def _load(session: Session, case: Case) -> list[DocView]:
    docs = session.scalars(
        select(EvidenceDocument).where(EvidenceDocument.case_id == case.id).order_by(EvidenceDocument.created_at)
    ).all()
    facts = session.scalars(select(ExtractedFact).where(ExtractedFact.case_id == case.id)).all()
    by_doc: dict[str, list[ExtractedFact]] = defaultdict(list)
    for f in facts:
        by_doc[f.document_id].append(f)
    return [DocView(d, by_doc[d.id]) for d in docs]


def _matches_case(view: DocView, case: Case) -> bool:
    orders = view.values("order_id")
    txns = view.values("transaction_id")
    return orders == {case.order_id} and (not txns or txns == {case.transaction_id})


def _supersede_mismatched(session: Session, case: Case, views: list[DocView]) -> None:
    """Corrected evidence supersedes an earlier same-type document for a different order."""
    for doc_type in ("invoice", "delivery_record", "dispatch_record"):
        matching = [v for v in views if is_active(v.doc) and v.doc.doc_type == doc_type and _matches_case(v, case)]
        if not matching:
            continue
        replacement = matching[-1].doc
        for v in views:
            orders = v.values("order_id")
            if (
                is_active(v.doc)
                and v.doc.doc_type == doc_type
                and orders
                and case.order_id not in orders
                and v.doc.created_at <= replacement.created_at
            ):
                v.doc.superseded_by_id = replacement.id
                v.doc.exclusion_reason = (
                    f"Superseded by {replacement.original_filename}: references {', '.join(sorted(orders))}, "
                    f"not {case.order_id}."
                )
                for f in v.facts:
                    f.stale = True
                audit(
                    session,
                    event_type="evidence.superseded",
                    summary=f"{v.doc.original_filename} superseded by {replacement.original_filename}.",
                    actor_type="system",
                    case_id=case.id,
                    merchant_id=case.merchant_id,
                    data={"document_id": v.doc.id, "superseded_by": replacement.id, "reason": v.doc.exclusion_reason},
                )


def _order_date(case: Case, invoices: list[DocView], settings: Settings) -> tuple[date | None, list[str]]:
    facts = [f for v in invoices for f in v.verified("order_date")]
    values = {f.normalized_value for f in facts}
    if len(values) == 1:
        return date.fromisoformat(next(iter(values))), [f.id for f in facts]  # type: ignore[arg-type]
    if case.transaction_at_utc is not None and not values:
        return case.transaction_at_utc.astimezone(ZoneInfo(settings.paytm_naive_timezone)).date(), []
    return None, [f.id for f in facts]


def evaluate(session: Session, settings: Settings, case: Case) -> tuple[list[FindingSpec], dict[str, dict[str, Any]]]:
    views = _load(session, case)
    _supersede_mismatched(session, case, views)
    active = [v for v in views if is_active(v.doc)]
    findings: list[FindingSpec] = []

    for v in active:
        d = v.doc
        if d.extraction_status == "ocr_required":
            findings.append(
                FindingSpec(
                    "OCR_REQUIRED",
                    "review",
                    [d.id],
                    f"{d.original_filename} has no extractable text; OCR is disabled. "
                    "Upload a text-based copy or provide a labelled manual transcription.",
                )
            )
            continue
        if d.extraction_status != "extracted":
            findings.append(
                FindingSpec(
                    "EXTRACTION_FAILED",
                    "review",
                    [d.id],
                    f"{d.original_filename} could not be read: {d.extraction_error}",
                )
            )
            continue
        pages = [
            p.text
            for p in session.scalars(
                select(DocumentPage).where(DocumentPage.document_id == d.id).order_by(DocumentPage.page_number)
            )
        ]
        phrases = detect_untrusted_instructions(pages)
        if phrases:
            findings.append(
                FindingSpec(
                    "UNTRUSTED_INSTRUCTIONS",
                    "info",
                    [d.id],
                    f"{d.original_filename} contains instruction-like text. It is treated as evidence data only "
                    "and cannot change policy, approve or submit anything.",
                    {"phrases": phrases},
                )
            )
        unverified = [f for f in v.facts if f.field in CRITICAL_FIELDS and not f.stale and f not in v.verified(f.field)]
        if unverified:
            findings.append(
                FindingSpec(
                    "EXTRACTION_UNVERIFIED",
                    "review",
                    [d.id, *(f.id for f in unverified)],
                    f"{d.original_filename}: {', '.join(sorted({f.field for f in unverified}))} could not be "
                    "verified or normalized; treated as unknown.",
                    {
                        "facts": [
                            {"field": f.field, "raw_value": f.raw_value, "verification": f.verification}
                            for f in unverified
                        ]
                    },
                )
            )
        orders = v.values("order_id")
        if len(orders) > 1:
            findings.append(
                FindingSpec(
                    "DOC_MULTIPLE_ORDER_IDS",
                    "review",
                    [d.id, *(f.id for f in v.verified("order_id"))],
                    f"{d.original_filename} references several orders: {', '.join(sorted(orders))}.",
                    {"order_ids": sorted(orders)},
                )
            )
        elif orders and case.order_id not in orders:
            findings.append(
                FindingSpec(
                    "ORDER_MISMATCH",
                    "blocking",
                    [d.id, *(f.id for f in v.verified("order_id"))],
                    f"{d.original_filename} references order {next(iter(orders))}, but the dispute is for "
                    f"{case.order_id}. Submission is blocked until corrected evidence or a source-backed exclusion.",
                    {"case_order_id": case.order_id, "document_order_id": next(iter(orders)), "document_id": d.id},
                )
            )
        elif not orders and d.doc_type in ("invoice", "delivery_record", "dispatch_record"):
            findings.append(
                FindingSpec(
                    "MISSING_ORDER_REFERENCE",
                    "review",
                    [d.id],
                    f"{d.original_filename} looks like a {d.doc_type.replace('_', ' ')} but has no verifiable "
                    "order ID, so it cannot support this dispute.",
                )
            )
        txns = v.values("transaction_id")
        if txns and case.transaction_id not in txns:
            findings.append(
                FindingSpec(
                    "TRANSACTION_MISMATCH",
                    "blocking",
                    [d.id, *(f.id for f in v.verified("transaction_id"))],
                    f"{d.original_filename} references transaction {', '.join(sorted(txns))}, not "
                    f"{case.transaction_id}.",
                    {"case_transaction_id": case.transaction_id, "document_transaction_ids": sorted(txns)},
                )
            )

    matching = [v for v in active if v.doc.extraction_status == "extracted" and _matches_case(v, case)]
    invoices = [v for v in matching if v.doc.doc_type == "invoice"]
    deliveries = [v for v in matching if v.doc.doc_type == "delivery_record"]
    dispatches = [v for v in matching if v.doc.doc_type == "dispatch_record"]

    order_date, order_date_sources = _order_date(case, invoices, settings)
    if order_date is None and order_date_sources:
        findings.append(
            FindingSpec("CONFLICTING_ORDER_DATES", "review", order_date_sources, "Invoices disagree on the order date.")
        )

    delivery_facts = [f for v in deliveries for f in v.verified("delivered_on")]
    delivery_dates = sorted({f.normalized_value for f in delivery_facts if f.normalized_value})
    if len(delivery_dates) > 1:
        findings.append(
            FindingSpec(
                "CONFLICTING_DELIVERY_DATES",
                "blocking",
                [f.id for f in delivery_facts],
                f"Delivery records disagree on the delivery date: {', '.join(delivery_dates)}.",
                {"delivery_dates": delivery_dates},
            )
        )
    if order_date is not None:
        for f in delivery_facts:
            if f.normalized_value and date.fromisoformat(f.normalized_value) < order_date:
                findings.append(
                    FindingSpec(
                        "DELIVERY_BEFORE_ORDER",
                        "blocking",
                        [f.document_id, f.id, *order_date_sources],
                        f"Delivery date {f.normalized_value} is before the order date {order_date.isoformat()}.",
                        {"delivered_on": f.normalized_value, "order_date": order_date.isoformat()},
                    )
                )

    amount_facts = [f for v in invoices for f in v.verified("amount")]
    amounts = {(f.normalized_value, f.unit) for f in amount_facts}
    invoice_amount_ok = False
    if len(amounts) > 1:
        findings.append(
            FindingSpec(
                "CONFLICTING_AMOUNTS",
                "review",
                [f.id for f in amount_facts],
                "Invoices for this order state different amounts.",
            )
        )
    elif len(amounts) == 1:
        value, unit = next(iter(amounts))
        currency = (unit or "paise:UNKNOWN").split(":", 1)[1]
        sources = [f.id for f in amount_facts]
        if currency == "UNKNOWN":
            findings.append(
                FindingSpec("CURRENCY_UNKNOWN", "review", sources, "The invoice amount has no explicit currency.")
            )
        elif currency != case.currency:
            findings.append(
                FindingSpec(
                    "CURRENCY_MISMATCH",
                    "review",
                    sources,
                    f"Invoice currency {currency} differs from the dispute currency {case.currency}.",
                )
            )
        elif int(value) != case.amount_paise:  # type: ignore[arg-type]
            findings.append(
                FindingSpec(
                    "AMOUNT_MISMATCH",
                    "review",
                    sources,
                    f"Invoice amount {format_inr(int(value))} differs from the disputed amount "  # type: ignore[arg-type]
                    f"{format_inr(case.amount_paise)}. A partial dispute needs an explicit reconciliation.",
                    {"invoice_amount_paise": int(value), "disputed_amount_paise": case.amount_paise},  # type: ignore[arg-type]
                )
            )
        else:
            invoice_amount_ok = True

    rules = {f.rule_id for f in findings}

    # Checklist ----------------------------------------------------------------
    checklist: dict[str, dict[str, Any]] = {}
    linkage_facts = [
        f for v in matching for f in v.verified("transaction_id") if f.normalized_value == case.transaction_id
    ]
    if "TRANSACTION_MISMATCH" in rules:
        checklist["order_linkage"] = {
            "status": "conflicting",
            "sources": [],
            "explanation": "A document cites a different transaction for this order.",
        }
    elif linkage_facts:
        checklist["order_linkage"] = {
            "status": "supported",
            "sources": [f.id for f in linkage_facts],
            "explanation": f"Document links {case.transaction_id} to {case.order_id}.",
        }
    else:
        checklist["order_linkage"] = {
            "status": "missing",
            "sources": [],
            "explanation": f"No document links transaction {case.transaction_id} to order {case.order_id}.",
        }

    def _mismatched(doc_type: str) -> list[DocView]:
        # Same-type documents that verifiably reference a different order.
        return [v for v in active if v.doc.doc_type == doc_type and v.values("order_id") and not _matches_case(v, case)]

    def _unlinked(doc_type: str) -> list[DocView]:
        return [v for v in active if v.doc.doc_type == doc_type and not v.values("order_id")]

    other_invoices = _mismatched("invoice")
    if invoices and invoice_amount_ok and not rules & {"CONFLICTING_ORDER_DATES"}:
        checklist["invoice"] = {
            "status": "supported",
            "sources": [f.id for f in amount_facts] + [f.id for v in invoices for f in v.verified("order_id")],
            "explanation": f"Invoice for {case.order_id} states {format_inr(case.amount_paise)}.",
        }
    elif invoices:
        checklist["invoice"] = {
            "status": "review_required",
            "sources": [v.doc.id for v in invoices],
            "explanation": "Invoice found, but its amount/currency needs review.",
        }
    elif other_invoices:
        checklist["invoice"] = {
            "status": "conflicting",
            "sources": [v.doc.id for v in other_invoices],
            "explanation": f"Only invoices that do not match {case.order_id} were provided.",
        }
    elif _unlinked("invoice"):
        checklist["invoice"] = {
            "status": "review_required",
            "sources": [v.doc.id for v in _unlinked("invoice")],
            "explanation": "An invoice was provided but has no verifiable order ID.",
        }
    else:
        checklist["invoice"] = {"status": "missing", "sources": [], "explanation": "No invoice for this order."}

    other_deliveries = _mismatched("delivery_record")
    if deliveries and delivery_dates and not rules & {"CONFLICTING_DELIVERY_DATES", "DELIVERY_BEFORE_ORDER"}:
        checklist["delivery_record"] = {
            "status": "supported",
            "sources": [f.id for f in delivery_facts] + [f.id for v in deliveries for f in v.verified("order_id")],
            "explanation": f"Delivery of {case.order_id} recorded on {delivery_dates[0]}.",
        }
    elif deliveries and delivery_dates:
        checklist["delivery_record"] = {
            "status": "conflicting",
            "sources": [f.id for f in delivery_facts],
            "explanation": "Delivery records contradict each other or the order date.",
        }
    elif deliveries:
        checklist["delivery_record"] = {
            "status": "review_required",
            "sources": [v.doc.id for v in deliveries],
            "explanation": "Delivery record found, but no verifiable delivery date.",
        }
    elif other_deliveries:
        checklist["delivery_record"] = {
            "status": "conflicting",
            "sources": [v.doc.id for v in other_deliveries],
            "explanation": f"The delivery record provided is not for {case.order_id}.",
        }
    elif _unlinked("delivery_record"):
        checklist["delivery_record"] = {
            "status": "review_required",
            "sources": [v.doc.id for v in _unlinked("delivery_record")],
            "explanation": "A delivery record was provided but has no verifiable order ID.",
        }
    elif dispatches:
        checklist["delivery_record"] = {
            "status": "missing",
            "sources": [v.doc.id for v in dispatches],
            "explanation": "Only dispatch/AWB evidence: it proves dispatch, not delivery to the customer.",
        }
    else:
        checklist["delivery_record"] = {
            "status": "missing",
            "sources": [],
            "explanation": "No delivery record for this order.",
        }
    return findings, checklist


def revalidate_case(session: Session, settings: Settings, case: Case) -> dict[str, Any]:
    """Recompute checklist and findings, persist changes with audit events, return the assessment."""
    findings, checklist = evaluate(session, settings, case)
    now = get_clock().now()

    current = {f.fingerprint: f for f in findings}
    open_rows = session.scalars(
        select(ValidationFinding).where(ValidationFinding.case_id == case.id, ValidationFinding.status == "open")
    ).all()
    open_by_fp = {r.fingerprint: r for r in open_rows}
    for fp, row in open_by_fp.items():
        if fp not in current:
            row.status = "resolved"
            row.resolved_at = now
            audit(
                session,
                event_type="validation.finding_resolved",
                summary=f"Resolved: {row.explanation}",
                actor_type="system",
                case_id=case.id,
                merchant_id=case.merchant_id,
                data={"finding_id": row.id, "rule_id": row.rule_id},
            )
    for fp, spec in current.items():
        if fp in open_by_fp:
            continue
        row = ValidationFinding(
            case_id=case.id,
            rule_id=spec.rule_id,
            severity=spec.severity,
            status="open",
            source_ids=spec.source_ids,
            explanation=spec.explanation,
            fingerprint=fp,
            details=spec.details,
            case_version=case.version,
        )
        session.add(row)
        session.flush()
        audit(
            session,
            event_type="validation.finding_opened",
            summary=spec.explanation,
            actor_type="system",
            case_id=case.id,
            merchant_id=case.merchant_id,
            data={
                "finding_id": row.id,
                "rule_id": spec.rule_id,
                "severity": spec.severity,
                "source_ids": spec.source_ids,
            },
        )

    staff = {
        u.staff_function: u.id
        for u in session.scalars(
            select(DemoUser).where(DemoUser.merchant_id == case.merchant_id, DemoUser.role == "staff")
        )
    }
    existing = {
        c.requirement_id: c for c in session.scalars(select(ChecklistItem).where(ChecklistItem.case_id == case.id))
    }
    for req_id, item in checklist.items():
        row = existing.get(req_id)
        if row is None:
            row = ChecklistItem(case_id=case.id, requirement_id=req_id, status="")
            session.add(row)
        changed = row.status != item["status"]
        row.status = item["status"]
        row.source_ids = item["sources"]
        row.explanation = item["explanation"]
        row.assignee_user_id = staff.get(REQUIREMENTS[req_id]["staff_function"])
        if changed:
            audit(
                session,
                event_type="checklist.updated",
                summary=f"{REQUIREMENTS[req_id]['label']}: {item['status'].replace('_', ' ')}.",
                actor_type="system",
                case_id=case.id,
                merchant_id=case.merchant_id,
                data={"requirement_id": req_id, "status": item["status"]},
            )

    flags = [f for f in case.flags if f != OperationalFlag.OCR_REQUIRED]
    if any(f.rule_id == "OCR_REQUIRED" for f in findings):
        flags.append(OperationalFlag.OCR_REQUIRED)
    case.flags = flags
    session.flush()
    return assess(session, case)


def assess(session: Session, case: Case) -> dict[str, Any]:
    """Evidence readiness for a pack. M2's submission gate rechecks this plus deadline/policy."""
    items = session.scalars(select(ChecklistItem).where(ChecklistItem.case_id == case.id)).all()
    open_findings = session.scalars(
        select(ValidationFinding).where(ValidationFinding.case_id == case.id, ValidationFinding.status == "open")
    ).all()
    blockers = [
        f"{REQUIREMENTS[i.requirement_id]['label']}: {i.status.replace('_', ' ')}"
        for i in items
        if i.status != "supported"
    ]
    blockers += [f"{f.rule_id}: {f.explanation}" for f in open_findings if f.severity in BLOCKING_SEVERITIES]
    has_blocking_contradiction = any(f.severity == "blocking" for f in open_findings)
    return {
        "evidence_ready": bool(items) and not blockers,
        "blocking_contradiction": has_blocking_contradiction,
        "blockers": blockers,
        "case_version": case.version,
    }
