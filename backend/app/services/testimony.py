"""Staff voice notes and transcripts: testimony with audio provenance (PRD 8.3 P0+).

A transcript is what a staff member *said*, not proof that delivery occurred. Nothing here
creates ExtractedFacts, touches the checklist or validators, or feeds `orderStatus`; the matching
delivery document stays required. STT output is unconfirmed until the speaker confirms or
corrects it, and a correction is a new version (earlier versions are kept). Segment offsets are
zero-based, end-exclusive code-point spans computed in Python while the text is assembled.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Case, DemoUser, StaffTask, Transcript, VoiceNote
from app.domain.citations import text_sha256
from app.domain.clock import get_clock
from app.providers.speech import SpeechTranscript
from app.services.audit import audit
from app.services.extraction import MAX_UPLOAD_BYTES, UploadRejected
from app.services.storage import save_original

MAX_TRANSCRIPT_CHARS = 2000
TIMESTAMP_TOLERANCE_MS = 250  # decoder rounding; beyond this a segment time is flagged as impossible
TESTIMONY_NOTE = "Staff testimony, not a delivery document; it cannot satisfy a checklist item."

_AUDIO_EXTENSIONS = {
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".webm": "audio/webm",
}
_DECLARED_OK = {
    "audio/wav": {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"},
    "audio/ogg": {"audio/ogg", "audio/opus", "application/ogg"},
    "audio/mpeg": {"audio/mpeg", "audio/mp3"},
    "audio/mp4": {"audio/mp4", "audio/x-m4a", "audio/m4a", "audio/aac"},
    "audio/webm": {"audio/webm", "video/webm"},
}
_ALWAYS_OK = {"application/octet-stream", ""}


class TestimonyError(ValueError):
    """Invalid testimony operation (wrong actor, stale version, bad state)."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _sniff_audio(data: bytes) -> str | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:4] == b"OggS":
        return "audio/ogg"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm"
    return None


def sniff_audio(filename: str, declared_mime: str | None, data: bytes) -> tuple[str, str]:
    """Return (mime, extension) after checking extension, declared type and actual content."""
    if not data:
        raise UploadRejected("empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"file exceeds {MAX_UPLOAD_BYTES} bytes")
    ext = PurePath(filename or "").suffix.lower()
    expected = _AUDIO_EXTENSIONS.get(ext)
    if expected is None:
        raise UploadRejected(
            f"unsupported audio extension {ext or '(none)'}; allowed: {', '.join(sorted(_AUDIO_EXTENSIONS))}"
        )
    actual = _sniff_audio(data)
    if actual is None:
        raise UploadRejected("content is not a recognised audio container (WAV, Ogg, MP3, MP4/M4A, WebM)")
    if actual != expected:
        raise UploadRejected(f"content is {actual} but the extension says {expected}")
    declared = (declared_mime or "").split(";")[0].strip().lower()
    if declared not in _DECLARED_OK[actual] | _ALWAYS_OK:
        raise UploadRejected(f"declared type {declared} does not match the content ({actual})")
    return actual, ext


def _safe_filename(name: str) -> str:
    base = PurePath(name.replace("\\", "/")).name or "voice-note"
    return "".join(ch for ch in base if ch.isprintable())[:255]


def _linked_task(session: Session, case: Case, staff: DemoUser) -> StaffTask | None:
    """The speaker's open evidence request, else their most recent one (provenance only)."""
    tasks = session.scalars(
        select(StaffTask)
        .where(StaffTask.case_id == case.id, StaffTask.assignee_user_id == staff.id, StaffTask.kind == "evidence")
        .order_by(StaffTask.created_at.desc())
    ).all()
    return next((t for t in tasks if t.status == "open"), tasks[0] if tasks else None)


def ingest_voice_note(
    session: Session,
    settings: Settings,
    case: Case,
    staff: DemoUser,
    *,
    filename: str,
    declared_mime: str | None,
    data: bytes,
    stt_available: bool,
    stt_detail: str,
) -> tuple[VoiceNote, bool]:
    """Store the original audio before anything else. Identical bytes on a case are not duplicated.

    Uploading testimony does not resolve the staff member's document request: the document is
    still needed.
    """
    mime, ext = sniff_audio(filename, declared_mime, data)
    sha = hashlib.sha256(data).hexdigest()
    existing = session.scalar(select(VoiceNote).where(VoiceNote.case_id == case.id, VoiceNote.sha256 == sha))
    if existing is not None:
        return existing, False
    task = _linked_task(session, case, staff)
    note = VoiceNote(
        case_id=case.id,
        merchant_id=case.merchant_id,
        staff_user_id=staff.id,
        staff_task_id=task.id if task else None,
        original_filename=_safe_filename(filename),
        storage_key="",
        mime_type=mime,
        size_bytes=len(data),
        sha256=sha,
        locale=staff.locale,
        stt_status="awaiting_transcription" if stt_available else "stt_unavailable",
        stt_provider=settings.speech_provider if stt_available else None,
        stt_detail=None if stt_available else stt_detail,
    )
    session.add(note)
    session.flush()
    note.storage_key = save_original(settings, case.id, f"voice-{note.id}", ext, data)
    audit(
        session,
        event_type="testimony.received",
        summary=(
            f"{staff.display_name} sent a voice note ({staff.locale}); "
            + ("transcription queued." if stt_available else "speech-to-text unavailable.")
        ),
        actor_type="user",
        actor_id=staff.id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"voice_note_id": note.id, "sha256": sha, "mime_type": mime, "staff_task_id": note.staff_task_id},
    )
    session.flush()
    return note, True


def assemble_segments(transcript: SpeechTranscript) -> tuple[str, list[dict[str, Any]]]:
    """Join segment texts with single spaces and record each segment's code-point span."""
    text = ""
    spans: list[dict[str, Any]] = []
    for seg in transcript.segments:
        if text:
            text += " "
        start = len(text)
        text += seg.text
        spans.append({"start": start, "end": len(text), "audio_start_ms": seg.start_ms, "audio_end_ms": seg.end_ms})
    for span, seg in zip(spans, transcript.segments, strict=True):
        assert text[span["start"] : span["end"]] == seg.text
    return text, spans


def _versions(session: Session, note: VoiceNote) -> list[Transcript]:
    return list(
        session.scalars(
            select(Transcript).where(Transcript.voice_note_id == note.id).order_by(Transcript.version)
        ).all()
    )


def record_transcription(session: Session, note: VoiceNote, result: SpeechTranscript) -> Transcript | None:
    """Persist STT output as an unconfirmed v1. Empty output is a failure, never an empty transcript."""
    text, spans = assemble_segments(result)
    note.duration_ms = result.duration_ms
    note.stt_provider = result.provider
    if not text.strip():
        note.stt_status = "stt_failed"
        note.stt_detail = "no speech was recognised"
        audit(
            session,
            event_type="testimony.transcription_failed",
            summary="Speech-to-text recognised no speech; the staff member can type a transcription.",
            actor_type="system",
            case_id=note.case_id,
            merchant_id=note.merchant_id,
            data={"voice_note_id": note.id, "provider": result.provider, "model": result.model},
        )
        return None
    transcript = Transcript(
        voice_note_id=note.id,
        case_id=note.case_id,
        version=1,
        text=text,
        text_sha256=text_sha256(text),
        method="stt",
        provider=result.provider,
        model=result.model,
        language=result.language,
        language_probability=result.language_probability,
        segments=spans,
        confirmation_state="unconfirmed",
    )
    session.add(transcript)
    note.stt_status = "transcribed"
    note.stt_detail = f"latency {result.latency_ms} ms; " + "; ".join(result.notes)
    session.flush()
    audit(
        session,
        event_type="testimony.transcribed",
        summary=f"Voice note transcribed by {result.provider} ({result.model}); unconfirmed until the staff member "
        "confirms it.",
        actor_type="system",
        case_id=note.case_id,
        merchant_id=note.merchant_id,
        data={
            "voice_note_id": note.id,
            "transcript_id": transcript.id,
            "version": 1,
            "text_sha256": transcript.text_sha256,
            "provider": result.provider,
            "model": result.model,
            "language": result.language,
            "segments": len(spans),
            "latency_ms": result.latency_ms,
        },
    )
    return transcript


def record_failure(session: Session, note: VoiceNote, kind: str, message: str) -> None:
    note.stt_status = "stt_unavailable" if kind == "unavailable" else "stt_failed"
    note.stt_detail = f"{kind}: {message}"
    audit(
        session,
        event_type="testimony.transcription_failed",
        summary=f"Speech-to-text did not produce a transcript ({kind}); the staff member can type one.",
        actor_type="system",
        case_id=note.case_id,
        merchant_id=note.merchant_id,
        data={"voice_note_id": note.id, "kind": kind, "error": message},
    )


def _require_speaker(note: VoiceNote, actor: DemoUser) -> None:
    if actor.id != note.staff_user_id:
        raise TestimonyError("only the staff member who recorded this voice note can confirm or transcribe it", 403)


def _clean_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise TestimonyError("transcript text is empty", 422)
    if len(cleaned) > MAX_TRANSCRIPT_CHARS:
        raise TestimonyError(f"transcript exceeds {MAX_TRANSCRIPT_CHARS} characters", 422)
    return cleaned


def confirm_transcript(session: Session, case: Case, note: VoiceNote, actor: DemoUser, version: int) -> Transcript:
    _require_speaker(note, actor)
    versions = _versions(session, note)
    if not versions or versions[-1].version != version:
        raise TestimonyError("that transcript version is not the latest one")
    latest = versions[-1]
    if latest.confirmation_state != "unconfirmed":
        raise TestimonyError(f"transcript version {version} is already {latest.confirmation_state}")
    latest.confirmation_state = "confirmed"
    latest.confirmed_by_user_id = actor.id
    latest.confirmed_at = get_clock().now()
    audit(
        session,
        event_type="testimony.confirmed",
        summary=f"{actor.display_name} confirmed the transcript of their voice note (v{version}).",
        actor_type="user",
        actor_id=actor.id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"voice_note_id": note.id, "transcript_id": latest.id, "version": version, "method": latest.method},
    )
    return latest


def _new_human_version(
    session: Session, case: Case, note: VoiceNote, actor: DemoUser, text: str, method: str
) -> Transcript:
    versions = _versions(session, note)
    for v in versions:
        if v.confirmation_state != "superseded":
            v.confirmation_state = "superseded"
    now = get_clock().now()
    transcript = Transcript(
        voice_note_id=note.id,
        case_id=case.id,
        version=(versions[-1].version + 1) if versions else 1,
        text=text,
        text_sha256=text_sha256(text),
        method=method,
        segments=[],  # audio timestamps are unknown for human-written text; never invented
        author_user_id=actor.id,
        confirmation_state="confirmed",  # written by the speaker themself
        confirmed_by_user_id=actor.id,
        confirmed_at=now,
    )
    session.add(transcript)
    session.flush()
    return transcript


def correct_transcript(
    session: Session, case: Case, note: VoiceNote, actor: DemoUser, base_version: int, text: str
) -> Transcript:
    _require_speaker(note, actor)
    cleaned = _clean_text(text)
    versions = _versions(session, note)
    if not versions or versions[-1].version != base_version:
        raise TestimonyError("the transcript changed; reload and correct the latest version")
    if cleaned == versions[-1].text:
        raise TestimonyError("the correction is identical to the current transcript; confirm it instead", 422)
    transcript = _new_human_version(session, case, note, actor, cleaned, "staff_correction")
    audit(
        session,
        event_type="testimony.corrected",
        summary=f"{actor.display_name} corrected the transcript (v{base_version} → v{transcript.version}).",
        actor_type="user",
        actor_id=actor.id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={
            "voice_note_id": note.id,
            "transcript_id": transcript.id,
            "version": transcript.version,
            "previous_version": base_version,
            "text_sha256": transcript.text_sha256,
        },
    )
    return transcript


def human_transcription(session: Session, case: Case, note: VoiceNote, actor: DemoUser, text: str) -> Transcript:
    """Labelled human transcription when speech-to-text produced nothing. Never relabelled as STT."""
    _require_speaker(note, actor)
    cleaned = _clean_text(text)
    if _versions(session, note):
        raise TestimonyError("a transcript already exists; correct it instead")
    if note.stt_status not in ("stt_unavailable", "stt_failed"):
        raise TestimonyError("speech-to-text is still pending for this voice note")
    transcript = _new_human_version(session, case, note, actor, cleaned, "human_transcription")
    audit(
        session,
        event_type="testimony.human_transcribed",
        summary=f"{actor.display_name} typed a transcription of their voice note (human transcription, not STT).",
        actor_type="user",
        actor_id=actor.id,
        case_id=case.id,
        merchant_id=case.merchant_id,
        data={"voice_note_id": note.id, "transcript_id": transcript.id, "text_sha256": transcript.text_sha256},
    )
    return transcript


def _transcript_view(t: Transcript, users: dict[str, str], duration_ms: int | None = None) -> dict[str, Any]:
    intact = text_sha256(t.text) == t.text_sha256
    segments = [
        {
            **s,
            "text": t.text[s["start"] : s["end"]],
            "recheck_ok": intact and 0 <= s["start"] < s["end"] <= len(t.text),
            # Provider timestamps are shown as reported, never altered; impossible ones are flagged.
            "timestamp_in_range": duration_ms is None
            or 0 <= s["audio_start_ms"] <= s["audio_end_ms"] <= duration_ms + TIMESTAMP_TOLERANCE_MS,
        }
        for s in t.segments
    ]
    return {
        "id": t.id,
        "version": t.version,
        "text": t.text,
        "text_sha256": t.text_sha256,
        "text_recheck_ok": intact,
        "method": t.method,
        "provider": t.provider,
        "model": t.model,
        "language": t.language,
        "language_probability": t.language_probability,
        "segments": segments,
        "timestamps_available": bool(segments),
        "author": users.get(t.author_user_id or ""),
        "confirmation_state": t.confirmation_state,
        "confirmed_by": users.get(t.confirmed_by_user_id or ""),
        "confirmed_at": t.confirmed_at,
        "created_at": t.created_at,
    }


def testimony_overview(session: Session, case: Case) -> list[dict[str, Any]]:
    staff = session.scalars(select(DemoUser).where(DemoUser.merchant_id == case.merchant_id))
    users = {u.id: u.display_name for u in staff}
    notes = session.scalars(select(VoiceNote).where(VoiceNote.case_id == case.id).order_by(VoiceNote.created_at)).all()
    tasks = {t.id: t for t in session.scalars(select(StaffTask).where(StaffTask.case_id == case.id))}
    out = []
    for n in notes:
        versions = _versions(session, n)
        task = tasks.get(n.staff_task_id or "")
        out.append(
            {
                "id": n.id,
                "staff": users.get(n.staff_user_id),
                "staff_user_id": n.staff_user_id,
                "staff_task": (
                    {"id": task.id, "requirement_id": task.requirement_id, "round": task.request_round}
                    if task
                    else None
                ),
                "original_filename": n.original_filename,
                "mime_type": n.mime_type,
                "size_bytes": n.size_bytes,
                "sha256": n.sha256,
                "locale": n.locale,
                "duration_ms": n.duration_ms,
                "stt_status": n.stt_status,
                "stt_provider": n.stt_provider,
                "stt_detail": n.stt_detail,
                "created_at": n.created_at,
                "note": TESTIMONY_NOTE,
                "current": _transcript_view(versions[-1], users, n.duration_ms) if versions else None,
                "versions": [_transcript_view(v, users, n.duration_ms) for v in versions],
            }
        )
    return out


def testimony_for_prompt(session: Session, case: Case) -> list[dict[str, Any]]:
    """Latest transcript per voice note, labelled, for the untrusted section of the agent prompt."""
    items = []
    for n in session.scalars(select(VoiceNote).where(VoiceNote.case_id == case.id).order_by(VoiceNote.created_at)):
        versions = _versions(session, n)
        if not versions:
            continue
        latest = versions[-1]
        items.append(
            {
                "locale": n.locale,
                "confirmation": latest.confirmation_state,
                "method": latest.method,
                "text": latest.text[:500],
                "note": TESTIMONY_NOTE,
            }
        )
    return items[-5:]


def has_transcript(session: Session, note: VoiceNote) -> bool:
    return bool(_versions(session, note))
