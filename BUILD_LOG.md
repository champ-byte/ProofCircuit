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

## M2 Tools and simulator: done

**Built**

- **Paytm-shaped simulator** (`app/simulator/`). It reads and writes only the `sim_*` tables; the app can see them only through the simulator's APIs.
  - Status API (JSON) and Action API (multipart) under `/api/simulator/v1/dispute/{status,action}`.
  - **Result codes:** the full §11.2 tables. Status: `1001/S/SUCCESS`, 4001–4004, 5001. Action: 1001 `UPLOADED_SUCCESS` (`S`, or `A` via a fault), 1003, 4001–4011, 5001. Every one is reachable in tests. `1002` (SFTP `filesPath`) is deferred and returns 4003.
  - **Lifecycle:** `NEW → POD_UPLOAD → POD_REJECT → POD_UPLOAD`. Expiry gives `LOST` with "Failed to respond". ACCEPT gives `LOST`. Outcomes are injected by an operator.
  - **Request handling:** the deadline is enforced at or after the exact instant, including non-midnight deadlines. File types are sniffed from content against the assumed PDF/JPEG/PNG allowlist. `tokenType` is case-insensitive. Seconds and milliseconds `requestTimestamp` are both accepted and recorded. Optional fields come back as `null`.
  - **Signatures:** demo HMAC-SHA256, labelled as *not* Paytm CHECKSUM.
  - **Receipts:** an independent receipt per accepted action. Its intent digest is computed from the received bytes, orderStatus and comments. Receipts are served only by `/api/simulator/receipts` (simulator-only, signed).
  - **Faults** are injected by an operator and consumed once:
    - Status: `system_error`, `stale_status`.
    - Action: `system_error_before`, `system_error_after`, `drop_response_after` (the effect is applied and the caller gets HTTP 504 with no body), `upload_failed` (4010), `ack_variant_a`.
  - **Webhooks:** a Chargeback Peon-style S2S webhook is sent on every status change, with harness headers `X-Demo-Event-Id` and `X-Demo-Sequence`.
- **S2S intake** (`POST /api/dispute-events`):
  - It verifies the demo signature; an invalid one returns 401 and the event is stored for audit.
  - A first `NEW` event creates exactly one case, with reason `requires_review`, because `disputeType` never establishes goods-not-received.
  - Duplicates (same event ID, or the same canonical hash) are ignored.
  - Any other webhook only queues an **authoritative Status read**, so out-of-order events cannot regress state.
- **App adapter** (`app/providers/paytm.py`): it talks to the simulator over the real HTTP contract in-process (`httpx.ASGITransport`) and classifies results as ack / duplicate (4006) / retryable (4010) / definitive / unknown (5001, lost response, or an inconsistent tuple).
- **Pack builder** (`app/services/pack.py`):
  - Packs are immutable and versioned; identical content reuses the existing version.
  - `orderStatus` is derived from a cited delivered-event fact. Dispatch-only evidence never yields a pack.
  - `comments` comes from a deterministic template filled only with span-verified values. It references files by position and is capped at 240 code points (application policy).
  - **Upload set:**
    - The cover is a deterministic neutral English summary PDF.
    - Original PDF/JPEG/PNG supporting files are uploaded, with their hashes re-verified.
    - TXT/JSON originals are cited, never redrawn.
  - **Outputs:** `manifest.json` (canonical; its SHA-256 is the pack hash), an escaped `evidence-index.html` with a sandbox CSP, and `cover.pdf`.
- **Policy gate** (`app/services/policy.py`), rechecked immediately before every write, including any resend:
  - The case is simulator-only, not closed, and has a confirmed reason.
  - The deadline is strictly in the future.
  - The pack is the latest one and built for the current case version, with `ORDER_DELIVERED`.
  - File count, size and type, and the comments cap, are within limits.
  - Fresh evidence readiness holds, with no open human review and no other submission in flight.
  - The provider state is eligible: `NEW`, or `POD_REJECT` with repair budget left.
  - `AUTO_SUBMIT_SIMULATOR` applies to agent actors.
- **Submission/reconciliation** (`app/services/submission.py`):
  - The intent is committed before the call.
  - The idempotency key is `(merchant_id, dispute_id, action, pack_hash)`.
  - Verification needs a successful Status read **and** a receipt whose intent digest matches.
  - An acknowledgement alone never verifies; neither does 4006.
  - Unknown or lost responses lead to SUBMISSION_UNCERTAIN, then bounded status reads (default 3, with backoff), then a receipt lookup, and only then **at most one** resend of the same serialized payload from an eligible state.
  - If status reads stay unavailable, the submission stays uncertain, gets the `PROVIDER_UNAVAILABLE` flag and a human-review task. A crash leaves `sent`, and startup reconciles it before any resend.
- **Runner** (`app/runner.py`, `app/handlers.py`):
  - Pending work is persisted and committed before BackgroundTasks run, with one asyncio.Lock per case. A trigger that finds the case locked returns at once, because the lock holder re-checks pending work with no await before releasing.
  - There is no polling worker. At startup a single recovery pass requeues interrupted work and queues reconciliation for every in-flight submission. Operators also get `POST /api/demo/resume-pending`.
- **Tools** (`app/agent/tools.py`): the 9 PRD §9 tools with typed, `extra=forbid` arguments.
  - Case and tenant come from run context only, and `source_ids` must belong to the case.
  - There is no concede, refund, HTTP or SQL tool.
  - Every call is persisted as a ToolCall plus an audit event with status ok, denied or error.
  - Humans use it now through `POST /api/cases/{id}/actions` (manual runs); M3 plugs the model into the same dispatcher.
- **Staff messaging:** approved en/hi/mr templates (missing and wrong-receipt variants; demo starter copy that needs language review). Tasks are deduplicated per `(case, requirement, round)`. Messages are delivered to the in-app inbox only (`sent_in_simulator`). A staff upload or reply marks the task responded and triggers re-evaluation.
- **Workflow sync** (§10.1): `NEW, COLLECTING, WAITING_FOR_EVIDENCE, NEEDS_HUMAN_REVIEW, READY_TO_SUBMIT, SUBMITTING, SUBMISSION_UNCERTAIN, MONITORING, CLOSED`. Operational flags (`DEADLINE_EXPIRED`, `PROVIDER_UNAVAILABLE`, `OCR_REQUIRED`) are kept separately. Provider status is set only from authoritative reads.
- **Human authority:**
  - `POST /api/cases/{id}/reviews` covers approve_concession, resolve_review and confirm_reason. An approval is single-use, lasts 15 minutes and is bound to the case version and action hash.
  - `POST /api/cases/{id}/accept-dispute` is reviewer-only and needs explicit confirmation.
  - `POST /api/cases/{id}/refund-policy-check` is a dry run that returns `DENY_OPEN_DISPUTE` while the dispute is open; there is no refund provider at all.
- **Other APIs:** `GET /api/cases/{id}/events?after=` (event feed), `/runs`, `/messages`, `/pack` (plus downloads), `/submissions`.
- Hero fixtures are now deterministic text-layer PDFs; the synthetic documents themselves are the originals.
- Migration `0003` adds the simulator fault table and the submission, pack and receipt fields, with upgrade-safe defaults.
- **UI:**
  - The workspace has a manual Actions panel and a pack/submission panel. It shows the "**Submission verified — dispute outcome pending**" banner, the reconciliation trail and pack downloads.
  - There is a staff inbox with Devanagari messages and a reply box.
  - The page follows the persisted event feed so background work appears without a reload.

**Commands run**

```bash
cd backend
uv run alembic revision --autogenerate --rev-id 0003 -m "simulator and submission fields"
uv run pytest -q              # 154 passed
uv run ruff check .           # All checks passed
uv run ruff format .
```

```bash
cd frontend
npm run build                 # OK
npm run lint                  # oxlint clean
```

**Tests: 154 passing** (72 new this milestone)

- **C01 Paytm boundary** (`test_c01_paytm_boundary.py`, 34):
  - Status `1001/S/SUCCESS`, never AUDIT_SUCCESS; `transactionId` spelling; null optionals.
  - `tokenType` casing; seconds and milliseconds timestamps; `version` ignored.
  - Status 4001–4004 and 5001. Action 4001, 4002 (including a missing orderStatus on DEFEND), 4003 (unknown action, bad orderStatus, filesPath), 4004, 4005/4011 exactly at the due instant (and allowed 1 s before), 4006, 4007, 4008, 4009 (including a disguised file), 4010, 5001, and 1003.
  - The `A` ack variant is classified as an ack; correction is allowed only from POD_REJECT.
  - A signed webhook creates exactly one case and a duplicate is ignored. The case stores disputeAmount, not transactionAmount, and the exact non-midnight deadline. An invalid signature gets 401.
  - A dispute created through the simulator's webhook appears as a case; UTR and debit reach the case through an authoritative read.
- **C05 Submission contract** (14):
  - orderStatus is derived and every citation resolves to stored text.
  - Comments contain only verified values and file positions, with no hashes or offsets, within 240.
  - Manifest hashes match the files; HTML is escaped; TXT originals are not uploaded; dispatch-only evidence cannot build or submit.
  - Happy path verified with receipt digest = submission digest = manifest digest.
  - Deadline denied at the instant and allowed 1 s before.
  - A stale pack is denied, a rebuild creates v2 while v1 is unchanged, and an identical rebuild is reused.
  - An unconfirmed reason blocks submission. File-count/size/type and comments limits are enforced by the policy. The auto-submit switch applies to agents only.
- **C06 Retry and restart** (14):
  - A lost response or 5001 after the effect verifies with **1 attempt and 1 receipt**.
  - 5001 before the effect, or 4010, follows: reconcile, then one resend, then verified (trail order asserted).
  - Status 5001 is retried within bounds. A status outage leaves the submission uncertain with PROVIDER_UNAVAILABLE, and resume then verifies it without another write.
  - A third-party 4006 never verifies, and leaves a review task.
  - **The v1 receipt does not verify corrected pack v2** after POD_REJECT.
  - Repeating the submit of a verified pack is idempotent.
  - A crash after the provider accepted recovers on restart with no duplicate; a crash before the request left resends exactly once on restart.
  - Interrupted pending work is requeued once. Duplicate webhooks are ignored. An out-of-order `NEW` webhook cannot regress `POD_UPLOAD`.
- **C04 Authority** (8, a subset of the full group):
  - The tool path has no concede, refund, HTTP or SQL. Tool arguments cannot switch the case, cite foreign sources, or pick a different staff assignee.
  - Only a reviewer can approve or concede, and confirmation is required. A concession executes once and a replay is refused.
  - A stale approval (after the case changed) and an expired one are denied. Approvals are tenant-scoped.
  - The refund dry run makes no write.
- **M2 manual end-to-end** (`test_m2_manual_e2e.py`, 2): the whole hero journey through the tools, plus a staff text reply resuming the case (a C03 subset).

**Real runs**

- **Browser journey:** fresh `data/`, uvicorn (one worker) and Vite, driven with Playwright Chromium, switching between the owner and the delivery staff user:
  1. Start the case. Request delivery proof: a Marathi message lands in the staff inbox as "sent in simulator".
  2. The staff user uploads the wrong-order receipt PDF, and the pack is denied with ORDER_MISMATCH.
  3. Round-2 request, then the correct receipt: READY_TO_SUBMIT. Pack v1 is built (3 files, ORDER_DELIVERED, cited comments).
  4. The operator injects `drop_response_after` and clicks Submit. The trail shows `action_response:unknown → reconcile` and the result is **verified with 1 attempt**; the workflow reads "Submission verified — outcome pending". Screenshot: `docs/m2-verified.png`.
- **Restart:** I restarted uvicorn on the same database. The state was still `MONITORING`/`POD_UPLOAD` with one verified submission and no resend.
- **Bugs found by the real runs and fixed:**
  1. The fixture listing still named `.txt` files after the switch to PDF, so browser uploads got 422 from content sniffing. A regression assertion now covers it.
  2. The workspace did not refresh after background work finished. TestClient hides this because it runs background tasks before returning. Fixed by following the persisted event feed.
  3. A policy denial of `submit_defense` was recorded as a tool `ok` (no write happened). Fixed, and unexpected exceptions are now recorded as `error` tool calls.

**Deviations / decisions**

- The simulator runs in-process behind an ASGI transport; it is still reached only through its HTTP contract. A "lost response" is emulated as HTTP 504 with an empty body after the effect is applied.
- **Error precedence is simulator policy.** The order is: mandatory → signature → format → lookup → DEFEND field/file checks → deadline → state. ACCEPT outside NEW/POD_REJECT returns 4003. None of this is confirmed for Paytm production.
- **Workflow mapping:** in manual mode a blocking contradiction moves the case to `NEEDS_HUMAN_REVIEW` unless a staff request is open (then `WAITING_FOR_EVIDENCE`). The M3 agent will usually request corrected evidence instead.
- A POD rejection currently moves the case to `NEEDS_HUMAN_REVIEW`. The bounded one-round automatic repair (C07) is scheduled for M7; `pod_repair_count` is not incremented yet.
- In development, unset secrets are ephemeral, so demo sessions and webhook signatures change on each restart. Set `SESSION_SECRET` and `DEMO_WEBHOOK_SECRET` for a stable demo.

## M3 Real agent: done

**Built**

- **Reasoner layer** (`app/providers/`):
  - **`GeminiReasoner`** (primary):
    - It calls `generateContent` with the key in the `x-goog-api-key` header only.
    - Requests use `temperature 0`, `responseMimeType: application/json` and `responseJsonSchema`; the smoke test can fall back to `responseSchema` (an OpenAPI-style subset).
    - It sends `thinkingConfig.thinkingLevel=low` when the model accepts it.
    - Thought parts are dropped and never stored. The model actually used is taken from `modelVersion`.
    - Failures are sorted into rate_limited (with the retry delay from `RetryInfo`), transient, timeout, config and blocked. Error messages are scrubbed of the key.
  - **`OpenRouterReasoner`** (optional fallback):
    - Requests follow PRD §9: strict `json_schema`, `require_parameters`, `data_collection: deny`.
    - A catalog preflight rejects any model with non-zero pricing while `ALLOW_PAID_MODELS=false`, and a 402 counts as a configuration error rather than a reason to switch to a paid model.
    - It is tested only with mocked transports, because `openrouter.ai` is blocked here.
  - **`ReplayReasoner`:** a pre-written hero script (`fixtures/hero/replay.json`). It is operator-only and labelled "Fixture replay (not AI)" everywhere; its runs never count as live and never turn the live badge on.
  - **Router:** primary first, then the fallback only when `FALLBACK_ENABLED` is set and its smoke test passed. The fallback repeats inference only, never a tool write.
- **Per-call accounting and limits:**
  - Every call is recorded in a new `reasoner_calls` table (migration 0004): provider, model returned, purpose, status, latency and tokens.
  - A daily cap (`REASONER_DAILY_CALL_CAP=150`, rolling 24 h) is checked before any request, with pacing of at least 4 s between calls (`REASONER_MIN_INTERVAL_SECONDS=4`).
  - A 429 is retried once if its retry delay is 20 s or less (`REASONER_RATE_LIMIT_MAX_WAIT_SECONDS`). A transient failure or timeout is also retried once.
- **Smoke test** (`cli smoke-reasoner`, plus operator-only `POST /api/providers/smoke`):
  - It sends one synthetic context and requires a schema-valid action that is on the tool list.
  - For Gemini it tries up to 4 request variants (schema field × thinking setting) and stores the one that works.
  - The result goes in a new `provider_checks` table and is valid for 24 h for the configured model.
  - Readiness, the badge and the router all depend on it: a provider with an untested, failed or expired check never runs.
- **Provider-facing schema** (`app/agent/schema.py`): a closed schema whose `action` must be one of the tools. `arguments` is the nullable union of all tool argument fields, with no extra keys allowed.
- **Prompt** (`app/agent/prompt.py`):
  - A compact system prompt (rules, tool list, no concession or refunds, documents are data).
  - A trusted case context: checklist, findings, tasks, pack and submission state, evidence readiness, and policy notes.
  - The run's history so far.
  - Verified facts with short excerpts and staff messages, placed inside `<<<UNTRUSTED_DOCUMENT_DATA>>>` markers.
- **Agent loop** (`app/agent/loop.py`):
  - Each step observes, proposes, validates, executes through the existing `dispatch(actor_kind="agent")`, then re-reads the case.
  - Limits: 8 proposals, 2 schema repairs per response, a per-run timeout, and a stop after 2 consecutive denials. Hitting a limit sets `AGENT_LIMIT_REACHED` and opens a human review.
  - **Idle states spend no model calls:** waiting for staff or review, monitoring, submitting, uncertain, closed, or past the deadline.
  - If no reasoner is available, the run is marked `paused_reasoner_unavailable` with its reasons, and manual operation is unaffected.
- **Event-triggered and coalesced:** a new runner job, `agent_run`, replaces the six `evaluate` triggers (case opened, manual start, evidence uploaded or excluded, staff reply, review decisions). It always runs the deterministic checks first and calls the model only if a reasoner is ready and `AGENT_AUTORUN` is on. A trigger that arrives while a run is already pending merges into it.
- **UI:**
  - Live badge `Gemini — <model returned>`, and a "Run agent / resume" button.
  - An agent-run history showing the mode tag (Live model / Fixture replay (not AI)), model, status, and each step's tool, outcome and the model's short rationale.
  - Operator-only buttons for the smoke test and fixture replay, and a reasoner-unavailable banner.

**Commands run**

```bash
cd backend
uv run alembic revision --autogenerate --rev-id 0004 -m "reasoner calls and provider checks"
uv run pytest -q                       # 191 passed
uv run ruff check .                    # All checks passed
uv run python -m app.cli smoke-reasoner  # LIVE, see below
```

```bash
cd frontend
npm run build                          # OK
npm run lint                           # oxlint clean
```

**Tests: 191 passing** (37 new, all network-free; they use a scripted fake reasoner and mocked HTTP transports)

- **C08 Provider contract** (`test_c08_provider_contract.py`, 30):
  - Bad JSON is repaired within the bound.
  - Unsupported output never runs a tool: free text, `accept_dispute`, `issue_refund`, an unknown argument such as `recipient_phone`, or an extra key all fail after 1 + 2 attempts, with no ToolCall, no receipt, and a review task.
  - Gemini requests have the right shape: the key is in the header and not the URL, the JSON schema, temperature 0, thinkingLevel, thought parts dropped, and `modelVersion` recorded. The OpenAPI fallback variant marks nullable fields.
  - Error classes are correct and the key never leaks; blocked or empty output is an error.
  - The smoke test negotiates the variant and persists it; the badge and readiness turn live only after it. Smoke checks expire after 24 h.
  - Rate limits: a short 429 is retried once; a long 429 pauses the run without calling a tool. The daily cap stops before any provider call.
  - The fallback is used only when enabled and ready, and is audited. With it disabled the run pauses and manual mode still works. An untested reasoner never runs.
  - The Gemma fallback is reported `not_implemented`.
  - OpenRouter requests have the right shape, the preflight blocks paid models unless allowed, and a 402 does not switch to paid.
  - Fixture replay is operator-only, labelled, never live, and never moves the live badge.
  - The secret appears nowhere in API output, reasoner calls or audit rows.
- **Agent loop** (`test_m3_agent_loop.py`, 7):
  - **The scripted hero:** the agent requests proof, then waits with no extra model call. The wrong receipt triggers a run in which the model sees ORDER_MISMATCH and requests round 2. The correct receipt triggers build and submit, verified, ending in MONITORING. That is 4 model calls in total.
  - Idle triggers spend no calls. Injected instructions appear only inside the untrusted markers, and two denied submits stop the run and open a review.
  - The proposal budget sets AGENT_LIMIT_REACHED. Triggers merge into one pending run. The agent actor respects `AUTO_SUBMIT_SIMULATOR=false`; a human can submit once the review is resolved.

**Live runs with the user's free-tier Gemini key** (all inputs synthetic)

- **Smoke test:** passed on the first variant, using `responseJsonSchema` and `thinkingLevel=low`. Model returned: `gemini-3.5-flash-lite`. Latency 1,737 ms, 600 prompt tokens and 121 output tokens. It proposed `request_evidence` for the missing delivery record.
- **Hero journey in the browser:** fresh `data/`, uvicorn with one worker, Vite, and Playwright Chromium. Nobody clicked a tool; the owner started the run and the delivery staff user uploaded the fixture PDFs.
  1. **Run 1, manual start** (1 call): `request_evidence` with the rationale "Requesting the missing delivery record to support the defense…". A Marathi request went to Sanjay's inbox.
  2. **Run 2, wrong-order receipt uploaded** (1 call): `request_evidence`, round 2, with the rationale "The previously provided delivery record references the wrong order ID, so we need staff to supply the correct delivery record for ORD-DEMO-18500."
  3. **Run 3, correct receipt uploaded** (2 calls): `build_evidence_pack`, then `submit_defense`. Result: "**Submission verified — dispute outcome pending**", receipt `SIMRCPT-…`, 1 attempt.
  - **Totals:** 5 Gemini calls (1 smoke test, 4 proposals), all OK, with no 429s. Latency was 1.6–2.2 s (average 1.8 s), with about 1.7k–2.7k prompt tokens per proposal. Elapsed time from each upload to its outcome was about 4.5 s and 12 s.
  - Screenshot: `docs/m3-live-agent.png`.
- **Free-tier limits:** not measured, because nothing came close to them. The cap, pacing and 429 handling are tested with fakes. The true daily quota for `gemini-3.5-flash-lite` on this key is still unknown.

**Decisions and notes**

- Agent runs are event-triggered with a daily cap of 150 and merge when they overlap (user decision).
- Waiting states return control without a model call. This keeps the hero journey at 4 calls and follows the PRD's "no repeated model polling".
- A run that ends after a verified submission is recorded as `waiting`, meaning it waits for the provider outcome.
- The badge reflects only live providers with a fresh passing smoke test. Replay runs are labelled per run and never change it.
- **Google data use:** on the free tier Google may use what we send, so only synthetic case data is sent.

## Open issues / next

- **M4 next**: product UI — case workspace polish, right-hand demo drawer (staff chat, simulator fault injector, identity, seed/reset, provider readiness, resume pending work), inline reviewer journey (concession with consequences), source preview at cited spans.
- Still partial: C03 (staff continuation) and C04 (authority) beyond the subsets above; C07 (POD repair) is M7.
- Actual Gemini free-tier quota for this key is still unmeasured (no limit was approached); the cap/pacing/429 paths are tested with fakes.
- OpenRouter fallback is implemented and mock-tested but cannot be exercised live until `openrouter.ai` is allowed in the environment's network settings and `OPENROUTER_API_KEY` is set.
- Starlette deprecation warning from the test client ("install httpx2") is harmless for now.
- Pre-event code eligibility under the hackathon rules is still unconfirmed (PRD §19.1).
