"""Deterministic source spans (PRD Section 8.3).

A proposer (rule-based extractor now, the LLM later) supplies only the exact `raw_value`
substring and optionally an anchor/quote around it. Python locates it in the stored page text
and computes zero-based, end-exclusive Unicode code-point offsets. Python `str` indexing is by
code point, so `text[start:end]` is the citation. Nobody ever asks a model to count indices.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

Verification = Literal["span_verified", "not_found", "ambiguous", "invalid_anchor"]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _occurrences(haystack: str, needle: str) -> list[int]:
    found: list[int] = []
    start = haystack.find(needle)
    while start != -1:
        found.append(start)
        start = haystack.find(needle, start + 1)
    return found


@dataclass(frozen=True)
class SpanResult:
    verification: Verification
    start: int | None = None
    end: int | None = None
    detail: str = ""


def locate_span(page_text: str, raw_value: str, anchor: str | None = None) -> SpanResult:
    """Find a unique occurrence of `raw_value`; use `anchor` only to disambiguate.

    - not found -> `not_found`
    - several matches and no unique anchor -> `ambiguous` (never pick the first arbitrarily)
    """
    if not raw_value:
        return SpanResult("not_found", detail="empty raw_value")
    if anchor:
        anchor_hits = _occurrences(page_text, anchor)
        if len(anchor_hits) != 1:
            return SpanResult(
                "invalid_anchor" if not anchor_hits else "ambiguous",
                detail=f"anchor occurs {len(anchor_hits)} times",
            )
        inner = _occurrences(anchor, raw_value)
        if len(inner) != 1:
            return SpanResult(
                "not_found" if not inner else "ambiguous", detail=f"value occurs {len(inner)} times in anchor"
            )
        start = anchor_hits[0] + inner[0]
        return SpanResult("span_verified", start, start + len(raw_value))

    hits = _occurrences(page_text, raw_value)
    if not hits:
        return SpanResult("not_found", detail="value not present in page text")
    if len(hits) > 1:
        return SpanResult("ambiguous", detail=f"value occurs {len(hits)} times; anchor required")
    return SpanResult("span_verified", hits[0], hits[0] + len(raw_value))


def verify_span(page_text: str, expected_sha256: str, start: int, end: int, raw_value: str) -> bool:
    """Re-check a stored citation against the exact stored text and its hash."""
    return (
        text_sha256(page_text) == expected_sha256
        and 0 <= start < end <= len(page_text)
        and page_text[start:end] == raw_value
    )


def snippet(page_text: str, start: int, end: int, context: int = 40) -> dict[str, str | int]:
    """Backend-generated snippet so the browser never slices by UTF-16 indices."""
    lo = max(0, start - context)
    hi = min(len(page_text), end + context)
    return {
        "before": page_text[lo:start],
        "match": page_text[start:end],
        "after": page_text[end:hi],
        "start": start,
        "end": end,
    }
