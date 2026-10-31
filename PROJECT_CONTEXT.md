# ProofCircuit / ProofSaathi: project context in one file

Read this first for the overall picture. Details live in [PRD.md](PRD.md) (spec), [CLAUDE.md](CLAUDE.md) (build rules and agent spec), [ARCHITECTURE.md](ARCHITECTURE.md), [Features.md](Features.md) (features and demo runbook), [HANDOFF.md](HANDOFF.md) (setup and decisions) and [BUILD_LOG.md](BUILD_LOG.md) (full history, test counts, open issues). The code is the source of truth.

Status as of 2026-10-31, branch `claude/stoic-pasteur-3b0gu1` (not merged to `main`).

## 1. What it is

When a customer tells Paytm "I never got my order", Paytm opens a **chargeback dispute** and holds the shop's money. The shop must answer with proof before a deadline. Small shop owners often miss it, because the proof sits with staff (a delivery slip on a driver's phone) and the process is confusing.

**ProofSaathi** (repo name ProofCircuit) handles one dispute case end to end: it finds what proof is missing, asks the right staff member in their own language, checks the documents against each other, builds a source-linked evidence pack, submits it, and verifies the receipt. An AI agent does the routine steps; the backend authorizes every step; only a human can give up (concede).

> The model proposes. The backend authorizes. Only a human can concede.

First scope: goods-not-received disputes for physical goods. **Synthetic data only; the Paytm side is a local simulator, never a real Paytm host.**

## 2. Who uses it (roles)

| Role | Demo person | Who that is in real life | What they do |
| --- | --- | --- | --- |
| Shop owner | Asha (Metro Furniture) | The merchant whose payment is disputed | Sees cases, collects proof, approves and sends the response |
| Staff member | Sanjay (delivery, Marathi), Meera (billing, Hindi) | The shop's own employees, **not Paytm staff** | Get requests in their language; reply, upload documents, send voice notes |
| Reviewer | Ravi | Shop manager or accountant | Decides hard cases (documents that disagree); the only one who can concede |
| Demo operator | Operator | Person running the demo | Reset data, inject simulator faults, check providers |
| Paytm | (simulated) | The payment company | Receives the response, confirms receipt, later decides WON/LOST |

## 3. The main flow (hero case DSP-DEMO-001, ₹18,500)

1. Dispute arrives → checklist shows the **delivery record is missing**.
2. Agent asks Sanjay for it **in Marathi**; an optional n8n reminder follows if he doesn't answer.
3. Sanjay uploads a receipt for the **wrong order** → the backend flags a contradiction (ORD-DEMO-18500 vs ORD-DEMO-OTHER) and blocks submission.
4. Agent asks again; Sanjay may send a voice note (kept as **testimony, never proof**).
5. The correct receipt arrives → evidence complete → frozen, versioned pack built.
6. Submitted to the simulator → receipt verified → "Submission verified — dispute outcome pending". It never claims a win until Paytm reports one.

## 4. How it is built

- **Backend:** FastAPI (one uvicorn worker), SQLAlchemy + SQLite (WAL), Alembic migrations 0001–0007. Work is event-triggered (PendingWork queue, per-case locks); nothing polls.
- **Agent:** Gemini `gemini-3.5-flash-lite` (Gemini 3.x only, free tier) behind a router with a daily cap (150), 4 s pacing, a 60 s hard limit per call and retries with backoff. It has exactly **9 tools** (get context, inspect, request evidence, validate, request review, build pack, submit, get status, wait). It has no concede or refund tool. Each run allows at most 8 proposals and lasts at most 180 s. Modes: live, manual, fixture replay (operator-only backup).
- **Deterministic services** (not AI): text extraction with exact code-point citations, validation rules, superseding wrong evidence, pack building, submission reconciliation, POD-rejection repair (C07).
- **Speech:** local faster-whisper (`small` by default). Transcripts are testimony that staff confirm or correct. Sarvam AI is not built.
- **Reminders:** self-hosted n8n 2.45.6 in Docker only schedules; the backend keeps authority and delivers to the in-app inbox.
- **Frontend:** React 19 + Vite + TypeScript, react-router, react-i18next (10 Indian languages), vitest tests, and a Playwright end-to-end test (`frontend/e2e/hero.e2e.mjs`). Fonts: Poppins/Inter plus Indic fallbacks.

Key folders: `backend/app/{agent,api,services,simulator,evaluation}`, `frontend/src/{pages,components,i18n}`, `fixtures/`, `n8n/`, `scripts/`, `docs/evaluation/`.

## 5. Milestones (PRD §17)

| Milestone | Status |
| --- | --- |
| M0 Bootstrap, M1 Evidence, M2 Tools + simulator, M3 Real agent, M4 Product UI | Done |
| M5 Staff voice notes (local faster-whisper) | Done; human Marathi clip CER 0.21 `small`, 0.16 `medium`, 0.09 `large-v3` |
| M6 n8n follow-up reminders | Done; live check passed |
| M7 Tests and evaluation | Done; PRD test groups C01–C08 pass; live 40-case Gemini evaluation exported to `docs/evaluation/` |
| M8 Optional (local Gemma, Cognee) | Not started |

Last recorded checks: backend 280 pytest passed, ruff clean; live hero run, fixture-replay backup, live authority check (C04) and n8n live check all passed.

## 6. Current work: making the UI understandable (not committed yet)

The user asked for three phases, each with a stop and report afterwards:

1. **Multi-language (done, uncommitted):** react-i18next, 10 languages (en, hi, mr, bn, gu, kn, ml, pa, ta, te), a header language switcher, the choice remembered in the browser, and a test that every language has every key. Translations are machine-drafted and need native-speaker review.
2. **Clearer flow (done, uncommitted):**
   - First-visit language/role chooser (the role is remembered).
   - Case page: 3-stage progress, tabs (Next step / Proof / Response / History) and an assistant card ("working" vs "Do it myself").
   - A staff screen at `/staff`, and a guided tour with read-aloud.
   - Remaining panels translated. Tamil and Telugu are paused (English fallback for the new text).
   - Checks: 42 frontend tests pass and the E2E passes.
3. **Voice assistant (next):** a floating mic. It speaks using browser speech; it listens using browser speech recognition, local faster-whisper, or a speak-only mode. It never submits, concedes or approves by voice.

Operator-only tools (fault injector, providers, reset) and the evaluation page stay in English. Text generated by the server (audit summaries, next-action lines, agent rationales) is still English.

## 7. Decisions to keep

Gemini 3.x only on free-tier caps. Synthetic data and the Paytm simulator only. No concede or refund tool for the agent. Local faster-whisper only (Sarvam not built). Test with **real runs** (live Gemini, real uvicorn, real n8n) as well as offline tests. Money is stored in paise, times in UTC, citations as code-point spans. Never print or commit `GEMINI_API_KEY`. Full list: HANDOFF.md "Decisions".

## 8. Run it locally

```bash
cd backend && uv sync && uv run uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8000 --workers 1
```

```bash
cd frontend && npm ci && npm run dev -- --host 127.0.0.1 --port 5173
```

Checks: `uv run pytest -q` (backend); `npm test`, `npm run build`, `npm run lint`; `E2E_ALLOW_LIVE=1 npm run e2e` with both servers running (it resets demo data). Secrets go in a gitignored `.env` (see HANDOFF.md).

## 9. Known open issues

- The Gemini free tier has 503 "high demand" waves. Backoff helps; manual mode always works.
- A backend 500 can occur if an action races a demo reset (demo-only).
- The robotic espeak speech smoke fixture fails for every model, so live STT needs `SPEECH_REQUIRE_PASSING_SMOKE=false`.
- The OpenRouter fallback can't be exercised (network-blocked).
- The frontend bundle is about 660 kB because all locales are bundled.
- Pre-event code eligibility under hackathon rules is unconfirmed (PRD §19.1).
