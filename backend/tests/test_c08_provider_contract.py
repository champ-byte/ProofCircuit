"""C08 Provider contract: unsupported/bad JSON cannot run a tool, bounded repairs and retries,
no paid auto-switch, replay never labelled live AI, fallback only when enabled and ready,
readiness says the optional Gemma fallback is unavailable. Network-free (mock transports)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent.schema import ACTION_JSON_SCHEMA, parse_action, to_openapi_subset
from app.db.models import AgentRun, AuditEvent, ProviderCheck, ReasonerCall, ToolCall
from app.db.session import session_scope
from app.domain.clock import FixedClock
from app.main import create_app
from app.providers.base import ReasonerError
from app.providers.fake import FakeReasoner, action
from app.providers.gemini import GeminiReasoner
from app.providers.openrouter import OpenRouterReasoner
from app.providers.readiness import provider_report, record_smoke_result
from tests.conftest import make_settings
from tests.helpers import Hero

SECRET = "AIza-super-secret-test-key"


@pytest.fixture
def make_hero(tmp_path: Path, clock: FixedClock):  # type: ignore[no-untyped-def]
    clients: list[TestClient] = []

    def factory(reasoners: dict[str, Any], smoke: tuple[str, ...] = ("gemini",), **overrides: Any) -> Hero:
        settings = make_settings(tmp_path, gemini_api_key=SECRET, openrouter_api_key="sk-or-test", **overrides)
        app = create_app(settings)
        app.state.reasoner_overrides = reasoners
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        for name in smoke:
            model = {"gemini": settings.gemini_model, "openrouter": settings.openrouter_model}[name]
            record_smoke_result(name, True, "fake smoke", model_requested=model, model_returned=f"{name}-returned")
        return Hero(client, settings)

    yield factory
    for c in clients:
        c.__exit__(None, None, None)


def agent_runs(h: Hero) -> list[dict[str, Any]]:
    return [r for r in h.c.get(f"/api/cases/{h.case_id}/runs", headers=h.owner).json() if r["mode"] != "manual"]


def tool_names() -> list[str]:
    with session_scope() as s:
        return [t.tool for t in s.scalars(select(ToolCall))]


# --- bad output never executes ---------------------------------------------------------------


def test_invalid_json_is_repaired_within_bounds(make_hero) -> None:  # type: ignore[no-untyped-def]
    fake = FakeReasoner(
        ["not json", '{"action": "request_evidence"}', action("request_evidence", requirement_id="delivery_record")]
    )
    h = make_hero({"gemini": fake})
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    run = agent_runs(h)[-1]
    assert run["status"] == "waiting" or run["tool_calls"][0]["status"] == "ok"
    assert [c["tool"] for c in run["tool_calls"]] == ["request_evidence"]
    assert "rejected" in fake.calls[1]["user"] and "rejected" in fake.calls[2]["user"]
    events = [e["event_type"] for e in h.c.get(f"/api/cases/{h.case_id}/events", headers=h.owner).json()["events"]]
    assert events.count("agent.invalid_output") == 2


@pytest.mark.parametrize(
    "bad",
    [
        "```nonsense```",
        json.dumps(action("accept_dispute", "Concede it.")),  # not a tool: schema enum rejects
        json.dumps(action("issue_refund")),
        json.dumps({**action("request_evidence"), "arguments": {"recipient_phone": "+91..."}}),  # unknown argument
        json.dumps({**action("wait_for_event"), "extra": 1}),
    ],
)
def test_unsupported_output_never_runs_a_tool(make_hero, bad: str) -> None:  # type: ignore[no-untyped-def]
    fake = FakeReasoner([bad, bad, bad])
    h = make_hero({"gemini": fake})
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    run = agent_runs(h)[-1]
    assert run["status"] == "failed" and run["tool_calls"] == []
    assert tool_names() == [] and len(fake.calls) == 3  # 1 + 2 repairs, then stop
    assert h.case()["workflow_state"] == "NEEDS_HUMAN_REVIEW"
    assert h.receipts() == []


def test_parse_action_drops_null_arguments_only() -> None:
    a = parse_action(
        json.dumps(
            {
                "action": "request_evidence",
                "arguments": {"requirement_id": "invoice", "locale": None, "assignee_id": None},
                "reason": "x",
                "source_ids": [],
            }
        )
    )
    assert a.arguments == {"requirement_id": "invoice"}


# --- Gemini adapter (mocked HTTP) -------------------------------------------------------------


def gemini_with(handler, **overrides: Any) -> GeminiReasoner:  # type: ignore[no-untyped-def]
    settings = make_settings(Path("/tmp"), gemini_api_key=SECRET, **overrides)
    return GeminiReasoner(settings, transport=httpx.MockTransport(handler))


def test_gemini_request_shape_and_thought_parts_dropped() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "PRIVATE CHAIN OF THOUGHT", "thought": True},
                                {"text": json.dumps(action("wait_for_event", waiting_for="staff_evidence"))},
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "gemini-3.5-flash-lite-07-2026",
                "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 40},
            },
        )

    g = gemini_with(handler)
    out = asyncio.run(g.complete(system="SYS", user="USER", schema=ACTION_JSON_SCHEMA))
    assert SECRET not in seen["url"] and seen["key"] == SECRET
    assert seen["url"].endswith(f"/models/{g.model}:generateContent")
    cfg = seen["body"]["generationConfig"]
    assert cfg["temperature"] == 0.0 and cfg["responseMimeType"] == "application/json"
    assert cfg["responseJsonSchema"] == ACTION_JSON_SCHEMA and "responseSchema" not in cfg
    assert cfg["thinkingConfig"] == {"thinkingLevel": "low"}
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert "PRIVATE CHAIN OF THOUGHT" not in out.text and parse_action(out.text).action == "wait_for_event"
    assert out.model_returned == "gemini-3.5-flash-lite-07-2026" and out.prompt_tokens == 900


def test_gemini_openapi_variant_and_no_thinking() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    g = gemini_with(handler)
    g.capabilities = {"schema_field": "responseSchema", "thinking_level": False}
    asyncio.run(g.complete(system="s", user="u", schema=ACTION_JSON_SCHEMA))
    cfg = seen["body"]["generationConfig"]
    assert cfg["responseSchema"] == to_openapi_subset(ACTION_JSON_SCHEMA) and "thinkingConfig" not in cfg
    assert cfg["responseSchema"]["properties"]["arguments"]["properties"]["locale"]["nullable"] is True


@pytest.mark.parametrize(
    ("status", "kind"), [(429, "rate_limited"), (500, "transient"), (400, "config"), (403, "config")]
)
def test_gemini_error_classes_never_leak_key(status: int, kind: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "error": {
                "message": f"echo {SECRET}",
                "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}],
            }
        }
        return httpx.Response(status, json=body)

    with pytest.raises(ReasonerError) as err:
        asyncio.run(gemini_with(handler).complete(system="s", user="u", schema=ACTION_JSON_SCHEMA))
    assert err.value.kind == kind and SECRET not in str(err.value)
    if status == 429:
        assert err.value.retry_after == 7.0


def test_gemini_blocked_or_empty_output_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

    with pytest.raises(ReasonerError) as err:
        asyncio.run(gemini_with(handler).complete(system="s", user="u", schema=ACTION_JSON_SCHEMA))
    assert err.value.kind == "blocked"


def test_smoke_test_negotiates_schema_variant_and_persists(make_hero) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        cfg = body["generationConfig"]
        if "responseJsonSchema" in cfg or "thinkingConfig" in cfg:
            return httpx.Response(400, json={"error": {"message": "Invalid JSON payload: unknown field"}})
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        action(
                                            "request_evidence",
                                            "Delivery proof missing.",
                                            requirement_id="delivery_record",
                                        )
                                    )
                                }
                            ]
                        }
                    }
                ],
                "modelVersion": "gemini-3.5-flash-lite-test",
            },
        )

    h = make_hero({}, smoke=())
    h.c.app.state.reasoner_overrides = {"gemini": GeminiReasoner(h.settings, transport=httpx.MockTransport(handler))}
    assert provider_report(h.settings)["reasoners"][0]["status"] == "configured_untested"
    res = h.c.post("/api/providers/smoke", headers=h.operator).json()
    assert res["ok"] and res["capabilities"] == {"schema_field": "responseSchema", "thinking_level": False}
    assert len(res["attempts"]) == 3
    report = provider_report(h.settings)
    assert report["reasoners"][0]["status"] == "ready"
    assert report["reasoning_mode"] == {"mode": "live", "label": "Gemini — gemini-3.5-flash-lite-test"}
    with session_scope() as s:
        check = s.scalars(select(ProviderCheck)).all()[-1]
        assert check.capabilities == {"schema_field": "responseSchema", "thinking_level": False}
        assert {c.purpose for c in s.scalars(select(ReasonerCall))} == {"smoke"}
    assert h.c.post("/api/providers/smoke", headers=h.owner).status_code == 403


def test_smoke_check_expires(make_hero, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    from datetime import timedelta

    h = make_hero({"gemini": FakeReasoner([])})
    assert provider_report(h.settings)["reasoning_mode"]["mode"] == "live"
    clock.advance(timedelta(hours=25))
    assert provider_report(h.settings)["reasoners"][0]["status"] == "configured_untested"
    assert provider_report(h.settings)["reasoning_mode"]["mode"] == "manual"


# --- routing, caps and fallback -------------------------------------------------------------


def test_rate_limit_retried_once_within_wait_bound(make_hero) -> None:  # type: ignore[no-untyped-def]
    fake = FakeReasoner(
        [
            ReasonerError("rate_limited", "429", http_status=429, retry_after=0.0),
            action("request_evidence", requirement_id="delivery_record"),
        ]
    )
    h = make_hero({"gemini": fake})
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    assert [c["tool"] for c in agent_runs(h)[-1]["tool_calls"]] == ["request_evidence"]
    with session_scope() as s:
        assert [c.status for c in s.scalars(select(ReasonerCall))] == ["rate_limited", "ok"]


def test_long_rate_limit_pauses_without_tool(make_hero) -> None:  # type: ignore[no-untyped-def]
    fake = FakeReasoner([ReasonerError("rate_limited", "429", http_status=429, retry_after=3600)])
    h = make_hero({"gemini": fake})
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    run = agent_runs(h)[-1]
    assert run["status"] == "paused_reasoner_unavailable" and run["tool_calls"] == []
    assert len(fake.calls) == 1


def test_daily_cap_stops_before_calling(make_hero) -> None:  # type: ignore[no-untyped-def]
    fake = FakeReasoner([action("request_evidence", requirement_id="delivery_record"), action("get_case_context")])
    h = make_hero({"gemini": fake}, reasoner_daily_call_cap=1)
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    h.upload("wrong.pdf", h.fixture("delivery_receipt_wrong_order"))
    run = agent_runs(h)[-1]
    assert run["status"] == "paused_reasoner_unavailable" and "daily call cap" in run["error"]
    assert len(fake.calls) == 1  # the capped run never reached the provider


def test_fallback_only_when_enabled_and_ready(make_hero) -> None:  # type: ignore[no-untyped-def]
    broken = FakeReasoner([ReasonerError("config", "400 schema unsupported", http_status=400)] * 4)
    backup = FakeReasoner(
        [action("request_evidence", requirement_id="delivery_record")], name="openrouter", model="openrouter/free"
    )
    h = make_hero({"gemini": broken, "openrouter": backup}, smoke=("gemini", "openrouter"), fallback_enabled=True)
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    run = agent_runs(h)[-1]
    assert run["provider"] == "openrouter" and run["model"] == "openrouter/free-returned"
    assert [c["tool"] for c in run["tool_calls"]] == ["request_evidence"]
    with session_scope() as s:
        fallback = s.scalars(select(AuditEvent).where(AuditEvent.event_type == "agent.reasoner_fallback")).all()
        assert len(fallback) == 1 and "gemini: config" in fallback[0].summary


def test_no_fallback_when_disabled(make_hero) -> None:  # type: ignore[no-untyped-def]
    broken = FakeReasoner([ReasonerError("config", "400", http_status=400)])
    backup = FakeReasoner([action("wait_for_event", waiting_for="staff_evidence")], name="openrouter")
    h = make_hero({"gemini": broken, "openrouter": backup}, smoke=("gemini", "openrouter"))
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    assert agent_runs(h)[-1]["status"] == "paused_reasoner_unavailable" and backup.calls == []
    # Manual operation still works while the reasoner is unavailable.
    assert h.act("request_evidence", requirement_id="delivery_record")["status"] == "ok"


def test_untested_reasoner_never_runs(make_hero) -> None:  # type: ignore[no-untyped-def]
    fake = FakeReasoner([action("request_evidence", requirement_id="delivery_record")])
    h = make_hero({"gemini": fake}, smoke=())
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    assert fake.calls == [] and agent_runs(h) == []
    events = [e["event_type"] for e in h.c.get(f"/api/cases/{h.case_id}/events", headers=h.owner).json()["events"]]
    assert "agent.not_run" in events


def test_readiness_gemma_fallback_unavailable(tmp_path: Path) -> None:
    from app.providers.readiness import _reasoner_readiness

    s = make_settings(tmp_path, fallback_provider="ollama", fallback_enabled=True, ollama_model="gemma3:4b")
    assert _reasoner_readiness("ollama", "fallback", s).status == "not_implemented"


# --- OpenRouter adapter (mocked HTTP; host blocked in this environment) ----------------------


def openrouter_with(handler, **overrides: Any) -> OpenRouterReasoner:  # type: ignore[no-untyped-def]
    return OpenRouterReasoner(
        make_settings(Path("/tmp"), openrouter_api_key="sk-or-test", **overrides),
        transport=httpx.MockTransport(handler),
    )


def test_openrouter_request_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "model": "meta/some-free-model",
                "choices": [{"message": {"content": json.dumps(action("get_case_context"))}}],
            },
        )

    out = asyncio.run(openrouter_with(handler).complete(system="s", user="u", schema=ACTION_JSON_SCHEMA))
    body = seen["body"]
    assert body["temperature"] == 0 and seen["auth"] == "Bearer sk-or-test"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == ACTION_JSON_SCHEMA
    assert body["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert out.model_returned == "meta/some-free-model"


@pytest.mark.parametrize(
    ("pricing", "allow_paid", "ok"),
    [
        ({"prompt": "0", "completion": "0"}, False, True),
        ({"prompt": "0.000001", "completion": "0"}, False, False),
        ({"prompt": "0.000001", "completion": "0"}, True, True),
    ],
)
def test_openrouter_preflight_blocks_paid_models(pricing: dict[str, str], allow_paid: bool, ok: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "vendor/model",
                        "pricing": pricing,
                        "supported_parameters": ["response_format", "temperature"],
                    }
                ]
            },
        )

    r = openrouter_with(handler, openrouter_model="vendor/model", allow_paid_models=allow_paid)
    if ok:
        assert asyncio.run(r.preflight())["model"] == "vendor/model"
    else:
        with pytest.raises(ReasonerError, match="not zero-priced"):
            asyncio.run(r.preflight())


def test_openrouter_402_is_config_not_paid_switch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": {"message": "Insufficient credits"}})

    with pytest.raises(ReasonerError) as err:
        asyncio.run(openrouter_with(handler).complete(system="s", user="u", schema=ACTION_JSON_SCHEMA))
    assert err.value.kind == "config"


# --- replay is never live --------------------------------------------------------------------


def test_fixture_replay_is_labelled_and_never_counted_live(make_hero) -> None:  # type: ignore[no-untyped-def]
    h = make_hero({}, smoke=())
    assert h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner, json={"mode": "fixture_replay"}).status_code == 403
    resp = h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.operator, json={"mode": "fixture_replay"})
    assert resp.json()["reasoning_label"] == "Fixture replay"
    [run] = agent_runs(h)
    assert run["mode"] == "fixture_replay" and run["provider"] == "replay" and run["model"] == "hero-replay-v1"
    assert [c["tool"] for c in run["tool_calls"]] == ["request_evidence"]
    assert h.c.get("/api/health").json()["reasoning_mode"]["mode"] == "manual"  # badge never claims live AI
    with session_scope() as s:
        assert {c.provider for c in s.scalars(select(ReasonerCall))} == {"replay"}
        assert s.scalars(select(AgentRun).where(AgentRun.mode == "live")).all() == []


def test_secret_never_stored(make_hero) -> None:  # type: ignore[no-untyped-def]
    fake = FakeReasoner([ReasonerError("config", "bad request", http_status=400)])
    h = make_hero({"gemini": fake})
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    dump = json.dumps(
        [
            h.c.get(p, headers=h.owner).json()
            for p in (f"/api/cases/{h.case_id}/runs", f"/api/cases/{h.case_id}/events", "/api/providers", "/api/health")
        ]
    )
    assert SECRET not in dump
    with session_scope() as s:
        rows = [*s.scalars(select(ReasonerCall)), *s.scalars(select(AuditEvent))]
        assert all(SECRET not in json.dumps({k: str(v) for k, v in vars(r).items()}) for r in rows)


def test_transient_503s_back_off_within_bounds(make_hero, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Seen live: Gemini 503 "model is currently experiencing high demand". Bounded retries with backoff."""
    from app.providers import router

    waits: list[float] = []
    real_sleep = router.asyncio.sleep

    async def record_sleep(seconds: float) -> None:
        waits.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(router.asyncio, "sleep", record_sleep)
    busy = ReasonerError("transient", "Gemini 503: high demand", http_status=503)
    fake = FakeReasoner([busy, busy, action("request_evidence", requirement_id="delivery_record")])
    h = make_hero({"gemini": fake})
    h.c.app.state.settings.reasoner_transient_backoff_seconds = 5.0  # type: ignore[attr-defined]
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    assert [c["tool"] for c in agent_runs(h)[-1]["tool_calls"]] == ["request_evidence"]
    assert [w for w in waits if w] == [5.0, 15.0]  # growing backoff, not an immediate retry
    with session_scope() as s:
        assert [c.status for c in s.scalars(select(ReasonerCall))] == ["transient", "transient", "ok"]


def test_persistent_503_stops_after_three_attempts(make_hero) -> None:  # type: ignore[no-untyped-def]
    busy = ReasonerError("transient", "Gemini 503: high demand", http_status=503)
    fake = FakeReasoner([busy, busy, busy, busy])
    h = make_hero({"gemini": fake})
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    run = agent_runs(h)[-1]
    assert run["status"] == "paused_reasoner_unavailable" and run["tool_calls"] == []
    assert len(fake.calls) == 3  # first attempt + REASONER_TRANSIENT_RETRIES (2); never unbounded


def test_a_stalled_model_call_hits_the_total_deadline(make_hero) -> None:  # type: ignore[no-untyped-def]
    """Seen live (EVAL-037): one request stalled for 38 minutes; the per-read HTTP timeout never fired."""

    async def stall(_user: str) -> dict[str, Any]:
        await asyncio.sleep(3600)
        return {}

    class Stalling(FakeReasoner):
        async def complete(self, *, system: str, user: str, schema: dict[str, Any]):  # type: ignore[no-untyped-def]
            self.calls.append({"user": user})
            if len(self.calls) == 1:
                await stall(user)
            return await super().complete(system=system, user=user, schema=schema)

    fake = Stalling([action("request_evidence", requirement_id="delivery_record")])
    h = make_hero({"gemini": fake})
    h.c.app.state.settings.model_timeout_seconds = 1  # type: ignore[attr-defined]
    h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner)
    assert [c["tool"] for c in agent_runs(h)[-1]["tool_calls"]] == ["request_evidence"]  # retried after the deadline
    with session_scope() as s:
        assert [c.status for c in s.scalars(select(ReasonerCall))] == ["timeout", "ok"]
