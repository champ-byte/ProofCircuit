"""Evaluation (PRD 15.2): exported results and the demo-only corpus case seeder.

Results come only from files written by the evaluator (`app.cli evaluate`); with none, the page
honestly reports zero executed cases and no metrics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Identity, get_db, get_settings_dep, require_role
from app.config import REPO_ROOT, Settings
from app.db.models import Merchant
from app.domain.clock import get_clock
from app.evaluation import corpus
from app.evaluation.seed import SeedError, seed_eval_case

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

CATEGORIES = list(corpus.CATEGORIES)
RESULTS_DIR = REPO_ROOT / "docs" / "evaluation"


def latest_results(results_dir: Path | None = None) -> dict[str, Any] | None:
    files = sorted((results_dir or RESULTS_DIR).glob("results-*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


@router.get("/results")
def results(settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    planned = settings.evaluation_target_cases
    split = {
        "development": 30,
        "held_out": 10,
        "first_pass": settings.evaluation_smoke_cases,
        "first_pass_selection": "one development and one held-out variant per category",
    }
    exported = latest_results()
    if exported is not None:
        return {**exported, "planned": planned, "split": split}
    return {
        "status": "not_run",
        "planned": planned,
        "executed": 0,
        "not_run": planned,
        "label": f"{planned} planned · 0 executed · {planned} not run",
        "categories": [{"category": c, "planned": planned // len(CATEGORIES), "executed": 0} for c in CATEGORIES],
        "split": split,
        "mode": None,
        "metrics": None,
        "cases": [],
        "note": "No evaluation results have been exported yet. No results are claimed until cases are executed.",
    }


class SeedRequest(BaseModel):
    corpus_case: str = Field(pattern=r"^EVAL-\d{3}$")
    run_tag: str = Field(pattern=r"^[A-Za-z0-9]{1,16}$")


@router.post("/cases", status_code=status.HTTP_201_CREATED)
def seed_case(
    req: SeedRequest,
    identity: Identity = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    """Demo-only harness control: open one corpus case for the operator's own merchant."""
    if not settings.demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not available outside DEMO_MODE")
    spec = next((c for c in corpus.load("all") if c["case_id"] == req.corpus_case), None)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown corpus case")
    merchant = db.get(Merchant, identity.merchant_id)
    assert merchant is not None
    try:
        case, order_date = seed_eval_case(db, settings, get_clock(), merchant, spec, req.run_tag)
    except SeedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return {
        "case_id": case.id,
        "dispute_id": case.external_dispute_id,
        "order_date": order_date.isoformat(),
        "deadline_utc": case.deadline_utc.isoformat(),
    }
