"""Reasoner selection, fallback and quota enforcement (PRD 6.2, 12).

Order: primary, then the fallback only when FALLBACK_ENABLED and its live smoke test passed.
Fallback repeats *inference only*; tool writes are never retried here. Every attempt is
recorded; the daily cap and pacing are checked before any request is made.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import Settings
from app.providers.base import Completion, Reasoner, ReasonerError
from app.providers.readiness import latest_check
from app.services.reasoner_accounting import CallCapReached, check_cap, pacing_delay, record_call


class ReasonerUnavailable(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons) or "no reasoner available")
        self.reasons = reasons


def build_reasoner(app: Any, name: str) -> Reasoner:
    overrides: dict[str, Reasoner] = getattr(app.state, "reasoner_overrides", {}) or {}
    if name in overrides:
        return overrides[name]
    settings: Settings = app.state.settings
    if name == "gemini":
        from app.providers.gemini import GeminiReasoner

        check = latest_check("gemini", settings.gemini_model, settings.smoke_check_ttl_hours)
        return GeminiReasoner(settings, capabilities=getattr(check, "capabilities", None))
    if name == "openrouter":
        from app.providers.openrouter import OpenRouterReasoner

        return OpenRouterReasoner(settings)
    if name == "replay":
        from app.providers.replay import ReplayReasoner

        return ReplayReasoner()
    raise ReasonerError("config", f"reasoner {name!r} is not implemented (optional local Gemma is M8)")


def ready_candidates(settings: Settings) -> list[str]:
    """Providers whose readiness is `ready`: configured, and a fresh passing smoke test for the current model."""
    from app.providers.readiness import _reasoner_readiness

    names = []
    for name, role in ((settings.reasoner_provider, "primary"), (settings.fallback_provider, "fallback")):
        if name in ("manual", "none"):
            continue
        if _reasoner_readiness(name, role, settings).status == "ready":
            names.append(name)
    return names


async def call_once(
    app: Any,
    reasoner: Reasoner,
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    purpose: str,
    run_id: str | None,
    case_id: str | None,
) -> Completion:
    """One provider, bounded: cap check, pacing, at most one retry for a 429 within the wait bound, and up to
    REASONER_TRANSIENT_RETRIES retries with growing backoff for transient errors (5xx such as a provider's
    "high demand" 503, or time-outs)."""
    settings: Settings = app.state.settings
    attempts = 1 + settings.reasoner_transient_retries
    for attempt in range(attempts):
        check_cap(settings, reasoner.name)
        delay = pacing_delay(settings, reasoner.name)
        if delay:
            await asyncio.sleep(delay)
        try:
            try:
                # Hard total deadline per call. The HTTP client's timeout limits each read, not the whole
                # request; a stalled response once held a live run for 38 minutes (EVAL-037).
                completion = await asyncio.wait_for(
                    reasoner.complete(system=system, user=user, schema=schema),
                    timeout=settings.model_timeout_seconds,
                )
            except TimeoutError as exc:
                raise ReasonerError(
                    "timeout", f"{reasoner.name} gave no complete response within {settings.model_timeout_seconds}s"
                ) from exc
        except ReasonerError as exc:
            record_call(
                provider=reasoner.name,
                model_requested=reasoner.model,
                model_returned=None,
                purpose=purpose,
                status=exc.kind,
                latency_ms=0,
                http_status=exc.http_status,
                error=str(exc),
                run_id=run_id,
                case_id=case_id,
            )
            if exc.kind == "rate_limited":
                retry = (
                    attempt == 0
                    and exc.retry_after is not None
                    and exc.retry_after <= settings.reasoner_rate_limit_max_wait_seconds
                )
                wait = exc.retry_after or 0
            elif exc.kind in ("transient", "timeout"):
                retry = attempt < attempts - 1
                wait = settings.reasoner_transient_backoff_seconds * (3**attempt)  # 5 s, then 15 s by default
            else:
                retry, wait = False, 0
            if not retry:
                raise
            await asyncio.sleep(wait)
            continue
        record_call(
            provider=reasoner.name,
            model_requested=reasoner.model,
            model_returned=completion.model_returned,
            purpose=purpose,
            status="ok",
            latency_ms=completion.latency_ms,
            prompt_tokens=completion.prompt_tokens,
            output_tokens=completion.output_tokens,
            run_id=run_id,
            case_id=case_id,
        )
        return completion
    raise ReasonerError("transient", "unreachable")  # pragma: no cover


async def complete_routed(
    app: Any,
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    purpose: str,
    run_id: str | None,
    case_id: str | None,
) -> tuple[Completion, Reasoner, list[str]]:
    """Returns (completion, reasoner used, notes about skipped/failed providers)."""
    settings: Settings = app.state.settings
    notes: list[str] = []
    candidates = ready_candidates(settings)
    if not candidates:
        raise ReasonerUnavailable(["no reasoner has passed a live smoke test"])
    for name in candidates:
        try:
            reasoner = build_reasoner(app, name)
            completion = await call_once(
                app, reasoner, system=system, user=user, schema=schema, purpose=purpose, run_id=run_id, case_id=case_id
            )
            return completion, reasoner, notes
        except CallCapReached as exc:
            notes.append(str(exc))
        except ReasonerError as exc:
            notes.append(f"{name}: {exc.kind}: {exc}")
    raise ReasonerUnavailable(notes)
