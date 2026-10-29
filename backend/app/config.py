"""Application settings.

Real environment variables take precedence over values in a `.env` file, so a key
set in the host/cloud environment works without any `.env` file at all.
"""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER_SECRET = "replace-with-a-local-development-secret"

log = logging.getLogger(__name__)


class SettingsError(ValueError):
    """Raised when configuration is unsafe or unsupported for this release."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    demo_mode: bool = True
    app_timezone: str = "Asia/Kolkata"
    database_url: str = "sqlite:///./data/proofcircuit.db"
    data_dir: str = "./data"

    # Reasoning providers. Gemini is the default primary (user decision, see BUILD_LOG.md).
    reasoner_provider: Literal["gemini", "openrouter", "ollama", "manual"] = "gemini"
    fallback_provider: Literal["openrouter", "gemini", "ollama", "none"] = "openrouter"
    fallback_enabled: bool = False
    allow_paid_models: bool = False

    gemini_api_key: SecretStr | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-3.5-flash-lite"

    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "openrouter/free"
    openrouter_require_parameters: bool = True
    openrouter_data_collection: Literal["deny", "allow"] = "deny"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    ollama_num_ctx: int = 8192
    ollama_temperature: float = 0.0
    ollama_think: bool = False

    uvicorn_workers: int = 1
    paytm_naive_timezone: str = "Asia/Kolkata"
    max_pod_repair_rounds: int = Field(default=1, ge=0)
    evaluation_target_cases: int = 40
    evaluation_smoke_cases: int = 10

    reminders_enabled: bool = False
    n8n_reminder_webhook_url: str = ""
    n8n_webhook_token: SecretStr | None = None
    n8n_service_token: SecretStr | None = None
    backend_base_url: str = "http://127.0.0.1:8000"
    reminder_delay_seconds: int = 120
    max_reminders_per_request_round: int = 1

    agent_max_steps: int = Field(default=8, ge=1)
    agent_timeout_seconds: int = 180
    model_timeout_seconds: int = 60
    agent_autorun: bool = True  # event-triggered agent runs (only when a reasoner is ready)
    agent_max_schema_repairs: int = Field(default=2, ge=0, le=5)
    agent_max_consecutive_denials: int = Field(default=2, ge=1)
    reasoner_daily_call_cap: int = Field(default=150, ge=0)  # rolling 24h, all purposes
    reasoner_min_interval_seconds: float = Field(default=4.0, ge=0)
    reasoner_max_output_tokens: int = Field(default=2048, ge=64)  # thinking models may use part of it
    gemini_thinking_level: str = "low"  # sent only if the smoke test shows the model accepts it; "" = omit
    reasoner_rate_limit_max_wait_seconds: float = Field(default=20.0, ge=0)
    smoke_check_ttl_hours: int = Field(default=24, ge=1)
    provider_status_reads: int = Field(default=3, ge=1, le=10)  # bounded status reads per reconciliation
    provider_retry_backoff_seconds: float = Field(default=0.5, ge=0)

    messaging_provider: Literal["local"] = "local"
    memory_provider: Literal["sql"] = "sql"
    speech_provider: Literal["disabled", "sarvam", "faster_whisper"] = "disabled"
    # Local faster-whisper (M5). Weights are never downloaded implicitly: either WHISPER_MODEL_DIR
    # points at a CTranslate2 model directory, or the model is already in the Hugging Face cache.
    whisper_model: str = "small"
    whisper_model_dir: str = ""
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = Field(default=5, ge=1, le=10)
    speech_max_audio_seconds: int = Field(default=120, ge=1)
    speech_timeout_seconds: int = Field(default=300, ge=1)
    # Default: transcribe only after a passing smoke check. False allows transcription after a failed check
    # (labelled as such); transcripts stay unconfirmed until the speaker checks them either way.
    speech_require_passing_smoke: bool = True
    speech_smoke_max_cer: float = Field(default=0.35, ge=0, le=1)  # smoke passes only at or below this CER
    ocr_provider: Literal["disabled"] = "disabled"
    paytm_mode: str = "simulator"
    paytm_live_enabled: bool = False
    auto_submit_simulator: bool = True

    sarvam_api_key: SecretStr | None = None
    demo_webhook_secret: SecretStr = SecretStr(PLACEHOLDER_SECRET)
    session_secret: SecretStr = SecretStr(PLACEHOLDER_SECRET)
    approval_ttl_seconds: int = 900

    @field_validator(
        "gemini_api_key",
        "openrouter_api_key",
        "sarvam_api_key",
        "n8n_webhook_token",
        "n8n_service_token",
        mode="before",
    )
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _check_release_constraints(self) -> Settings:
        if self.paytm_mode != "simulator":
            raise SettingsError("PAYTM_MODE must be 'simulator'; live Paytm integration is out of scope.")
        if self.paytm_live_enabled:
            raise SettingsError("PAYTM_LIVE_ENABLED=true is not supported: the live adapter is not implemented.")
        if self.uvicorn_workers != 1:
            raise SettingsError("UVICORN_WORKERS must be 1: per-case locks are in-memory (PRD Section 7).")
        for name in ("session_secret", "demo_webhook_secret"):
            value: SecretStr = getattr(self, name)
            if not value.get_secret_value() or value.get_secret_value() == PLACEHOLDER_SECRET:
                if self.app_env == "production":
                    raise SettingsError(f"{name.upper()} must be set to a generated secret.")
                # Development: generate an ephemeral secret so the placeholder is never used.
                log.warning("%s is unset or a placeholder; using an ephemeral random secret.", name.upper())
                setattr(self, name, SecretStr(secrets.token_urlsafe(32)))
        return self

    # Paths -----------------------------------------------------------------
    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir)
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()

    @property
    def resolved_database_url(self) -> str:
        """Resolve relative SQLite paths against the repo root, not the process CWD."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix) and not self.database_url.startswith(prefix + "/"):
            rel = self.database_url[len(prefix) :]
            if rel != ":memory:":
                return prefix + str((REPO_ROOT / rel).resolve())
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
