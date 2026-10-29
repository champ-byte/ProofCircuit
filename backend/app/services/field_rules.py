"""Deterministic field proposals from stored page text.

This is the M1 proposer: it reads labelled lines ("Order ID: ...") and JSON keys and proposes
(field, raw_value, anchor). It never computes offsets itself; `locate_span` does that. In M3 an
LLM proposer can supply the same (raw_value, quote) shape and go through the same locator.
Evidence text is untrusted data: nothing here executes or obeys it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_LABELS: dict[str, tuple[str, ...]] = {
    "order_id": ("order id", "order no", "order no.", "order number", "ऑर्डर आयडी", "ऑर्डर आईडी", "ऑर्डर क्रमांक"),
    "transaction_id": ("transaction id", "txn id"),
    "invoice_number": ("invoice no", "invoice no.", "invoice number"),
    "receipt_number": ("receipt no", "receipt no.", "receipt number", "पावती क्रमांक"),
    "order_date": ("order date", "ऑर्डर दिनांक"),
    "delivered_on": ("delivered on", "delivery date", "डिलिव्हरी दिनांक", "डिलीवरी तिथि"),
    "dispatched_on": ("dispatched on", "shipped on"),
    "awb_number": ("awb", "awb no", "awb no.", "awb number", "tracking no", "tracking number"),
    "amount": ("amount", "invoice amount", "total", "total amount"),
    "received_by": ("received by", "received by (signature)", "प्राप्तकर्ता"),
}
_LABEL_TO_FIELD = {label.casefold(): field for field, labels in _LABELS.items() for label in labels}

_JSON_KEYS: dict[str, str] = {
    "order_id": r"order_?id|order_?no|order_?number",
    "transaction_id": r"transaction_?id|txn_?id",
    "invoice_number": r"invoice_?(?:no|number)",
    "receipt_number": r"receipt_?(?:no|number)",
    "order_date": r"order_?date",
    "delivered_on": r"delivered_?on|delivery_?date",
    "dispatched_on": r"dispatched_?on|shipped_?on",
    "awb_number": r"awb(?:_?(?:no|number))?",
    "amount": r"amount|total(?:_?amount)?",
    "received_by": r"received_?by",
}

_LINE = re.compile(r"^[ \t]*(?P<label>[^:：\n]{1,60}?)[ \t]*[:：][ \t]*(?P<value>[^\n]*?)[ \t]*$", re.MULTILINE)
_INJECTION = re.compile(
    r"ignore (?:all |any |the |previous |prior )*(?:instructions|rules|polic(?:y|ies))"
    r"|disregard (?:all |any |the |previous )*(?:instructions|rules)"
    r"|(?:approve|submit|accept) (?:this|the) (?:case|dispute|defen[cs]e|pack)"
    r"|system prompt|reveal (?:the |your )?(?:secrets?|keys?|prompt)|call the tool",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FieldProposal:
    field: str
    raw_value: str
    page_number: int
    anchor: str


def propose_text_fields(pages: list[str]) -> list[FieldProposal]:
    proposals: list[FieldProposal] = []
    for page_number, text in enumerate(pages, start=1):
        for m in _LINE.finditer(text):
            field = _LABEL_TO_FIELD.get(m.group("label").strip().casefold())
            value = m.group("value")
            if field and value:
                proposals.append(FieldProposal(field, value, page_number, m.group(0)))
    return proposals


def propose_json_fields(text: str) -> list[FieldProposal]:
    proposals: list[FieldProposal] = []
    for field, key in _JSON_KEYS.items():
        pattern = re.compile(rf'"(?:{key})"\s*:\s*(?:"(?P<s>(?:[^"\\\n]|\\.)*)"|(?P<n>-?\d+(?:\.\d+)?))', re.IGNORECASE)
        for m in pattern.finditer(text):
            value = m.group("s") if m.group("s") is not None else m.group("n")
            if value:
                proposals.append(FieldProposal(field, value, 1, m.group(0)))
    return proposals


def classify_document(pages: list[str], fields: set[str]) -> str:
    head = next((line for page in pages for line in page.splitlines() if line.strip()), "").casefold()
    if "invoice_number" in fields or "invoice" in head:
        return "invoice"
    if "delivered_on" in fields:
        return "delivery_record"
    if fields & {"awb_number", "dispatched_on"}:
        return "dispatch_record"
    return "other"


def detect_untrusted_instructions(pages: list[str]) -> list[str]:
    return sorted({m.group(0) for page in pages for m in _INJECTION.finditer(page)})
