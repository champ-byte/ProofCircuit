from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import PLACEHOLDER_SECRET, REPO_ROOT, Settings
from tests.conftest import make_settings


def test_live_paytm_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="PAYTM_LIVE_ENABLED"):
        make_settings(tmp_path, paytm_live_enabled=True)
    with pytest.raises(ValidationError, match="PAYTM_MODE"):
        make_settings(tmp_path, paytm_mode="live")


def test_multiple_workers_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="UVICORN_WORKERS"):
        make_settings(tmp_path, uvicorn_workers=2)


def test_placeholder_secret_never_used(tmp_path: Path) -> None:
    s = make_settings(tmp_path, app_env="development", session_secret=PLACEHOLDER_SECRET)
    assert s.session_secret.get_secret_value() not in ("", PLACEHOLDER_SECRET)
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        make_settings(tmp_path, app_env="production", session_secret=PLACEHOLDER_SECRET)


def test_defaults_are_free_first_and_gemini_primary() -> None:
    s = Settings(_env_file=None)
    assert s.reasoner_provider == "gemini"
    assert s.gemini_model.startswith("gemini-3")
    assert s.allow_paid_models is False
    assert s.openrouter_data_collection == "deny"
    assert s.paytm_mode == "simulator" and s.paytm_live_enabled is False


def test_blank_key_means_unconfigured(tmp_path: Path) -> None:
    assert make_settings(tmp_path, gemini_api_key="  ").gemini_api_key is None


def test_env_var_overrides_and_relative_sqlite_resolves_to_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/x.db")
    s = Settings(_env_file=None)
    assert s.gemini_model == "gemini-3.8-flash"
    assert s.resolved_database_url == f"sqlite:///{REPO_ROOT / 'data' / 'x.db'}"
