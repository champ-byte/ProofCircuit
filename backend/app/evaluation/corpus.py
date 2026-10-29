"""Deterministic 40-case synthetic corpus (PRD 15.2): 5 categories x 8 variants from reusable templates.

Each category has 6 development and 2 held-out variants; the ten-case first pass is variant 0
(development) plus variant 6 (held-out) of every category. Specs say what each case looks like and
how simulated staff/provider respond; ground truth (expected behaviour) is kept in a separate file
and never enters model context. These are synthetic variants, not independent merchant histories.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.services.fixtures import format_doc_date, text_pdf

CORPUS_VERSION = "corpus_v1"
SEED = 20261029
CATEGORIES = (
    "missing_receipt",
    "wrong_order_id",
    "conflicting_delivery_dates",
    "expired_deadline",
    "upload_pod_rejection",
)
VARIANTS = 8
HELD_OUT = (6, 7)
FIRST_PASS = (0, 6)  # one development + one held-out variant per category

CORPUS_PATH = REPO_ROOT / "fixtures" / "benchmark" / f"{CORPUS_VERSION}.json"
GROUND_TRUTH_PATH = REPO_ROOT / "fixtures" / "ground_truth" / f"{CORPUS_VERSION}.json"

EVAL_MID = "MID-EVAL-001"  # its users are in fixtures/demo_org.json (seeded with the demo)

ITEMS = (
    "Sheesham wood 3-seater sofa x 1",
    "Teak dining table (6 seater) x 1",
    "Queen bed frame with storage x 1",
    "Two-door wardrobe x 1",
    "Office chair, ergonomic x 2",
    "Bookshelf, 5 tier x 1",
    "Coffee table, glass top x 1",
    "Shoe rack, 4 shelf x 3",
)
NAMES = ("P. Deshmukh", "R. Kulkarni", "S. Patil", "A. Joshi", "M. Shaikh", "K. Iyer", "N. Gupta", "V. Rao")
AGENTS = ("Sanjay", "Imran", "Rahul", "Pooja")
REJECTIONS = (
    "Customer signature not visible on the delivery receipt",
    "Delivery receipt is not legible; please upload a clear copy",
    "Proof does not show the recipient's signature",
    "Delivery date on the receipt cannot be read",
)
REPLIES = ("पावती शोधतो आहे, थोड्या वेळात पाठवतो.", "हो, पाठवतो.", "आज पाठवतो.")


def _variant(category: str, i: int) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(f"{SEED}:{category}:{i}")
    n = CATEGORIES.index(category) * VARIANTS + i + 1
    case_id = f"EVAL-{n:03d}"
    amount_paise = rng.randrange(1_499_00, 79_999_00, 100) + rng.choice((0, 50))
    dispute = {
        "disputeId": f"DSP-EVAL-{n:03d}",
        "orderId": f"ORD-EVAL-{rng.randrange(10_000, 99_999)}",
        "transactionId": f"TXN-EVAL-{rng.randrange(100_000, 999_999)}",
        "custId": f"CUST-EVAL-{rng.randrange(100, 999)}",
        "bankReferenceNo": f"BANK-EVAL-{rng.randrange(10_000, 99_999)}",
        "extSerialNo": f"EXT-EVAL-{n:03d}",
        "amount": f"{amount_paise // 100}.{amount_paise % 100:02d}",
    }
    # Exact, non-midnight deadlines relative to the seed time (PRD 11.2.1).
    deadline_minutes = rng.randrange(24 * 60, 72 * 60) + rng.choice((7, 23, 41))
    timing = {
        "transaction_hours_before": rng.randrange(30, 120),
        "deadline_minutes_from_seed": deadline_minutes,
        "delivery_offset_days": rng.randrange(1, 4),
    }
    docs: dict[str, dict[str, Any]] = {
        "invoice": {"invoice_no": f"INV-EVAL-{rng.randrange(1000, 9999)}", "item": rng.choice(ITEMS)},
        "receipt_correct": {
            "receipt_no": f"DLV-EVAL-{rng.randrange(1000, 9999)}",
            "received_by": rng.choice(NAMES),
            "agent": rng.choice(AGENTS),
        },
    }
    script: list[dict[str, Any]] = []
    changed = ["order/transaction IDs", "amount", "item", "dates relative to seed"]
    truth: dict[str, Any] = {"category": category}

    if category == "missing_receipt":
        if i % 3 == 2:
            # Staff answer in text first and then send the file without being asked again (as people do).
            script.append({"when": "evidence_requested", "do": "reply", "text": rng.choice(REPLIES)})
            script.append({"when": "immediately", "do": "upload", "doc": "receipt_correct"})
            changed.append("staff replies in text, then sends the receipt unprompted")
        else:
            script.append({"when": "evidence_requested", "do": "upload", "doc": "receipt_correct"})
        truth |= {
            "expected_behavior": "submit",
            "acceptable_outcomes": ["verified"],
            "expected_rules": [],
            "submission_expected": True,
        }
    elif category == "wrong_order_id":
        docs["receipt_wrong"] = {
            "receipt_no": f"DLV-EVAL-{rng.randrange(1000, 9999)}",
            "order_id": f"ORD-EVAL-{rng.randrange(10_000, 99_999)}",
            "received_by": rng.choice(NAMES),
            "agent": rng.choice(AGENTS),
        }
        script += [
            {"when": "evidence_requested", "do": "upload", "doc": "receipt_wrong"},
            {"when": "evidence_requested", "do": "upload", "doc": "receipt_correct"},
        ]
        changed.append("first receipt names another order")
        truth |= {
            "expected_behavior": "detect contradiction, request the correct receipt, then submit",
            "acceptable_outcomes": ["verified"],
            "expected_rules": ["ORDER_MISMATCH"],
            "submission_expected": True,
        }
    elif category == "conflicting_delivery_dates":
        # The conflict must exist before any submission is possible, so the first receipt is always dated
        # before the order. Some variants then get a second receipt with yet another date if the agent asks
        # again; both rules may fire, and no pack can be submitted either way.
        docs["receipt_conflict"] = {**docs["receipt_correct"], "delivery_offset_days": -rng.randrange(1, 4)}
        script.append({"when": "evidence_requested", "do": "upload", "doc": "receipt_conflict"})
        if i in (0, 2, 4, 7):
            changed.append("receipt dated before the order")
        else:
            script.append({"when": "evidence_requested", "do": "upload", "doc": "receipt_correct"})
            changed.append("receipt dated before the order, then a second receipt with a different date")
        truth |= {
            "expected_behavior": "do not submit; escalate or keep asking staff",
            "acceptable_outcomes": ["escalated", "waiting"],
            "expected_rules": ["DELIVERY_BEFORE_ORDER"],
            "submission_expected": False,
        }
    elif category == "expired_deadline":
        if i in (0, 2, 4, 7):
            timing["deadline_minutes_from_seed"] = -rng.randrange(30, 48 * 60)
            changed.append("deadline already passed at intake")
            script.append({"when": "evidence_requested", "do": "upload", "doc": "receipt_correct"})
        else:
            timing["deadline_minutes_from_seed"] = 2  # passes while waiting for staff
            changed.append("deadline passes while waiting for staff")
            script += [
                {"when": "evidence_requested", "do": "wait_for_deadline"},
                {"when": "immediately", "do": "upload", "doc": "receipt_correct"},
            ]
        truth |= {
            "expected_behavior": "no submission after the deadline",
            "acceptable_outcomes": ["denied"],
            "expected_rules": [],
            "submission_expected": False,
        }
    else:  # upload_pod_rejection
        docs["receipt_signed"] = {
            **docs["receipt_correct"],
            "receipt_no": docs["receipt_correct"]["receipt_no"] + "-S",
            "received_by": docs["receipt_correct"]["received_by"] + " (legible signed copy)",
        }
        reason = rng.choice(REJECTIONS)
        script += [
            {"when": "evidence_requested", "do": "upload", "doc": "receipt_correct"},
            {"when": "verified", "count": 1, "do": "pod_reject", "comment": reason},
            {"when": "evidence_requested", "do": "upload", "doc": "receipt_signed"},
        ]
        changed.append(f"provider rejects the first upload: {reason!r}")
        repeat = i in (4, 7)
        if repeat:
            script.append({"when": "verified", "count": 2, "do": "pod_reject", "comment": "Signature still unclear"})
            changed.append("provider rejects the corrected upload too")
        truth |= {
            "expected_behavior": "one correction round, then escalate" if repeat else "one correction round",
            "acceptable_outcomes": ["escalated"] if repeat else ["repaired"],
            "expected_rules": [],
            "submission_expected": True,
            "expected_verified_submissions": 2,
        }

    spec = {
        "case_id": case_id,
        "category": category,
        "variant": i,
        "split": "held_out" if i in HELD_OUT else "development",
        "first_pass": i in FIRST_PASS,
        "dispute": dispute,
        "timing": timing,
        "documents": docs,
        "script": script,
        "changed_fields": changed,
    }
    return spec, truth


def generate() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    specs, truth = [], {}
    for category in CATEGORIES:
        for i in range(VARIANTS):
            spec, t = _variant(category, i)
            specs.append(spec)
            truth[spec["case_id"]] = t
    return specs, truth


def write(corpus_path: Path = CORPUS_PATH, truth_path: Path = GROUND_TRUTH_PATH) -> None:
    specs, truth = generate()
    corpus_path.write_text(
        json.dumps({"version": CORPUS_VERSION, "seed": SEED, "cases": specs}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    truth_path.write_text(
        json.dumps({"version": CORPUS_VERSION, "labels": truth}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load(split: str = "first_pass") -> list[dict[str, Any]]:
    cases = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))["cases"]
    if split == "first_pass":
        return [c for c in cases if c["first_pass"]]
    if split in ("development", "held_out"):
        return [c for c in cases if c["split"] == split]
    if split == "all":
        return cases
    raise ValueError(f"unknown split {split}")


def load_ground_truth() -> dict[str, dict[str, Any]]:
    return json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))["labels"]


# --- Document rendering (deterministic text-layer PDFs, Latin text only) -----------------------------


def render(
    spec: dict[str, Any], name: str, order_date: date, order_id_override: str | None = None
) -> tuple[str, bytes]:
    d, doc = spec["dispute"], spec["documents"][name]
    footer = "This document is synthetic and was generated for an evaluation corpus."
    if name == "invoice":
        lines = [
            "EVAL FURNITURE DEMO - TAX INVOICE (SYNTHETIC EVALUATION DOCUMENT)",
            f"Invoice No: {doc['invoice_no']}",
            f"Order ID: {d['orderId']}",
            f"Order Date: {format_doc_date(order_date)}",
            f"Customer: {d['custId']}",
            f"Item: {doc['item']}",
            f"Amount: INR {d['amount']}",
            "Payment Mode: Paytm",
            f"Transaction ID: {d['transactionId']}",
            footer,
        ]
    else:
        offset = doc.get("delivery_offset_days", spec["timing"]["delivery_offset_days"])
        lines = [
            "EVAL FURNITURE DEMO - DELIVERY RECEIPT (SYNTHETIC EVALUATION DOCUMENT)",
            f"Receipt No: {doc['receipt_no']}",
            f"Order ID: {order_id_override or doc.get('order_id') or d['orderId']}",
            f"Delivered On: {format_doc_date(order_date + timedelta(days=offset))}",
            "Delivered To: Registered address on file",
            f"Received By (signature): {doc['received_by']}",
            f"Delivery Agent: {doc['agent']}",
            footer,
        ]
    return f"{name}_{spec['case_id']}.pdf", text_pdf(lines)
