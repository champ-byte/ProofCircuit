"""C06 Retry and restart: one provider effect per pack; a lost acknowledgement plus a matching
independent receipt verifies without another write; 4006 or an older/different pack's receipt
never verifies the current pack; timeout reads precede retries; correction only from
POD_REJECT; startup/resume without duplicate sends; duplicate and out-of-order webhooks."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Case, PendingWork
from app.db.session import session_scope
from app.main import create_app
from app.services.fixtures import text_pdf
from app.simulator.signing import sign_body
from tests.helpers import Hero

PDF = text_pdf(["Third-party upload"])


@pytest.fixture
def hero(client: TestClient, settings) -> Hero:  # type: ignore[no-untyped-def]
    return Hero(client, settings)


@pytest.fixture
def no_webhooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model lost webhook deliveries so only explicit reconciliation can heal state."""

    async def drop(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr("app.simulator.api.send_callback", drop)


def steps(sub: dict) -> list[str]:  # type: ignore[type-arg]
    return [r["step"] + (":" + r["kind"] if "kind" in r else "") for r in sub["reconciliation"]]


@pytest.mark.parametrize("fault", ["drop_response_after", "system_error_after"])
def test_effect_applied_but_response_lost_verifies_without_second_write(hero: Hero, fault: str) -> None:
    hero.make_ready()
    hero.fault("action", fault)
    out = hero.act("submit_defense")
    assert out["result"]["status"] == "verified"
    [sub] = hero.submissions()
    assert sub["attempts"] == 1  # never resent
    assert steps(sub)[:2] == ["action_response:unknown", "reconcile"]  # read status/receipts before anything else
    assert len(hero.receipts()) == 1
    assert hero.case()["workflow_state"] == "MONITORING"


@pytest.mark.parametrize("fault", ["system_error_before", "upload_failed"])
def test_no_effect_then_single_reconciled_resend(hero: Hero, fault: str) -> None:
    hero.make_ready()
    hero.fault("action", fault)
    assert hero.act("submit_defense")["result"]["status"] == "verified"
    [sub] = hero.submissions()
    kind = "unknown" if fault == "system_error_before" else "retryable"
    assert steps(sub) == [f"action_response:{kind}", "reconcile", "resend", "action_response:ack", "reconcile"]
    assert sub["attempts"] == 2
    [receipt] = hero.receipts()
    assert receipt["intentDigest"] == sub["intent_digest"]


def test_status_5001_is_retried_with_bounded_reads(hero: Hero) -> None:
    hero.make_ready()
    hero.fault("action", "drop_response_after")
    hero.fault("status", "system_error", count=2)  # 3 reads allowed: 5001, 5001, success
    assert hero.act("submit_defense")["result"]["status"] == "verified"
    assert len(hero.receipts()) == 1


def test_status_unavailable_stays_uncertain_then_resume_verifies(hero: Hero, no_webhooks: None) -> None:
    hero.make_ready()
    hero.fault("action", "drop_response_after")
    hero.fault("status", "system_error", count=4)
    out = hero.act("submit_defense")
    assert out["status"] == "error" and out["result"]["status"] == "uncertain"
    case = hero.case()
    assert case["workflow_state"] == "SUBMISSION_UNCERTAIN" and "PROVIDER_UNAVAILABLE" in case["flags"]
    assert hero.submissions()[0]["state"] == "uncertain"
    resumed = hero.c.post("/api/demo/resume-pending", headers=hero.operator)
    assert resumed.status_code == 200 and resumed.json()["reconcile_submissions"] == 1
    [sub] = hero.submissions()
    assert sub["state"] == "verified" and sub["attempts"] == 1
    assert len(hero.receipts()) == 1
    assert "PROVIDER_UNAVAILABLE" not in hero.case()["flags"]


def test_4006_never_verifies_the_current_pack(hero: Hero, no_webhooks: None) -> None:
    hero.make_ready()
    # Someone else's upload reaches the provider; our case never hears about it (lost webhook).
    assert (
        hero.action_call(
            {"action": "DEFEND", "orderStatus": "ORDER_DELIVERED"}, [("other.pdf", PDF, "application/pdf")]
        ).json()["body"]["resultInfo"]["resultCodeId"]
        == "1001"
    )
    out = hero.act("submit_defense")
    assert out["result"]["status"] == "uncertain"
    [sub] = hero.submissions()
    assert sub["state"] == "uncertain" and sub["provider_reference"] is None
    assert steps(sub)[0] == "action_response:duplicate"
    assert len(hero.receipts()) == 1  # only the third-party receipt; no second write
    inbox = hero.c.get(f"/api/cases/{hero.case_id}/messages", headers=hero.owner).json()
    assert any(t["kind"] == "review" and t["status"] == "open" for t in inbox["tasks"])


def test_older_pack_receipt_cannot_verify_corrected_pack(hero: Hero) -> None:
    hero.make_ready()
    assert hero.act("submit_defense")["result"]["status"] == "verified"
    assert hero.inject(type="pod_reject", comment="Receipt signature unclear").status_code == 200
    assert hero.case()["provider_status"] == "POD_REJECT"
    receipt = (
        "DELIVERY RECEIPT\nReceipt No: DLV-DEMO-0418-B\nOrder ID: ORD-DEMO-18500\nDelivered On: 31-Dec-2029\n"
        "Received By (signature): P. Deshmukh (clear copy)\n"
    )
    hero.upload("receipt_clear.txt", receipt, "text/plain")
    assert hero.act("build_evidence_pack")["result"]["version"] == 2
    hero.fault("action", "system_error_before")
    assert hero.act("submit_defense")["result"]["status"] == "verified"
    subs = hero.submissions()
    assert [s["pack_version"] for s in subs] == [1, 2]
    v2 = subs[1]
    first_reconcile = next(r for r in v2["reconciliation"] if r["step"] == "reconcile")
    assert first_reconcile["matching_receipt"] is None and first_reconcile["receipts"] == 1  # v1 receipt ignored
    receipts = hero.receipts()
    assert len(receipts) == 2 and receipts[1]["intentDigest"] == v2["intent_digest"] != receipts[0]["intentDigest"]


def test_repeat_submit_of_verified_pack_is_idempotent(hero: Hero) -> None:
    hero.make_ready()
    hero.act("submit_defense")
    again = hero.act("submit_defense")
    assert again["result"]["status"] == "already_verified"
    assert len(hero.receipts()) == 1 and len(hero.submissions()) == 1


def test_crash_after_send_recovers_on_restart_without_duplicate(
    hero: Hero,
    settings,
    monkeypatch: pytest.MonkeyPatch,
    no_webhooks: None,  # type: ignore[no-untyped-def]
) -> None:
    hero.make_ready()

    async def crash(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("process died after the provider accepted")

    monkeypatch.setattr("app.services.submission._handle_action_result", crash)
    hero.c.post(f"/api/cases/{hero.case_id}/actions", headers=hero.owner, json={"tool": "submit_defense"})
    assert hero.submissions()[0]["state"] == "sent" and len(hero.receipts()) == 1
    monkeypatch.undo()
    with TestClient(create_app(settings)) as restarted:  # startup recovery scan + reconcile
        h2 = Hero(restarted, settings)
        [sub] = h2.submissions()
        assert sub["state"] == "verified" and sub["attempts"] == 1
        assert len(h2.receipts()) == 1


def test_crash_before_provider_received_resends_once_on_restart(
    hero: Hero,
    settings,
    monkeypatch: pytest.MonkeyPatch,
    no_webhooks: None,  # type: ignore[no-untyped-def]
) -> None:
    hero.make_ready()

    async def died(self, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("process died before the request left")

    monkeypatch.setattr("app.providers.paytm.PaytmSimulatorAdapter.act", died)
    hero.c.post(f"/api/cases/{hero.case_id}/actions", headers=hero.owner, json={"tool": "submit_defense"})
    assert hero.submissions()[0]["state"] == "sent" and hero.receipts() == []
    monkeypatch.undo()
    with TestClient(create_app(settings)) as restarted:
        h2 = Hero(restarted, settings)
        [sub] = h2.submissions()
        assert sub["state"] == "verified" and sub["attempts"] == 2
        assert len(h2.receipts()) == 1


def test_interrupted_pending_work_is_requeued_once(hero: Hero, settings) -> None:  # type: ignore[no-untyped-def]
    with session_scope() as s:
        case = s.get(Case, hero.case_id)
        s.add(PendingWork(case_id=case.id, kind="evaluate", case_version=case.version, status="running", attempts=1))  # type: ignore[union-attr]
    with TestClient(create_app(settings)) as restarted:
        h2 = Hero(restarted, settings)
        with session_scope() as s:
            rows = s.scalars(select(PendingWork).where(PendingWork.case_id == h2.case_id)).all()
            assert [r.status for r in rows] == ["completed"] and rows[0].attempts == 2
        assert h2.case()["workflow_state"] == "COLLECTING"


def test_duplicate_webhooks_are_ignored(hero: Hero) -> None:
    hero.make_ready()
    hero.act("submit_defense")
    with session_scope() as s:
        before = len(s.scalars(select(PendingWork).where(PendingWork.kind == "reconcile_status")).all())
    for _ in range(2):
        assert hero.inject(type="resend_callback").status_code == 200
    with session_scope() as s:
        after = len(s.scalars(select(PendingWork).where(PendingWork.kind == "reconcile_status")).all())
    assert after == before
    events = hero.c.get(f"/api/cases/{hero.case_id}/events", headers=hero.owner).json()["events"]
    assert sum(e["event_type"] == "provider.callback_duplicate" for e in events) == 2


def test_out_of_order_webhook_cannot_regress_state(hero: Hero) -> None:
    hero.make_ready()
    hero.act("submit_defense")
    stale = hero.status_call()["body"]
    stale = {
        k: v for k, v in stale.items() if k not in ("resultInfo", "disputeCreateDateTime", "disputeUpdateDateTime")
    }
    stale["disputeStatus"] = "NEW"
    resp = hero.c.post(
        "/api/dispute-events",
        json={"head": {"signature": sign_body(hero.secret, stale)}, "body": stale},
        headers={"X-Demo-Event-Id": "DSP-DEMO-001:0", "X-Demo-Sequence": "0"},
    )
    assert resp.json()["duplicate"] is False
    case = hero.case()
    assert case["provider_status"] == "POD_UPLOAD" and case["workflow_state"] == "MONITORING"
