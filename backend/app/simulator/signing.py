"""Demo signatures: HMAC-SHA256 with a local development secret.

Field names follow Paytm's documents, but this is NOT Paytm's CHECKSUM algorithm and a
signature produced here is not a valid Paytm signature (PRD Section 11.1).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical_json(body: Any) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_body(secret: str, body: dict[str, Any]) -> str:
    """Signature over the JSON-stringified body (Status API, S2S callback)."""
    return hmac.new(secret.encode(), canonical_json(body).encode(), hashlib.sha256).hexdigest()


def sign_params(secret: str, params: dict[str, str]) -> str:
    """Signature over sorted form parameters, excluding `signature` and file parts (Action API)."""
    text = "|".join(f"{k}={params[k]}" for k in sorted(params) if k != "signature")
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()


def verify(expected: str, provided: str | None) -> bool:
    return bool(provided) and hmac.compare_digest(expected, provided or "")
