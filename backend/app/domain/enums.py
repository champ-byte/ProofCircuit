"""Workflow, provider and flag enums. Kept separate on purpose (PRD Section 10.1)."""

from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    NEW = "NEW"
    COLLECTING = "COLLECTING"
    WAITING_FOR_EVIDENCE = "WAITING_FOR_EVIDENCE"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTING = "SUBMITTING"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class ProviderDisputeStatus(StrEnum):
    """Normalized simulator dispute status. Raw strings are always stored alongside."""

    NEW = "NEW"
    POD_UPLOAD = "POD_UPLOAD"
    POD_REJECT = "POD_REJECT"
    WON = "WON"
    LOST = "LOST"
    UNKNOWN = "UNKNOWN"


class OperationalFlag(StrEnum):
    DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    OCR_REQUIRED = "OCR_REQUIRED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    AGENT_LIMIT_REACHED = "AGENT_LIMIT_REACHED"


class DisputeReason(StrEnum):
    GOODS_NOT_RECEIVED = "goods_not_received"
    REQUIRES_REVIEW = "requires_review"


class Role(StrEnum):
    OWNER = "owner"
    STAFF = "staff"
    REVIEWER = "reviewer"
    OPERATOR = "operator"


class PendingStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReasoningMode(StrEnum):
    LIVE = "live"
    MANUAL = "manual"
    FIXTURE_REPLAY = "fixture_replay"


# Documented aliases only (PRD 11.2.3). Do not guess more.
_STATUS_ALIASES: dict[str, ProviderDisputeStatus] = {
    "NEW": ProviderDisputeStatus.NEW,
    "POD_UPLOAD": ProviderDisputeStatus.POD_UPLOAD,
    "POD UPLOADED": ProviderDisputeStatus.POD_UPLOAD,
    "POD_REJECT": ProviderDisputeStatus.POD_REJECT,
    "WON": ProviderDisputeStatus.WON,
    "LOST": ProviderDisputeStatus.LOST,
}


def normalize_dispute_status(raw: str | None) -> ProviderDisputeStatus:
    if raw is None:
        return ProviderDisputeStatus.UNKNOWN
    return _STATUS_ALIASES.get(raw.strip(), ProviderDisputeStatus.UNKNOWN)
