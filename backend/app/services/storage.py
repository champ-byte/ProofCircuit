"""Original evidence bytes on local disk under server-generated names (never user paths)."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings


def _root(settings: Settings) -> Path:
    return (settings.data_path / "evidence").resolve()


def save_original(settings: Settings, case_id: str, doc_id: str, ext: str, data: bytes) -> str:
    rel = Path(case_id) / f"{doc_id}{ext}"
    path = _root(settings) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel.as_posix()


def read_original(settings: Settings, storage_key: str) -> bytes:
    root = _root(settings)
    path = (root / storage_key).resolve()
    if root not in path.parents:
        raise ValueError("storage key escapes the evidence directory")
    return path.read_bytes()
