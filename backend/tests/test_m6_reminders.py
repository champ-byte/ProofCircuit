"""M6 n8n staff reminders (PRD 12.1): backend-started trigger, authenticated idempotent callback,
backend-enforced cancellation. Network-free: the n8n webhook is an httpx.MockTransport."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import Message, OutboxEvent, PendingWork, StaffReminder
from app.db.session import session_scope
from app.domain.clock import FixedClock
from app.main import create_app
from app.services import reminders
from tests.conftest import make_settings
from tests.helpers import Hero

WEBHOOK = "http://n8n.test/webhook/proofcircuit-staff-reminder"
ON = {
    "reminders_enabled": True,
    "n8n_reminder_webhook_url": WEBHOOK,
    "n8n_webhook_token": "webhook-token",
    "n8n_service_token": "service-token",
}
SERVICE = {"Authorization": "Bearer service-token"}


class FakeN8n:
    """Records trigger POSTs; `responses` scripts each attempt (int status or an exception)."""

    def __init__(self, *responses: int | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        nxt = self.responses.pop(0) if self.responses else 200
        if isinstance(nxt, Exception):
            raise nxt
        return httpx.Response(nxt, json={"message": "Workflow was started"})

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture
def on_settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path, **ON)


@pytest.fixture
def hero(on_settings: Settings, clock: FixedClock) -> Iterator[Hero]:
    with TestClient(create_app(on_settings)) as c:
        yield Hero(c, on_settings)


def use_n8n(hero: Hero, fake: FakeN8n) -> FakeN8n:
    hero.c.app.state.n8n_transport = httpx.MockTransport(fake)  # type: ignore[attr-defined]
    return fake


def request_delivery_proof(hero: Hero) -> dict[str, Any]:
    call = hero.act("request_evidence", requirement_id="delivery_record")
    assert call["status"] == "ok", call
    return call["result"]


def task_view(hero: Hero) -> dict[str, Any]:
    tasks = hero.c.get(f"/api/cases/{hero.case_id}/messages", headers=hero.owner).json()["tasks"]
    return next(t for t in tasks if t["kind"] == "evidence")


def callback(hero: Hero, task_id: str, round_no: int = 1, number: int = 1, headers=None, case_id=None):  # type: ignore[no-untyped-def]
    return hero.c.post(
        f"/api/cases/{case_id or hero.case_id}/reminders",
        headers=SERVICE if headers is None else headers,
        json={"staff_task_id": task_id, "request_round": round_no, "reminder_number": number},
    )


def reminder_messages(hero: Hero) -> list[str]:
    msgs = hero.c.get(f"/api/cases/{hero.case_id}/messages", headers=hero.owner).json()["messages"]
    return [m["body"] for m in msgs if m["body"].startswith(("स्मरणपत्र", "Reminder", "रिमाइंडर"))]


def iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# --- Feature off --------------------------------------------------------------------------------


def test_feature_off_creates_no_trigger_and_callback_is_unavailable(tmp_path: Path, clock: FixedClock) -> None:
    settings = make_settings(tmp_path, reminders_enabled=True)  # enabled, but no URL/tokens
    with TestClient(create_app(settings)) as c:
        hero = Hero(c, settings)
        fake = use_n8n(hero, FakeN8n())
        result = request_delivery_proof(hero)
        assert result["created"] is True
        assert fake.requests == []
        assert task_view(hero)["reminder"] is None
        assert callback(hero, result["staff_task_id"]).status_code == 503
        n8n = next(i for i in c.get("/api/providers").json()["integrations"] if i["name"] == "n8n_reminders")
        assert n8n["status"] == "disabled" and "N8N_REMINDER_WEBHOOK_URL" in n8n["detail"]
        msgs = c.get(f"/api/cases/{hero.case_id}/messages", headers=hero.owner).json()["messages"]
        assert [m["delivery_state"] for m in msgs] == ["sent_in_simulator"]  # the request journey still works


# --- Trigger: backend -> n8n --------------------------------------------------------------------


def test_request_evidence_triggers_n8n_once_per_task_round(hero: Hero) -> None:
    fake = use_n8n(hero, FakeN8n(200))
    result = request_delivery_proof(hero)
    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert str(req.url) == WEBHOOK and req.headers["authorization"] == "Bearer webhook-token"
    body = fake.bodies[0]
    assert set(body) == {
        "event_id",
        "event_type",
        "case_id",
        "staff_task_id",
        "request_round",
        "reminder_number",
        "requested_at",
        "remind_at",
        "deadline_at",
    }
    assert body["event_type"] == "staff.evidence_requested" and body["case_id"] == hero.case_id
    assert body["staff_task_id"] == result["staff_task_id"]
    assert body["request_round"] == 1 and body["reminder_number"] == 1
    assert iso(body["remind_at"]) - iso(body["requested_at"]) == timedelta(seconds=120)
    assert iso(body["deadline_at"]) == iso(hero.case()["deadline_utc"])
    assert "token" not in json.dumps(body)  # no credentials, files, recipients or free text
    view = task_view(hero)["reminder"]["trigger"]
    assert view["status"] == "delivered" and view["remind_at"] == body["remind_at"] and view["label"] is None

    again = request_delivery_proof(hero)  # duplicate request: same open task, no second trigger
    assert again["created"] is False and len(fake.requests) == 1


def test_transient_failures_retry_with_the_same_event_id(hero: Hero) -> None:
    fake = use_n8n(hero, FakeN8n(503, httpx.ConnectError("refused"), 200))
    request_delivery_proof(hero)
    assert len(fake.requests) == 3
    assert len({b["event_id"] for b in fake.bodies}) == 1
    trigger = task_view(hero)["reminder"]["trigger"]
    assert trigger["status"] == "delivered" and trigger["attempts"] == 3


def test_exhausted_retries_show_unavailable_then_explicit_retry_reuses_identity(hero: Hero) -> None:
    fake = use_n8n(hero, FakeN8n(500, 502, 503))
    request_delivery_proof(hero)
    trigger = task_view(hero)["reminder"]["trigger"]
    assert len(fake.requests) == 3  # first attempt + two bounded retries
    assert trigger["status"] == "failed" and trigger["label"] == "Reminder scheduling unavailable"
    assert hero.case()["workflow_state"] == "WAITING_FOR_EVIDENCE"  # the case continues normally

    staff_try = hero.c.post(f"/api/cases/{hero.case_id}/reminder-triggers/{trigger['id']}/retry", headers=hero.staff)
    assert staff_try.status_code == 403
    r = hero.c.post(f"/api/cases/{hero.case_id}/reminder-triggers/{trigger['id']}/retry", headers=hero.owner)
    assert r.status_code == 202, r.text
    assert len(fake.requests) == 4 and len({b["event_id"] for b in fake.bodies}) == 1
    assert task_view(hero)["reminder"]["trigger"]["status"] == "delivered"
    again = hero.c.post(f"/api/cases/{hero.case_id}/reminder-triggers/{trigger['id']}/retry", headers=hero.owner)
    assert again.status_code == 409


def test_authentication_error_pauses_without_retrying(hero: Hero) -> None:
    fake = use_n8n(hero, FakeN8n(401))
    request_delivery_proof(hero)
    trigger = task_view(hero)["reminder"]["trigger"]
    assert len(fake.requests) == 1
    assert trigger["status"] == "paused" and trigger["error"] == "HTTP 401"
    assert trigger["label"] == "Reminder scheduling unavailable"


def test_pending_trigger_rechecks_eligibility_before_dispatch(hero: Hero) -> None:
    fake = use_n8n(hero, FakeN8n(200))
    task_id = request_delivery_proof(hero)["staff_task_id"]
    assert hero.c.post(f"/api/cases/{hero.case_id}/messages", headers=hero.staff, json={"body": "ok"}).status_code
    with session_scope() as s:
        event = s.scalar(select(OutboxEvent).where(OutboxEvent.event_type == reminders.TRIGGER_EVENT))
        assert event is not None
        event.status = "pending"  # as if the dispatch had not happened yet
        event_id = event.id
    result = asyncio.run(reminders.dispatch_trigger(hero.c.app, event_id))
    assert result == {"status": "skipped", "reason": "task_responded"}
    assert len(fake.requests) == 1
    assert task_view(hero)["id"] == task_id


def test_interrupted_dispatch_resumes_on_recovery_with_same_event_id(hero: Hero) -> None:
    fake = use_n8n(hero, FakeN8n(200))
    request_delivery_proof(hero)
    with session_scope() as s:
        event = s.scalar(select(OutboxEvent).where(OutboxEvent.event_type == reminders.TRIGGER_EVENT))
        work = s.scalar(select(PendingWork).where(PendingWork.kind == "dispatch_reminder_trigger"))
        assert event is not None and work is not None
        event.status, work.status = "pending", "running"  # crash mid-dispatch
    r = hero.c.post("/api/demo/resume-pending", headers=hero.operator)
    assert r.status_code == 200 and r.json()["requeued_work"] >= 1
    assert len(fake.requests) == 2 and fake.bodies[0]["event_id"] == fake.bodies[1]["event_id"]
    assert task_view(hero)["reminder"]["trigger"]["status"] == "delivered"


# --- Callback: n8n -> backend -------------------------------------------------------------------


def test_callback_authentication_and_scope(tmp_path: Path, clock: FixedClock) -> None:
    settings = make_settings(tmp_path, **ON, reminder_merchant_mids="MID-SOMEONE-ELSE")
    with TestClient(create_app(settings)) as c:
        hero = Hero(c, settings)
        use_n8n(hero, FakeN8n())
        task_id = request_delivery_proof(hero)["staff_task_id"]
        assert callback(hero, task_id, headers={}).status_code == 401
        assert callback(hero, task_id, headers={"Authorization": "Bearer webhook-token"}).status_code == 401
        assert callback(hero, task_id, headers=hero.owner).status_code == 401  # a demo session is not the service
        assert callback(hero, task_id).status_code == 404  # merchant outside the service's scope


def test_callback_validates_task_and_reminder_number(hero: Hero, clock: FixedClock) -> None:
    use_n8n(hero, FakeN8n())
    task_id = request_delivery_proof(hero)["staff_task_id"]
    assert callback(hero, "no-such-task").status_code == 404
    assert callback(hero, task_id, case_id="no-such-case").status_code == 404
    assert callback(hero, task_id, number=2).status_code == 422  # at most one reminder per round
    clock.advance(timedelta(seconds=121))
    r = callback(hero, task_id, round_no=2)
    assert r.status_code == 200 and r.json() == {"result": "skipped", "reason": "round_changed"}


def test_one_eligible_reminder_reaches_the_staff_inbox_and_duplicates_are_idempotent(
    hero: Hero, clock: FixedClock
) -> None:
    use_n8n(hero, FakeN8n())
    task_id = request_delivery_proof(hero)["staff_task_id"]

    early = callback(hero, task_id)
    assert early.status_code == 200 and early.json() == {"result": "skipped", "reason": "not_due"}
    with session_scope() as s:
        assert s.scalars(select(StaffReminder)).all() == []  # a not-due call does not consume the key

    clock.advance(timedelta(seconds=120))
    r = callback(hero, task_id)
    assert r.status_code == 202, r.text
    assert r.json()["result"] == "queued" and r.json()["status"] == "queued"
    reminder_id = r.json()["reminder_id"]

    texts = reminder_messages(hero)
    assert len(texts) == 1 and "ORD-DEMO-18500" in texts[0] and texts[0].startswith("स्मरणपत्र")  # task locale mr-IN
    task = task_view(hero)
    assert task["status"] == "open"  # a reminder never resolves the request
    assert task["reminder"]["reminders"][0]["status"] == "sent"
    with session_scope() as s:
        msg = s.scalar(select(Message).where(Message.dedup_key.like("reminder:%")))
        assert msg is not None and msg.delivery_state == "sent_in_simulator" and msg.staff_task_id == task_id

    for _ in range(2):  # n8n retry / lost acknowledgement
        dup = callback(hero, task_id)
        assert dup.status_code == 200
        assert dup.json()["result"] == "already_processed" and dup.json()["reminder_id"] == reminder_id
        assert dup.json()["status"] == "sent"
    assert len(reminder_messages(hero)) == 1
    events = hero.c.get(f"/api/cases/{hero.case_id}/events", headers=hero.owner).json()
    sent = [e for e in events["events"] if e["event_type"] == "reminder.sent"]
    assert len(sent) == 1 and sent[0]["actor_type"] == "service"


@pytest.mark.parametrize("how", ["reply", "upload", "voice_note"])
def test_staff_response_before_due_suppresses_the_reminder(hero: Hero, clock: FixedClock, how: str) -> None:
    use_n8n(hero, FakeN8n())
    task_id = request_delivery_proof(hero)["staff_task_id"]
    if how == "reply":
        r = hero.c.post(f"/api/cases/{hero.case_id}/messages", headers=hero.staff, json={"body": "पाठवतो"})
    elif how == "upload":
        r = hero.upload("delivery_receipt_correct.pdf", hero.fixture("delivery_receipt_correct"))
    else:
        from tests.test_m5_testimony import FIXTURE

        hero.c.app.state.speech_provider = None  # type: ignore[attr-defined]
        r = hero.c.post(
            f"/api/cases/{hero.case_id}/voice-notes",
            headers=hero.staff,
            files={"file": ("voice.ogg", FIXTURE, "audio/ogg")},
        )
    assert r.status_code == 201, r.text
    clock.advance(timedelta(seconds=150))
    res = callback(hero, task_id)
    assert res.status_code == 200 and res.json()["result"] == "skipped"
    assert res.json()["reason"] in ("task_responded", "staff_replied")
    assert reminder_messages(hero) == []


def test_expired_deadline_cancels_the_reminder(hero: Hero, clock: FixedClock) -> None:
    use_n8n(hero, FakeN8n())
    task_id = request_delivery_proof(hero)["staff_task_id"]
    clock.advance(timedelta(hours=49))  # seeded deadline is 48h after seeding
    hero.relogin()
    res = callback(hero, task_id)
    assert res.status_code == 200 and res.json() == {"result": "skipped", "reason": "deadline_passed"}
    assert reminder_messages(hero) == []


def test_queued_reminder_rechecks_cancellation_before_sending(hero: Hero, clock: FixedClock) -> None:
    """A reply that lands between the accepted callback and delivery still wins."""
    use_n8n(hero, FakeN8n())
    task_id = request_delivery_proof(hero)["staff_task_id"]
    clock.advance(timedelta(seconds=121))
    with session_scope() as s:
        from app.db.models import Case

        case = s.get(Case, hero.case_id)
        assert case is not None
        status_code, body = reminders.handle_callback(
            s, hero.settings, case, staff_task_id=task_id, request_round=1, reminder_number=1, actor="test"
        )
        assert status_code == 202
    assert hero.c.post(f"/api/cases/{hero.case_id}/messages", headers=hero.staff, json={"body": "ok"}).status_code
    with session_scope() as s:
        assert reminders.send_reminder(s, body["reminder_id"]) == {"status": "skipped", "reason": "task_responded"}
    with session_scope() as s:
        assert reminders.send_reminder(s, body["reminder_id"])["skipped"] is True  # idempotent
    assert reminder_messages(hero) == []
    dup = callback(hero, task_id)
    assert dup.json()["result"] == "already_processed" and dup.json()["status"] == "skipped"


def test_staff_message_outbox_never_consumes_n8n_triggers(hero: Hero) -> None:
    use_n8n(hero, FakeN8n(500, 500, 500))
    request_delivery_proof(hero)
    with session_scope() as s:
        trigger = s.scalar(select(OutboxEvent).where(OutboxEvent.event_type == reminders.TRIGGER_EVENT))
        assert trigger is not None and trigger.status == "failed"  # left for the explicit retry
        from app.services.messaging import deliver_outbox

        deliver_outbox(s, hero.case_id)
        assert trigger.status == "failed"


def test_readiness_reports_configured_without_secrets(hero: Hero) -> None:
    body = hero.c.get("/api/providers").json()
    n8n = next(i for i in body["integrations"] if i["name"] == "n8n_reminders")
    assert n8n["status"] == "configured" and WEBHOOK in n8n["detail"]
    assert "service-token" not in json.dumps(body) and "webhook-token" not in json.dumps(body)
