"""Gemini API Reasoner (primary; user decision, see BUILD_LOG.md).

- Key sent only in the `x-goog-api-key` header (never in URLs, logs or stored rows).
- Structured JSON output via `responseJsonSchema` (JSON Schema) or, when the smoke test found
  that unsupported, `responseSchema` (OpenAPI subset). Output is still validated by Pydantic.
- Thinking models may return thought parts; they are dropped and never stored (PRD 9).
- Free tier: Google may use free-tier data; ProofCircuit sends synthetic data only.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from app.agent.schema import to_openapi_subset
from app.config import Settings
from app.providers.base import Completion, ReasonerError

DEFAULT_CAPABILITIES = {"schema_field": "responseJsonSchema", "thinking_level": True}


def _retry_after(payload: Any, headers: httpx.Headers) -> float | None:
    try:
        for detail in payload["error"].get("details", []):
            if str(detail.get("@type", "")).endswith("RetryInfo"):
                match = re.fullmatch(r"([\d.]+)s", str(detail.get("retryDelay", "")))
                if match:
                    return float(match.group(1))
    except (KeyError, TypeError, AttributeError):
        pass
    value = headers.get("retry-after")
    return float(value) if value and value.replace(".", "", 1).isdigit() else None


class GeminiReasoner:
    name = "gemini"
    mode = "live"

    def __init__(
        self,
        settings: Settings,
        capabilities: dict[str, Any] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if settings.gemini_api_key is None:
            raise ReasonerError("config", "GEMINI_API_KEY is not set")
        self._settings = settings
        self.model = settings.gemini_model
        self.capabilities = {**DEFAULT_CAPABILITIES, **(capabilities or {})}
        self._transport = transport

    def build_body(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        config: dict[str, Any] = {
            "temperature": 0.0,
            "maxOutputTokens": self._settings.reasoner_max_output_tokens,
            "responseMimeType": "application/json",
        }
        if self.capabilities["schema_field"] == "responseSchema":
            config["responseSchema"] = to_openapi_subset(schema)
        else:
            config["responseJsonSchema"] = schema
        if self.capabilities.get("thinking_level") and self._settings.gemini_thinking_level:
            config["thinkingConfig"] = {"thinkingLevel": self._settings.gemini_thinking_level}
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }

    async def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion:
        url = f"{self._settings.gemini_base_url}/models/{self.model}:generateContent"
        key = self._settings.gemini_api_key.get_secret_value()  # type: ignore[union-attr]
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._settings.model_timeout_seconds, transport=self._transport) as c:
                resp = await c.post(
                    url,
                    json=self.build_body(system, user, schema),
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise ReasonerError("timeout", f"Gemini timed out after {self._settings.model_timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise ReasonerError("transient", f"Gemini request failed: {type(exc).__name__}") from exc
        latency = int((time.monotonic() - started) * 1000)
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code != 200:
            message = str(payload.get("error", {}).get("message", resp.text[:200])) if isinstance(payload, dict) else ""
            message = message.replace(key, "[redacted]")
            if resp.status_code == 429:
                raise ReasonerError(
                    "rate_limited",
                    f"Gemini 429: {message}",
                    http_status=429,
                    retry_after=_retry_after(payload, resp.headers),
                )
            if resp.status_code >= 500:
                raise ReasonerError("transient", f"Gemini {resp.status_code}: {message}", http_status=resp.status_code)
            raise ReasonerError("config", f"Gemini {resp.status_code}: {message}", http_status=resp.status_code)

        candidates = payload.get("candidates") or []
        if not candidates:
            reason = (payload.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise ReasonerError("blocked", f"Gemini returned no candidate ({reason})", http_status=200)
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            finish = candidates[0].get("finishReason")
            raise ReasonerError("transient", f"Gemini returned no text (finishReason={finish})", http_status=200)
        usage = payload.get("usageMetadata") or {}
        return Completion(
            text=text,
            model_returned=payload.get("modelVersion") or self.model,
            latency_ms=latency,
            prompt_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )
