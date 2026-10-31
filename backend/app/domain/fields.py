"""Normalize located raw values. Normalization happens only *after* the raw substring is cited."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

ID_FIELDS = {"order_id", "transaction_id", "invoice_number", "receipt_number", "awb_number"}
DATE_FIELDS = {"order_date", "delivered_on", "dispatched_on"}
AMOUNT_FIELDS = {"amount"}
TEXT_FIELDS = {"received_by"}

_DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y")  # ISO and 02-Jan-2030 only; slash dates are ambiguous
_CURRENCY = re.compile(r"^(?:(INR|Rs\.?|₹)\s*)?([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(INR)?$", re.IGNORECASE)
_GROUPED = re.compile(r"^\d{1,3}(,\d{2})*,\d{3}$|^\d{1,3}(,\d{3})+$|^\d+$")  # Indian or Western grouping


@dataclass(frozen=True)
class Normalized:
    value: str | None  # None means "present but not normalizable" -> treated as unknown
    unit: str | None
    note: str = ""


def normalize_id(raw: str) -> Normalized:
    # Keep raw formatting; only trim surrounding whitespace. Never strip inner characters.
    value = raw.strip()
    return Normalized(value or None, "id")


def parse_date(raw: str) -> date | None:
    text = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def normalize_date(raw: str) -> Normalized:
    parsed = parse_date(raw)
    if parsed is None:
        return Normalized(None, "date", f"unrecognized date format {raw!r}")
    return Normalized(parsed.isoformat(), "date")


def normalize_amount(raw: str) -> Normalized:
    """'INR 18500.00' -> '1850000' with unit 'paise:INR'. Missing currency stays explicit."""
    match = _CURRENCY.fullmatch(raw.strip())
    if not match:
        return Normalized(None, "paise:UNKNOWN", f"unrecognized amount {raw!r}")
    prefix, number, suffix = match.groups()
    if "," in number and not _GROUPED.fullmatch(number.split(".")[0]):
        return Normalized(None, "paise:UNKNOWN", f"invalid digit grouping {raw!r}")
    try:
        amount = Decimal(number.replace(",", ""))
    except InvalidOperation:
        return Normalized(None, "paise:UNKNOWN", f"invalid amount {raw!r}")
    currency = "INR" if (prefix or suffix) else "UNKNOWN"
    return Normalized(str(int(amount * 100)), f"paise:{currency}")


def normalize_field(field: str, raw: str) -> Normalized:
    if field in ID_FIELDS:
        return normalize_id(raw)
    if field in DATE_FIELDS:
        return normalize_date(raw)
    if field in AMOUNT_FIELDS:
        return normalize_amount(raw)
    return Normalized(raw.strip() or None, "text")
