"""App-side DisputeProvider adapter for the Paytm-shaped simulator.

It speaks the documented HTTP contracts (JSON Status, multipart Action) to the in-process
simulator through an ASGI transport, so the real request/response encoding is exercised.
`PAYTM_MODE` can only be `simulator`; no live adapter exists in this release.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.config import Settings
from app.domain.clock import get_clock
from app.domain.enums import ProviderDisputeStatus, normalize_dispute_status
from app.simulator.signing import sign_body, sign_params

log = logging.getLogger(__name__)

ActionKind = Literal["ack", "duplicate", "retryable", "definitive", "unknown"]


@dataclass
class StatusRead:
    ok: bool
    retryable: bool
    code: str | None
    status_raw: str | None = None
    status: ProviderDisputeStatus = ProviderDisputeStatus.UNKNOWN
    body: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ActionResult:
    kind: ActionKind
    code: str | None
    result_status: str | None
    raw: dict[str, Any] | None
    http_status: int | None
    error: str | None = None


@dataclass
class UploadPart:
    filename: str
    data: bytes
    mime: str


class PaytmSimulatorAdapter:
    def __init__(self, app: Any, settings: Settings, timeout: float = 10.0) -> None:
        self._app = app
        self._settings = settings
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self._app), base_url="http://simulator.internal", timeout=self._timeout
        )

    @property
    def _secret(self) -> str:
        return self._settings.demo_webhook_secret.get_secret_value()

    def _timestamp(self, ms: bool = False) -> str:
        now = get_clock().now().timestamp()
        return str(int(now * 1000)) if ms else str(int(now))

    async def get_status(self, mid: str, dispute_id: str) -> StatusRead:
        body = {"mid": mid, "disputeId": dispute_id}
        head = {
            "requestTimestamp": self._timestamp(),
            "clientId": "proofcircuit",
            "tokenType": "CHECKSUM",
            "signature": sign_body(self._secret, body),
        }
        try:
            async with self._client() as client:
                resp = await client.post("/api/simulator/v1/dispute/status", json={"head": head, "body": body})
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return StatusRead(False, True, None, error=f"status read failed: {type(exc).__name__}")
        rbody = data.get("body", {}) if isinstance(data, dict) else {}
        info = rbody.get("resultInfo", {})
        code = info.get("resultCodeId")
        if code == "1001" and info.get("resultCode") == "SUCCESS":
            raw = rbody.get("disputeStatus")
            return StatusRead(True, False, code, raw, normalize_dispute_status(raw), rbody)
        return StatusRead(False, code == "5001", code, body=rbody, error=f"{code} {info.get('resultCode')}")

    async def act(
        self,
        *,
        action: str,
        mid: str,
        dispute_id: str,
        order_status: str | None = None,
        comments: str | None = None,
        files: list[UploadPart] | None = None,
        timestamp_ms: bool = False,
    ) -> ActionResult:
        params = {
            "mid": mid,
            "disputeId": dispute_id,
            "action": action,
            "requestTimestamp": self._timestamp(timestamp_ms),
            "clientId": "proofcircuit",
            "tokenType": "CHECKSUM",
        }
        if order_status:
            params["orderStatus"] = order_status
        if comments:
            params["comments"] = comments
        params["signature"] = sign_params(self._secret, params)
        multipart = [("files", (f.filename, f.data, f.mime)) for f in files or []]
        try:
            async with self._client() as client:
                resp = await client.post("/api/simulator/v1/dispute/action", data=params, files=multipart or None)
        except httpx.HTTPError as exc:
            return ActionResult("unknown", None, None, None, None, f"no response: {type(exc).__name__}")
        if resp.status_code != 200:
            return ActionResult(
                "unknown", None, None, None, resp.status_code, f"HTTP {resp.status_code}, no business response"
            )
        try:
            data = resp.json()
            info = data["body"]["resultInfo"]
        except (ValueError, KeyError, TypeError):
            return ActionResult("unknown", None, None, None, resp.status_code, "unparseable response")
        code, rcode, rstatus = info.get("resultCodeId"), info.get("resultCode"), info.get("resultStatus")
        if code == "1001" and rcode == "UPLOADED_SUCCESS" and rstatus in ("S", "A"):
            kind: ActionKind = "ack"
        elif code == "1003" and rcode == "DISPUTE_ACCEPTED" and rstatus == "S":
            kind = "ack"
        elif code == "4006":
            kind = "duplicate"
        elif code == "4010":
            kind = "retryable"
        elif code == "5001":
            kind = "unknown"
        elif code and code.startswith("4") and rstatus == "F":
            kind = "definitive"
        else:
            kind = "unknown"  # inconsistent tuple: reconcile, never assume
        return ActionResult(kind, code, rstatus, data, resp.status_code, None if kind == "ack" else f"{code} {rcode}")

    async def list_receipts(self, mid: str, dispute_id: str) -> list[dict[str, Any]] | None:
        params = {"mid": mid, "disputeId": dispute_id}
        try:
            async with self._client() as client:
                resp = await client.get(
                    "/api/simulator/receipts",
                    params=params,
                    headers={"X-Demo-Signature": sign_params(self._secret, params)},
                )
            if resp.status_code != 200:
                return None
            return list(resp.json())
        except (httpx.HTTPError, ValueError):
            return None


def get_provider(app: Any) -> PaytmSimulatorAdapter:
    provider = getattr(app.state, "dispute_provider", None)
    if provider is None:
        provider = app.state.dispute_provider = PaytmSimulatorAdapter(app, app.state.settings)
    return provider
