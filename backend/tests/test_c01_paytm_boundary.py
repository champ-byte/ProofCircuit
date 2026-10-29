"""C01 Paytm boundary: S2S normalization, Status JSON, Action multipart, every documented code
reachable, invalid-signature denial, seconds and millisecond requestTimestamp.
(Money/time/field-mapping unit cases live in test_m0_paytm_boundary.py.)"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.domain.clock import FixedClock
from app.providers.paytm import PaytmSimulatorAdapter
from app.services.fixtures import text_pdf
from app.simulator.signing import sign_body
from tests.conftest import SEED_NOW
from tests.helpers import DISPUTE, MID, Hero, code

PDF = text_pdf(["Synthetic proof"])
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def hero(client: TestClient, settings) -> Hero:  # type: ignore[no-untyped-def]
    return Hero(client, settings)


def defend(hero: Hero, files: list[tuple[str, bytes, str]] | None = None, **params: str):  # type: ignore[no-untyped-def]
    return hero.action_call(
        {"action": "DEFEND", "orderStatus": "ORDER_DELIVERED", **params},
        files if files is not None else [("proof.pdf", PDF, "application/pdf")],
    )


# --- Status API -------------------------------------------------------------------------------


def test_status_success_is_1001_success_never_audit_success(hero: Hero) -> None:
    resp = hero.status_call()
    assert code(resp) == ("1001", "S", "SUCCESS")
    body = resp["body"]
    assert body["disputeStatus"] == "NEW" and body["transactionId"] == "TXN-DEMO-001" and "txnId" not in body
    assert body["debitAmount"] is None and body["disputeLostReason"] is None and body["comment"] is None
    assert body["disputeAmount"] == "18500.00"
    assert "version" in resp["head"] and resp["head"]["responseTimestamp"].isdigit()
    assert "AUDIT_SUCCESS" not in str(resp)


@pytest.mark.parametrize("token_type", ["CHECKSUM", "Checksum", "checksum"])
def test_status_token_type_case_insensitive(hero: Hero, token_type: str) -> None:
    assert code(hero.status_call(head={"tokenType": token_type}))[0] == "1001"


@pytest.mark.parametrize("ts", [str(int(SEED_NOW.timestamp())), str(int(SEED_NOW.timestamp() * 1000))])
def test_status_accepts_seconds_and_milliseconds(hero: Hero, ts: str) -> None:
    assert code(hero.status_call(head={"requestTimestamp": ts}))[0] == "1001"


def test_status_error_codes(hero: Hero) -> None:
    assert code(hero.status_call(head={"signature": "DEMO_SIGNATURE"}))[0] == "4001"
    assert code(hero.status_call(body={"mid": MID}))[0] == "4002"
    assert code(hero.status_call(head={"tokenType": "MD5"}))[0] == "4003"
    assert code(hero.status_call(head={"requestTimestamp": "12345"}))[0] == "4003"
    assert code(hero.status_call(body={"mid": MID, "disputeId": "DSP-NOPE"}))[0] == "4004"
    raw = hero.c.post("/api/simulator/v1/dispute/status", json={"head": {}, "body": "x"}).json()
    assert code(raw)[0] == "4003"
    hero.fault("status", "system_error")
    assert code(hero.status_call()) == ("5001", "U", "SYSTEM_ERROR")
    assert code(hero.status_call())[0] == "1001"  # fault consumed; 5001 is never a case state


def test_version_in_status_request_is_ignored(hero: Hero) -> None:
    assert code(hero.status_call(head={"version": "v9"}))[0] == "1001"


# --- Action API (multipart) -------------------------------------------------------------------


def test_defend_upload_success_and_lifecycle(hero: Hero) -> None:
    resp = defend(hero)
    assert code(resp.json()) == ("1001", "S", "UPLOADED_SUCCESS")
    assert len(resp.json()["head"]["responseTimestamp"]) == 13  # response heads use milliseconds
    assert hero.status_call()["body"]["disputeStatus"] == "POD_UPLOAD"
    receipts = hero.receipts()
    assert len(receipts) == 1 and receipts[0]["timestampUnit"] == "s" and receipts[0]["action"] == "DEFEND"
    # POD_UPLOAD -> second DEFEND is 4006 (documents exist; says nothing about which pack)
    assert code(defend(hero).json())[0] == "4006"


def test_ack_variant_a_is_an_acknowledgement(hero: Hero) -> None:
    hero.fault("action", "ack_variant_a")
    assert code(defend(hero).json()) == ("1001", "A", "UPLOADED_SUCCESS")


def test_millisecond_request_timestamp_recorded(hero: Hero) -> None:
    defend(hero, requestTimestamp=str(int(SEED_NOW.timestamp() * 1000)))
    assert hero.receipts()[0]["timestampUnit"] == "ms"


@pytest.mark.parametrize(
    ("params", "files", "expected"),
    [
        ({"signature": "DEMO_SIGNATURE"}, None, "4001"),
        ({"orderStatus": ""}, None, "4002"),  # orderStatus missing on DEFEND
        ({"action": "ESCALATE"}, None, "4003"),
        ({"orderStatus": "ORDER_LOST"}, None, "4003"),
        ({"filesPath": "/sftp/x"}, [], "4003"),
        ({"disputeId": "DSP-NOPE"}, None, "4004"),
        ({}, [], "4002"),  # files are required for DEFEND
        ({}, [(f"f{i}.pdf", PDF, "application/pdf") for i in range(6)], "4007"),
        ({}, [("big.pdf", b"%PDF-" + b"0" * 5_000_000, "application/pdf")], "4008"),
        ({}, [("notes.txt", b"plain text", "text/plain")], "4009"),
        ({}, [("disguised.pdf", b"GIF89a", "application/pdf")], "4009"),  # type is sniffed, not trusted
    ],
)
def test_action_validation_codes(hero: Hero, params: dict[str, str], files, expected: str) -> None:  # type: ignore[no-untyped-def]
    base = {"action": "DEFEND", "orderStatus": "ORDER_DELIVERED"}
    merged = {**base, **params}
    if merged.get("orderStatus") == "":
        merged.pop("orderStatus")
    resp = hero.action_call(merged, files if files is not None else [("proof.pdf", PDF, "application/pdf")])
    assert code(resp.json())[0] == expected
    assert hero.receipts() == []  # no effect


def test_mandatory_param_missing_dispute_id(hero: Hero) -> None:
    resp = hero.c.post(
        "/api/simulator/v1/dispute/action",
        data={"mid": MID, "action": "DEFEND", "requestTimestamp": "1893492000", "signature": "x"},
    )
    assert code(resp.json())[0] == "4002"


def test_png_and_five_files_are_accepted(hero: Hero) -> None:
    files = [("a.png", PNG, "image/png")] + [(f"f{i}.pdf", PDF, "application/pdf") for i in range(4)]
    assert code(defend(hero, files).json())[0] == "1001"


def test_deadline_codes_4005_and_4011(hero: Hero, clock: FixedClock) -> None:
    clock.advance(timedelta(hours=48))  # exactly the due instant: writes are denied at/after it
    assert code(defend(hero).json()) == ("4005", "F", "POD_UPLOAD_NOT_ALLOWED")
    assert code(hero.action_call({"action": "ACCEPT"}).json()) == ("4011", "F", "DISPUTE_ACCEPTANCE_NOT_ALLOWED")
    # The status read then reflects expiry with no response: LOST / Failed to respond.
    body = hero.status_call()["body"]
    assert body["disputeStatus"] == "LOST" and body["disputeLostReason"] == "Failed to respond"


def test_one_second_before_deadline_is_allowed(hero: Hero, clock: FixedClock) -> None:
    clock.advance(timedelta(hours=48) - timedelta(seconds=1))
    assert code(defend(hero).json())[0] == "1001"


def test_injected_4010_and_5001(hero: Hero) -> None:
    hero.fault("action", "upload_failed")
    assert code(defend(hero).json()) == ("4010", "F", "POD_UPLOAD_FAILED")
    hero.fault("action", "system_error_before")
    assert code(defend(hero).json()) == ("5001", "U", "SYSTEM_ERROR")
    assert hero.receipts() == [] and hero.status_call()["body"]["disputeStatus"] == "NEW"


def test_accept_returns_1003_and_lost(hero: Hero) -> None:
    assert code(hero.action_call({"action": "ACCEPT"}).json()) == ("1003", "S", "DISPUTE_ACCEPTED")
    assert hero.status_call()["body"]["disputeStatus"] == "LOST"


def test_correction_only_from_pod_reject(hero: Hero) -> None:
    defend(hero)
    assert code(defend(hero).json())[0] == "4006"
    assert hero.inject(type="pod_reject", comment="Signature not visible").status_code == 200
    body = hero.status_call()["body"]
    assert body["disputeStatus"] == "POD_REJECT" and body["comment"] == "Signature not visible"
    assert code(defend(hero, [("v2.pdf", text_pdf(["Signed receipt"]), "application/pdf")]).json())[0] == "1001"
    assert hero.status_call()["body"]["disputeStatus"] == "POD_UPLOAD"


def test_adapter_classifies_both_ack_variants(hero: Hero) -> None:
    adapter = PaytmSimulatorAdapter(hero.c.app, hero.settings)
    hero.fault("action", "ack_variant_a")
    result = asyncio.run(
        adapter.act(
            action="DEFEND", mid=MID, dispute_id=DISPUTE, order_status="ORDER_DELIVERED", files=[], timestamp_ms=True
        )
    )
    assert result.kind == "definitive" and result.code == "4002"  # no files: fault not consumed
    from app.providers.paytm import UploadPart

    result = asyncio.run(
        adapter.act(
            action="DEFEND",
            mid=MID,
            dispute_id=DISPUTE,
            order_status="ORDER_DELIVERED",
            files=[UploadPart("p.pdf", PDF, "application/pdf")],
            timestamp_ms=True,
        )
    )
    assert (result.kind, result.code, result.result_status) == ("ack", "1001", "A")
    assert hero.receipts()[0]["timestampUnit"] == "ms"


# --- S2S intake -------------------------------------------------------------------------------


def callback(hero: Hero, body: dict, event_id: str | None = None, signature: str | None = None):  # type: ignore[no-untyped-def]
    headers = {"X-Demo-Event-Id": event_id} if event_id else {}
    sig = signature or sign_body(hero.secret, body)
    return hero.c.post(
        "/api/dispute-events", json={"head": {"version": "v1", "signature": sig}, "body": body}, headers=headers
    )


NEW_DISPUTE = {
    "transactionId": "TXN-DEMO-777",
    "orderId": "ORD-DEMO-777",
    "disputeAmount": "2.00",
    "disputeDueDate": "2030-01-05 12:39:00",
    "bankReferenceNo": "BANK-777",
    "disputeType": "Successful Order, Service/product delivered",
    "message": "Chargeback dispute has been filed",
    "extSerialNo": "EXT-777",
    "mid": MID,
    "merchantName": "Metro Furniture Demo",
    "custId": "CUST-777",
    "transactionDateTime": "2030-01-01 15:30:00",
    "transactionAmount": "1200.00",
    "disputeId": "DSP-DEMO-777",
    "disputeStatus": "NEW",
}


def test_signed_callback_creates_exactly_one_case(hero: Hero) -> None:
    first = callback(hero, NEW_DISPUTE, event_id="evt-1")
    assert first.status_code == 200 and first.json()["created"] is True
    again = callback(hero, NEW_DISPUTE, event_id="evt-1")
    assert again.json() == {**first.json(), "created": False, "duplicate": True}
    cases = [
        c for c in hero.c.get("/api/cases", headers=hero.owner).json() if c["external_dispute_id"] == "DSP-DEMO-777"
    ]
    assert len(cases) == 1
    c = cases[0]
    assert c["amount_paise"] == 200  # disputeAmount, not the 1200.00 transaction amount
    assert datetime.fromisoformat(c["deadline_utc"]).replace(tzinfo=UTC) == datetime(2030, 1, 5, 7, 9, tzinfo=UTC)
    assert c["deadline_raw"] == "2030-01-05 12:39:00"  # non-midnight deadline preserved exactly
    assert c["reason"] == "requires_review"  # disputeType never establishes goods-not-received
    assert c["workflow_state"] == "COLLECTING"  # event-triggered first run happened


def test_invalid_callback_signature_denied(hero: Hero) -> None:
    resp = callback(hero, NEW_DISPUTE, signature="DEMO_SIGNATURE")
    assert resp.status_code == 401
    assert all(c["external_dispute_id"] != "DSP-DEMO-777" for c in hero.c.get("/api/cases", headers=hero.owner).json())


def test_create_dispute_through_simulator_webhook(hero: Hero) -> None:
    resp = hero.inject(
        type="create_dispute",
        body={k: v for k, v in NEW_DISPUTE.items() if k != "disputeId"} | {"disputeId": "ignored"},
        dispute_id="DSP-DEMO-778",
    )
    assert resp.status_code == 200
    ids = [c["external_dispute_id"] for c in hero.c.get("/api/cases", headers=hero.owner).json()]
    assert "DSP-DEMO-778" in ids


def test_webhook_utr_alias_reaches_case_via_authoritative_read(hero: Hero) -> None:
    assert (
        hero.inject(
            type="outcome",
            outcome="LOST",
            debit_amount="18500.00",
            dispute_utr="UTR-DEMO-1",
            lost_reason="Proof not provided",
        ).status_code
        == 200
    )
    case = hero.case()
    assert case["provider_status"] == "LOST" and case["workflow_state"] == "CLOSED"
    assert case["dispute_utr"] == "UTR-DEMO-1" and case["debit_amount_paise"] == 1850000
