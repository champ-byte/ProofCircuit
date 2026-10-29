"""C05 Submission contract: derived/cited orderStatus, no autonomous defense from AWB alone,
file limits, deadline at/after due, comments cap with verified facts only, exact non-midnight
deadlines, stale-pack protection and immutable pack versions."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.domain.clock import FixedClock
from tests.helpers import Hero


@pytest.fixture
def hero(client: TestClient, settings) -> Hero:  # type: ignore[no-untyped-def]
    return Hero(client, settings)


def manifest(hero: Hero, version: int) -> dict:  # type: ignore[type-arg]
    return hero.c.get(f"/api/cases/{hero.case_id}/pack/{version}/manifest.json", headers=hero.owner).json()


def test_pack_derives_and_cites_order_status(hero: Hero) -> None:
    built = hero.make_ready()["result"]
    assert built["order_status"] == "ORDER_DELIVERED" and built["files"] == 3 and built["version"] == 1
    m = manifest(hero, 1)
    cites = m["order_status"]["citations"]
    assert cites and all(c["filename"] == "delivery_receipt_correct.pdf" for c in cites)
    # Each citation resolves to the stored page text of its original document.
    for c in cites:
        doc = hero.c.get(f"/api/evidence/{c['document_id']}", headers=hero.owner).json()
        page = doc["pages"][c["page"] - 1]["text"]
        assert page[c["start"] : c["end"]] == c["raw_value"]
    # Upload files: cover summary + original invoice PDF + original delivery receipt PDF, in order.
    assert [f["role"] for f in m["upload_files"]] == ["summary", "invoice", "delivery_record"]


def test_comments_use_only_verified_facts_and_fit_cap(hero: Hero) -> None:
    built = hero.make_ready()["result"]
    comments = built["comments"]
    assert len(comments) <= 240
    m = manifest(hero, 1)
    cited_values = {c["raw_value"] for claim in m["claims"] for c in claim["citations"]}
    for token in ("ORD-DEMO-18500", "DLV-DEMO-0418", "INV-DEMO-7731"):
        assert token in comments and token in cited_values
    assert "file 3" in comments and "file 2" in comments  # positions in the uploaded files list
    for forbidden in (m["intent_digest"], "sha256", "["):  # no hashes or offsets in the remark
        assert forbidden not in comments


def test_pack_files_match_manifest_hashes_and_index_is_escaped(hero: Hero) -> None:
    hero.make_ready()
    m = manifest(hero, 1)
    cover = hero.c.get(f"/api/cases/{hero.case_id}/pack/1/cover.pdf", headers=hero.owner)
    assert hashlib.sha256(cover.content).hexdigest() == m["upload_files"][0]["sha256"]
    index = hero.c.get(f"/api/cases/{hero.case_id}/pack/1/evidence-index.html", headers=hero.owner)
    assert index.headers["content-security-policy"].startswith("default-src 'none'")
    assert "attachment" in index.headers["content-disposition"]


def test_index_escapes_untrusted_document_text(hero: Hero) -> None:
    receipt = (
        "DELIVERY RECEIPT\nReceipt No: <script>alert(1)</script>\nOrder ID: ORD-DEMO-18500\nDelivered On: 31-Dec-2029\n"
    )
    assert hero.upload("r.txt", receipt, "text/plain").status_code == 201
    built = hero.act("build_evidence_pack")
    assert built["status"] == "ok"
    html = hero.c.get(f"/api/cases/{hero.case_id}/pack/1/evidence-index.html", headers=hero.owner).text
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_text_originals_are_cited_not_redrawn(hero: Hero) -> None:
    receipt = "DELIVERY RECEIPT\nReceipt No: DLV-T-1\nOrder ID: ORD-DEMO-18500\nDelivered On: 31-Dec-2029\n"
    hero.upload("receipt.txt", receipt, "text/plain")
    built = hero.act("build_evidence_pack")["result"]
    m = manifest(hero, built["version"])
    assert [f["role"] for f in m["upload_files"]] == ["summary", "invoice"]  # TXT is not uploaded
    receipt_doc = next(d for d in m["evidence_documents"] if d["filename"] == "receipt.txt")
    assert receipt_doc["uploaded"] is False
    assert "see file 1" in built["comments"]


def test_dispatch_only_cannot_build_or_submit(hero: Hero) -> None:
    hero.upload(
        "awb.txt", "SHIPPING LABEL\nAWB No: AWB-1\nOrder ID: ORD-DEMO-18500\nDispatched On: 30-Dec-2029\n", "text/plain"
    )
    pack = hero.act("build_evidence_pack")
    assert pack["status"] == "denied"
    submit = hero.act("submit_defense")
    assert submit["status"] == "denied" and any("no evidence pack" in r for r in submit["result"]["reasons"])
    assert hero.receipts() == []


def test_submit_verified_happy_path(hero: Hero) -> None:
    hero.make_ready()
    result = hero.act("submit_defense")
    assert result["status"] == "ok" and result["result"]["status"] == "verified"
    case = hero.case()
    assert case["workflow_state"] == "MONITORING" and case["provider_status"] == "POD_UPLOAD"
    [sub] = hero.submissions()
    [receipt] = hero.receipts()
    assert sub["state"] == "verified" and sub["provider_reference"] == receipt["reference"]
    assert receipt["intentDigest"] == sub["intent_digest"] == manifest(hero, 1)["intent_digest"]
    assert (
        receipt["comments"] == hero.c.get(f"/api/cases/{hero.case_id}/pack", headers=hero.owner).json()[0]["comments"]
    )


def test_deadline_is_exact_and_denies_at_the_instant(hero: Hero, clock: FixedClock) -> None:
    hero.make_ready()
    clock.advance(timedelta(hours=48))  # deadline instant (seeded 48h ahead, whole seconds)
    hero.relogin()
    denied = hero.act("submit_defense")
    assert denied["status"] == "denied" and any("deadline" in r for r in denied["result"]["reasons"])
    assert hero.receipts() == []


def test_one_second_before_deadline_submits(hero: Hero, clock: FixedClock) -> None:
    hero.make_ready()
    clock.advance(timedelta(hours=48) - timedelta(seconds=1))
    hero.relogin()
    assert hero.act("submit_defense")["result"]["status"] == "verified"


def test_stale_pack_is_denied_and_rebuild_creates_new_version(hero: Hero) -> None:
    hero.make_ready()
    again = hero.act("build_evidence_pack")["result"]
    assert again["created"] is False and again["version"] == 1  # identical content reuses the pack
    hero.upload("note.txt", "Courier note: customer asked for evening delivery.\n", "text/plain")
    denied = hero.act("submit_defense")
    assert denied["status"] == "denied" and any("rebuild" in r for r in denied["result"]["reasons"])
    v2 = hero.act("build_evidence_pack")["result"]
    assert v2["created"] is True and v2["version"] == 2
    packs = hero.c.get(f"/api/cases/{hero.case_id}/pack", headers=hero.owner).json()
    assert [p["stale"] for p in packs] == [True, False]
    assert manifest(hero, 1)["case_version"] < manifest(hero, 2)["case_version"]  # v1 unchanged on disk
    assert hero.act("submit_defense")["result"]["status"] == "verified"


def test_unconfirmed_reason_blocks_submission(hero: Hero) -> None:
    from tests.test_c01_paytm_boundary import NEW_DISPUTE, callback

    created = callback(hero, NEW_DISPUTE, event_id="evt-x").json()
    hero.case_id = created["case_id"]
    denied = hero.act("submit_defense")
    assert any("reason is not confirmed" in r for r in denied["result"]["reasons"])


def test_policy_file_limits(hero: Hero, settings) -> None:  # type: ignore[no-untyped-def]
    from app.db.models import Case, EvidencePack
    from app.db.session import session_scope
    from app.services.policy import check_defense

    hero.make_ready()
    with session_scope() as s:
        case = s.get(Case, hero.case_id)
        pack = s.get(EvidencePack, case.latest_pack_id)  # type: ignore[union-attr]
        base = list(pack.upload_files)  # type: ignore[union-attr]
        for files, check in (
            (base * 2, "file_count"),
            ([{**base[0], "size": 5_000_001}], "file_size"),
            ([{**base[0], "mime": "text/plain"}], "file_types"),
        ):
            pack.upload_files = files  # type: ignore[union-attr]
            decision = check_defense(s, settings, case, pack, actor_kind="human")  # type: ignore[arg-type]
            assert decision.checks[check] is False and not decision.allowed
        pack.comments = "x" * 241  # type: ignore[union-attr]
        assert check_defense(s, settings, case, pack, actor_kind="human").checks["comments_length"] is False  # type: ignore[arg-type]
        s.rollback()


def test_agent_auto_submit_switch(hero: Hero, settings) -> None:  # type: ignore[no-untyped-def]
    from app.db.models import Case, EvidencePack
    from app.db.session import session_scope
    from app.services.policy import check_defense

    hero.make_ready()
    settings.auto_submit_simulator = False
    with session_scope() as s:
        case = s.get(Case, hero.case_id)
        pack = s.get(EvidencePack, case.latest_pack_id)  # type: ignore[union-attr]
        assert check_defense(s, settings, case, pack, actor_kind="agent").checks["auto_submit_enabled"] is False  # type: ignore[arg-type]
        assert check_defense(s, settings, case, pack, actor_kind="human").allowed  # type: ignore[arg-type]
    settings.auto_submit_simulator = True


def test_manifest_is_canonical_json(hero: Hero) -> None:
    hero.make_ready()
    packs = hero.c.get(f"/api/cases/{hero.case_id}/pack", headers=hero.owner).json()
    m = manifest(hero, 1)
    canonical = json.dumps(m, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert hashlib.sha256(canonical).hexdigest() == packs[0]["pack_hash"]
