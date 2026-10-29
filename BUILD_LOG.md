# ProofCircuit build log

Entries record commands actually run, test results and open issues. Nothing below is claimed working without a passing test or a real run.

## Environment (cloud session, 2026-10-29)

- Python 3.13.17, uv 0.11.32, Node 22.22.0, npm 10.9.4, Playwright Chromium (preinstalled).
- Network: PyPI, npm and `generativelanguage.googleapis.com` are reachable. **`openrouter.ai` is blocked** by this environment's network policy (proxy CONNECT 403). `ai.google.dev` docs are also blocked.
- Ollama is not installed, so the local Gemma fallback cannot run in this environment.
- `GEMINI_API_KEY` is set in the environment settings, not in the repo. A read-only `GET /v1beta/models` with the key succeeded. Gemini 3.x text models available to the key include `gemini-3.5-flash-lite`, `gemini-3.8-flash`, `gemini-3.1-flash-lite`, `gemini-3-flash-preview` and `gemini-3.1-pro-preview`. No generation call has been made yet.

## Decisions that deviate from PRD.md

1. **Gemini is the default primary reasoner** (`REASONER_PROVIDER=gemini`), using the user's free-tier key; OpenRouter becomes the optional fallback (`FALLBACK_PROVIDER=openrouter`, disabled by default). PRD §6.2 made OpenRouter primary and Gemini a P1 adapter. This was the user's decision, given that `openrouter.ai` is blocked here and Gemini is reachable.
2. **Gemini 3.x models only**, per the user: Gemini 2.5 is deprecated. The default is `gemini-3.5-flash-lite`, the newest Flash-Lite available to the key. Flash-Lite was chosen over Flash for free-tier headroom. A forum report (unverified) puts Gemini 3.8 Flash's free tier at about 20 requests/day, which is below one ten-case pass. Free-tier quotas will be measured in M3, not assumed.
3. Free-tier Gemini data may be used by Google. That is acceptable only because the app sends synthetic data. The readiness notes and README say so.
4. No `scripts/seed_demo.py`. Seed/reset live in the backend CLI (`python -m app.cli seed|reset --yes`) so they share the app's settings and migrations. The PRD layout says to adapt it to conventions.
5. In `DEMO_MODE`, an empty database is seeded automatically at startup so a fresh start shows the hero case. A populated database is never reseeded.

## M0 Bootstrap: done

**Built**

- `backend/`: FastAPI app factory (`uvicorn --factory app.main:create_app`), pydantic-settings config with release guards, and SQLAlchemy 2 models for every PRD §10.2 entity. This includes the pending-work/outbox tables and an independent simulator store (`sim_disputes`, `sim_submissions`).
  - Release guards: `PAYTM_MODE` must be `simulator`, `PAYTM_LIVE_ENABLED=true` is rejected, workers must be 1, and placeholder secrets are never used.
  - Persistence: SQLite in WAL mode with a busy timeout and foreign keys. Times are stored as UTC through a type that rejects naive datetimes. Money is integer paise.
  - Alembic: initial migration `0001_initial_schema.py`, applied automatically on startup and by `cli init-db`.
- Paytm boundary helpers: Decimal-string → paise (no rounding, rejects more than two decimals, negatives and non-strings), naive `YYYY-MM-DD HH:mm:ss` under the configured IST *assumption* → aware UTC, `transactionId` spelling, `disputeutr`/`disputeUtr` mapping with conflict rejection, documented status aliases only, and a canonical payload hash.
- Case intake service: one case per (merchant, dispute). A repeat event records a duplicate audit event instead of creating a second case.
- Seed fixtures:
  - `fixtures/demo_org.json`: Metro Furniture Demo plus a second merchant for isolation checks, owner, reviewer, operator and delivery/billing staff.
  - The hero callback template, with the deadline set 48h after the seed clock.
  - Hero invoice and wrong/correct delivery receipts, used from M1.
- APIs: `GET /api/health`, `GET /api/providers` (no secrets), `GET /api/demo/users`, `POST /api/demo/session` (HMAC-signed, merchant-scoped demo token, revalidated against the DB), `POST /api/demo/seed` and `POST /api/demo/reset` (operator only; reset needs `confirm=true`), and `GET /api/cases` and `GET /api/cases/{id}` (merchant-scoped, scoped 404, timeline from the audit table).
- Provider readiness:
  - Reasoner statuses are `unconfigured`, `configured_untested`, `ready`, `failed` and `disabled`. Only `ready`, after a passing smoke test, switches the badge from **Manual** to live.
  - Integrations (Paytm simulator, local messaging, SQL memory, speech/OCR/n8n) are reported as ready, disabled or not implemented.
- Startup recovery scan: counts pending work, outbox, interrupted runs and uncertain submissions, and audits them. Actual resume/reconcile is M2.
- `frontend/`: Vite + React + TypeScript `/cases` queue. It has the persistent badges (`Synthetic data`, `Paytm simulator`, `Reasoning: <mode>`), a demo identity selector, amount at risk, the deadline in IST with a countdown, and workflow/provider state. The light theme has visible focus.

**Commands run**

```bash
cd backend
uv add fastapi "uvicorn[standard]" "sqlalchemy>=2" alembic pydantic pydantic-settings httpx python-multipart pypdf reportlab
uv add --dev pytest pytest-asyncio ruff
uv run alembic revision --autogenerate -m "initial schema"
uv run pytest -q          # 45 passed
uv run ruff check .       # All checks passed
uv run ruff format --check .
uv sync
uv run python -m app.cli init-db
uv run python -m app.cli seed     # ran twice: same case id
uv run python -m app.cli check-config
uv run python -m app.cli reset --yes
uv run python -m app.cli providers
```

```bash
cd frontend
npm create vite@latest frontend -- --template react-ts --no-interactive
npm install
npm ci
npm run build    # tsc + vite build OK
npm run lint     # oxlint clean
```

**Tests (45 passing)**: `backend/tests/test_m0_*.py`

- Config guards: live Paytm rejected, multiple workers rejected, placeholder secrets replaced (dev) or rejected (production), free-first defaults, env-var precedence, relative SQLite path resolution.
- Paytm boundary (a C01 subset): the PRD sample maps to 1,850,000 paise and `2030-01-03T18:29:59Z`; disputeAmount is used rather than transactionAmount; a non-midnight deadline is preserved; malformed dates and amounts are rejected; `txnId` is not guessed; null/empty optional fields are handled; UTR alias conflicts are rejected; status aliases; canonical hash; ₹ Indian grouping.
- Bootstrap API: all tables migrated on a fresh DB; health OK with no keys; Gemini `unconfigured` without a key; a key is never echoed and stays `configured_untested` (badge Manual) until a smoke result is recorded; the seeded hero case is visible with the correct amount, 48h deadline and timeline; tenant isolation (an empty list plus scoped 404); 401 without a token or with a tampered one; seed is idempotent and operator-only; reset needs confirmation, reseeds, and invalidates old sessions; a restart keeps data without reseeding.

**Real run (exit criterion)**

- From an empty `data/`, the backend started (`uvicorn --factory app.main:create_app --workers 1`) and auto-seeded. The frontend ran on Vite with the `/api` proxy.
- Playwright Chromium loaded `/` and showed DSP-DEMO-001, `₹18,500.00`, a deadline 48h ahead in IST and the badge `Reasoning: Manual`. Switching to the other merchant's owner showed "No dispute cases". Screenshot: `docs/m0-cases.png`.

## Open issues / next

- **M1 next**: evidence upload, extraction (TXT/JSON/PDF text), Python-computed code-point citations, checklist and deterministic validators (C02).
- `POST /api/dispute-events` (signed S2S intake endpoint), the simulator APIs and the runner are M2. The normalization they use already exists and is tested.
- Gemini adapter and live smoke test are M3. They must measure actual free-tier limits for `gemini-3.5-flash-lite` and handle 429s and daily caps.
- OpenRouter fallback cannot be exercised here until `openrouter.ai` is allowed in the environment's network settings and `OPENROUTER_API_KEY` is set.
- Starlette deprecation warning from the test client ("install httpx2") is harmless for now.
- Pre-event code eligibility under the hackathon rules is still unconfirmed (PRD §19.1).
