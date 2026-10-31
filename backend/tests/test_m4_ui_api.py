"""M4 backend additions for the UI: drawer simulator state, provider usage, reviewer questions in
the inbox, and the honest evaluation placeholder."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers import DISPUTE, Hero


@pytest.fixture
def hero(client: TestClient, settings) -> Hero:  # type: ignore[no-untyped-def]
    return Hero(client, settings)


def test_simulator_state_for_drawer(hero: Hero) -> None:
    url = f"/api/simulator/state?dispute_id={DISPUTE}"
    assert hero.c.get(url, headers=hero.owner).status_code == 403  # operator demo control only
    hero.fault("action", "drop_response_after")
    state = hero.c.get(url, headers=hero.operator).json()
    assert state["dispute_status"] == "NEW" and state["receipts"] == []
    assert state["queued_faults"] == [{"api": "action", "kind": "drop_response_after", "remaining": 1}]
    assert "not part of any Paytm API" in state["note"]


def test_provider_usage_reported(hero: Hero) -> None:
    usage = hero.c.get("/api/providers").json()["usage"]
    assert usage == {"calls_24h": 0, "cap": 150, "min_interval_s": 0.0}


def test_review_question_in_inbox(hero: Hero) -> None:
    hero.act("request_human_review", reason="needs_check", question="Is the invoice amount right?")
    tasks = hero.c.get(f"/api/cases/{hero.case_id}/messages", headers=hero.reviewer).json()["tasks"]
    [review] = [t for t in tasks if t["kind"] == "review"]
    assert review["question"] == "Is the invoice amount right?" and review["status"] == "open"


def test_evaluation_placeholder_is_honest(hero: Hero, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.api import evaluation

    monkeypatch.setattr(evaluation, "RESULTS_DIR", tmp_path / "no-results")  # no export yet
    res = hero.c.get("/api/evaluation/results").json()
    assert res["status"] == "not_run" and res["executed"] == 0 and res["not_run"] == 40
    assert res["label"] == "40 planned · 0 executed · 40 not run" and res["metrics"] is None
    assert sum(c["planned"] for c in res["categories"]) == 40


def test_reset_keeps_quota_accounting_and_smoke_checks(hero: Hero) -> None:
    from app.providers.readiness import record_smoke_result
    from app.services.reasoner_accounting import calls_last_24h, record_call

    record_call(
        provider="gemini", model_requested="m", model_returned="m", purpose="propose", status="ok", latency_ms=1
    )
    record_smoke_result("gemini", True, "ok", model_requested="m")
    assert hero.c.post("/api/demo/reset", headers=hero.operator, json={"confirm": True}).status_code == 200
    assert calls_last_24h("gemini") == 1
    from sqlalchemy import select

    from app.db.models import ProviderCheck
    from app.db.session import session_scope

    with session_scope() as s:
        assert len(s.scalars(select(ProviderCheck)).all()) == 1
