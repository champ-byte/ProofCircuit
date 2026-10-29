"""Render synthetic hero documents with dates relative to the case, never hard-coded."""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

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


def render_hero_document(name: str, case: Case, settings: Settings) -> tuple[str, bytes]:
    if name not in HERO_DOCUMENTS:
        raise KeyError(name)
    filename = HERO_DOCUMENTS[name]
    if case.transaction_at_utc is None:
        raise ValueError("case has no transaction date to anchor fixture dates")
    order_date = case.transaction_at_utc.astimezone(ZoneInfo(settings.paytm_naive_timezone)).date()
    text = (HERO_DIR / filename).read_text(encoding="utf-8")
    text = text.replace("{{ORDER_DATE}}", format_doc_date(order_date))
    text = text.replace("{{DELIVERY_DATE}}", format_doc_date(order_date + timedelta(days=1)))
    return filename, text.encode("utf-8")
