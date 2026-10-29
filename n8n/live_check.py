"""Live M6 exit check against a running backend (reminders on, 30 s delay) and the published n8n workflow.

    uv run --project backend python -I n8n/live_check.py .

Prerequisites: `python n8n/setup.py`, and the backend started with REMINDERS_ENABLED=true,
N8N_REMINDER_WEBHOOK_URL, both tokens from n8n/.env, REMINDER_DELAY_SECONDS=30 and AGENT_AUTORUN=false
(so no model calls). It resets the demo data. Takes about 80 seconds.

PRD 12.1: creating an evidence request starts n8n automatically; one eligible reminder reaches the
staff inbox; replying before it is due suppresses delivery; duplicate trigger/callback retries do not
duplicate the reminder. Tokens are read from n8n/.env and never printed.
"""

import json
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(sys.argv[1])
env = dict(
    line.split("=", 1)
    for line in (ROOT / "n8n" / ".env").read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
WEBHOOK = "http://127.0.0.1:5678/webhook/proofcircuit-staff-reminder"
c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=30)
t0 = time.monotonic()


def log(*a):
    print(f"[{time.monotonic() - t0:6.1f}s]", *a, flush=True)


def login(handle):
    r = c.post("/api/demo/session", json={"mid": "MID-DEMO-001", "handle": handle})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def inbox(case_id):
    return c.get(f"/api/cases/{case_id}/messages", headers=login("owner")).json()


def reminders_in_inbox(case_id):
    return [m for m in inbox(case_id)["messages"] if m["body"].startswith("स्मरणपत्र")]


def task(case_id, round_no):
    return next(t for t in inbox(case_id)["tasks"] if t["kind"] == "evidence" and t["round"] == round_no)


def wait_for(pred, timeout, what):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = pred()
        if value:
            return value
        time.sleep(1)
    raise SystemExit(f"FAILED: timed out waiting for {what}")


def request_proof(case_id):
    r = c.post(
        f"/api/cases/{case_id}/actions",
        headers=login("owner"),
        json={
            "tool": "request_evidence",
            "arguments": {"requirement_id": "delivery_record"},
            "reason": "M6 live check",
        },
    )
    assert r.status_code == 202, r.text


# Fresh hero case
r = c.post("/api/demo/reset", headers=login("operator"), json={"confirm": True})
r.raise_for_status()
case_id = r.json()["case_id"]
log("reset; case", case_id)

# 1. Evidence request -> backend triggers n8n automatically
request_proof(case_id)
trig = wait_for(
    lambda: (
        (task(case_id, 1).get("reminder") or {}).get("trigger", {}).get("status") == "delivered"
        and task(case_id, 1)["reminder"]["trigger"]
    ),
    20,
    "trigger delivered to n8n",
)
log("trigger acknowledged by n8n:", {k: trig[k] for k in ("status", "remind_at", "attempts")})
task1 = task(case_id, 1)["id"]

# 2. Duplicate trigger (as after a lost acknowledgement): same payload re-posted to n8n
events = c.get(f"/api/cases/{case_id}/events", headers=login("owner")).json()["events"]
created = next(e for e in events if e["event_type"] == "reminder.trigger_created")
assert created["data"]["staff_task_id"] == task1

# 3. One eligible reminder reaches the staff inbox without manual workflow start
sent = wait_for(lambda: reminders_in_inbox(case_id), 75, "reminder in staff inbox")
log("reminder in staff inbox:", sent[0]["body"], "|", sent[0]["delivery_state"])
rem = task(case_id, 1)["reminder"]["reminders"]
log("reminder rows:", [(x["status"], x["reason"]) for x in rem])

# 4. Duplicate callback (n8n retry): idempotent
svc = {"Authorization": f"Bearer {env['N8N_SERVICE_TOKEN']}"}
body = {"staff_task_id": task1, "request_round": 1, "reminder_number": 1}
dup = c.post(f"/api/cases/{case_id}/reminders", headers=svc, json=body)
log("duplicate callback:", dup.status_code, dup.json())
assert dup.status_code == 200 and dup.json()["result"] == "already_processed"
bad = c.post(f"/api/cases/{case_id}/reminders", headers={"Authorization": "Bearer wrong"}, json=body)
log("callback with wrong token:", bad.status_code)
assert bad.status_code == 401

# 5. Duplicate trigger to n8n with the original event identity -> second execution, still one reminder
trigger_payload = {
    "event_id": trig["id"],
    "event_type": "staff.evidence_requested",
    "case_id": case_id,
    "staff_task_id": task1,
    "request_round": 1,
    "reminder_number": 1,
    "requested_at": created["created_at"],
    "remind_at": trig["remind_at"],
    "deadline_at": "2099-01-01T00:00:00Z",
}
again = httpx.post(WEBHOOK, json=trigger_payload, headers={"Authorization": f"Bearer {env['N8N_WEBHOOK_TOKEN']}"})
log("re-sent same trigger to n8n:", again.status_code)
time.sleep(12)  # remind_at is already past, so n8n calls back almost at once
log("reminders in inbox after duplicate trigger:", len(reminders_in_inbox(case_id)))
assert len(reminders_in_inbox(case_id)) == 1

# 6. Reply before due suppresses delivery (round 2)
staff = login("staff-delivery")
assert c.post(f"/api/cases/{case_id}/messages", headers=staff, json={"body": "पावती शोधतो आहे"}).status_code == 201
time.sleep(2)
request_proof(case_id)
wait_for(lambda: any(t["round"] == 2 for t in inbox(case_id)["tasks"] if t["kind"] == "evidence"), 20, "round 2 task")
wait_for(
    lambda: (task(case_id, 2).get("reminder") or {}).get("trigger", {}).get("status") == "delivered",
    20,
    "round 2 trigger delivered",
)
log("round 2 trigger delivered; staff replies before it is due:", task(case_id, 2)["reminder"]["trigger"]["remind_at"])
assert c.post(f"/api/cases/{case_id}/messages", headers=staff, json={"body": "पाठवतो"}).status_code == 201
skipped = wait_for(
    lambda: [
        e
        for e in c.get(f"/api/cases/{case_id}/events", headers=login("owner")).json()["events"]
        if e["event_type"] == "reminder.skipped"
    ],
    75,
    "n8n callback for round 2",
)
log(
    "round 2 callback:",
    skipped[-1]["summary"],
    "| actor:",
    skipped[-1]["actor_type"],
    "| at",
    skipped[-1]["created_at"],
    "| data",
    skipped[-1]["data"],
)
log("reminders in inbox (expect 1):", len(reminders_in_inbox(case_id)))
assert len(reminders_in_inbox(case_id)) == 1

events = c.get(f"/api/cases/{case_id}/events", headers=login("owner")).json()["events"]
for e in events:
    if e["event_type"].startswith("reminder."):
        log(e["created_at"], e["event_type"], "|", e["actor_type"], "|", e["summary"], "|", json.dumps(e["data"]))
print("M6 LIVE CHECK PASSED")
