"""Render synthetic hero documents with dates relative to the case, never hard-coded.

The rendered PDFs *are* the synthetic originals in the demo world (text layer, deterministic
bytes). Templates live in fixtures/hero/*.txt for review.
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.config import REPO_ROOT, Settings
from app.db.models import Case

HERO_DIR = REPO_ROOT / "fixtures" / "hero"
HERO_DOCUMENTS = {
    "invoice": "invoice_ORD-DEMO-18500.txt",
    "delivery_receipt_wrong_order": "delivery_receipt_wrong_order.txt",
    "delivery_receipt_correct": "delivery_receipt_correct.txt",
}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_doc_date(d: date) -> str:
    """02-Jan-2030, locale-independent."""
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def text_pdf(lines: list[str]) -> bytes:
    """Deterministic single-page PDF with a real text layer (Latin text only)."""
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4, invariant=1)
    pdf.setFont("Helvetica", 11)
    y = 800
    for line in lines:
        pdf.drawString(60, y, line)
        y -= 16
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


def render_hero_text(name: str, case: Case, settings: Settings) -> str:
    if name not in HERO_DOCUMENTS:
        raise KeyError(name)
    if case.transaction_at_utc is None:
        raise ValueError("case has no transaction date to anchor fixture dates")
    order_date = case.transaction_at_utc.astimezone(ZoneInfo(settings.paytm_naive_timezone)).date()
    text = (HERO_DIR / HERO_DOCUMENTS[name]).read_text(encoding="utf-8")
    text = text.replace("{{ORDER_DATE}}", format_doc_date(order_date))
    return text.replace("{{DELIVERY_DATE}}", format_doc_date(order_date + timedelta(days=1)))


def render_hero_document(name: str, case: Case, settings: Settings) -> tuple[str, bytes]:
    text = render_hero_text(name, case, settings)
    filename = HERO_DOCUMENTS[name].removesuffix(".txt") + ".pdf"
    return filename, text_pdf(text.rstrip("\n").splitlines())
