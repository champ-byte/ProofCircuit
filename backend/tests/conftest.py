from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.clock import Clock, FixedClock, set_clock
from app.main import create_app
from app.providers.readiness import clear_smoke_results

SEED_NOW = datetime(2030, 1, 2, 4, 30, tzinfo=UTC)  # 10:00 IST

PROVIDER_ENV = ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "SARVAM_API_KEY", "N8N_WEBHOOK_TOKEN", "N8N_SERVICE_TOKEN")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Contract tests must not depend on whatever keys the host environment provides.
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    clear_smoke_results()
    yield
    clear_smoke_results()
    set_clock(Clock())


@pytest.fixture
def clock() -> FixedClock:
    fixed = FixedClock(SEED_NOW)
    set_clock(fixed)
    return fixed


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "database_url": f"sqlite:///{tmp_path / 'test.db'}",
        "data_dir": str(tmp_path / "data"),
        "session_secret": "test-session-secret",
        "demo_webhook_secret": "test-webhook-secret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings, clock: FixedClock) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


def login(client: TestClient, handle: str, mid: str = "MID-DEMO-001") -> dict[str, str]:
    resp = client.post("/api/demo/session", json={"mid": mid, "handle": handle})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}
