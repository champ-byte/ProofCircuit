"""Provider interfaces (PRD Section 12). Core domain code must not import vendor SDKs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

AgentTool = Literal[
    "get_case_context",
    "inspect_evidence",
    "request_evidence",
    "validate_evidence",
    "request_human_review",
    "build_evidence_pack",
    "submit_defense",
    "get_submission_status",
    "wait_for_event",
]

# Deliberately absent: accept_dispute, issue_refund, arbitrary HTTP/SQL/shell, free messaging.
AGENT_TOOLS: tuple[str, ...] = AgentTool.__args__  # type: ignore[attr-defined]


class ProposedAction(BaseModel):
    """Provider-neutral JSON action. The same model generates the schema sent to providers."""

    action: AgentTool
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(max_length=500, description="Short rationale shown to users.")
    source_ids: list[str] = Field(default_factory=list)


class ReasonerError(Exception):
    """Inference failed. `kind` drives routing: rate_limited | config | transient | timeout | blocked."""

    def __init__(
        self, kind: str, message: str, *, http_status: int | None = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status
        self.retry_after = retry_after


@dataclass
class Completion:
    text: str  # model output text only; private reasoning/thought parts are dropped by adapters
    model_returned: str | None
    latency_ms: int
    prompt_tokens: int | None = None
    output_tokens: int | None = None


class Reasoner(Protocol):
    """Inference only. Adapters never execute tools; the loop validates and the backend authorizes."""

    name: str
    model: str
    mode: str  # live | fixture_replay

    async def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion: ...
