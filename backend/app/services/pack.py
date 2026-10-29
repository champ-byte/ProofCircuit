"""Immutable, source-linked evidence packs (PRD 8.5, 11.2.4).

- `orderStatus` is derived from verified shipping facts and cited; dispatch alone never yields
  an autonomous `ORDER_DELIVERED` and does not permit a defense under the demo policy.
- `comments` is a short plain-English remark from a deterministic template filled only with
  span-verified values; it references evidence by position in the uploaded `files` list.
  The 240 code-point cap is *application policy*, not a confirmed Paytm limit.
- Uploads: a neutral English cover PDF plus original supporting files that the simulator's
  assumed allowlist accepts (PDF/JPEG/PNG). TXT/JSON originals are never redrawn as PDFs; their
  cited excerpts appear in the cover and manifest instead.
- Identical content reuses the existing pack; any change creates a new version.
"""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Case, ChecklistItem, EvidenceDocument, EvidencePack, ExtractedFact
from app.domain.intent import intent_digest
from app.domain.money import format_inr
from app.services.audit import audit
from app.services.fixtures import format_doc_date, text_pdf
from app.services.storage import read_original
from app.services.validation import is_active, revalidate_case

UPLOADABLE = ("application/pdf", "image/jpeg", "image/png")
MAX_UPLOAD_FILES = 5
COMMENTS_MAX_CODE_POINTS = 240


class PackBlocked(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass
class BuiltPack:
    pack: EvidencePack
    created: bool


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _facts(session: Session, ids: list[str]) -> list[ExtractedFact]:
    if not ids:
        return []
    return list(session.scalars(select(ExtractedFact).where(ExtractedFact.id.in_(ids))))


def _citation(f: ExtractedFact, doc: EvidenceDocument) -> dict[str, Any]:
    return {
        "fact_id": f.id,
        "document_id": doc.id,
        "filename": doc.original_filename,
        "document_sha256": doc.sha256,
        "page": f.page_number,
        "start": f.span_start,
        "end": f.span_end,
        "raw_value": f.raw_value,
        "page_text_sha256": f.page_text_sha256,
        "method": f.method,
    }


def _ascii_safe(text: str) -> str:
    return text if text.isascii() else "[non-Latin text; see manifest.json]"


def _pack_dir(settings: Settings, case_id: str, version: int) -> Path:
    return settings.data_path / "packs" / case_id / f"v{version}"


def build_comments(
    *,
    order_id: str,
    delivered_on: str,
    receipt_no: str | None,
    delivery_pos: int | None,
    invoice_no: str | None,
    invoice_pos: int | None,
    amount_paise: int,
) -> str:
    """Template-first remark from verified values only. Progressively drops optional detail."""
    delivered = format_doc_date(date.fromisoformat(delivered_on))
    amount = f"INR {amount_paise // 100}.{amount_paise % 100:02d}"
    receipt = f" (delivery receipt {receipt_no})" if receipt_no else ""
    dfile = f", file {delivery_pos}" if delivery_pos else ", see file 1"
    ifile = f" is file {invoice_pos}" if invoice_pos else " is summarised in file 1"
    invoice = f"invoice {invoice_no} for {amount}" if invoice_no else f"invoice for {amount}"
    candidates = [
        f"Order {order_id} delivered on {delivered}{receipt}{dfile}; {invoice}{ifile}. Case summary: file 1.",
        f"Order {order_id} delivered on {delivered}{dfile}; {invoice}{ifile}.",
        f"Order {order_id} delivered on {delivered}. Evidence summary: file 1.",
    ]
    for text in candidates:
        if len(text) <= COMMENTS_MAX_CODE_POINTS:
            return text
    raise PackBlocked(["comments cannot fit the 240 code-point application cap"])


def build_pack(session: Session, settings: Settings, case: Case) -> BuiltPack:
    assessment = revalidate_case(session, settings, case)
    if not assessment["evidence_ready"]:
        raise PackBlocked(assessment["blockers"] or ["evidence is not ready"])

    checklist = {
        c.requirement_id: c for c in session.scalars(select(ChecklistItem).where(ChecklistItem.case_id == case.id))
    }
    delivery_facts = _facts(session, list(checklist["delivery_record"].source_ids))
    invoice_facts = _facts(session, list(checklist["invoice"].source_ids))
    linkage_facts = _facts(session, list(checklist["order_linkage"].source_ids))
    docs = {d.id: d for d in session.scalars(select(EvidenceDocument).where(EvidenceDocument.case_id == case.id))}

    delivered = [f for f in delivery_facts if f.field == "delivered_on"]
    if not delivered:
        # A dispatch/AWB record could map to ORDER_IN_TRANSIT, but it does not satisfy this
        # goods-not-received policy and never permits an autonomous defense.
        raise PackBlocked(["no verified delivered-event record; orderStatus cannot be derived"])
    order_status = "ORDER_DELIVERED"
    delivery_doc = docs[delivered[0].document_id]
    invoice_doc_ids = list(dict.fromkeys(f.document_id for f in invoice_facts))
    invoice_doc = docs[invoice_doc_ids[0]] if invoice_doc_ids else None

    # Upload list: cover first, then uploadable originals (invoice, delivery record).
    supporting = [d for d in (invoice_doc, delivery_doc) if d is not None]
    uploadable = [d for d in supporting if d.mime_type in UPLOADABLE and is_active(d)][: MAX_UPLOAD_FILES - 1]
    positions = {d.id: i + 2 for i, d in enumerate(uploadable)}

    def fact_value(facts: list[ExtractedFact], name: str) -> ExtractedFact | None:
        return next((f for f in facts if f.field == name and f.verification == "span_verified"), None)

    receipt_fact = next(
        (
            f
            for f in session.scalars(select(ExtractedFact).where(ExtractedFact.document_id == delivery_doc.id))
            if f.field == "receipt_number" and f.verification == "span_verified" and not f.stale
        ),
        None,
    )
    invoice_no_fact = None
    if invoice_doc is not None:
        invoice_no_fact = next(
            (
                f
                for f in session.scalars(select(ExtractedFact).where(ExtractedFact.document_id == invoice_doc.id))
                if f.field == "invoice_number" and f.verification == "span_verified" and not f.stale
            ),
            None,
        )
    comments = build_comments(
        order_id=case.order_id,
        delivered_on=delivered[0].normalized_value or "",
        receipt_no=receipt_fact.normalized_value if receipt_fact else None,
        delivery_pos=positions.get(delivery_doc.id),
        invoice_no=invoice_no_fact.normalized_value if invoice_no_fact else None,
        invoice_pos=positions.get(invoice_doc.id) if invoice_doc else None,
        amount_paise=case.amount_paise,
    )

    claims: list[dict[str, Any]] = []
    for label, facts in (
        ("Order delivered on the stated date", delivered + [f for f in delivery_facts if f.field == "order_id"]),
        ("Invoice for the disputed order and amount", invoice_facts),
        ("Transaction linked to the order", linkage_facts),
    ):
        claims.append(
            {
                "claim": label,
                "citations": [_citation(f, docs[f.document_id]) for f in facts],
            }
        )
    if receipt_fact:
        claims.append({"claim": "Delivery receipt number", "citations": [_citation(receipt_fact, delivery_doc)]})
    if invoice_no_fact and invoice_doc:
        claims.append({"claim": "Invoice number", "citations": [_citation(invoice_no_fact, invoice_doc)]})

    tz = ZoneInfo(settings.app_timezone)
    cover_lines = [
        "DISPUTE RESPONSE SUMMARY (SYNTHETIC DEMO - PAYTM SIMULATOR ONLY)",
        f"Merchant MID: {case.mid}    Dispute: {case.external_dispute_id}",
        f"Order: {case.order_id}    Transaction: {case.transaction_id}",
        f"Disputed amount: {format_inr(case.amount_paise).replace('₹', 'INR ')}",
        f"Response deadline: {case.deadline_utc.astimezone(tz).strftime('%Y-%m-%d %H:%M')} IST",
        f"Order status asserted: {order_status} (derived from a cited delivery record)",
        "",
        "Verified facts and their sources:",
    ]
    for claim in claims:
        cover_lines.append(f"- {claim['claim']}")
        for c in claim["citations"]:
            pos = positions.get(c["document_id"])
            where = f"file {pos}" if pos else "original not uploaded (text evidence; see manifest)"
            cover_lines.append(
                f"    {_ascii_safe(c['raw_value'])[:60]}  <- {_ascii_safe(c['filename'])[:40]}, p{c['page']}, {where}"
            )
    cover_lines += ["", "Files: 1 = this summary"] + [
        f"       {pos} = {_ascii_safe(docs[doc_id].original_filename)[:60]} (sha256 {docs[doc_id].sha256[:16]}...)"
        for doc_id, pos in positions.items()
    ]
    cover_lines += [
        "",
        "This summary was generated by ProofCircuit from cited source records.",
        "It is not itself evidence of delivery; see the original files.",
    ]
    cover = text_pdf(cover_lines)

    upload_files: list[dict[str, Any]] = [
        {
            "position": 1,
            "name": "cover.pdf",
            "sha256": hashlib.sha256(cover).hexdigest(),
            "size": len(cover),
            "mime": "application/pdf",
            "role": "summary",
            "document_id": None,
        }
    ]
    originals: dict[str, bytes] = {}
    for d in uploadable:
        data = read_original(settings, d.storage_key)
        if hashlib.sha256(data).hexdigest() != d.sha256:
            raise PackBlocked([f"stored original {d.original_filename} no longer matches its SHA-256"])
        originals[d.id] = data
        upload_files.append(
            {
                "position": positions[d.id],
                "name": d.original_filename,
                "sha256": d.sha256,
                "size": d.size_bytes,
                "mime": d.mime_type,
                "role": d.doc_type,
                "document_id": d.id,
            }
        )

    digest = intent_digest(
        mid=case.mid,
        dispute_id=case.external_dispute_id,
        action="DEFEND",
        order_status=order_status,
        comments=comments,
        file_sha256s=[f["sha256"] for f in upload_files],
    )
    manifest: dict[str, Any] = {
        "schema": "proofcircuit.pack/1",
        "synthetic": True,
        "provider": "paytm-simulator",
        "case": {
            "case_id": case.id,
            "mid": case.mid,
            "dispute_id": case.external_dispute_id,
            "order_id": case.order_id,
            "transaction_id": case.transaction_id,
            "amount_paise": case.amount_paise,
            "currency": case.currency,
            "deadline_utc": case.deadline_utc.isoformat(),
            "reason": case.reason,
        },
        "case_version": case.version,
        "order_status": {"value": order_status, "citations": [_citation(f, docs[f.document_id]) for f in delivered]},
        "comments": comments,
        "comments_policy": "Application cap of 240 code points; not a confirmed Paytm limit.",
        "upload_files": upload_files,
        "claims": claims,
        "evidence_documents": [
            {
                "document_id": d.id,
                "filename": d.original_filename,
                "sha256": d.sha256,
                "mime": d.mime_type,
                "doc_type": d.doc_type,
                "active": is_active(d),
                "exclusion_reason": d.exclusion_reason,
                "uploaded": d.id in positions,
            }
            for d in sorted(docs.values(), key=lambda d: (d.created_at, d.id))
        ],
        "intent_digest": digest,
        "notes": ["Hashes identify content; they do not prove a document is authentic."],
    }
    pack_hash = hashlib.sha256(_canonical(manifest)).hexdigest()

    existing = session.scalar(
        select(EvidencePack).where(EvidencePack.case_id == case.id, EvidencePack.pack_hash == pack_hash)
    )
    if existing is not None:
        case.latest_pack_id = existing.id
        return BuiltPack(existing, False)

    version = (
        int(
            session.scalar(
                select(func.coalesce(func.max(EvidencePack.version), 0)).where(EvidencePack.case_id == case.id)
            )
        )
        + 1
    )
    out = _pack_dir(settings, case.id, version)
    out.mkdir(parents=True, exist_ok=True)  # an orphan dir from a rolled-back build is overwritten
    (out / "manifest.json").write_bytes(json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
    (out / "cover.pdf").write_bytes(cover)
    for d in uploadable:
        (out / f"file{positions[d.id]}{Path(d.storage_key).suffix}").write_bytes(originals[d.id])
    (out / "evidence-index.html").write_text(_index_html(manifest, pack_hash, version), encoding="utf-8")

    pack = EvidencePack(
        case_id=case.id,
        version=version,
        case_version=case.version,
        document_hashes=[f["sha256"] for f in upload_files],
        manifest=manifest,
        pack_hash=pack_hash,
        upload_files=upload_files,
        intent_digest=digest,
        order_status=order_status,
        comments=comments,
        storage_dir=str(out.relative_to(settings.data_path)),
    )
    session.add(pack)
    session.flush()
    case.latest_pack_id = pack.id
    audit(
        session,
        event_type="pack.built",
        summary=f"Evidence pack v{version} built ({len(upload_files)} upload files).",
        actor_type="system",
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={
            "pack_id": pack.id,
            "version": version,
            "pack_hash": pack_hash,
            "order_status": order_status,
            "comments": comments,
        },
    )
    return BuiltPack(pack, True)


def pack_upload_parts(settings: Settings, pack: EvidencePack) -> list[tuple[str, bytes, str]]:
    """Read the exact stored upload files and re-verify their hashes before any send."""
    base = settings.data_path / pack.storage_dir
    parts: list[tuple[str, bytes, str]] = []
    for f in pack.upload_files:
        path = base / "cover.pdf" if f["position"] == 1 else next(base.glob(f"file{f['position']}.*"))
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise PackBlocked([f"pack file {f['name']} changed on disk"])
        parts.append((f["name"], data, f["mime"]))
    return parts


def _index_html(manifest: dict[str, Any], pack_hash: str, version: int) -> str:
    e = html.escape
    c = manifest["case"]
    amount = f"{c['amount_paise'] // 100}.{c['amount_paise'] % 100:02d}"
    rows = []
    for claim in manifest["claims"]:
        for cit in claim["citations"]:
            rows.append(
                f"<tr><td>{e(claim['claim'])}</td><td><code>{e(cit['raw_value'])}</code></td>"
                f"<td>{e(cit['filename'])} p{cit['page']} [{cit['start']}, {cit['end']})</td>"
                f"<td><code>{e(cit['document_sha256'][:16])}…</code></td></tr>"
            )
    files = "".join(
        f"<li>File {f['position']}: {e(f['name'])} ({e(f['role'])}, sha256 <code>{e(f['sha256'][:16])}…</code>)</li>"
        for f in manifest["upload_files"]
    )
    docs = "".join(
        f"<li>{e(d['filename'])}: {'active' if d['active'] else 'excluded — ' + e(d['exclusion_reason'] or '')}</li>"
        for d in manifest["evidence_documents"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Evidence index — {e(c["dispute_id"])} v{version}</title>
<style>body{{font-family:system-ui,sans-serif;color:#1f2933;max-width:960px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #d9e2e2;padding:6px;text-align:left}}</style>
</head><body>
<p><strong>Synthetic data · Paytm simulator</strong></p>
<h1>Evidence index: {e(c["dispute_id"])} (pack v{version})</h1>
<p>Order {e(c["order_id"])} · Transaction {e(c["transaction_id"])} · Amount {amount} {e(c["currency"])}</p>
<p>orderStatus: <code>{e(manifest["order_status"]["value"])}</code><br>comments: {e(manifest["comments"])}</p>
<p>Pack hash <code>{e(pack_hash)}</code></p>
<h2>Uploaded files</h2><ol style="list-style:none;padding:0">{files}</ol>
<h2>Claims and sources</h2>
<table><thead><tr><th>Claim</th><th>Cited value</th><th>Source (code-point span)</th><th>Document hash</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<h2>All evidence documents</h2><ul>{docs}</ul>
<p>Hashes identify content; they do not prove that a document is authentic.</p>
</body></html>
"""
