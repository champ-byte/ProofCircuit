from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Identity, get_db, get_settings_dep, issue_token, require_role
from app.config import Settings
from app.db.models import DemoUser, Merchant
from app.domain.clock import get_clock
from app.services.audit import audit
from app.services.seed import reset_demo, seed_demo

router = APIRouter(prefix="/api/demo", tags=["demo"])


def _require_demo_mode(settings: Settings = Depends(get_settings_dep)) -> Settings:
    if not settings.demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "demo endpoints are disabled")
    return settings


class SessionRequest(BaseModel):
    mid: str
    handle: str


@router.get("/users")
def list_demo_users(
    _: Settings = Depends(_require_demo_mode), db: Session = Depends(get_db, scope="function")
) -> list[dict[str, Any]]:
    rows = db.execute(select(DemoUser, Merchant).join(Merchant, DemoUser.merchant_id == Merchant.id)).all()
    return [
        {
            "mid": m.mid,
            "merchant_name": m.name,
            "handle": u.handle,
            "display_name": u.display_name,
            "role": u.role,
            "locale": u.locale,
        }
        for u, m in rows
    ]


@router.post("/session")
def create_session(
    req: SessionRequest,
    settings: Settings = Depends(_require_demo_mode),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    row = db.execute(
        select(DemoUser, Merchant)
        .join(Merchant, DemoUser.merchant_id == Merchant.id)
        .where(Merchant.mid == req.mid, DemoUser.handle == req.handle)
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown demo user")
    user, merchant = row
    identity = Identity(user_id=user.id, merchant_id=merchant.id, role=user.role)
    return {
        "token": issue_token(settings, identity),
        "user": {"handle": user.handle, "display_name": user.display_name, "role": user.role, "locale": user.locale},
        "merchant": {"name": merchant.name, "mid": merchant.mid},
        "demo_only": True,
    }


class ResetRequest(BaseModel):
    confirm: bool = False


@router.post("/seed")
def seed(
    settings: Settings = Depends(_require_demo_mode),
    identity: Identity = Depends(require_role("operator")),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    case = seed_demo(db, settings, get_clock())
    return {"case_id": case.id, "dispute_id": case.external_dispute_id}


@router.post("/reset")
def reset(
    req: ResetRequest,
    settings: Settings = Depends(_require_demo_mode),
    identity: Identity = Depends(require_role("operator")),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    if not req.confirm:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "reset requires confirm=true")
    reset_demo(db, settings)
    db.flush()
    case = seed_demo(db, settings, get_clock())
    audit(
        db,
        event_type="demo.reset",
        summary="Demo data reset by operator.",
        actor_type="user",
        actor_id=identity.user_id,
        data={},
    )
    # The operator's session no longer resolves (users were recreated); the client must re-login.
    return {"reset": True, "case_id": case.id, "session_invalidated": True}
