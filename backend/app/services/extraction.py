"""Content sniffing and text extraction for uploaded evidence (PRD 8.3, 14).

Digital TXT/JSON/PDF are parsed in P0. Images and image-only PDFs produce OCR_REQUIRED, never an
empty "successful" extraction. pypdf extraction is not OCR.
"""

from __future__ import annotations

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import PurePath

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 5_000_000  # matches the simulator's conservative per-file ceiling
MAX_PDF_PAGES = 20
PARSE_TIMEOUT_SECONDS = 15.0

_EXTENSIONS = {
    ".txt": "text/plain",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
# Declared MIME types browsers commonly send for each sniffed type.
_DECLARED_OK = {
    "text/plain": {"text/plain", "application/octet-stream", ""},
    "application/json": {"application/json", "text/json", "text/plain", "application/octet-stream", ""},
    "application/pdf": {"application/pdf", "application/x-pdf", "application/octet-stream", ""},
    "image/png": {"image/png", "application/octet-stream", ""},
    "image/jpeg": {"image/jpeg", "image/jpg", "image/pjpeg", "application/octet-stream", ""},
}

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="extract")


class UploadRejected(ValueError):
    pass


def sniff(filename: str, declared_mime: str | None, data: bytes) -> tuple[str, str]:
    """Return (mime, extension) after checking extension, declared type and actual content."""
    if not data:
        raise UploadRejected("empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"file exceeds {MAX_UPLOAD_BYTES} bytes")
    ext = PurePath(filename or "").suffix.lower()
    expected = _EXTENSIONS.get(ext)
    if expected is None:
        raise UploadRejected(f"unsupported file extension {ext or '(none)'}; allowed: {', '.join(sorted(_EXTENSIONS))}")

    if data.startswith(b"%PDF-"):
        actual = "application/pdf"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        actual = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        actual = "image/jpeg"
    else:
        if b"\x00" in data:
            raise UploadRejected("binary content is not a supported text document")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UploadRejected("text documents must be UTF-8") from exc
        actual = "text/plain"
        if ext == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise UploadRejected(f"invalid JSON: {exc.msg}") from exc
            actual = "application/json"

    if actual != expected:
        raise UploadRejected(f"content is {actual} but the extension says {expected}")
    declared = (declared_mime or "").split(";")[0].strip().lower()
    if declared not in _DECLARED_OK[actual]:
        raise UploadRejected(f"declared type {declared!r} does not match content {actual}")
    return actual, ext


@dataclass
class ExtractionOutcome:
    status: str  # extracted | ocr_required | failed
    method: str | None
    pages: list[str] = field(default_factory=list)
    error: str | None = None


def _pdf_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise UploadRejected(f"PDF has {len(reader.pages)} pages; limit is {MAX_PDF_PAGES}")
    return [page.extract_text() or "" for page in reader.pages]


def extract(mime: str, data: bytes) -> ExtractionOutcome:
    if mime in ("text/plain", "application/json"):
        text = data.decode("utf-8-sig")
        if not text.strip():
            return ExtractionOutcome("failed", "utf8_text", error="document has no text")
        return ExtractionOutcome("extracted", "json_text" if mime == "application/json" else "utf8_text", [text])
    if mime in ("image/png", "image/jpeg"):
        return ExtractionOutcome("ocr_required", None, error="image evidence requires OCR (disabled in P0)")
    if mime == "application/pdf":
        future = _executor.submit(_pdf_pages, data)
        try:
            pages = future.result(timeout=PARSE_TIMEOUT_SECONDS)
        except FutureTimeout:
            return ExtractionOutcome("failed", "pdf_text", error=f"PDF parsing exceeded {PARSE_TIMEOUT_SECONDS}s")
        except UploadRejected as exc:
            return ExtractionOutcome("failed", "pdf_text", error=str(exc))
        except Exception as exc:  # malformed PDFs raise many pypdf error types
            log.info("PDF parse failure: %s", exc)
            return ExtractionOutcome("failed", "pdf_text", error=f"unreadable PDF: {type(exc).__name__}")
        if not any(p.strip() for p in pages):
            return ExtractionOutcome(
                "ocr_required", "pdf_text", error="PDF has no extractable text layer (scanned/image-only)"
            )
        return ExtractionOutcome("extracted", "pdf_text", pages)
    return ExtractionOutcome("failed", None, error=f"unsupported type {mime}")
