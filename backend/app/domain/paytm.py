"""Paytm-shaped boundary helpers: money, naive timestamps and S2S callback normalization.

External money is a decimal string; internally we use integer paise. External times are
naive `YYYY-MM-DD HH:mm:ss` strings; the timezone is an explicit, configurable *assumption*
(PAYTM_NAIVE_TIMEZONE), not a verified property of real payloads (PRD Section 8.1).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.enums import ProviderDisputeStatus, normalize_dispute_status

PAYTM_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_PAYTM_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_MONEY_RE = re.compile(r"^\d+(\.\d{1,2})?$")


class PaytmFieldError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


def parse_amount_paise(value: Any, field: str) -> int:
    """Parse a Paytm decimal string to integer paise. Never rounds; rejects >2 decimals."""
    if not isinstance(value, str):
        raise PaytmFieldError(field, "amount must be a decimal string")
    text = value.strip()
    if not _MONEY_RE.fullmatch(text):
        raise PaytmFieldError(field, f"invalid amount {value!r} (non-negative, at most two decimals)")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - regex already guards
        raise PaytmFieldError(field, f"invalid amount {value!r}") from exc
    if not amount.is_finite() or amount < 0:
        raise PaytmFieldError(field, "amount must be finite and non-negative")
    return int(amount * 100)


def parse_optional_amount_paise(value: Any, field: str) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_amount_paise(value, field)


def parse_naive_time(value: Any, field: str, assumed_tz: str) -> datetime:
    """Convert a naive Paytm timestamp to aware UTC under the configured timezone assumption."""
    if not isinstance(value, str) or not _PAYTM_TIME_RE.fullmatch(value.strip()):
        raise PaytmFieldError(field, f"expected 'YYYY-MM-DD HH:mm:ss', got {value!r}")
    try:
        naive = datetime.strptime(value.strip(), PAYTM_TIME_FORMAT)
    except ValueError as exc:
        raise PaytmFieldError(field, f"invalid date {value!r}") from exc
    return naive.replace(tzinfo=ZoneInfo(assumed_tz)).astimezone(UTC)


def format_naive_time(at: datetime, tz: str) -> str:
    return at.astimezone(ZoneInfo(tz)).strftime(PAYTM_TIME_FORMAT)


def canonical_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _optional_str(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return str(value)


@dataclass(frozen=True)
class NormalizedDispute:
    mid: str
    dispute_id: str
    transaction_id: str
    order_id: str
    merchant_name: str | None
    cust_id: str | None
    bank_reference_no: str | None
    ext_serial_no: str | None
    dispute_type_raw: str | None
    message: str | None
    amount_paise: int
    transaction_amount_paise: int | None
    debit_amount_paise: int | None
    dispute_utr: str | None
    deadline_utc: datetime
    deadline_raw: str
    transaction_at_utc: datetime | None
    transaction_at_raw: str | None
    timezone_assumption: str
    provider_status_raw: str | None
    provider_status: ProviderDisputeStatus
    comment: str | None
    payload_hash: str


REQUIRED_CALLBACK_FIELDS = ("mid", "disputeId", "transactionId", "orderId", "disputeAmount", "disputeDueDate")


def normalize_callback_body(body: dict[str, Any], assumed_tz: str) -> NormalizedDispute:
    """Normalize a Chargeback Peon-style callback body. Uses `transactionId` (not `txnId`)."""
    missing = [k for k in REQUIRED_CALLBACK_FIELDS if _optional_str(body, k) is None]
    if missing:
        raise PaytmFieldError(missing[0], "mandatory field missing")

    # Documented UTR spellings: `disputeutr` (S2S) and `disputeUtr` (Status API). Reject conflicts.
    utr_values = {v for v in (_optional_str(body, "disputeutr"), _optional_str(body, "disputeUtr")) if v}
    if len(utr_values) > 1:
        raise PaytmFieldError("disputeUtr", "conflicting disputeutr/disputeUtr values")

    txn_raw = _optional_str(body, "transactionDateTime")
    status_raw = _optional_str(body, "disputeStatus")
    return NormalizedDispute(
        mid=str(body["mid"]),
        dispute_id=str(body["disputeId"]),
        transaction_id=str(body["transactionId"]),
        order_id=str(body["orderId"]),
        merchant_name=_optional_str(body, "merchantName"),
        cust_id=_optional_str(body, "custId"),
        bank_reference_no=_optional_str(body, "bankReferenceNo"),
        ext_serial_no=_optional_str(body, "extSerialNo"),
        dispute_type_raw=_optional_str(body, "disputeType"),
        message=_optional_str(body, "message"),
        amount_paise=parse_amount_paise(body["disputeAmount"], "disputeAmount"),
        transaction_amount_paise=parse_optional_amount_paise(body.get("transactionAmount"), "transactionAmount"),
        debit_amount_paise=parse_optional_amount_paise(body.get("debitAmount"), "debitAmount"),
        dispute_utr=next(iter(utr_values), None),
        deadline_utc=parse_naive_time(body["disputeDueDate"], "disputeDueDate", assumed_tz),
        deadline_raw=str(body["disputeDueDate"]),
        transaction_at_utc=parse_naive_time(txn_raw, "transactionDateTime", assumed_tz) if txn_raw else None,
        transaction_at_raw=txn_raw,
        timezone_assumption=assumed_tz,
        provider_status_raw=status_raw,
        provider_status=normalize_dispute_status(status_raw),
        comment=_optional_str(body, "comment"),
        payload_hash=canonical_hash(body),
    )
