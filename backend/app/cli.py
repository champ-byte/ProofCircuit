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


if __name__ == "__main__":
    raise SystemExit(main())
