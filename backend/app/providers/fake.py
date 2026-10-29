"""Scripted reasoner for deterministic, network-free tests (C08 and the agent loop)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.providers.base import Completion, ReasonerError

Step = str | dict[str, Any] | ReasonerError | Callable[[str], str | dict[str, Any]]


def action(name: str, reason: str = "test", **arguments: Any) -> dict[str, Any]:
    return {"action": name, "arguments": arguments, "reason": reason, "source_ids": []}


class FakeReasoner:
    mode = "live"

    def __init__(self, steps: list[Step], *, name: str = "gemini", model: str = "fake-model-001") -> None:
        self.name = name
        self.model = model
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if not self.steps:
            raise ReasonerError("transient", "fake reasoner has no scripted step left")
        step = self.steps.pop(0)
        if isinstance(step, ReasonerError):
            raise step
        if callable(step):
            step = step(user)
        text = step if isinstance(step, str) else json.dumps(step)
        return Completion(
            text=text, model_returned=f"{self.model}-returned", latency_ms=1, prompt_tokens=10, output_tokens=5
        )
