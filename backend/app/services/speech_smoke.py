"""Live speech-to-text smoke check on the bundled synthetic Marathi voice note.

It proves the local runtime and model transcribe the fixture; the character error rate against
the known script is a measurement on one robotic espeak-ng clip, not an accuracy claim.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.config import REPO_ROOT, Settings
from app.providers.readiness import record_smoke_result
from app.providers.speech import FasterWhisperProvider, SpeechError

FIXTURE_AUDIO = REPO_ROOT / "fixtures" / "hero" / "voice_note_mr.ogg"
FIXTURE_SCRIPT = REPO_ROOT / "fixtures" / "hero" / "voice_note_mr.txt"


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[^\w\s]", " ", text)  # drop punctuation (Devanagari marks are \w in Python)
    return " ".join(text.split())


def character_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = _normalize(reference), _normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, start=1):
        cur = [i]
        for j, hc in enumerate(hyp, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


async def smoke_speech(settings: Settings, provider: Any | None = None) -> dict[str, Any]:
    stt = provider or FasterWhisperProvider(settings)
    model = settings.whisper_model_dir or settings.whisper_model
    reference = FIXTURE_SCRIPT.read_text(encoding="utf-8").strip()
    try:
        result = await stt.transcribe(FIXTURE_AUDIO.read_bytes(), "mr-IN")
    except SpeechError as exc:
        detail = f"{exc.kind}: {exc}"
        record_smoke_result("faster_whisper", False, detail, model_requested=model)
        return {"ok": False, "provider": "faster_whisper", "model": model, "error": detail}
    text = " ".join(s.text for s in result.segments)
    cer = character_error_rate(reference, text)
    # A non-empty but wrong transcript must not pass: require a usable CER on the known script.
    ok = bool(text.strip()) and cer <= settings.speech_smoke_max_cer
    if not text.strip():
        detail = "No speech recognised in the fixture"
    else:
        detail = (
            f"Synthetic Marathi fixture: CER {cer:.2f} (limit {settings.speech_smoke_max_cer:.2f}), "
            f"{result.latency_ms} ms; one espeak-ng clip, not an accuracy claim"
        )
    record_smoke_result(
        "faster_whisper",
        ok,
        detail,
        model_requested=model,
        model_returned=result.model,
        capabilities={"language": result.language, "cer": round(cer, 4), "latency_ms": result.latency_ms},
    )
    return {
        "ok": ok,
        "provider": result.provider,
        "model": result.model,
        "language": result.language,
        "language_probability": result.language_probability,
        "duration_ms": result.duration_ms,
        "latency_ms": result.latency_ms,
        "segments": [{"text": s.text, "start_ms": s.start_ms, "end_ms": s.end_ms} for s in result.segments],
        "reference": reference,
        "transcript": text,
        "character_error_rate": round(cer, 4),
    }
