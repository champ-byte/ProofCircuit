"""Provider-facing action schema and parser.

Strict structured-output modes need a closed schema, so the provider sees `arguments` as the
union of every tool's argument fields (all nullable, no extra keys). The backend then drops
nulls and re-validates against the specific tool's `ARG_MODELS` entry in the dispatcher.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.providers.base import AGENT_TOOLS, ProposedAction

ARGUMENT_FIELDS: dict[str, dict[str, Any]] = {
    "document_id": {"type": ["string", "null"], "description": "inspect_evidence: a document_id from the context"},
    "requirement_id": {"type": ["string", "null"], "enum": ["delivery_record", "invoice", "order_linkage", None]},
    "assignee_id": {"type": ["string", "null"], "description": "request_evidence: leave null (configured staff)"},
    "locale": {"type": ["string", "null"], "enum": ["en-IN", "hi-IN", "mr-IN", None]},
    "reason": {"type": ["string", "null"], "description": "request_human_review: snake_case reason code"},
    "question": {"type": ["string", "null"], "description": "request_human_review: question for the reviewer"},
    "pack_version": {"type": ["integer", "null"], "description": "submit_defense: null means latest pack"},
    "waiting_for": {"type": ["string", "null"], "enum": ["staff_evidence", "review", "provider", None]},
}

ACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(AGENT_TOOLS)},
        "arguments": {
            "type": "object",
            "properties": ARGUMENT_FIELDS,
            "required": list(ARGUMENT_FIELDS),
            "additionalProperties": False,
        },
        "reason": {"type": "string", "description": "One or two sentences shown to the merchant team."},
        "source_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["action", "arguments", "reason", "source_ids"],
    "additionalProperties": False,
}


def to_openapi_subset(schema: dict[str, Any]) -> dict[str, Any]:
    """JSON Schema -> Gemini `responseSchema` (OpenAPI subset): nullable flags, upper-case types."""
    out: dict[str, Any] = {}
    s = copy.deepcopy(schema)
    t = s.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        out["type"] = non_null[0].upper()
        if "null" in t:
            out["nullable"] = True
    elif isinstance(t, str):
        out["type"] = t.upper()
    if "enum" in s:
        out["enum"] = [v for v in s["enum"] if v is not None]
    if "description" in s:
        out["description"] = s["description"]
    if "properties" in s:
        out["properties"] = {k: to_openapi_subset(v) for k, v in s["properties"].items()}
        out["propertyOrdering"] = list(s["properties"])
    if "required" in s:
        out["required"] = s["required"]
    if "items" in s:
        out["items"] = to_openapi_subset(s["items"])
    return out


class _ProviderAction(BaseModel):
    model_config = {"extra": "forbid"}
    action: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(max_length=500)
    source_ids: list[str] = Field(default_factory=list)


class InvalidModelOutput(ValueError):
    pass


def parse_action(text: str) -> ProposedAction:
    """Parse and validate one provider response. Raises InvalidModelOutput with a repair hint."""
    cleaned = text.strip()
    if cleaned.startswith("```"):  # tolerate a fenced block, nothing else
        cleaned = cleaned.strip("`")
        cleaned = cleaned[cleaned.find("{") :]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise InvalidModelOutput(f"response is not valid JSON ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise InvalidModelOutput("response must be one JSON object")
    try:
        raw = _ProviderAction.model_validate(data)
    except ValidationError as exc:
        raise InvalidModelOutput(f"response does not match the action schema: {exc.errors(include_url=False)}") from exc
    unknown_args = set(raw.arguments) - set(ARGUMENT_FIELDS)
    if unknown_args:
        raise InvalidModelOutput(f"unknown argument fields: {sorted(unknown_args)}")
    try:
        return ProposedAction(
            action=raw.action,  # type: ignore[arg-type]  # Literal check happens here
            arguments={k: v for k, v in raw.arguments.items() if v is not None},
            reason=raw.reason,
            source_ids=raw.source_ids,
        )
    except ValidationError as exc:
        raise InvalidModelOutput(f"action must be one of {list(AGENT_TOOLS)}") from exc
