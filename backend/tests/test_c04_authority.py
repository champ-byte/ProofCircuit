"""C04 Authority: the agent/tool path cannot concede; concession needs a reviewer's single-use,
version-bound, unexpired approval; refund checks never write; tenant scope holds.
(The malicious-evidence variant is in test_c02_evidence_citations.py.)"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.agent.tools import ToolContext, dispatch
from app.domain.clock import FixedClock
from tests.conftest import login
from tests.helpers import Hero


@pytest.fixture
def hero(client: TestClient, settings) -> Hero:  # type: ignore[no-untyped-def]
    return Hero(client, settings)


def approve(hero: Hero) -> str:
    resp = hero.c.post(
        f"/api/cases/{hero.case_id}/reviews",
        headers=hero.reviewer,
        json={"decision": "approve_concession", "explanation": "Customer evidence is credible."},
    )
    assert resp.status_code == 201, resp.text
    assert "₹18,500.00" in resp.json()["consequence"]
    return resp.json()["approval_id"]


def concede(hero: Hero, approval_id: str, headers: dict[str, str] | None = None, confirm: bool = True):  # type: ignore[no-untyped-def]
    return hero.c.post(
        f"/api/cases/{hero.case_id}/accept-dispute",
        headers=headers or hero.reviewer,
        json={"approval_id": approval_id, "confirm": confirm},
    )


def test_tool_path_has_no_concession_or_refund(hero: Hero) -> None:
    for tool in ("accept_dispute", "issue_refund", "http_request", "run_sql"):
        resp = hero.c.post(f"/api/cases/{hero.case_id}/actions", headers=hero.owner, json={"tool": tool})
        assert resp.status_code == 422
    ctx = ToolContext(case_id=hero.case_id, run_id=hero.new_run(), actor_kind="agent")
    out = asyncio.run(dispatch(hero.c.app, ctx, step=1, tool_name="accept_dispute", arguments={}, rationale="x"))
    assert out["status"] == "denied"
    assert hero.receipts() == []


def test_tool_arguments_cannot_switch_case_or_cite_foreign_sources(hero: Hero) -> None:
    ctx = ToolContext(case_id=hero.case_id, run_id=hero.new_run(), actor_kind="agent")
    bad = asyncio.run(
        dispatch(hero.c.app, ctx, step=1, tool_name="validate_evidence", arguments={"case_id": "other"}, rationale="x")
    )
    assert bad["status"] == "denied"
    foreign = asyncio.run(
        dispatch(
            hero.c.app,
            ctx,
            step=1,
            tool_name="validate_evidence",
            arguments={},
            rationale="x",
            source_ids=["doc-from-elsewhere"],
        )
    )
    assert foreign["status"] == "denied"
    wrong_assignee = asyncio.run(
        dispatch(
            hero.c.app,
            ctx,
            step=1,
            tool_name="request_evidence",
            arguments={"requirement_id": "delivery_record", "assignee_id": "staff-billing"},
            rationale="x",
        )
    )
    assert wrong_assignee["status"] == "denied"


def test_only_reviewer_approves_and_concedes(hero: Hero) -> None:
    for role in ("owner", "operator", "staff-delivery"):
        headers = login(hero.c, role)
        assert (
            hero.c.post(
                f"/api/cases/{hero.case_id}/reviews",
                headers=headers,
                json={"decision": "approve_concession", "explanation": "nope nope"},
            ).status_code
            == 403
        )
    approval = approve(hero)
    assert concede(hero, approval, headers=hero.owner).status_code == 403
    assert concede(hero, approval, confirm=False).status_code == 422


def test_concession_executes_once(hero: Hero) -> None:
    approval = approve(hero)
    resp = concede(hero, approval)
    assert resp.status_code == 202
    [sub] = hero.submissions()
    assert sub["action"] == "ACCEPT" and sub["state"] == "verified"
    case = hero.case()
    assert case["provider_status"] == "LOST" and case["workflow_state"] == "CLOSED"
    replay = concede(hero, approval)
    assert replay.status_code == 409 and "approval already used" in str(replay.json())
    assert len(hero.receipts()) == 1


def test_stale_approval_after_case_change(hero: Hero) -> None:
    approval = approve(hero)
    hero.upload("note.txt", "Courier note: delivered to the security desk.\n", "text/plain")
    resp = concede(hero, approval)
    assert resp.status_code == 409 and "case changed since approval" in str(resp.json())
    assert hero.receipts() == []


def test_expired_approval(hero: Hero, clock: FixedClock) -> None:
    approval = approve(hero)
    clock.advance(timedelta(minutes=15))
    resp = concede(hero, approval)
    assert resp.status_code == 409 and "approval expired" in str(resp.json())


def test_approval_bound_to_case_and_tenant(hero: Hero) -> None:
    approval = approve(hero)
    other = login(hero.c, "owner", mid="MID-DEMO-002")
    assert (
        hero.c.post(
            f"/api/cases/{hero.case_id}/accept-dispute", headers=other, json={"approval_id": approval, "confirm": True}
        ).status_code
        == 403
    )
    assert hero.c.get(f"/api/cases/{hero.case_id}/submissions", headers=other).status_code == 404
    assert (
        hero.c.post(f"/api/cases/{hero.case_id}/actions", headers=other, json={"tool": "get_case_context"}).status_code
        == 404
    )


def test_refund_check_denies_open_dispute_without_any_write(hero: Hero) -> None:
    before = hero.status_call()["body"]
    resp = hero.c.post(f"/api/cases/{hero.case_id}/refund-policy-check", headers=hero.owner)
    assert resp.json()["decision"] == "DENY_OPEN_DISPUTE" and resp.json()["dry_run"] is True
    assert hero.status_call()["body"] == before and hero.receipts() == []
