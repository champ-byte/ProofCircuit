"""Provider interfaces (PRD Section 12). Core domain code must not import vendor SDKs."""

from __future__ import annotations

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


class AgentContext(BaseModel):
    case_id: str
    case_version: int
    summary: dict[str, Any]
    allowed_actions: list[str]


class ProposalResult(BaseModel):
    action: ProposedAction
    provider: str
    model: str | None  # model the provider actually reported
    latency_ms: int
    attempts: int


class Reasoner(Protocol):
    name: str

    async def propose(self, context: AgentContext) -> ProposalResult: ...
