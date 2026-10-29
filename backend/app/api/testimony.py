"""Staff voice notes: upload, original audio, transcript confirmation/correction (PRD 8.3 P0+)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Identity, current_identity, get_db, get_settings_dep, require_role
from app.api.evidence import scoped_case
from app.config import REPO_ROOT, Settings
from app.db.models import DemoUser, VoiceNote
from app.providers.speech import transcription_allowed
from app.runner import enqueue, enqueue_continuation, schedule
from app.services import testimony
from app.services.extraction import MAX_UPLOAD_BYTES, UploadRejected
from app.services.storage import read_original

router = APIRouter(prefix="/api", tags=["testimony"])

VOICE_FIXTURE = REPO_ROOT / "fixtures" / "hero" / "voice_note_mr.ogg"


def transcription_available(app: Any) -> tuple[bool, str]:
    if getattr(app.state, "speech_provider", None) is not None:
        return True, "speech provider override"
    return transcription_allowed(app.state.settings)


def scoped_note(db: Session, identity: Identity, note_id: str) -> VoiceNote:
    note = db.get(VoiceNote, note_id)
    if note is None or note.merchant_id != identity.merchant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "voice note not found")
    return note


def _actor(db: Session, identity: Identity) -> DemoUser:
    user = db.get(DemoUser, identity.user_id)
    assert user is not None
    return user


def _error(exc: testimony.TestimonyError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.get("/cases/{case_id}/voice-notes")
def list_voice_notes(
    case_id: str, request: Request, identity: Identity = Depends(current_identity), db: Session = Depends(get_db)
) -> dict[str, Any]:
    case = scoped_case(db, identity, case_id)
    available, detail = transcription_available(request.app)
    return {
        "speech": {"available": available, "provider": request.app.state.settings.speech_provider, "detail": detail},
        "voice_notes": testimony.testimony_overview(db, case),
    }


@router.post("/cases/{case_id}/voice-notes", status_code=status.HTTP_201_CREATED)
def upload_voice_note(
    case_id: str,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    identity: Identity = Depends(require_role("staff")),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    case = scoped_case(db, identity, case_id)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    available, detail = transcription_available(request.app)
    try:
        note, created = testimony.ingest_voice_note(
            db,
            settings,
            case,
            _actor(db, identity),
            filename=file.filename or "voice-note",
            declared_mime=file.content_type,
            data=data,
            stt_available=available,
            stt_detail=detail,
        )
    except UploadRejected as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    elif note.stt_status == "awaiting_transcription":
        enqueue(db, case, "transcribe_voice_note", {"voice_note_id": note.id})
    db.commit()
    if created:
        schedule(background, request.app, case.id)
    return {"voice_note_id": note.id, "created": created, "stt_status": note.stt_status}


@router.get("/voice-notes/{note_id}/audio")
def get_audio(
    note_id: str,
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db),
) -> Response:
    note = scoped_note(db, identity, note_id)
    return Response(
        content=read_original(settings, note.storage_key),
        media_type=note.mime_type,
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )


class ConfirmRequest(BaseModel):
    version: int = Field(ge=1)


class CorrectRequest(BaseModel):
    base_version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=testimony.MAX_TRANSCRIPT_CHARS + 100)


class ManualRequest(BaseModel):
    text: str = Field(min_length=1, max_length=testimony.MAX_TRANSCRIPT_CHARS + 100)


def _finish(db: Session, request: Request, background: BackgroundTasks, note: VoiceNote, identity: Identity) -> None:
    case = scoped_case(db, identity, note.case_id)
    enqueue_continuation(db, case, "testimony_confirmed")
    db.commit()
    schedule(background, request.app, case.id)


@router.post("/voice-notes/{note_id}/confirm")
def confirm(
    note_id: str,
    req: ConfirmRequest,
    request: Request,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("staff")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    note = scoped_note(db, identity, note_id)
    case = scoped_case(db, identity, note.case_id)
    try:
        t = testimony.confirm_transcript(db, case, note, _actor(db, identity), req.version)
    except testimony.TestimonyError as exc:
        raise _error(exc) from exc
    _finish(db, request, background, note, identity)
    return {"transcript_id": t.id, "version": t.version, "confirmation_state": t.confirmation_state}


@router.post("/voice-notes/{note_id}/correct", status_code=status.HTTP_201_CREATED)
def correct(
    note_id: str,
    req: CorrectRequest,
    request: Request,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("staff")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    note = scoped_note(db, identity, note_id)
    case = scoped_case(db, identity, note.case_id)
    try:
        t = testimony.correct_transcript(db, case, note, _actor(db, identity), req.base_version, req.text)
    except testimony.TestimonyError as exc:
        raise _error(exc) from exc
    _finish(db, request, background, note, identity)
    return {"transcript_id": t.id, "version": t.version, "confirmation_state": t.confirmation_state}


@router.post("/voice-notes/{note_id}/transcribe-manually", status_code=status.HTTP_201_CREATED)
def transcribe_manually(
    note_id: str,
    req: ManualRequest,
    request: Request,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("staff")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    note = scoped_note(db, identity, note_id)
    case = scoped_case(db, identity, note.case_id)
    try:
        t = testimony.human_transcription(db, case, note, _actor(db, identity), req.text)
    except testimony.TestimonyError as exc:
        raise _error(exc) from exc
    _finish(db, request, background, note, identity)
    return {"transcript_id": t.id, "version": t.version, "method": t.method}


@router.post("/voice-notes/{note_id}/retry-transcription", status_code=status.HTTP_202_ACCEPTED)
def retry_transcription(
    note_id: str,
    request: Request,
    background: BackgroundTasks,
    identity: Identity = Depends(require_role("staff", "operator")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    note = scoped_note(db, identity, note_id)
    if identity.role == "staff" and identity.user_id != note.staff_user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the speaker or an operator can retry transcription")
    if note.stt_status not in ("stt_unavailable", "stt_failed"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"voice note is {note.stt_status}")
    if testimony.has_transcript(db, note):
        raise HTTPException(status.HTTP_409_CONFLICT, "a transcript already exists")
    available, detail = transcription_available(request.app)
    if not available:
        raise HTTPException(status.HTTP_409_CONFLICT, f"speech-to-text unavailable: {detail}")
    case = scoped_case(db, identity, note.case_id)
    note.stt_status = "awaiting_transcription"
    note.stt_detail = None
    enqueue(db, case, "transcribe_voice_note", {"voice_note_id": note.id, "retry": True})
    db.commit()
    schedule(background, request.app, case.id)
    return {"voice_note_id": note.id, "stt_status": note.stt_status}


@router.get("/demo/cases/{case_id}/voice-fixture")
def voice_fixture(
    case_id: str,
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_db),
) -> Response:
    """Synthetic Marathi voice note (espeak-ng, robotic voice). Downloading it is not an upload."""
    if not settings.demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "demo endpoints are disabled")
    scoped_case(db, identity, case_id)
    return Response(
        content=VOICE_FIXTURE.read_bytes(),
        media_type="audio/ogg",
        headers={
            "Content-Disposition": 'attachment; filename="voice_note_mr.ogg"',
            "X-Content-Type-Options": "nosniff",
        },
    )
