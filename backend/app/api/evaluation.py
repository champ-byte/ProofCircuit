"""Evaluation results (PRD 15.2). Honest placeholder until the M7 harness runs: it reports the
planned corpus and split with zero executed cases and never fabricates metrics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_settings_dep
from app.config import Settings

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

CATEGORIES = [
    "missing_receipt",
    "wrong_order_id",
    "conflicting_delivery_dates",
    "expired_deadline",
    "upload_pod_rejection",
]


@router.get("/results")
def results(settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    planned = settings.evaluation_target_cases
    return {
        "status": "not_run",
        "planned": planned,
        "executed": 0,
        "not_run": planned,
        "label": f"{planned} planned · 0 executed · {planned} not run",
        "categories": [{"category": c, "planned": planned // len(CATEGORIES), "executed": 0} for c in CATEGORIES],
        "split": {
            "development": 30,
            "held_out": 10,
            "first_pass": settings.evaluation_smoke_cases,
            "first_pass_selection": "one development and one held-out variant per category",
        },
        "mode": None,
        "metrics": None,
        "note": "The synthetic corpus and harness arrive in M7. No results are claimed until cases are executed.",
    }
