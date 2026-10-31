"""Speech-to-text providers behind `SpeechProvider` (PRD 6.1, 8.3, 12).

M5 implements local faster-whisper only (user decision; the Sarvam adapter is not built). Weights
are never downloaded implicitly: the model must already be in WHISPER_MODEL_DIR or the local
Hugging Face cache. Output is staff testimony, never proof that delivery occurred.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
import time
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Protocol

from app.config import Settings

log = logging.getLogger(__name__)

# App locales -> Whisper language codes. The language is passed explicitly, never guessed.
WHISPER_LANGUAGES = {"en-IN": "en", "hi-IN": "hi", "mr-IN": "mr"}


class SpeechError(Exception):
    """`kind`: unavailable (not configured/installed) | too_long | failed | timeout | not_implemented."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class SpeechSegment:
    text: str
    start_ms: int
    end_ms: int


@dataclass
class SpeechTranscript:
    segments: list[SpeechSegment]
    provider: str
    model: str
    language: str | None = None
    language_probability: float | None = None
    duration_ms: int | None = None
    latency_ms: int = 0
    notes: list[str] = field(default_factory=list)


class SpeechProvider(Protocol):
    name: str
    model: str

    async def transcribe(self, audio: bytes, locale: str) -> SpeechTranscript: ...

    async def synthesize(self, text: str, locale: str) -> bytes: ...


@dataclass
class ModelLocation:
    path: str | None
    detail: str


_location_cache: dict[tuple[str, str], tuple[float, ModelLocation]] = {}
_LOCATION_TTL_SECONDS = 30.0


def locate_model(settings: Settings) -> ModelLocation:
    """Find the model on local disk without loading or downloading it (cached briefly)."""
    key = (settings.whisper_model, settings.whisper_model_dir)
    cached = _location_cache.get(key)
    if cached is not None and time.monotonic() - cached[0] < _LOCATION_TTL_SECONDS:
        return cached[1]
    location = _locate_uncached(settings)
    _location_cache[key] = (time.monotonic(), location)
    return location


def _locate_uncached(settings: Settings) -> ModelLocation:
    if find_spec("faster_whisper") is None:
        return ModelLocation(None, "faster-whisper is not installed (cd backend && uv sync --extra speech).")
    if settings.whisper_model_dir:
        path = Path(settings.whisper_model_dir).expanduser()
        if (path / "model.bin").is_file():
            return ModelLocation(str(path), f"Local CTranslate2 model at {path}.")
        return ModelLocation(None, f"WHISPER_MODEL_DIR={path} has no model.bin.")
    try:
        from faster_whisper.utils import download_model

        path = download_model(settings.whisper_model, local_files_only=True)
    except Exception:  # noqa: BLE001 - any lookup failure means "not available locally"
        return ModelLocation(
            None,
            f"Model {settings.whisper_model!r} is not in the local Hugging Face cache and will not be downloaded "
            "implicitly. Run `uv run python -m app.cli speech-download` where huggingface.co is reachable, or set "
            "WHISPER_MODEL_DIR.",
        )
    return ModelLocation(path, f"Cached model {settings.whisper_model!r} at {path}.")


_models: dict[tuple[str, str, str], Any] = {}
_models_lock = threading.Lock()


def _load_model(path: str, device: str, compute_type: str) -> Any:
    key = (path, device, compute_type)
    with _models_lock:
        model = _models.get(key)
        if model is None:
            from faster_whisper import WhisperModel

            model = _models[key] = WhisperModel(path, device=device, compute_type=compute_type, local_files_only=True)
        return model


class FasterWhisperProvider:
    name = "faster_whisper"

    def __init__(self, settings: Settings, model_factory: Any = None) -> None:
        self.settings = settings
        self.model = settings.whisper_model_dir or settings.whisper_model
        self._factory = model_factory  # tests inject a stand-in for WhisperModel

    def _model(self) -> Any:
        if self._factory is not None:
            return self._factory()
        location = locate_model(self.settings)
        if location.path is None:
            raise SpeechError("unavailable", location.detail)
        return _load_model(location.path, self.settings.whisper_device, self.settings.whisper_compute_type)

    def _run(self, audio: bytes, locale: str) -> SpeechTranscript:
        started = time.monotonic()
        model = self._model()
        segments_iter, info = model.transcribe(
            io.BytesIO(audio),
            language=WHISPER_LANGUAGES[locale],
            task="transcribe",
            beam_size=self.settings.whisper_beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        duration = getattr(info, "duration", None)
        if duration is not None and duration > self.settings.speech_max_audio_seconds:
            raise SpeechError(
                "too_long", f"audio is {duration:.1f}s; the limit is {self.settings.speech_max_audio_seconds}s"
            )
        segments = []
        for seg in segments_iter:  # decoding happens lazily while iterating
            text = (seg.text or "").strip()
            if text:
                segments.append(SpeechSegment(text, round(seg.start * 1000), round(seg.end * 1000)))
        return SpeechTranscript(
            segments=segments,
            provider=self.name,
            model=self.model,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration_ms=round(duration * 1000) if duration is not None else None,
            latency_ms=round((time.monotonic() - started) * 1000),
            notes=[f"device={self.settings.whisper_device}", f"compute_type={self.settings.whisper_compute_type}"],
        )

    async def transcribe(self, audio: bytes, locale: str) -> SpeechTranscript:
        if locale not in WHISPER_LANGUAGES:
            raise SpeechError("failed", f"unsupported locale {locale}")
        try:
            # CPU-bound: run off the event loop. A timeout stops waiting; it cannot kill the thread.
            return await asyncio.wait_for(
                asyncio.to_thread(self._run, audio, locale), timeout=self.settings.speech_timeout_seconds
            )
        except SpeechError:
            raise
        except TimeoutError as exc:
            raise SpeechError("timeout", f"transcription exceeded {self.settings.speech_timeout_seconds}s") from exc
        except Exception as exc:  # noqa: BLE001 - decoder/runtime errors are reported, never swallowed
            log.exception("faster-whisper transcription failed")
            raise SpeechError("failed", f"{type(exc).__name__}: {exc}") from exc

    async def synthesize(self, text: str, locale: str) -> bytes:
        raise SpeechError("not_implemented", "speech synthesis is not implemented; text is always shown")


def speech_availability(settings: Settings) -> tuple[str, str]:
    """(status, detail) for readiness. Transcription may run only when status is ready/configured_untested."""
    if settings.speech_provider == "disabled":
        return "disabled", "SPEECH_PROVIDER=disabled; staff can type text or a labelled human transcription."
    if settings.speech_provider == "sarvam":
        return "not_implemented", "Sarvam Saaras adapter is not built (M5 used local faster-whisper only)."
    location = locate_model(settings)
    if location.path is None:
        return "unconfigured", location.detail
    from app.providers.readiness import latest_check

    check = latest_check("faster_whisper", settings.whisper_model_dir or settings.whisper_model, 24 * 365)
    if check is None:
        return "configured_untested", f"{location.detail} Run `app.cli smoke-speech` to record a live check."
    detail = f"{getattr(check, 'detail', '')} (checked {check.checked_at.isoformat()})"
    return ("ready" if check.ok else "failed"), detail


def transcription_allowed(settings: Settings) -> tuple[bool, str]:
    status, detail = speech_availability(settings)
    if status in ("ready", "configured_untested"):
        return True, detail
    if status == "failed" and not settings.speech_require_passing_smoke:
        return True, f"Smoke check FAILED, transcribing anyway (SPEECH_REQUIRE_PASSING_SMOKE=false): {detail}"
    return False, detail


def build_speech_provider(app: Any) -> SpeechProvider:
    override = getattr(app.state, "speech_provider", None)
    if override is not None:
        return override  # type: ignore[no-any-return]
    settings: Settings = app.state.settings
    if settings.speech_provider != "faster_whisper":
        raise SpeechError("unavailable", f"SPEECH_PROVIDER={settings.speech_provider}")
    return FasterWhisperProvider(settings)
