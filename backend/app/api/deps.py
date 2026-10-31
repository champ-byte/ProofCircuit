"""Request dependencies: DB session and server-issued demo identity.

Demo sessions are a localhost demo mechanism (DEMO_MODE), not production authentication.
The merchant scope always comes from the signed token, never from the browser or model.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import DemoUser
from app.db.session import session_factory
from app.domain.clock import get_clock

SESSION_TTL = timedelta(hours=12)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db() -> Iterator[Session]:
    """Request session that commits on success. Always declare it as `Depends(get_db, scope="function")`:
    the default "request" scope would commit only after the response is sent, so a client acting on
    the response could read stale state and a failed commit would hide behind a 2xx."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@dataclass(frozen=True)
class Identity:
    user_id: str
    merchant_id: str
    role: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(settings: Settings, identity: Identity) -> str:
    exp = int((get_clock().now() + SESSION_TTL).timestamp())
    payload = _b64(
        json.dumps({"u": identity.user_id, "m": identity.merchant_id, "r": identity.role, "e": exp}).encode()
    )
    sig = hmac.new(settings.session_secret.get_secret_value().encode(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64(sig)}"


def verify_token(settings: Settings, token: str) -> Identity | None:
    try:
        payload, sig = token.split(".", 1)
        expected = hmac.new(
            settings.session_secret.get_secret_value().encode(), payload.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _unb64(sig)):
            return None
        data = json.loads(_unb64(payload))
        if int(data["e"]) <= int(get_clock().now().timestamp()):
            return None
        return Identity(user_id=data["u"], merchant_id=data["m"], role=data["r"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def current_identity(
    request: Request, settings: Settings = Depends(get_settings_dep), db: Session = Depends(get_db, scope="function")
) -> Identity:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "demo session required")
    identity = verify_token(settings, header[7:].strip())
    if identity is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired demo session")
    # The signed claims must still match a stored user (e.g. not invalidated by a demo reset).
    user = db.get(DemoUser, identity.user_id)
    if user is None or user.merchant_id != identity.merchant_id or user.role != identity.role:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "demo session no longer valid")
    return identity


def require_role(*roles: str):  # type: ignore[no-untyped-def]
    def checker(identity: Identity = Depends(current_identity)) -> Identity:
        if identity.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role: {', '.join(roles)}")
        return identity

    return checker
