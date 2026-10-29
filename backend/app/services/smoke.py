"""Live reasoner smoke test (PRD 6.2): one synthetic context must yield a schema-valid, allowed
action. For Gemini it also discovers which structured-output field and thinking control the
model accepts, trying the cheapest-to-reject variants in order. Results are persisted."""

from __future__ import annotations

import json
from typing import Any

from app.agent.prompt import SYSTEM_PROMPT, user_prompt
from app.agent.schema import ACTION_JSON_SCHEMA, InvalidModelOutput, parse_action
from app.providers.base import ReasonerError
from app.providers.readiness import record_smoke_result
from app.providers.router import build_reasoner, call_once
from app.services.reasoner_accounting import CallCapReached

SMOKE_CONTEXT: dict[str, Any] = {
    "case_id": "smoke-test",
    "dispute_id": "DSP-SMOKE",
    "order_id": "ORD-SMOKE-1",
    "reason": "goods_not_received",
    "workflow_state": "COLLECTING",
    "provider_status": "NEW",
    "seconds_to_deadline": 172800,
    "checklist": [
        {"requirement_id": "order_linkage", "status": "supported", "explanation": "Invoice links the transaction."},
        {"requirement_id": "invoice", "status": "supported", "explanation": "Invoice matches the amount."},
        {"requirement_id": "delivery_record", "status": "missing", "explanation": "No delivery record."},
    ],
    "open_findings": [],
    "staff_tasks": [],
    "evidence_ready": False,
    "latest_pack_current": False,
}
GEMINI_VARIANTS = [
    {"schema_field": "responseJsonSchema", "thinking_level": True},
    {"schema_field": "responseJsonSchema", "thinking_level": False},
    {"schema_field": "responseSchema", "thinking_level": True},
    {"schema_field": "responseSchema", "thinking_level": False},
]


async def smoke_test(app: Any, provider: str) -> dict[str, Any]:
    settings = app.state.settings
    prompt = user_prompt(SMOKE_CONTEXT, {"verified_facts": [], "staff_messages": []}, [], None)
    variants = GEMINI_VARIANTS if provider == "gemini" else [{}]
    attempts: list[str] = []
    model_requested = {"gemini": settings.gemini_model, "openrouter": settings.openrouter_model}.get(provider, provider)
    for caps in variants:
        try:
            reasoner = build_reasoner(app, provider)
            if caps and hasattr(reasoner, "capabilities"):
                reasoner.capabilities = dict(caps)  # type: ignore[attr-defined]
            if provider == "openrouter" and hasattr(reasoner, "preflight"):
                await reasoner.preflight()  # type: ignore[attr-defined]
            completion = await call_once(
                app,
                reasoner,
                system=SYSTEM_PROMPT,
                user=prompt,
                schema=ACTION_JSON_SCHEMA,
                purpose="smoke",
                run_id=None,
                case_id=None,
            )
        except CallCapReached as exc:
            return {"ok": False, "provider": provider, "detail": str(exc), "attempts": attempts}
        except ReasonerError as exc:
            attempts.append(f"{json.dumps(caps)} -> {exc.kind}: {exc}")
            if exc.kind == "config" and exc.http_status == 400:
                continue  # try the next request variant
            break
        try:
            action = parse_action(completion.text)
        except InvalidModelOutput as exc:
            attempts.append(f"{json.dumps(caps)} -> invalid output: {exc}")
            break
        detail = (
            f"returned {action.action!r} in {completion.latency_ms} ms; schema-valid; "
            f"variant {json.dumps(caps) if caps else 'default'}"
        )
        record_smoke_result(
            provider,
            True,
            detail,
            model_requested=model_requested,
            model_returned=completion.model_returned,
            capabilities=caps,
        )
        return {
            "ok": True,
            "provider": provider,
            "model_returned": completion.model_returned,
            "action": action.action,
            "reason": action.reason,
            "latency_ms": completion.latency_ms,
            "capabilities": caps,
            "attempts": attempts,
        }
    detail = "; ".join(attempts)[:1000] or "no attempt made"
    record_smoke_result(provider, False, detail, model_requested=model_requested)
    return {"ok": False, "provider": provider, "detail": detail, "attempts": attempts}
