"""Submission-intent identity shared by the app and the simulator.

The app computes it from the pack it intends to send; the simulator computes it independently
from the bytes and fields it actually received. Agreement of the two is what lets a receipt
verify *this exact pack* (PRD 8.6). Hashes identify content; they do not prove authenticity.
"""

from __future__ import annotations

import hashlib
import json


def intent_digest(
    *, mid: str, dispute_id: str, action: str, order_status: str | None, comments: str | None, file_sha256s: list[str]
) -> str:
    payload = {
        "mid": mid,
        "disputeId": dispute_id,
        "action": action,
        "orderStatus": order_status or "",
        "comments": comments or "",
        "files": list(file_sha256s),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
