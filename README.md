# ProofCircuit

An AI teammate that prepares a merchant's payment-dispute response: it finds missing proof, requests it from staff, checks consistency, builds a source-linked evidence pack, submits it to a **Paytm-shaped simulator**, and verifies the submission independently. See [PRD.md](PRD.md) for the full specification and [BUILD_LOG.md](BUILD_LOG.md) for progress and test results. Continuing development in a new session? Start with [HANDOFF.md](HANDOFF.md).

> **Synthetic-data hackathon prototype.** No real merchants, no real money movement, no real messages, and no Paytm production or staging hosts.

## Status

- **M0 (Bootstrap)** is done: schema and migrations, settings validation, provider readiness, the seeded hero case, and the case list.
- **M1 (Evidence)** is done: upload of TXT/JSON/text-PDF evidence, Python-computed code-point citations, the goods-not-received checklist, deterministic contradiction checks, and a case workspace at `/cases/:id`.
- **M2 (Tools and simulator)** is done:
  - A Paytm-shaped simulator implementing the PRD §11.2 code tables and lifecycle, with fault injection and independent receipts.
  - The policy gate, immutable evidence packs, and the event-triggered runner with per-case locks and startup recovery.
  - Idempotent, independently verified simulator submissions.
  - Reviewer-only concession and a staff inbox.
  - The case can be driven end to end manually from the workspace.
- **M3 (Real agent)** is done. A Gemini-driven agent (default `gemini-3.5-flash-lite`) chooses each next tool through the same dispatcher and policy gate as manual mode.
  - Runs are event-triggered and coalesced, bounded (8 proposals, 2 schema repairs), and capped at a daily call limit.
  - OpenRouter is an optional fallback. A clearly labelled fixture replay is available as a non-AI demo mode.
- **M4 (Product UI)** is done:
  - A case workspace with a sticky header (amount at risk, a live deadline countdown), plain-language status banners, a key-steps timeline and the full audit log.
  - Source previews that open at the cited span, plus side-by-side mismatch views.
  - A reviewer panel with a two-step concession, a collapsible six-tab demo drawer, and an `/evaluation` page.
- **M5 (Staff voice notes)** is done with **local faster-whisper only**; the Sarvam adapter is not built.
  - Staff send a voice note from the drawer. The original audio and its SHA-256, the speaker, the linked request, the locale, the provider/model and timed segments (code-point spans) are stored and shown.
  - Speech-to-text output is **unconfirmed** until the speaker confirms it or corrects it; a correction is a new version and the earlier ones are kept. With no usable speech-to-text, the speaker types a labelled human transcription.
  - A transcript is **staff testimony**: it never satisfies a checklist item, never feeds `orderStatus` and is not part of the submitted pack. The matching delivery document is still required.
  - Measured result on the bundled synthetic (espeak-ng) Marathi clip: `small` and `medium` both failed to transcribe it usefully, so the smoke check fails and transcription is blocked by default. On one human Marathi recording, `small`/`medium`/`large-v3` scored CER 0.21/0.16/0.09. See BUILD_LOG.md.
- **M6 (n8n follow-up)** is done, as an optional self-hosted n8n Community workflow ([n8n/README.md](n8n/README.md)).
  - When a staff evidence request is created, the backend starts the workflow itself (an authenticated, retried, persisted trigger). n8n waits until `remind_at` and calls `POST /api/cases/{id}/reminders` with a separate service token.
  - The backend keeps all authority: one reminder per request round, idempotent callbacks, and cancellation if staff replied or uploaded, the request was superseded, the case moved on or the deadline passed. Reminders go to the local in-app inbox only.
  - Without `REMINDERS_ENABLED`, a webhook URL and both tokens, reminders are reported unavailable and the rest of the app works unchanged.
- No real Paytm host is ever called.

### Enabling the live agent

The agent runs only after a live smoke test has passed (1–4 model calls; the result is kept for 24 hours):

```bash
cd backend
uv run python -m app.cli smoke-reasoner
```

Until then, and whenever the reasoner is unavailable or `REASONER_DAILY_CALL_CAP` is reached, the reasoning badge reads "Manual" and every action still works by hand.

### Enabling local speech-to-text (optional)

Install the optional extra, download the model once (needs `huggingface.co` and its file hosts such as `*.xethub.hf.co`), then run the smoke check. It transcribes `fixtures/hero/voice_note_mr.ogg` and records a pass only when the character error rate against the known script is at most `SPEECH_SMOKE_MAX_CER`:

```bash
cd backend
uv sync --extra speech
SPEECH_PROVIDER=faster_whisper uv run python -m app.cli speech-download
SPEECH_PROVIDER=faster_whisper uv run python -m app.cli smoke-speech
```

Models are never downloaded implicitly at runtime. With `SPEECH_PROVIDER=disabled` (the default), a missing model or a failed smoke check, voice notes are still stored with full provenance and the speaker types the transcription.

## Requirements

- Python ≥ 3.11 (tested with 3.13.17 and 3.12.12) and [uv](https://docs.astral.sh/uv/) (tested with 0.11.32 and 0.9.8)
- Node.js ≥ 22.19 (tested with 22.22.0 and 26.13.0) and npm 10+
- Optional: Docker with the compose plugin, for the n8n reminder workflow (tested with Docker 28.5.1)

## Configuration

Copy `.env.example` to `.env` if you want a local file. Real environment variables override `.env`, so keys set in a cloud environment's settings work without a `.env` file. Never commit a populated `.env`.

| Variable | Needed for | Notes |
| --- | --- | --- |
| `GEMINI_API_KEY` | Live reasoning (M3+). | Default primary reasoner. The free tier has low daily limits, and Google may use free-tier data, so send synthetic data only. |
| `GEMINI_MODEL` | Live reasoning. | Default `gemini-3.5-flash-lite`. Only Gemini 3.x models are used. |
| `REASONER_DAILY_CALL_CAP`, `REASONER_MIN_INTERVAL_SECONDS`, `AGENT_AUTORUN` | Quota control. | Defaults: 150 calls per rolling 24 h, at least 4 s between calls, agent runs triggered by events. |
| `OPENROUTER_API_KEY`, `FALLBACK_ENABLED=true` | Optional fallback. | Requires network access to `openrouter.ai`. |
| `SPEECH_PROVIDER=faster_whisper`, `WHISPER_MODEL`, `WHISPER_MODEL_DIR` | Optional voice-note transcription (M5). | Local CPU `int8` by default. `SPEECH_REQUIRE_PASSING_SMOKE=true` blocks transcription until `smoke-speech` passes. `sarvam` is reported as not implemented. |
| `SESSION_SECRET`, `DEMO_WEBHOOK_SECRET` | Stable demo sessions. | If left as placeholders in development, a random secret is generated each run. |

Without any model key the app still runs, and its reasoning badge reads **Manual**. A configured key is reported as `configured_untested` until the live smoke test in M3 passes.

## Run locally (no Docker)

```bash
cd backend
uv sync
uv run python -m app.cli init-db
uv run python -m app.cli seed
uv run uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8000 --workers 1
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. On an empty database in `DEMO_MODE`, the backend also seeds the hero case at startup.

Other commands:

```bash
cd backend
uv run python -m app.cli providers
uv run python -m app.cli check-config
uv run python -m app.cli reset --yes
```

Use exactly one Uvicorn worker. The per-case locks are in memory, and settings validation rejects `UVICORN_WORKERS` other than 1.

## Tests

```bash
cd backend
uv run pytest -q
uv run ruff check .
```

```bash
cd frontend
npm run build
npm run lint
```

```bash
cd frontend
npm test
```

Browser E2E: start the backend and frontend first. The script resets demo data through the drawer and refuses to run while the live agent is active, so it never spends model quota.

```bash
cd backend
AGENT_AUTORUN=false uv run uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8000 --workers 1
```

```bash
cd frontend
npm run e2e
```

Contract tests never call a live model and ignore any provider keys present in the environment.

## Layout

```text
backend/   FastAPI app (app/), Alembic migrations, pytest suite
frontend/  React + TypeScript + Vite
fixtures/  Synthetic demo organisation and hero-case documents
docs/      Screenshots from real runs
data/      Runtime database/evidence/packs (git-ignored)
```
