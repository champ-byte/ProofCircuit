"""M0 exit criterion: fresh startup, seeded case visible, scoped access, honest provider readiness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.db.base import Base
from app.main import create_app
from app.providers.readiness import record_smoke_result
from tests.conftest import SEED_NOW, login, make_settings


def test_fresh_startup_migrates_all_tables(client: TestClient, settings) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(settings.resolved_database_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert set(Base.metadata.tables) <= tables
    assert "alembic_version" in tables


def test_health_ok_without_any_keys(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["synthetic_data"] is True and body["paytm_mode"] == "simulator"
    assert body["reasoning_mode"] == {"mode": "manual", "label": "Manual"}


def test_providers_unconfigured_without_key(client: TestClient) -> None:
    body = client.get("/api/providers").json()
    primary = body["reasoners"][0]
    assert primary["name"] == "gemini" and primary["role"] == "primary"
    assert primary["status"] == "unconfigured" and "GEMINI_API_KEY" in primary["detail"]
    fallback = body["reasoners"][1]
    assert fallback["name"] == "openrouter" and fallback["status"] == "disabled"


def test_configured_key_is_untested_until_smoke_test_and_never_exposed(tmp_path: Path, clock) -> None:  # type: ignore[no-untyped-def]
    secret = "AIza-test-secret-value-123"
    s = make_settings(tmp_path, gemini_api_key=secret)
    with TestClient(create_app(s)) as c:
        resp = c.get("/api/providers")
        assert secret not in resp.text
        assert resp.json()["reasoners"][0]["status"] == "configured_untested"
        assert resp.json()["reasoning_mode"]["mode"] == "manual"  # untested is not live
        record_smoke_result("gemini", True, "smoke ok")
        body = c.get("/api/providers").json()
        assert body["reasoners"][0]["status"] == "ready"
        assert body["reasoning_mode"] == {"mode": "live", "label": f"Gemini — {s.gemini_model}"}


def test_seeded_hero_case_visible(client: TestClient) -> None:
    headers = login(client, "owner")
    cases = client.get("/api/cases", headers=headers).json()
    assert len(cases) == 1
    case = cases[0]
    assert case["external_dispute_id"] == "DSP-DEMO-001"
    assert case["order_id"] == "ORD-DEMO-18500"
    assert case["amount_paise"] == 1850000 and case["amount_display"] == "₹18,500.00"
    assert case["reason"] == "goods_not_received"
    assert case["workflow_state"] == "NEW" and case["provider_status"] == "NEW"
    assert case["debit_amount_paise"] is None and case["dispute_utr"] is None
    assert case["synthetic"] is True
    # Deadline is 48h after the seed clock (whole seconds), never a hard-coded date.
    assert datetime.fromisoformat(case["deadline_utc"]).replace(tzinfo=UTC) == SEED_NOW + timedelta(hours=48)
    assert case["seconds_to_deadline"] == 48 * 3600 and case["deadline_expired"] is False

    detail = client.get(f"/api/cases/{case['id']}", headers=headers).json()
    assert [e["event_type"] for e in detail["timeline"]] == ["case.opened", "demo.seeded"]


def test_tenant_isolation(client: TestClient) -> None:
    owner = login(client, "owner")
    case_id = client.get("/api/cases", headers=owner).json()[0]["id"]
    other = login(client, "owner", mid="MID-DEMO-002")
    assert client.get("/api/cases", headers=other).json() == []
    assert client.get(f"/api/cases/{case_id}", headers=other).status_code == 404


def test_auth_required_and_tampered_token_rejected(client: TestClient) -> None:
    assert client.get("/api/cases").status_code == 401
    token = login(client, "owner")["Authorization"]
    payload, sig = token.split(".", 1)
    forged = payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB") + "." + sig
    assert client.get("/api/cases", headers={"Authorization": forged}).status_code == 401


def test_seed_is_idempotent_and_operator_only(client: TestClient) -> None:
    assert client.post("/api/demo/seed", headers=login(client, "owner")).status_code == 403
    op = login(client, "operator")
    first = client.post("/api/demo/seed", headers=op).json()
    second = client.post("/api/demo/seed", headers=op).json()
    assert first["case_id"] == second["case_id"]
    assert len(client.get("/api/cases", headers=login(client, "owner")).json()) == 1


def test_reset_requires_confirmation_and_reseeds(client: TestClient) -> None:
    op = login(client, "operator")
    old_id = client.get("/api/cases", headers=login(client, "owner")).json()[0]["id"]
    assert client.post("/api/demo/reset", headers=op, json={}).status_code == 422
    resp = client.post("/api/demo/reset", headers=op, json={"confirm": True})
    assert resp.status_code == 200 and resp.json()["case_id"] != old_id
    cases = client.get("/api/cases", headers=login(client, "owner")).json()
    assert [c["id"] for c in cases] == [resp.json()["case_id"]]
    # Sessions issued before the reset no longer resolve to a user.
    assert client.get("/api/cases", headers=op).status_code == 401


def test_restart_keeps_data_and_does_not_reseed(settings, clock) -> None:  # type: ignore[no-untyped-def]
    with TestClient(create_app(settings)) as c:
        first = c.get("/api/cases", headers=login(c, "owner")).json()
    with TestClient(create_app(settings)) as c:
        second = c.get("/api/cases", headers=login(c, "owner")).json()
    assert [x["id"] for x in first] == [x["id"] for x in second]
