"""M2 exit criterion: the manual end-to-end path (no model) through the same tools, policy gate,
runner and simulator the agent will use. Also covers in-app staff continuation basics."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import Hero


def test_manual_hero_journey(client: TestClient, settings) -> None:  # type: ignore[no-untyped-def]
    h = Hero(client, settings)
    assert client.post(f"/api/cases/{h.case_id}/runs", headers=h.owner).status_code == 202
    assert h.case()["workflow_state"] == "COLLECTING"

    first = h.act("request_evidence", requirement_id="delivery_record")
    assert first["status"] == "ok" and first["result"]["created"] and first["result"]["locale"] == "mr-IN"
    dup = h.act("request_evidence", requirement_id="delivery_record")
    assert dup["result"]["created"] is False and dup["result"]["staff_task_id"] == first["result"]["staff_task_id"]
    assert h.case()["workflow_state"] == "WAITING_FOR_EVIDENCE"
    inbox = client.get(f"/api/cases/{h.case_id}/messages", headers=h.staff).json()
    [msg] = inbox["messages"]
    assert msg["to"] == "Sanjay (Delivery)" and msg["delivery_state"] == "sent_in_simulator"
    assert msg["body"].startswith("ऑर्डर ORD-DEMO-18500") and "पावती" in msg["body"]

    h.upload("wrong.pdf", h.fixture("delivery_receipt_wrong_order"))
    assert h.case()["workflow_state"] == "NEEDS_HUMAN_REVIEW"
    assert h.act("build_evidence_pack")["status"] == "denied"
    assert h.act("submit_defense")["status"] == "denied"

    second = h.act("request_evidence", requirement_id="delivery_record")
    assert second["result"]["round"] == 2
    bodies = [m["body"] for m in client.get(f"/api/cases/{h.case_id}/messages", headers=h.staff).json()["messages"]]
    assert "दुसऱ्या ऑर्डरची" in bodies[-1]  # the "wrong receipt" template
    assert h.case()["workflow_state"] == "WAITING_FOR_EVIDENCE"

    h.upload("right.pdf", h.fixture("delivery_receipt_correct"))
    assert h.case()["workflow_state"] == "READY_TO_SUBMIT"
    assert h.act("build_evidence_pack")["status"] == "ok"
    result = h.act("submit_defense")["result"]
    assert result["status"] == "verified"
    case = h.case()
    assert (case["workflow_state"], case["provider_status"]) == ("MONITORING", "POD_UPLOAD")

    refund = client.post(f"/api/cases/{h.case_id}/refund-policy-check", headers=h.owner).json()
    assert refund["decision"] == "DENY_OPEN_DISPUTE"

    events = [e["event_type"] for e in client.get(f"/api/cases/{h.case_id}/events", headers=h.owner).json()["events"]]
    order = [
        "evidence.requested",
        "message.delivered_local",
        "validation.finding_opened",
        "evidence.superseded",
        "pack.built",
        "submission.requested",
        "submission.provider_response",
        "submission.verified",
    ]
    positions = [events.index(e) for e in order]
    assert positions == sorted(positions)
    assert "Delivered on WhatsApp" not in str(events)


def test_staff_text_reply_resumes_the_case(client: TestClient, settings) -> None:  # type: ignore[no-untyped-def]
    h = Hero(client, settings)
    h.act("request_evidence", requirement_id="delivery_record")
    version = h.case()["version"]
    resp = client.post(f"/api/cases/{h.case_id}/messages", headers=h.staff, json={"body": "पावती उद्या पाठवतो."})
    assert resp.status_code == 201
    case = h.case()
    assert case["version"] == version + 1
    assert case["workflow_state"] == "COLLECTING"  # task responded; evidence still missing
    tasks = client.get(f"/api/cases/{h.case_id}/messages", headers=h.staff).json()["tasks"]
    assert [t["status"] for t in tasks] == ["responded"]
    assert client.post(f"/api/cases/{h.case_id}/messages", headers=h.owner, json={"body": "x"}).status_code == 403
