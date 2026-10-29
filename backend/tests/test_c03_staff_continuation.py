"""C03 Staff continuation (PRD 8.2, 15.1): the request reaches the configured assignee in their locale,
one message per (case, requirement, round) however often it is proposed, and the case resumes only
when staff actually reply or upload (no polling, no model call while waiting)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Message, OutboxEvent, StaffTask
from app.db.session import session_scope
from app.domain.clock import FixedClock
from app.providers.fake import FakeReasoner, action
from tests.helpers import Hero
from tests.test_m3_agent_loop import agent_client


@pytest.fixture
def hero(client: TestClient, settings) -> Hero:  # type: ignore[no-untyped-def]
    return Hero(client, settings)


@pytest.fixture
def agent(tmp_path: Path, clock: FixedClock):  # type: ignore[no-untyped-def]
    gens: list[Iterator[Hero]] = []

    def factory(fake: FakeReasoner) -> Hero:
        gen = agent_client(tmp_path, clock, fake)
        gens.append(gen)
        return next(gen)

    yield factory
    for gen in gens:
        for _ in gen:
            pass


def inbox(hero: Hero) -> dict[str, Any]:
    return hero.c.get(f"/api/cases/{hero.case_id}/messages", headers=hero.owner).json()


def counts() -> tuple[int, int, int]:
    with session_scope() as s:
        return (
            int(s.scalar(select(func.count()).select_from(StaffTask).where(StaffTask.kind == "evidence")) or 0),
            int(s.scalar(select(func.count()).select_from(Message).where(Message.direction == "outbound")) or 0),
            int(
                s.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == "staff_message"))
                or 0
            ),
        )


@pytest.mark.parametrize(
    ("requirement", "assignee", "locale", "marker"),
    [
        ("delivery_record", "Sanjay (Delivery)", "mr-IN", "पावती"),  # Marathi template
        ("invoice", "Meera (Billing)", "hi-IN", "इनवॉइस"),  # Hindi template
        ("order_linkage", "Meera (Billing)", "hi-IN", "लेनदेन"),
    ],
)
def test_request_goes_to_the_configured_assignee_in_their_locale(
    hero: Hero, requirement: str, assignee: str, locale: str, marker: str
) -> None:
    call = hero.act("request_evidence", requirement_id=requirement)
    assert call["status"] == "ok" and call["result"]["locale"] == locale
    view = inbox(hero)
    task = next(t for t in view["tasks"] if t["requirement_id"] == requirement)
    assert task["assignee"] == assignee and task["locale"] == locale and task["status"] == "open"
    [msg] = [m for m in view["messages"] if m["direction"] == "outbound"]
    assert msg["to"] == assignee and msg["locale"] == locale and marker in msg["body"]
    assert msg["delivery_state"] == "sent_in_simulator"  # local inbox, never "delivered on WhatsApp"


def test_locale_override_and_invalid_arguments(hero: Hero) -> None:
    call = hero.act("request_evidence", requirement_id="delivery_record", locale="en-IN")
    assert call["result"]["locale"] == "en-IN"
    [msg] = [m for m in inbox(hero)["messages"] if m["direction"] == "outbound"]
    assert msg["body"].startswith("Order ORD-DEMO-18500:")
    assert hero.act("request_evidence", requirement_id="invoice", locale="fr-FR")["status"] != "ok"
    assert hero.act("request_evidence", requirement_id="delivery_record", assignee_id="staff-billing")["status"] != "ok"
    assert hero.act("request_evidence", requirement_id="refund_approval")["status"] != "ok"


def test_repeated_requests_send_one_message_per_round(hero: Hero) -> None:
    first = hero.act("request_evidence", requirement_id="delivery_record")
    for _ in range(3):
        again = hero.act("request_evidence", requirement_id="delivery_record")
        assert (
            again["result"]["created"] is False and again["result"]["staff_task_id"] == first["result"]["staff_task_id"]
        )
    assert counts() == (1, 1, 1)

    hero.upload("wrong.pdf", hero.fixture("delivery_receipt_wrong_order"))  # answers round 1
    round2 = hero.act("request_evidence", requirement_id="delivery_record")
    assert round2["result"]["created"] is True and round2["result"]["round"] == 2
    hero.act("request_evidence", requirement_id="delivery_record")
    assert counts() == (2, 2, 2)
    bodies = [m["body"] for m in inbox(hero)["messages"] if m["direction"] == "outbound"]
    assert "दुसऱ्या ऑर्डरची" in bodies[1]  # the wrong-receipt variant, not a copy of round 1


def test_agent_resumes_only_on_an_actual_staff_reply(agent, clock: FixedClock) -> None:  # type: ignore[no-untyped-def]
    fake = FakeReasoner(
        [
            action("request_evidence", "Delivery proof is missing.", requirement_id="delivery_record"),
            action("request_evidence", "Ask again.", requirement_id="delivery_record"),
        ]
    )
    h = agent(fake)
    assert h.c.post(f"/api/cases/{h.case_id}/runs", headers=h.owner).status_code == 202
    assert len(fake.calls) == 1 and h.case()["workflow_state"] == "WAITING_FOR_EVIDENCE"

    clock.advance(timedelta(hours=6))  # time passing alone triggers nothing
    h.relogin()
    assert h.c.get(f"/api/cases/{h.case_id}", headers=h.owner).status_code == 200
    assert len(fake.calls) == 1

    r = h.c.post(f"/api/cases/{h.case_id}/messages", headers=h.staff, json={"body": "पावती शोधतो आहे"})
    assert r.status_code == 201
    # The reply resumed the case with exactly one model call: the request it proposed opened round 2, the
    # case is waiting again, and the loop returned control without a further call.
    assert len(fake.calls) == 2
    assert "पावती शोधतो आहे" in fake.calls[1]["user"]  # the model saw the actual reply (as untrusted data)
    assert counts()[1] == 2  # round 2 only after the reply answered round 1; never two per round
    tasks = [t for t in inbox(h)["tasks"] if t["kind"] == "evidence"]
    assert [t["status"] for t in tasks] == ["responded", "open"]
