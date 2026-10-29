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

## M1 Evidence vertical slice: done

**Built**

- `POST /api/cases/{id}/evidence`: multipart upload by any role of the case's merchant. It checks the extension allowlist, the declared MIME type, the actual content (magic bytes, UTF-8, JSON validity), a 5,000,000-byte cap and a 20-page PDF cap. Rejections return 422 and store nothing. Identical bytes on the same case return the existing document (200) instead of creating a duplicate.
- The original bytes are stored under a server-generated path (`data/evidence/<case>/<doc><ext>`) and hashed with SHA-256 **before** parsing. User filenames are sanitized and never used as paths.
- Extraction:
  - TXT is stored as UTF-8 text and JSON keeps its original text. Text-layer PDFs go through pypdf, run in a worker thread with a 15 s timeout.
  - PNG/JPEG and image-only PDFs get `OCR_REQUIRED`, never an empty "successful" extraction. Their originals are kept.
  - Text is stored per page with a per-page SHA-256.
- Fact proposals: a **deterministic rule-based proposer** reads labelled lines (English plus a few Hindi/Marathi labels) and JSON keys, and outputs `(field, raw_value, anchor)`. The M3 LLM proposer can supply the same shape.
- **Citations are computed in Python** (`app/domain/citations.py`):
  - Offsets are zero-based, end-exclusive Unicode code points into the stored page text.
  - A value must match exactly once. Several matches need a unique anchor, otherwise the fact is `ambiguous`; no match is `not_found`.
  - Every view rechecks `text[start:end] == raw_value` against the stored text hash. Snippets are generated by the backend, and the UI slices with `Array.from` (code points).
- Normalization happens only after a value is located:
  - IDs keep their raw formatting and are only trimmed.
  - Amounts use Decimal and become paise with an explicit currency. A missing currency is recorded as `UNKNOWN`, and invalid digit grouping is rejected.
  - Dates are accepted only as ISO or `DD-Mon-YYYY`. Slash dates are ambiguous and stay unknown.
- Document classification is deterministic: invoice, delivery_record, dispatch_record or other.
- The checklist follows the demo policy for goods not received (PRD 8.2). It has three items: order linkage, invoice, and delivery record. Each is `missing`, `supported`, `conflicting` or `review_required` and carries its sources and an assignee (billing or delivery staff).
- Validators (`app/services/validation.py`):

  | Severity | Findings |
  | --- | --- |
  | Blocking | `ORDER_MISMATCH`, `TRANSACTION_MISMATCH`, `CONFLICTING_DELIVERY_DATES`, `DELIVERY_BEFORE_ORDER` |
  | Review | `AMOUNT_MISMATCH`, `CURRENCY_UNKNOWN`, `CURRENCY_MISMATCH`, `CONFLICTING_AMOUNTS`, `CONFLICTING_ORDER_DATES`, `MISSING_ORDER_REFERENCE`, `DOC_MULTIPLE_ORDER_IDS`, `EXTRACTION_UNVERIFIED`, `EXTRACTION_FAILED`, `OCR_REQUIRED` |
  | Info | `UNTRUSTED_INSTRUCTIONS`: instruction-like text is flagged and otherwise treated purely as data |

  Findings are kept with fingerprints: they are opened and resolved with audit events, never deleted.
- **Supersede rule:** when a same-type document for the correct order arrives, an earlier document for a different order is marked superseded with a reason, and its facts go stale. The original stays downloadable and in the history.
- Reviewer/owner exclusion: `POST /api/evidence/{id}/exclude` requires a reason of at least 10 characters. Staff get 403.
- The seed renders the hero invoice (dates relative to the case's transaction date) and ingests it through the same path. Result: invoice present, delivery proof missing.
- `GET /api/evidence/{id}/content` serves the scoped original bytes with `nosniff`, a sandbox CSP and `no-store`. Other endpoints: `GET /api/cases/{id}/evidence`, `GET /api/evidence/{id}`, and `GET /api/demo/cases/{id}/fixtures[/{name}]` (renders synthetic demo documents; rendering is not an upload).
- The case queue now shows a Blocker column.
- New `/cases/:id` workspace:
  - Header: amount at risk, IST deadline and countdown, workflow/provider state, and flags.
  - A readiness banner, the checklist, and findings with side-by-side values and links to their sources.
  - The evidence table: type, extraction method, active/excluded status with reason, uploader, and an upload control.
  - Buttons to upload the synthetic demo receipts, a source viewer with highlighted cited spans and a facts table, and the timeline.
- Migration `0002` adds the new columns with server defaults, so an existing M0 database upgrades in place (tested).

**Commands run**

```bash
cd backend
uv run alembic revision --autogenerate --rev-id 0002 -m "evidence extraction fields"
uv run pytest -q              # 82 passed
uv run ruff check .           # All checks passed
uv run ruff format --check .
```

```bash
cd frontend
npm install react-router-dom@7
npm run build                 # OK
npm run lint                  # oxlint clean
```

**Tests (82 passing; 36 new in `tests/test_c02_evidence_citations.py` plus `tests/test_migrations.py`)**

- Spans: unique / absent / duplicate / anchored lookups. Offsets are code points (Devanagari and an emoji, where the UTF-16 count would differ). Recheck fails after any text or offset tampering.
- Normalization of amounts (₹, Rs., Indian grouping, missing currency, bad grouping, three decimals) and dates (an ambiguous slash format is rejected).
- Sniffing rejects bad extensions, content/extension mismatches, declared-type mismatches, invalid JSON, non-UTF-8 text, empty files and oversize files. PDFs with a text layer are extracted; image-only PDFs and PNGs return OCR_REQUIRED.
- The hero sequence is **missing → wrong → correct**:
  - After seeding, the invoice and linkage are supported and delivery is missing (assigned to Sanjay).
  - The wrong-order receipt raises a blocking ORDER_MISMATCH showing both order IDs, and delivery becomes conflicting.
  - The correct receipt supersedes the wrong one with a reason. The finding resolves, delivery becomes supported, and evidence_ready turns true. The original wrong file can still be downloaded.
- Conflicting delivery dates block. A delivery date before the order date blocks. After a reviewer excludes the invoice and a 17,000-rupee invoice replaces it, AMOUNT_MISMATCH goes to review (staff cannot exclude; a reason is required).
- Dispatch/AWB alone does not count as delivery proof. A scanned PDF raises OCR_REQUIRED and sets the case flag.
- Injected instructions are flagged as info and the case stays blocked. Duplicate label lines stay ambiguous, and an unlinked receipt is `review_required`, not a contradiction.
- A Devanagari receipt cites correct spans, a JSON proof of delivery works, a text-layer PDF receipt works, and duplicate bytes are not stored twice.
- A rejected upload stores nothing. A path-traversal filename is neutralized. Tenant isolation holds for list, detail, content and upload. The fixture endpoints drive the hero sequence.
- Migration: a populated M0 database upgrades to head and downgrades back.

**Real run (exit criterion: missing/wrong/correct proof observable)**

From an empty `data/`, I started uvicorn (one worker) and the Vite dev server, then drove the app with Playwright Chromium as the delivery staff user. The banner read:

1. "Evidence incomplete — Delivery record …: missing"
2. After the wrong-order receipt: "Submission blocked: contradiction found", with ORDER_MISMATCH showing `ORD-DEMO-18500` beside `ORD-DEMO-OTHER`.
3. After the correct receipt: "Evidence complete and consistent for a pack (case version 4)". The wrong receipt was listed as "Excluded — Superseded by delivery_receipt_correct.txt …".

Uploading fake PDF bytes as a `.txt` file showed "Upload rejected: content is application/pdf but the extension says text/plain". Screenshots: `docs/m1-1-missing.png`, `docs/m1-2-wrong.png`, `docs/m1-3-correct.png`.

**Not done in M1 (by design or deferred)**

- Workflow-state transitions (`COLLECTING` → `WAITING_FOR_EVIDENCE` → `READY_TO_SUBMIT` …) belong to the runner (M2/M3). The case stays `NEW`; readiness is exposed as an assessment.
- The parts of C02 about packs and submissions ("no submission with unsupported claims" at the write boundary, `comments` built only from verified facts) complete in M2. In M1 only the readiness gate is tested.
- No LLM extraction yet. The rule proposer covers labelled synthetic documents only; free-form documents yield no facts and stay unknown, which is safe but limited.
- Manual-transcription records for image evidence are not implemented. Images stop at OCR_REQUIRED.
- The PDF parse timeout cannot kill a hung pypdf thread; it only stops waiting for it.
- Only a handful of Hindi/Marathi labels are recognised. This is not a claim of multilingual extraction.

## Open issues / next

- **M2 next**: policy gate, pending/outbox records, event-triggered runner with per-case locks, pack builder, Paytm simulator (full 11.2 code tables and lifecycle), idempotency; C01, C05, C06.
- `POST /api/dispute-events` (signed S2S intake endpoint), the simulator APIs and the runner are M2. The normalization they use already exists and is tested.
- Gemini adapter and live smoke test are M3. They must measure actual free-tier limits for `gemini-3.5-flash-lite` and handle 429s and daily caps.
- OpenRouter fallback cannot be exercised here until `openrouter.ai` is allowed in the environment's network settings and `OPENROUTER_API_KEY` is set.
- Starlette deprecation warning from the test client ("install httpx2") is harmless for now.
- Pre-event code eligibility under the hackathon rules is still unconfirmed (PRD §19.1).
