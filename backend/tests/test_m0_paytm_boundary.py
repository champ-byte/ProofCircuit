"""Bootstrap subset of the C01 Paytm boundary contract (money, time, field mapping)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.enums import ProviderDisputeStatus, normalize_dispute_status
from app.domain.money import format_inr
from app.domain.paytm import PaytmFieldError, normalize_callback_body, parse_amount_paise, parse_naive_time

PRD_SAMPLE = {
    "transactionId": "TXN-DEMO-001",
    "orderId": "ORD-DEMO-18500",
    "disputeAmount": "18500.00",
    "disputeDueDate": "2030-01-03 23:59:59",
    "bankReferenceNo": "BANK-DEMO-001",
    "disputeType": "Successful Order, Service/product delivered",
    "message": "Chargeback dispute has been filed",
    "extSerialNo": "EXT-DEMO-001",
    "mid": "MID-DEMO-001",
    "merchantName": "Metro Furniture Demo",
    "custId": "CUST-DEMO-001",
    "transactionDateTime": "2030-01-01 15:30:00",
    "transactionAmount": "18500.00",
    "disputeId": "DSP-DEMO-001",
    "disputeStatus": "NEW",
}


def test_prd_sample_normalizes() -> None:
    d = normalize_callback_body(PRD_SAMPLE, "Asia/Kolkata")
    assert d.amount_paise == 1850000
    assert d.deadline_utc == datetime(2030, 1, 3, 18, 29, 59, tzinfo=UTC)
    assert d.deadline_raw == "2030-01-03 23:59:59"
    assert d.transaction_id == "TXN-DEMO-001"
    assert d.provider_status is ProviderDisputeStatus.NEW
    assert d.debit_amount_paise is None and d.dispute_utr is None


@pytest.mark.parametrize(
    ("raw", "paise"), [("18500.00", 1850000), ("2.00", 200), ("0.5", 50), ("1200", 120000), ("0.01", 1)]
)
def test_amounts_to_paise(raw: str, paise: int) -> None:
    assert parse_amount_paise(raw, "disputeAmount") == paise


@pytest.mark.parametrize("raw", ["-1.00", "1.234", "abc", "NaN", "Infinity", "", "1e3", 18500.0, None])
def test_bad_amounts_rejected(raw: object) -> None:
    with pytest.raises(PaytmFieldError):
        parse_amount_paise(raw, "disputeAmount")


def test_dispute_amount_not_transaction_amount() -> None:
    d = normalize_callback_body({**PRD_SAMPLE, "disputeAmount": "2.00", "transactionAmount": "1200.00"}, "Asia/Kolkata")
    assert d.amount_paise == 200 and d.transaction_amount_paise == 120000


def test_non_midnight_deadline_preserved_exactly() -> None:
    assert parse_naive_time("2030-01-03 12:39:00", "f", "Asia/Kolkata") == datetime(2030, 1, 3, 7, 9, tzinfo=UTC)


@pytest.mark.parametrize("raw", ["2030-01-03", "2030-01-03T23:59:59", "03-01-2030 23:59:59", "2030-02-30 10:00:00"])
def test_malformed_dates_rejected(raw: str) -> None:
    with pytest.raises(PaytmFieldError):
        parse_naive_time(raw, "disputeDueDate", "Asia/Kolkata")


def test_txnid_is_not_guessed_as_transaction_id() -> None:
    body = {k: v for k, v in PRD_SAMPLE.items() if k != "transactionId"} | {"txnId": "TXN-DEMO-001"}
    with pytest.raises(PaytmFieldError, match="transactionId"):
        normalize_callback_body(body, "Asia/Kolkata")


def test_null_and_empty_optional_fields_are_not_reported() -> None:
    d = normalize_callback_body({**PRD_SAMPLE, "debitAmount": None, "disputeutr": "", "comment": None}, "Asia/Kolkata")
    assert d.debit_amount_paise is None and d.dispute_utr is None and d.comment is None


def test_utr_spellings_mapped_and_conflicts_rejected() -> None:
    assert normalize_callback_body({**PRD_SAMPLE, "disputeutr": "UTR1"}, "Asia/Kolkata").dispute_utr == "UTR1"
    assert normalize_callback_body({**PRD_SAMPLE, "disputeUtr": "UTR1"}, "Asia/Kolkata").dispute_utr == "UTR1"
    with pytest.raises(PaytmFieldError):
        normalize_callback_body({**PRD_SAMPLE, "disputeutr": "UTR1", "disputeUtr": "UTR2"}, "Asia/Kolkata")


def test_status_aliases_documented_only() -> None:
    assert normalize_dispute_status("POD UPLOADED") is ProviderDisputeStatus.POD_UPLOAD
    assert normalize_dispute_status("Accept") is ProviderDisputeStatus.UNKNOWN
    assert normalize_dispute_status("pod_upload") is ProviderDisputeStatus.UNKNOWN
    assert normalize_dispute_status(None) is ProviderDisputeStatus.UNKNOWN


def test_payload_hash_is_canonical() -> None:
    reordered = dict(reversed(list(PRD_SAMPLE.items())))
    assert (
        normalize_callback_body(PRD_SAMPLE, "Asia/Kolkata").payload_hash
        == normalize_callback_body(reordered, "Asia/Kolkata").payload_hash
    )


@pytest.mark.parametrize(("paise", "text"), [(1850000, "₹18,500.00"), (12345678, "₹1,23,456.78"), (5, "₹0.05")])
def test_format_inr(paise: int, text: str) -> None:
    assert format_inr(paise) == text
