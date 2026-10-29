"""Request writes must be committed before the response is sent.

FastAPI's default dependency scope ("request") runs the code after `yield` only after the response
has gone out. With `get_db` committing there, a client acting on a response could still read the
pre-request state: after `POST /api/demo/reset`, an immediate login picked up a deleted user
("demo session no longer valid"). A failed commit would also hide behind a 2xx already sent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Case, DemoUser
from app.db.session import session_scope
from app.domain.clock import FixedClock
from app.main import create_app
from tests.conftest import login, make_settings


def test_reset_is_committed_when_the_response_starts(tmp_path: Path, clock: FixedClock) -> None:
    app = create_app(make_settings(tmp_path))
    seen: dict[str, Any] = {}

    async def probe(scope: dict[str, Any], receive: Any, send: Any) -> None:
        async def send_and_look(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start" and scope.get("path") == "/api/demo/reset":
                # What a second client sees at the moment this response starts.
                with session_scope() as s:
                    seen["cases"] = set(s.scalars(select(Case.id)))
                    seen["owners"] = set(s.scalars(select(DemoUser.id).where(DemoUser.handle == "owner")))
            await send(message)

        await app(scope, receive, send_and_look)

    with TestClient(probe) as c:
        operator = login(c, "operator")
        old_case = c.get("/api/cases", headers=operator).json()[0]["id"]
        r = c.post("/api/demo/reset", headers=operator, json={"confirm": True})
        assert r.status_code == 200, r.text
        new_case = r.json()["case_id"]
        assert new_case != old_case
        assert seen["cases"] == {new_case}, "the response was sent before the reset was committed"

        # The follow-up that used to fail: log in right away and act on the new case.
        with session_scope() as s:
            assert set(s.scalars(select(DemoUser.id).where(DemoUser.handle == "owner"))) == seen["owners"]
        owner = login(c, "owner")
        assert c.get(f"/api/cases/{new_case}", headers=owner).status_code == 200
