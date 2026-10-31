# Handoff: start here in a new session

This page is short on purpose. [Features.md](Features.md) (features and demo runbook), [ARCHITECTURE.md](ARCHITECTURE.md) and the agent spec in [CLAUDE.md](CLAUDE.md) summarise the system; the code is the source of truth. [BUILD_LOG.md](BUILD_LOG.md) holds the detailed history and [PRD.md](PRD.md) holds the specification; read both before coding, as [CLAUDE.md](CLAUDE.md) requires.

## Where things are

- **Branch:** `claude/stoic-pasteur-3b0gu1`. All work lives here and is **not merged to `main`**: a checkout of `main` shows only the PRD. Run `git fetch origin claude/stoic-pasteur-3b0gu1 && git checkout claude/stoic-pasteur-3b0gu1` first.
- **Working rules** (CLAUDE.md):
  - Do one PRD §17 milestone at a time, then stop and report to the user.
  - Keep BUILD_LOG.md updated with the commands run, the tests passed and the open issues.
  - Never claim a feature works without a passing test or a real run.
- **Last milestone commit:** M7 (tests and evaluation).

## Status (verified 2026-10-29)

- **Milestones:**
  - Done: M0 Bootstrap, M1 Evidence, M2 Tools and simulator, M3 Real agent, M4 Product UI, M5 Staff voice notes (local faster-whisper only; Sarvam not built), M6 n8n follow-up (optional self-hosted n8n; live exit check passed), M7 Tests and evaluation (C01–C08 all pass; live 40-case evaluation, see BUILD_LOG).
  - Not started: M8 Optional.
- **Tests:**
  - Backend: 280 pytest passed (locally on Windows, Python 3.12 via uv).
  - Frontend: 24 vitest passed, and `npm run e2e` (Playwright) passes against a running stack.
  - Speech: on one human Marathi recording (local, not committed), faster-whisper scored CER 0.21 (`small`), 0.16 (`medium`) and 0.09 (`large-v3`). All three still fail the robotic espeak smoke fixture, so transcription stays blocked by default unless `SPEECH_REQUIRE_PASSING_SMOKE=false`. See BUILD_LOG "Local setup and M5 follow-up".
  - Live Gemini hero runs passed in M3 and M4 (5 calls each).
- **PRD test groups:**
  - Done: all eight, C01–C08 (C07 one-round POD repair added in M7). Live checks: C04 (`scripts/live_authority_check.py`), C07/C03 via the live evaluation, n8n via `n8n/live_check.py`.
- **Evaluation:** live Gemini runs of the 40-case synthetic corpus; `/evaluation` shows the latest export from `docs/evaluation/`. Numbers and not-run cases are in BUILD_LOG "M7".

## Decisions the next session must keep

These are user decisions; see BUILD_LOG "Decisions that deviate from PRD.md".

1. **Reasoner:**
   - Gemini is the primary reasoner, using Gemini 3.x models only (2.5 is deprecated). The default model is `gemini-3.5-flash-lite`, on a free-tier key.
   - The key lives in the environment settings as `GEMINI_API_KEY`. Never ask for it in chat, print it or commit it.
2. **Fallback:** OpenRouter is an optional fallback, disabled by default because `openrouter.ai` is blocked by the network policy.
3. **Agent runs:**
   - Runs are event-triggered and coalesced into one `agent_run` work item per case. There is no polling.
   - `REASONER_DAILY_CALL_CAP=150` per rolling 24 h and `REASONER_MIN_INTERVAL_SECONDS=4`.
   - Each run allows at most 8 proposals and 2 schema repairs.
   - Spend live quota only on smoke tests and hero runs. About 11 calls have been used so far, with no 429s; the real free-tier limit is unmeasured.
4. **Data and simulator:**
   - Synthetic data only. Use the Paytm-shaped simulator only, never a real Paytm host.
   - Demo HMAC signatures are not Paytm CHECKSUM.
5. **Agent tools:** the agent has no concede or refund tool. Concession is reviewer-only and takes two steps.
6. **Speech (M5):** local faster-whisper only. Weights are never downloaded at runtime. Transcripts are staff testimony and never satisfy the checklist, `orderStatus` or the pack. Pin `av<17` for faster-whisper 1.2.1. `WHISPER_MODEL` stays `small` for now, because Sarvam AI may replace local STT; `large-v3` scored best on a human clip (see BUILD_LOG).
7. **Reminders (M6):** n8n only schedules. The backend starts the workflow, keeps cancellation, recipient and idempotency authority, and delivers reminders to the local inbox only. Two separate tokens: `N8N_WEBHOOK_TOKEN` (backend → n8n) and `N8N_SERVICE_TOKEN` (n8n → backend). n8n is pinned to `n8nio/n8n:2.45.6`, set up through `python n8n/setup.py` (CLI, no UI or account).
8. **Testing (M7):** the user requires **real runs** (live Gemini on a real uvicorn server, real n8n) in addition to the offline tests. Evaluation cases run under the synthetic merchant `MID-EVAL-001` and never enter the demo queue. Unexecuted cases are reported "not run", never replayed or scored. The daily cap default stays 150; it was raised to 300 only for the evaluation server, with the user's OK.
9. **Stored values:** money is stored as integer paise and times as UTC. Paytm's naive timestamps are read as IST. Citations are Unicode code-point spans computed in Python.

## Local setup (your own machine)

The cloud container's database, smoke-test results and downloaded models do not carry over. On a new machine, do this once.

**Prerequisites:**

- Required: Python ≥ 3.11, [uv](https://docs.astral.sh/uv/), Node ≥ 22.19 (jsdom's undici 8 needs it) and git.
- Optional: ffmpeg (audio), Docker (M6 n8n), and Ollama with an installed Gemma tag (M8).

**Get the branch** (the work is not on `main`):

```bash
git clone https://github.com/champ-byte/ProofCircuit.git
```

```bash
cd ProofCircuit && git checkout claude/stoic-pasteur-3b0gu1
```

**Secrets:** set them in your shell, or in a repo-root `.env`, which is gitignored. Never commit them or paste them into chat.

```bash
export GEMINI_API_KEY=your-key-here
```

```bash
export SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))") DEMO_WEBHOOK_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
```

**Install and verify:** expect 221 backend and 20 frontend tests to pass.

```bash
cd backend && uv sync --extra speech && uv run pytest -q
```

```bash
cd frontend && npm ci && npm test && npx playwright install chromium
```

**Re-enable the live agent:** 1–4 Gemini calls; the result lasts 24 h.

```bash
cd backend && uv run python -m app.cli smoke-reasoner
```

**Optional speech-to-text:** downloads ~460 MB for `small`. Models are never downloaded at runtime.

```bash
cd backend && SPEECH_PROVIDER=faster_whisper uv run python -m app.cli speech-download
```

```bash
cd backend && SPEECH_PROVIDER=faster_whisper uv run python -m app.cli smoke-speech
```

**What differs from the cloud container:**

- No proxy blocks: Hugging Face, Docker Hub (n8n) and `openrouter.ai` should be reachable.
- Playwright needs its own browser (`npx playwright install chromium`, as above). `PC_CHROMIUM=/path/to/chrome` also works.
- Stop servers with Ctrl+C. The `ps aux | grep` workaround below only mattered in the cloud shell.
- **Human speech:** measure any recording with `uv run python -m app.cli transcribe-file AUDIO --reference ../fixtures/hero/voice_note_mr.txt --out result.json`. One human Marathi clip has been measured (see BUILD_LOG); Hindi is still untested.
- Record the local environment (OS, Python, Node, CPU/GPU, Docker/Ollama) in BUILD_LOG.md at the start of the first local milestone.

## Run and verify

```bash
cd backend && uv sync && uv run pytest -q && uv run ruff check .
```

```bash
cd frontend && npm ci && npm test && npm run build && npm run lint
```

Start the stack (one Uvicorn worker only; settings validation enforces it):

```bash
cd backend && uv run uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8000 --workers 1
```

```bash
cd frontend && npm run dev
```

- **Enable the live agent** with `uv run python -m app.cli smoke-reasoner` (1–4 calls; the result lasts 24 h). Runtime data does not carry across sessions, so a new session must run the smoke test again.
- **Browser E2E:** start the backend with `AGENT_AUTORUN=false`, then run `npm run e2e`. If the Gemini smoke check is fresh, health still reads `live`; then run `E2E_ALLOW_LIVE=1 npm run e2e` (no model call happens with autorun off).
- **Speech:** `uv sync --extra speech`, then `SPEECH_PROVIDER=faster_whisper uv run python -m app.cli speech-download` and `... smoke-speech`. The model cache (`~/.cache/huggingface`) does not carry across sessions.

## Environment gotchas (learned the hard way)

Items marked *(cloud only)* applied to the claude.ai cloud container, not to a local machine.

- **Network** *(cloud only)*:
  - `generativelanguage.googleapis.com` is reachable; since M5, `huggingface.co` and `*.xethub.hf.co` too.
  - `openrouter.ai` and the `ai.google.dev` docs are blocked (proxy 403).
  - Ollama is not installed.
- **Stopping servers** *(cloud only)*: `pgrep -f` or `pkill -f` with a pattern matches the agent's own shell and kills it. Stop servers with `ps aux | grep '[u]vicorn' | awk '{print $2}' | xargs kill`.
- **E2E with a fresh smoke check:** `/api/health` reads `live` even under `AGENT_AUTORUN=false`, so run `E2E_ALLOW_LIVE=1 npm run e2e` (no model call happens with autorun off).
- **Speech deps:** faster-whisper 1.2.1 needs `av<17` (pinned in the `speech` extra); `av` 19 raises `TypeError` on every transcription.
- **Background tasks:**
  - `TestClient` runs `BackgroundTasks` before returning, but a real server does not.
  - The UI follows `/api/cases/{id}/events`, so verify UI flows in a real browser, not only with TestClient.
- **Scratch scripts:**
  - Run them from `backend/` with `PYTHONPATH=.`.
  - *(cloud only)* For Node scripts, use the preinstalled Chromium and do not run `playwright install`. ES-module scripts ignore `NODE_PATH`, so import Playwright from `frontend/node_modules/playwright/index.mjs`.
- **Secrets:** without `SESSION_SECRET` and `DEMO_WEBHOOK_SECRET`, secrets are regenerated on each restart, so old demo sessions stop working after a restart.
- **Test clock:**
  - Tests use a fixed clock in 2030 and the session TTL is 12 h. After advancing the clock, call `relogin()` (see `tests/helpers.py`).
  - Use 2030 dates in fixtures.
- **Migrations:**
  - Alembic revisions 0001–0005. Autogenerate a revision, then add a `server_default` to new NOT NULL columns so populated databases can upgrade.
  - `tests/test_migrations.py` covers the upgrades.
- **Demo reset:**
  - A reset keeps `reasoner_calls` and `provider_checks` (`PRESERVED_ON_RESET` in `services/seed.py`), so the daily cap and smoke result survive.
  - After a reset the hero case has a new ID. The UI remounts the workspace per case ID.

## Code map

| Area | Files |
| --- | --- |
| Agent loop | `backend/app/agent/loop.py` (bounded proposals and repairs), `tools.py` (the 9 PRD tools and the dispatcher), `prompt.py`, `schema.py` (closed `ACTION_JSON_SCHEMA`) |
| Providers | `backend/app/providers/gemini.py`, `router.py` (cap, pacing, 429 retries, fallback), `readiness.py` (badge, usage), `replay.py` (fixture replay, labelled "not AI"), `fake.py` |
| Evidence | `backend/app/services/evidence.py`, `extraction.py`, `field_rules.py`, `validation.py` (checklist and contradictions), `domain/citations.py` |
| Execution | `backend/app/services/policy.py` (gate), `pack.py` (immutable packs), `submission.py` (idempotency, verification by status read plus receipt), `workflow.py`, `messaging.py` (staff inbox) |
| Runner | `backend/app/runner.py` (`PendingWork`, per-case locks, recovery), `handlers.py` |
| Simulator | `backend/app/simulator/` (Paytm-shaped API, faults, receipts, webhooks) |
| API | `backend/app/api/` (cases, evidence, actions/runs, demo, intake, evaluation) |
| Seed and fixtures | `backend/app/services/seed.py`, `fixtures.py` (deterministic hero PDFs), `fixtures/` |
| POD repair (C07) | `backend/app/services/repair.py` (handled-rejection marker, one correction round), hooks in `submission.refresh_status`, `policy.check_defense`, `workflow.sync_workflow`, `validation._supersede_rejected`, `pack.build_comments` |
| Evaluation | `backend/app/evaluation/` (`corpus.py` generator, `seed.py`, `harness.py` HTTP harness + scoring), `api/evaluation.py`, `fixtures/benchmark/corpus_v1.json`, `fixtures/ground_truth/corpus_v1.json`, `docs/evaluation/` (exports), `scripts/live_authority_check.py` |
| n8n reminders | `backend/app/services/reminders.py` (trigger, callback rules, sending), `api/reminders.py`, `frontend/src/components/Reminder.tsx`, `n8n/` (workflow export, compose, `setup.py`, `live_check.py`, README) |
| Speech / testimony | `backend/app/providers/speech.py`, `services/testimony.py`, `services/speech_smoke.py`, `api/testimony.py`, `frontend/src/components/Testimony.tsx` |
| UI | `frontend/src/pages/` (CaseWorkspace, CasePanels, CasesPage, EvaluationPage), `frontend/src/components/` (DemoDrawer, Evidence, Reviewer, …) |
| E2E | `frontend/e2e/hero.e2e.mjs` |

## Next steps

Ask the user which of these to do before starting:

- **M5 follow-up (optional):** measure STT on a human Marathi/Hindi recording; Sarvam stays blocked until `SARVAM_API_KEY` and network access exist.
- **M8 Optional:** local Gemma (needs Ollama) and Cognee. Otherwise label them "not implemented".

Other open items are listed under BUILD_LOG "Open issues / next", including the unconfirmed pre-event code eligibility (PRD §19.1).
