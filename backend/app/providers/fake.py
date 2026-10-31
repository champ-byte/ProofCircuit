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


class FakeSpeechProvider:
    """Scripted speech-to-text for network-free tests. Results are never labelled live STT in the UI
    because tests are the only callers; the stored provider name is `fake_stt`."""

    name = "fake_stt"
    model = "fake-stt-001"

    def __init__(self, results: list[Any]) -> None:
        self.results = list(results)  # SpeechTranscript | SpeechError, consumed in order
        self.calls: list[dict[str, Any]] = []

    async def transcribe(self, audio: bytes, locale: str) -> Any:
        from app.providers.speech import SpeechError

        self.calls.append({"bytes": len(audio), "locale": locale})
        if not self.results:
            raise SpeechError("failed", "fake speech provider has no scripted result left")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def synthesize(self, text: str, locale: str) -> bytes:
        from app.providers.speech import SpeechError

        raise SpeechError("not_implemented", "not implemented")
