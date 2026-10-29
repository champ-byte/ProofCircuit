"""M7 evaluation corpus and harness (PRD 15.2). Network-free.

The harness self-check drives all 40 corpus cases through the real API in-process, with a scripted
rule-based policy standing in for the model. It proves the harness and that every expected behaviour
is reachable through the backend; it is NOT an AI result and is never exported as one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.clock import FixedClock
from app.evaluation import corpus
from app.evaluation.harness import Harness, run_suite
from app.main import create_app
from app.providers.fake import FakeReasoner, action
from app.providers.readiness import record_smoke_result
from tests.conftest import login, make_settings


def _section(user: str, start: str, end: str) -> Any:
    return json.loads(user.split(start, 1)[1].split(end, 1)[0])


def scripted_policy(user: str) -> dict[str, Any]:
    """A deterministic baseline: the obvious next action from the trusted context. Not AI."""
    ctx = _section(user, "CASE_CONTEXT_JSON:\n", "\n\nRUN_HISTORY_JSON:")
    history = _section(user, "RUN_HISTORY_JSON:\n", "\n\n<<<UNTRUSTED_DOCUMENT_DATA>>>")
    rules = {f["rule_id"] for f in ctx["open_findings"]}
    checklist = {c["requirement_id"]: c["status"] for c in ctx["checklist"]}
    if history and history[-1]["status"] == "denied":
        return {
            "action": "request_human_review",
            "arguments": {"reason": "denied", "question": "A step was denied."},
            "reason": "A step was denied.",
            "source_ids": [],
        }
    if rules & {"CONFLICTING_DELIVERY_DATES", "DELIVERY_BEFORE_ORDER"}:
        return {
            "action": "request_human_review",
            "arguments": {"reason": "conflicting_dates", "question": "Delivery dates conflict."},
            "reason": "Delivery dates conflict.",
            "source_ids": [],
        }
    if ctx["evidence_ready"]:
        if not ctx["latest_pack_current"]:
            return action("build_evidence_pack", "Evidence is ready.")
        return action("submit_defense", "The current pack is built.")
    if checklist.get("delivery_record") in ("missing", "conflicting"):
        return action("request_evidence", "Delivery proof is needed.", requirement_id="delivery_record")
    return action("wait_for_event", "Waiting.")


@pytest.fixture
def harness(tmp_path: Path, clock: FixedClock) -> Iterator[Harness]:
    settings = make_settings(tmp_path, gemini_api_key="AIza-test-secret-key")
    app = create_app(settings)
    app.state.reasoner_overrides = {"gemini": FakeReasoner([scripted_policy] * 2000, model="scripted-baseline")}
    with TestClient(app) as c:
        record_smoke_result("gemini", True, "scripted baseline (test)", model_requested=settings.gemini_model)
        yield Harness(
            c,
            quiet_seconds=0,
            poll_seconds=0,
            wait_until=lambda at: clock.advance(max(timedelta(0), at - clock.now())),
            now=clock.now,
        )


def test_corpus_is_deterministic_split_and_label_free() -> None:
    specs, truth = corpus.generate()
    assert (specs, truth) == corpus.generate()
    committed = json.loads(corpus.CORPUS_PATH.read_text(encoding="utf-8"))["cases"]
    assert committed == json.loads(json.dumps(specs, ensure_ascii=False))  # the committed file is current
    assert json.loads(corpus.GROUND_TRUTH_PATH.read_text(encoding="utf-8"))["labels"] == truth
    assert len(specs) == 40 and len(truth) == 40
    for cat in corpus.CATEGORIES:
        mine = [s for s in specs if s["category"] == cat]
        assert len(mine) == 8 and sum(s["split"] == "held_out" for s in mine) == 2
        first = [s for s in mine if s["first_pass"]]
        assert [(s["variant"], s["split"]) for s in first] == [(0, "development"), (6, "held_out")]
    assert len(corpus.load("first_pass")) == 10
    flat = json.dumps(committed)
    for label_key in ("expected_behavior", "acceptable_outcomes", "expected_rules", "submission_expected"):
        assert label_key not in flat  # ground truth never ships with the specs the app could see
    assert len({s["dispute"]["orderId"] for s in specs}) == 40


def test_harness_self_check_all_40_cases_with_a_scripted_policy(harness: Harness) -> None:
    report = run_suite(
        harness,
        corpus.load("all"),
        "t1",
        planned=40,
        split="all",
        mode={"mode": "scripted_baseline_not_ai"},
        categories=corpus.CATEGORIES,
    )
    wrong = [
        (c["corpus_case"], c["outcome"], c["unsafe"], c["missing_rules"]) for c in report["cases"] if not c["correct"]
    ]
    assert report["executed"] == 40 and not report["not_run_cases"]
    assert wrong == []
    m = report["metrics"]
    assert m["duplicate_writes"] == 0 and m["unsafe_actions"] == 0
    assert m["outcomes"] == {"denied": 8, "escalated": 10, "repaired": 6, "verified": 16}
    assert m["contradictions"] == {"expected_cases": 16, "detected_in_expected_cases": 16, "false_positive_cases": 0}
    assert all(c["agent_runs"] == len([s for s in c["run_statuses"] if s != "running"]) for c in report["cases"])
    assert m["eligible_on_time_submissions"] == {"count": 24, "eligible": 24}
    repaired = next(c for c in report["cases"] if c["corpus_case"] == "EVAL-033")
    assert repaired["verified_submissions"] == 2 and repaired["receipts"] == 2


def test_a_reasoner_outage_marks_cases_not_run_and_stops(tmp_path: Path, clock: FixedClock) -> None:
    settings = make_settings(tmp_path, gemini_api_key="AIza-test-secret-key")
    app = create_app(settings)
    app.state.reasoner_overrides = {"gemini": FakeReasoner([])}  # every call fails
    with TestClient(app) as c:
        record_smoke_result("gemini", True, "fake", model_requested=settings.gemini_model)
        h = Harness(c, quiet_seconds=0, poll_seconds=0, now=clock.now)
        report = run_suite(
            h, corpus.load("first_pass"), "t2", planned=40, split="first_pass", mode={}, categories=corpus.CATEGORIES
        )
    assert report["executed"] == 0 and report["status"] == "not_run"
    assert len(report["not_run_cases"]) == 10
    assert "reasoner unavailable" in report["not_run_cases"][0]["reason"]
    assert report["label"] == "40 planned · 0 executed · 40 not run"


def test_results_api_reads_only_exported_files(tmp_path: Path, clock: FixedClock, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.api import evaluation

    monkeypatch.setattr(evaluation, "RESULTS_DIR", tmp_path / "results")
    (tmp_path / "results").mkdir()
    with TestClient(create_app(make_settings(tmp_path))) as c:
        empty = c.get("/api/evaluation/results").json()
        assert empty["executed"] == 0 and empty["metrics"] is None and empty["mode"] is None
        (tmp_path / "results" / "results-01.json").write_text(
            json.dumps({"status": "executed", "executed": 10, "label": "40 planned · 10 executed · 30 not run"}),
            encoding="utf-8",
        )
        got = c.get("/api/evaluation/results").json()
        assert got["executed"] == 10 and got["planned"] == 40 and got["split"]["held_out"] == 10


def test_seed_endpoint_is_operator_only_and_scoped(tmp_path: Path, clock: FixedClock) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as c:
        body = {"corpus_case": "EVAL-001", "run_tag": "x1"}
        owner = login(c, "owner", mid=corpus.EVAL_MID)
        assert c.post("/api/evaluation/cases", headers=owner, json=body).status_code == 403
        op = login(c, "operator", mid=corpus.EVAL_MID)
        r = c.post("/api/evaluation/cases", headers=op, json=body)
        assert r.status_code == 201, r.text
        assert c.post("/api/evaluation/cases", headers=op, json=body).status_code == 409  # same run tag
        assert c.post("/api/evaluation/cases", headers=op, json={**body, "corpus_case": "EVAL-999"}).status_code == 404
        demo_owner = login(c, "owner")
        assert c.get(f"/api/cases/{r.json()['case_id']}", headers=demo_owner).status_code == 404  # other merchant
        deadline = datetime.fromisoformat(r.json()["deadline_utc"])
        assert deadline.minute != 0 or deadline.second != 0  # exact, non-midnight deadline preserved


def test_disjoint_runs_merge_into_one_report(harness: Harness) -> None:
    from app.evaluation.harness import merge_reports

    cases = corpus.load("first_pass")
    a = run_suite(harness, cases[:4], "m1", planned=40, split="a", mode={"label": "x"}, categories=corpus.CATEGORIES)
    b = run_suite(harness, cases[4:], "m2", planned=40, split="b", mode={"label": "x"}, categories=corpus.CATEGORIES)
    merged = merge_reports([a, b], planned=40, categories=corpus.CATEGORIES)
    assert merged["executed"] == 10 and merged["label"] == "40 planned · 10 executed · 30 not run"
    assert merged["metrics"]["correct"] == a["metrics"]["correct"] + b["metrics"]["correct"]
    assert merged["metrics"]["model_calls"] == a["metrics"]["model_calls"] + b["metrics"]["model_calls"]
    with pytest.raises(ValueError):
        merge_reports([a, a], planned=40, categories=corpus.CATEGORIES)
    pending = {"corpus_case": "EVAL-040", "category": "upload_pod_rejection", "reason": "not run"}
    a2, b2 = (
        {**a, "not_run_cases": [pending]},
        {**b, "not_run_cases": [pending, {**pending, "corpus_case": "EVAL-001"}]},
    )
    again = merge_reports([a2, b2], planned=40, categories=corpus.CATEGORIES)
    assert [n["corpus_case"] for n in again["not_run_cases"]] == ["EVAL-040"]  # deduplicated; ran cases dropped
