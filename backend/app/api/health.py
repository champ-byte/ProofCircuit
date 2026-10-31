from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_settings_dep
from app.config import Settings
from app.providers.readiness import provider_report

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(
    settings: Settings = Depends(get_settings_dep), db: Session = Depends(get_db, scope="function")
) -> dict[str, Any]:
    db.execute(text("SELECT 1"))
    report = provider_report(settings)
    return {
        "status": "ok",
        "database": "ok",
        "app_env": settings.app_env,
        "demo_mode": settings.demo_mode,
        "synthetic_data": True,
        "paytm_mode": settings.paytm_mode,
        "reasoning_mode": report["reasoning_mode"],
    }


@router.get("/providers")
def providers(settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    return provider_report(settings)
