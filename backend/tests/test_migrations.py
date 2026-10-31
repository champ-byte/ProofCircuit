from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from app.db.migrate import alembic_config


def test_upgrade_populated_m0_database_to_head(tmp_path: Path) -> None:
    db = tmp_path / "m0.db"
    cfg = alembic_config(f"sqlite:///{db}")
    command.upgrade(cfg, "879c148df646")  # M0 schema
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO merchants (id, name, mid, default_locale, synthetic, created_at) "
        "VALUES ('m1','M','MID-X','en-IN',1,'2030-01-01 00:00:00')"
    )
    con.execute(
        "INSERT INTO cases (id, merchant_id, mid, external_dispute_id, transaction_id, order_id, amount_paise, "
        "currency, reason, deadline_utc, deadline_raw, timezone_assumption, locale, workflow_state, provider_status, "
        "flags, version, pod_repair_count, synthetic, created_at, updated_at) VALUES ('c1','m1','MID-X','D','T','O',"
        "100,'INR','goods_not_received','2030-01-03 00:00:00','2030-01-03 05:30:00','Asia/Kolkata','en-IN','NEW',"
        "'NEW','[]',1,0,1,'2030-01-01 00:00:00','2030-01-01 00:00:00')"
    )
    con.execute(
        "INSERT INTO evidence_documents (id, case_id, merchant_id, original_filename, storage_key, mime_type, "
        "size_bytes, sha256, extraction_status, created_at) VALUES ('d1','c1','m1','a.txt','k','text/plain',1,'x',"
        "'pending','2030-01-01 00:00:00')"
    )
    con.execute(
        "INSERT INTO validation_findings (id, case_id, rule_id, severity, status, source_ids, explanation, "
        "case_version, created_at) VALUES ('f1','c1','R','info','open','[]','e',1,'2030-01-01 00:00:00')"
    )
    con.commit()
    con.close()

    command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    assert con.execute("SELECT doc_type, page_count FROM evidence_documents").fetchone() == ("unknown", 0)
    assert con.execute("SELECT fingerprint, details FROM validation_findings").fetchone() == ("", "{}")
    con.close()
    command.downgrade(cfg, "879c148df646")
