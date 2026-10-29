"""ASGI entry point. Run with: uvicorn --factory app.main:create_app (one worker)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.api import cases, demo, evidence, health
from app.config import Settings, get_settings
from app.db.migrate import upgrade_to_head
from app.db.models import Merchant
from app.db.session import init_engine, session_scope
from app.domain.clock import get_clock
from app.services.recovery import startup_recovery_scan
from app.services.seed import seed_demo

log = logging.getLogger("proofcircuit")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.data_path.mkdir(parents=True, exist_ok=True)
        upgrade_to_head(settings.resolved_database_url)
        init_engine(settings)
        with session_scope() as session:
            if settings.demo_mode and session.scalar(select(Merchant.id).limit(1)) is None:
                case = seed_demo(session, settings, get_clock())
                log.info("Empty database in DEMO_MODE: seeded hero case %s", case.external_dispute_id)
        with session_scope() as session:
            counts = startup_recovery_scan(session)
            log.info("Startup recovery scan: %s", counts)
        yield

    app = FastAPI(title="ProofCircuit", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(demo.router)
    app.include_router(cases.router)
    app.include_router(evidence.router)
    return app
