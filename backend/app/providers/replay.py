"""Fixture replay: a pre-written hero script used only when explicitly chosen.

It is a fallback demonstration mode, not proof of autonomous reasoning (PRD 1.9). Runs are
labelled `fixture_replay` in the API, UI and evaluation output and are never counted as live AI.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import REPO_ROOT
from app.providers.base import Completion

REPLAY_FILE = REPO_ROOT / "fixtures" / "hero" / "replay.json"
CONTEXT_MARKER = "CASE_CONTEXT_JSON:\n"


def _matches(when: dict[str, Any], ctx: dict[str, Any]) -> bool:
    for key, expected in when.items():
        if key.startswith("checklist."):
            req = key.split(".", 1)[1]
            status = next((c["status"] for c in ctx.get("checklist", []) if c["requirement_id"] == req), None)
            if status not in expected:
                return False
        elif ctx.get(key) != expected:
            return False
    return True


class ReplayReasoner:
    name = "replay"
    model = "hero-replay-v1"
    mode = "fixture_replay"

    def __init__(self) -> None:
        self._rules = json.loads(REPLAY_FILE.read_text(encoding="utf-8"))["rules"]

    async def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion:
        start = user.index(CONTEXT_MARKER) + len(CONTEXT_MARKER)
        ctx = json.JSONDecoder().raw_decode(user[start:])[0]
        rule = next(r for r in self._rules if _matches(r["when"], ctx))
        args = {k: None for k in schema["properties"]["arguments"]["properties"]} | rule["action"]["arguments"]
        return Completion(
            text=json.dumps({**rule["action"], "arguments": args}), model_returned=self.model, latency_ms=0
        )
