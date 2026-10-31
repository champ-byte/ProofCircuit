"""OpenRouter Reasoner (optional fallback; PRD 6.2, 9).

Free-first: with ALLOW_PAID_MODELS=false the preflight rejects any model whose catalog pricing
is non-zero, and nothing ever switches to a paid variant. `openrouter.ai` is blocked by this
cloud session's network policy, so this adapter is exercised with mocked transports only.
"""

from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import Completion, ReasonerError

FREE_ROUTER = "openrouter/free"


class OpenRouterReasoner:
    name = "openrouter"
    mode = "live"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if settings.openrouter_api_key is None:
            raise ReasonerError("config", "OPENROUTER_API_KEY is not set")
        self._settings = settings
        self.model = settings.openrouter_model
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings.openrouter_api_key.get_secret_value()}"}  # type: ignore[union-attr]

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._settings.openrouter_base_url,
            timeout=self._settings.model_timeout_seconds,
            transport=self._transport,
        )

    async def preflight(self) -> dict[str, Any]:
        """Catalog check: model exists, supports structured outputs, and is zero-priced unless allowed."""
        try:
            async with self._client() as c:
                resp = await c.get("/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise ReasonerError("transient", f"OpenRouter catalog unreachable: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ReasonerError("config", f"OpenRouter catalog HTTP {resp.status_code}", http_status=resp.status_code)
        models = {m.get("id"): m for m in resp.json().get("data", [])}
        if self.model == FREE_ROUTER and self.model not in models:
            return {"model": self.model, "free": True, "note": "free router; returned model logged per call"}
        entry = models.get(self.model)
        if entry is None:
            raise ReasonerError("config", f"model {self.model} not in the OpenRouter catalog")
        params = set(entry.get("supported_parameters") or [])
        if not params & {"structured_outputs", "response_format"}:
            raise ReasonerError("config", f"{self.model} does not advertise structured outputs")
        try:
            paid = any(Decimal(str(v)) != 0 for v in (entry.get("pricing") or {}).values())
        except InvalidOperation:
            paid = True
        if paid and not self._settings.allow_paid_models:
            raise ReasonerError("config", f"{self.model} is not zero-priced and ALLOW_PAID_MODELS=false")
        return {"model": self.model, "free": not paid, "supported_parameters": sorted(params)}

    def build_body(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": self._settings.reasoner_max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "proposed_action", "strict": True, "schema": schema},
            },
            "provider": {
                "require_parameters": self._settings.openrouter_require_parameters,
                "data_collection": self._settings.openrouter_data_collection,
            },
        }

    async def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion:
        started = time.monotonic()
        try:
            async with self._client() as c:
                resp = await c.post(
                    "/chat/completions", json=self.build_body(system, user, schema), headers=self._headers()
                )
        except httpx.TimeoutException as exc:
            raise ReasonerError("timeout", "OpenRouter timed out") from exc
        except httpx.HTTPError as exc:
            raise ReasonerError("transient", f"OpenRouter request failed: {type(exc).__name__}") from exc
        latency = int((time.monotonic() - started) * 1000)
        if resp.status_code == 429:
            retry = resp.headers.get("retry-after")
            raise ReasonerError(
                "rate_limited",
                "OpenRouter 429",
                http_status=429,
                retry_after=float(retry) if retry and retry.isdigit() else None,
            )
        if resp.status_code == 402:
            raise ReasonerError("config", "OpenRouter 402: no paid usage allowed", http_status=402)
        if resp.status_code >= 500:
            raise ReasonerError("transient", f"OpenRouter {resp.status_code}", http_status=resp.status_code)
        if resp.status_code != 200:
            raise ReasonerError("config", f"OpenRouter {resp.status_code}", http_status=resp.status_code)
        payload = resp.json()
        try:
            text = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ReasonerError("transient", "OpenRouter returned no message") from exc
        usage = payload.get("usage") or {}
        return Completion(
            text=text,
            model_returned=payload.get("model") or self.model,
            latency_ms=latency,
            prompt_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
