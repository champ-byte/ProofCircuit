"""Persisted inference accounting: daily cap, pacing and an audit trail of model calls."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.config import Settings
from app.db.models import ReasonerCall
from app.db.session import session_scope
from app.domain.clock import get_clock


class CallCapReached(Exception):
    pass


def calls_last_24h(provider: str | None = None) -> int:
    since = get_clock().now() - timedelta(hours=24)
    with session_scope() as session:
        stmt = select(func.count()).select_from(ReasonerCall).where(ReasonerCall.created_at >= since)
        if provider:
            stmt = stmt.where(ReasonerCall.provider == provider)
        return int(session.scalar(stmt) or 0)


def last_call_at(provider: str) -> datetime | None:
    with session_scope() as session:
        return session.scalar(select(func.max(ReasonerCall.created_at)).where(ReasonerCall.provider == provider))


def check_cap(settings: Settings, provider: str) -> None:
    used = calls_last_24h(provider)
    if used >= settings.reasoner_daily_call_cap:
        raise CallCapReached(f"{provider}: daily call cap reached ({used}/{settings.reasoner_daily_call_cap} in 24h)")


def pacing_delay(settings: Settings, provider: str) -> float:
    last = last_call_at(provider)
    if last is None:
        return 0.0
    elapsed = (get_clock().now() - last).total_seconds()
    return max(0.0, settings.reasoner_min_interval_seconds - elapsed)


def record_call(
    *,
    provider: str,
    model_requested: str,
    model_returned: str | None,
    purpose: str,
    status: str,
    latency_ms: int,
    http_status: int | None = None,
    error: str | None = None,
    prompt_tokens: int | None = None,
    output_tokens: int | None = None,
    run_id: str | None = None,
    case_id: str | None = None,
) -> None:
    with session_scope() as session:
        session.add(
            ReasonerCall(
                provider=provider,
                model_requested=model_requested,
                model_returned=model_returned,
                purpose=purpose,
                status=status,
                latency_ms=latency_ms,
                http_status=http_status,
                error=(error or "")[:500] or None,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                run_id=run_id,
                case_id=case_id,
            )
        )
