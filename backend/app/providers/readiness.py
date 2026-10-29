"""Provider readiness report for /api/health and /api/providers. Never exposes secrets.

M0 performs no network calls: a configured provider is reported as `configured_untested`
until the M3 live smoke test passes. Only `ready` providers may drive a live agent run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Literal

from app.config import Settings
from app.domain.clock import get_clock

Status = Literal["ready", "configured_untested", "unconfigured", "disabled", "failed", "not_implemented"]


def record_smoke_result(
    provider: str,
    ok: bool,
    detail: str,
    *,
    model_requested: str = "",
    model_returned: str | None = None,
    capabilities: dict[str, object] | None = None,
) -> None:
    """Persist a live smoke-test outcome (survives restarts; expires after SMOKE_CHECK_TTL_HOURS)."""
    from app.db.models import ProviderCheck
    from app.db.session import session_scope

    with session_scope() as session:
        session.add(
            ProviderCheck(
                provider=provider,
                model_requested=model_requested,
                model_returned=model_returned,
                ok=ok,
                detail=detail,
                capabilities=capabilities or {},
            )
        )


def clear_smoke_results() -> None:
    """Kept for test isolation; persisted checks live in each test's own database."""


def latest_check(provider: str, model: str | None, ttl_hours: int) -> object | None:
    from sqlalchemy import select

    from app.db.models import ProviderCheck
    from app.db.session import session_scope

    try:
        with session_scope() as session:
            row = session.scalar(
                select(ProviderCheck)
                .where(ProviderCheck.provider == provider, ProviderCheck.model_requested == (model or ""))
                .order_by(ProviderCheck.checked_at.desc())
            )
            if row is None or row.checked_at < get_clock().now() - timedelta(hours=ttl_hours):
                return None
            session.expunge(row)
            return row
    except RuntimeError:  # engine not initialised (e.g. CLI before init-db)
        return None


@dataclass
class ProviderReadiness:
    name: str
    role: str  # primary | fallback | integration
    status: Status
    model: str | None = None
    detail: str = ""
    notes: list[str] = field(default_factory=list)


def _reasoner_readiness(name: str, role: str, settings: Settings) -> ProviderReadiness:
    if name == "gemini":
        model = settings.gemini_model
        configured = settings.gemini_api_key is not None and bool(model)
        missing = "GEMINI_API_KEY is not set"
        notes = ["Free tier: low daily request limits; data may be used by Google. Synthetic data only."]
    elif name == "openrouter":
        model = settings.openrouter_model
        configured = settings.openrouter_api_key is not None and bool(model)
        missing = "OPENROUTER_API_KEY is not set"
        notes = [f"data_collection={settings.openrouter_data_collection}", f"allow_paid={settings.allow_paid_models}"]
    elif name == "ollama":
        return ProviderReadiness(
            name,
            role,
            "not_implemented",
            settings.ollama_model or None,
            "Optional local Gemma adapter is M8; fallback unavailable.",
        )
    else:  # manual
        return ProviderReadiness(name, role, "disabled", None, "Manual operation; no model inference.")

    if role == "fallback" and not settings.fallback_enabled:
        return ProviderReadiness(name, role, "disabled", model, "FALLBACK_ENABLED=false", notes)
    if not configured:
        return ProviderReadiness(name, role, "unconfigured", model, missing, notes)
    check = latest_check(name, model, settings.smoke_check_ttl_hours)
    if check is None:
        return ProviderReadiness(
            name, role, "configured_untested", model, "Live smoke test not run (or expired).", notes
        )
    returned = getattr(check, "model_returned", None) or model
    detail = f"{getattr(check, 'detail', '')} (checked {check.checked_at.isoformat()})"
    return ProviderReadiness(name, role, "ready" if check.ok else "failed", returned, detail, notes)


def provider_report(settings: Settings) -> dict[str, object]:
    primary = _reasoner_readiness(settings.reasoner_provider, "primary", settings)
    fallback = (
        _reasoner_readiness(settings.fallback_provider, "fallback", settings)
        if settings.fallback_provider != "none"
        else None
    )
    live = next((p for p in (primary, fallback) if p is not None and p.status == "ready"), None)
    reasoning_mode = {
        "mode": "live" if live else "manual",
        "label": f"{live.name.capitalize()} — {live.model}" if live else "Manual",
    }

    reminders_ready = bool(
        settings.reminders_enabled
        and settings.n8n_reminder_webhook_url
        and settings.n8n_webhook_token
        and settings.n8n_service_token
    )
    integrations = [
        ProviderReadiness("paytm", "integration", "ready", None, "Local Paytm-shaped simulator (no live hosts)."),
        ProviderReadiness("messaging", "integration", "ready", None, "Local in-app staff inbox; no WhatsApp."),
        ProviderReadiness("memory", "integration", "ready", None, "SQL case-scoped retrieval."),
        ProviderReadiness(
            "speech",
            "integration",
            "disabled" if settings.speech_provider == "disabled" else "not_implemented",
            None,
            f"SPEECH_PROVIDER={settings.speech_provider}",
        ),
        ProviderReadiness("ocr", "integration", "disabled", None, "Image-only evidence returns OCR_REQUIRED."),
        ProviderReadiness(
            "n8n_reminders",
            "integration",
            "not_implemented" if reminders_ready else "disabled",
            None,
            "Reminders require REMINDERS_ENABLED, webhook URL and both tokens.",
        ),
    ]
    return {
        "reasoning_mode": reasoning_mode,
        "reasoners": [asdict(p) for p in (primary, fallback) if p is not None],
        "integrations": [asdict(p) for p in integrations],
        "synthetic_data": True,
        "paytm_mode": settings.paytm_mode,
        "usage": _usage(settings),
    }


def _usage(settings: Settings) -> dict[str, object]:
    try:
        from app.services.reasoner_accounting import calls_last_24h

        used: int | None = calls_last_24h()
    except RuntimeError:  # engine not initialised
        used = None
    return {
        "calls_24h": used,
        "cap": settings.reasoner_daily_call_cap,
        "min_interval_s": settings.reasoner_min_interval_seconds,
    }
