"""Shared helpers for API-level contract tests."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.simulator.signing import sign_body, sign_params
from tests.conftest import login

MID = "MID-DEMO-001"
DISPUTE = "DSP-DEMO-001"


class Hero:
    def __init__(self, client: TestClient, settings: Settings) -> None:
        self.c = client
        self.settings = settings
        self.relogin()
        self.case_id = client.get("/api/cases", headers=self.owner).json()[0]["id"]

    def relogin(self) -> None:
        """Demo sessions last 12h of (test) clock time; call after advancing the clock past that."""
        self.owner = login(self.c, "owner")
        self.staff = login(self.c, "staff-delivery")
        self.reviewer = login(self.c, "reviewer")
        self.operator = login(self.c, "operator")

    def new_run(self) -> str:
        from app.db.models import AgentRun
        from app.db.session import session_scope

        with session_scope() as s:
            run = AgentRun(case_id=self.case_id, provider="test", mode="manual")
            s.add(run)
            s.flush()
            return run.id

    @property
    def secret(self) -> str:
        return self.settings.demo_webhook_secret.get_secret_value()

    def case(self) -> dict[str, Any]:
        return self.c.get(f"/api/cases/{self.case_id}", headers=self.owner).json()

    def act(self, tool: str, **arguments: Any) -> dict[str, Any]:
        r = self.c.post(
            f"/api/cases/{self.case_id}/actions",
            headers=self.owner,
            json={"tool": tool, "arguments": arguments, "reason": "test"},
        )
        assert r.status_code == 202, r.text
        run = next(
            x
            for x in self.c.get(f"/api/cases/{self.case_id}/runs", headers=self.owner).json()
            if x["id"] == r.json()["run_id"]
        )
        return run["tool_calls"][0]

    def fixture(self, name: str) -> bytes:
        return self.c.get(f"/api/demo/cases/{self.case_id}/fixtures/{name}", headers=self.staff).content

    def upload(
        self, name: str, data: bytes | str, mime: str = "application/pdf", headers: dict[str, str] | None = None
    ) -> Any:
        body = data.encode() if isinstance(data, str) else data
        return self.c.post(
            f"/api/cases/{self.case_id}/evidence", headers=headers or self.staff, files={"file": (name, body, mime)}
        )

    def make_ready(self) -> dict[str, Any]:
        """Upload the correct receipt and build a pack. Returns the build_evidence_pack tool call."""
        assert self.upload("delivery_receipt_correct.pdf", self.fixture("delivery_receipt_correct")).status_code == 201
        call = self.act("build_evidence_pack")
        assert call["status"] == "ok", call
        return call

    def submissions(self) -> list[dict[str, Any]]:
        return self.c.get(f"/api/cases/{self.case_id}/submissions", headers=self.owner).json()

    def receipts(self) -> list[dict[str, Any]]:
        params = {"mid": MID, "disputeId": DISPUTE}
        r = self.c.get(
            "/api/simulator/receipts", params=params, headers={"X-Demo-Signature": sign_params(self.secret, params)}
        )
        assert r.status_code == 200, r.text
        return r.json()

    def inject(self, **event: Any) -> Any:
        return self.c.post("/api/simulator/events", headers=self.operator, json={"dispute_id": DISPUTE, **event})

    def fault(self, api: str, kind: str, count: int = 1) -> None:
        assert self.inject(type="fault", api=api, kind=kind, count=count).status_code == 200

    # --- direct, signed simulator calls (as Paytm's API would be called) ---------------------

    def status_call(
        self, body: dict[str, Any] | None = None, head: dict[str, Any] | None = None, sign: bool = True
    ) -> dict[str, Any]:
        body = body if body is not None else {"mid": MID, "disputeId": DISPUTE}
        h = {"requestTimestamp": str(int(time.time())), "tokenType": "CHECKSUM", **(head or {})}
        if sign and "signature" not in h:
            h["signature"] = sign_body(self.secret, body)
        return self.c.post("/api/simulator/v1/dispute/status", json={"head": h, "body": body}).json()

    def action_call(
        self, params: dict[str, str], files: list[tuple[str, bytes, str]] | None = None, sign: bool = True
    ) -> Any:
        p = {"mid": MID, "disputeId": DISPUTE, "requestTimestamp": str(int(time.time())), **params}
        if sign and "signature" not in p:
            p["signature"] = sign_params(self.secret, p)
        multipart = [("files", f) for f in files or []]
        return self.c.post("/api/simulator/v1/dispute/action", data=p, files=multipart or None)


def code(resp_json: dict[str, Any]) -> tuple[str, str, str]:
    info = resp_json["body"]["resultInfo"]
    return info["resultCodeId"], info["resultStatus"], info["resultCode"]
