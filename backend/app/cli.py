"""Operator commands: `uv run python -m app.cli {init-db,seed,reset,providers,check-config}`."""

from __future__ import annotations

import argparse
import json
import sys

from app.config import SettingsError, get_settings
from app.db.migrate import upgrade_to_head
from app.db.session import init_engine, session_scope
from app.domain.clock import get_clock
from app.providers.readiness import provider_report
from app.providers.speech import WHISPER_LANGUAGES
from app.services.seed import reset_demo, seed_demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proofcircuit")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-config", help="validate settings without printing secrets")
    sub.add_parser("init-db", help="create/upgrade the database schema")
    sub.add_parser("seed", help="seed the synthetic hero case (idempotent)")
    reset = sub.add_parser("reset", help="delete all demo data and runtime files, then reseed")
    reset.add_argument("--yes", action="store_true", help="confirm the destructive reset")
    sub.add_parser("providers", help="print provider readiness (no secrets)")
    smoke = sub.add_parser("smoke-reasoner", help="live smoke test of a reasoner (spends 1-4 model calls)")
    smoke.add_argument("--provider", default=None, help="gemini | openrouter (default: REASONER_PROVIDER)")
    sub.add_parser("smoke-speech", help="transcribe the synthetic Marathi fixture with local faster-whisper")
    sub.add_parser("speech-download", help="explicitly download WHISPER_MODEL into the Hugging Face cache")
    sub.add_parser("corpus", help="(re)write the deterministic 40-case corpus and its separate ground truth")
    ev = sub.add_parser("evaluate", help="run corpus cases against a running backend (live model)")
    ev.add_argument("--base-url", default="http://127.0.0.1:8000")
    ev.add_argument("--split", default="first_pass", choices=["first_pass", "development", "held_out", "all"])
    ev.add_argument("--cases", default=None, help="comma-separated corpus IDs instead of a split, e.g. EVAL-001")
    ev.add_argument("--exclude", default=None, help="comma-separated corpus IDs to skip (e.g. already run)")
    ev.add_argument("--run-tag", default=None, help="suffix for dispute IDs (default: UTC timestamp)")
    ev.add_argument("--out", default=None, help="results file (default: docs/evaluation/results-<tag>.json)")
    ev.add_argument("--allow-manual", action="store_true", help="debug the harness without a live model")
    mg = sub.add_parser("merge-results", help="combine disjoint evaluation exports into one report")
    mg.add_argument("files", nargs="+")
    mg.add_argument("--out", required=True)
    tf = sub.add_parser("transcribe-file", help="measure local faster-whisper on a recording (records no check)")
    tf.add_argument("audio", help="path to the recording")
    tf.add_argument("--locale", default="mr-IN", choices=sorted(WHISPER_LANGUAGES))
    tf.add_argument("--reference", default=None, help="UTF-8 text file with what was said; adds the CER")
    tf.add_argument("--out", default=None, help="write the UTF-8 JSON result here instead of stdout")
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except (SettingsError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "check-config":
        print(
            f"OK: app_env={settings.app_env} reasoner={settings.reasoner_provider} db={settings.resolved_database_url}"
        )
        return 0
    if args.cmd == "providers":
        settings.data_path.mkdir(parents=True, exist_ok=True)
        upgrade_to_head(settings.resolved_database_url)
        init_engine(settings)
        print(json.dumps(provider_report(settings), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "smoke-reasoner":
        return _smoke(settings, args.provider or settings.reasoner_provider)
    if args.cmd == "smoke-speech":
        return _smoke_speech(settings)
    if args.cmd == "speech-download":
        from faster_whisper.utils import download_model

        print(f"Model {settings.whisper_model!r} at {download_model(settings.whisper_model)}")
        return 0
    if args.cmd == "transcribe-file":
        return _transcribe_file(settings, args.audio, args.locale, args.reference, args.out)
    if args.cmd == "corpus":
        from app.evaluation import corpus

        corpus.write()
        print(f"Wrote {corpus.CORPUS_PATH} and {corpus.GROUND_TRUTH_PATH}")
        return 0
    if args.cmd == "evaluate":
        return _evaluate(settings, args)
    if args.cmd == "merge-results":
        from pathlib import Path

        from app.evaluation import corpus
        from app.evaluation.harness import merge_reports

        reports = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.files]
        merged = merge_reports(reports, planned=settings.evaluation_target_cases, categories=corpus.CATEGORIES)
        Path(args.out).write_text(
            json.dumps(merged, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
        )
        print(f"{merged['label']}; correct {merged['metrics']['correct']}/{merged['executed']} -> {args.out}")
        return 0

    settings.data_path.mkdir(parents=True, exist_ok=True)
    upgrade_to_head(settings.resolved_database_url)
    init_engine(settings)
    if args.cmd == "init-db":
        print(f"Database at head: {settings.resolved_database_url}")
        return 0
    if args.cmd == "seed":
        with session_scope() as session:
            case = seed_demo(session, settings, get_clock())
            print(
                f"Seeded case {case.id} ({case.external_dispute_id}, deadline {case.deadline_raw} "
                f"{case.timezone_assumption})"
            )
        return 0
    if args.cmd == "reset":
        if not args.yes:
            print("Refusing to reset without --yes", file=sys.stderr)
            return 1
        with session_scope() as session:
            reset_demo(session, settings)
        with session_scope() as session:
            case = seed_demo(session, settings, get_clock())
            print(f"Reset complete; reseeded case {case.id}")
        return 0
    return 1


def _smoke(settings, provider: str) -> int:  # type: ignore[no-untyped-def]
    import asyncio
    from types import SimpleNamespace

    from app.services.smoke import smoke_test

    settings.data_path.mkdir(parents=True, exist_ok=True)
    upgrade_to_head(settings.resolved_database_url)
    init_engine(settings)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    result = asyncio.run(smoke_test(app, provider))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


def _smoke_speech(settings) -> int:  # type: ignore[no-untyped-def]
    import asyncio

    from app.services.speech_smoke import smoke_speech

    settings.data_path.mkdir(parents=True, exist_ok=True)
    upgrade_to_head(settings.resolved_database_url)
    init_engine(settings)
    result = asyncio.run(smoke_speech(settings))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


def _evaluate(settings, args) -> int:  # type: ignore[no-untyped-def]
    """Drive corpus cases through a running backend's HTTP API and export measured results."""
    from datetime import UTC, datetime
    from pathlib import Path

    import httpx

    from app.api.evaluation import RESULTS_DIR
    from app.evaluation import corpus
    from app.evaluation.harness import Harness, run_suite

    client = httpx.Client(base_url=args.base_url, timeout=120)
    health = client.get("/api/health").json()
    mode = health["reasoning_mode"]
    if mode["mode"] != "live" and not args.allow_manual:
        print(f"Reasoning mode is {mode['label']!r}, not live: run `app.cli smoke-reasoner` first.", file=sys.stderr)
        return 2
    if client.post("/api/demo/session", json={"mid": corpus.EVAL_MID, "handle": "operator"}).status_code == 404:
        demo = client.post("/api/demo/session", json={"mid": "MID-DEMO-001", "handle": "operator"}).json()["token"]
        client.post("/api/demo/seed", headers={"Authorization": f"Bearer {demo}"}).raise_for_status()
    specs = corpus.load("all" if args.cases else args.split)
    if args.cases:
        wanted = set(args.cases.split(","))
        specs = [s for s in specs if s["case_id"] in wanted]
    if args.exclude:
        specs = [s for s in specs if s["case_id"] not in set(args.exclude.split(","))]
    tag = args.run_tag or datetime.now(UTC).strftime("%m%d%H%M")
    harness = Harness(client, log=lambda m: print(m, flush=True))
    report = run_suite(
        harness,
        specs,
        tag,
        planned=settings.evaluation_target_cases,
        split=args.cases or args.split,
        mode={**mode, "autorun": health.get("agent_autorun")},
        categories=corpus.CATEGORIES,
        log=lambda m: print(m, flush=True),
    )
    out = Path(args.out) if args.out else RESULTS_DIR / f"results-{tag}.json"
    if mode["mode"] != "live" and not args.out:
        out = settings.data_path / "evaluation" / f"manual-{tag}.json"  # never shown as measured AI results
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(f"{report['label']}; correct {report['metrics']['correct']}/{report['executed']} -> {out}")
    return 0


def _transcribe_file(settings, audio: str, locale: str, reference: str | None, out: str | None) -> int:  # type: ignore[no-untyped-def]
    import asyncio
    from pathlib import Path

    from app.services.speech_smoke import transcribe_file

    ref = Path(reference).read_text(encoding="utf-8").strip() if reference else None
    result = asyncio.run(transcribe_file(settings, Path(audio), locale, ref))
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        cer = result.get("character_error_rate")
        print(f"ok={result['ok']} cer={cer} latency_ms={result.get('latency_ms')} -> {out}")
    else:
        print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
