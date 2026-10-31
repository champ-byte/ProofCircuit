# ProofCircuit: Features

**Team:** MergeInfinity | **Track:** Paytm Build for India AI Hackathon, Track 3: Autonomous AI Teammates

ProofCircuit is an AI teammate that owns a merchant's payment-dispute response from the first notification to a verified submission. It finds missing proof, asks the right staff member, catches wrong evidence, builds a source-linked pack, submits it, and then independently checks that the submission registered.

> **Honesty notes.** All data is synthetic. Paytm is a simulator. No real money, WhatsApp or production Paytm endpoints are used. Results below come from our own synthetic test set, not real disputes. A submission is never claimed as a dispute win.

---

## 1. One-line pitch

A teammate that **understands, acts and escalates**: it does the evidence work for a "goods not received" dispute, and only a human can concede.

## 2. Hero flow

1. A synthetic Paytm-shaped dispute opens one case (the demo seeds it; the same intake also accepts signed Paytm-style callbacks). The header shows the amount at risk and a deadline countdown.
2. The invoice is present; delivery proof is missing.
3. The agent asks the delivery staff member in Marathi (Hindi and English are also supported).
4. Staff upload a receipt for the wrong order. The system detects the mismatch and blocks submission, showing both order IDs side by side.
5. The agent asks again. Staff upload the correct receipt. The old one stays in history, marked superseded with a reason.
6. The agent builds a frozen evidence pack, submits it to the simulator, and the backend reads the status separately.
7. The UI shows **"Submission verified — dispute outcome pending"** with the receipt ID and pack hash.

## 3. Feature list

### 3.1 Case handling
| Feature | What it does |
| --- | --- |
| Intake | Turns a Paytm-style notification into exactly one case; duplicate events are ignored. |
| Evidence ingestion | Accepts PDF, text and JSON; stores original files with SHA-256 fingerprints. |
| Source-linked facts | Every extracted fact points to the exact characters in its source document (code-point spans computed by the backend). |
| OCR safety | Scanned images are flagged "OCR required" rather than guessed. |
| Checklist | Tracks transaction/order link, invoice and delivery record as missing, supported, conflicting or review-required. |
| Contradiction checks | Wrong order ID, delivery date before order date, conflicting delivery dates, amount mismatches. |
| Prompt-injection defence | Hidden instructions inside documents ("ignore all rules…") are flagged as untrusted and never followed. |
| Staff requests | Sent to the configured staff member in their language, at most one per request round. |
| Superseded evidence | Wrong documents stay in history with a reason; nothing is silently deleted. |

### 3.2 The AI agent
- Gemini (3.x, default `gemini-3.5-flash-lite`) chooses each next step; the backend validates and executes it.
- 9 bounded tools. No concede, refund or free-form messaging tool.
- Wakes on events (manual start, staff reply, upload, provider update). It does not poll and makes no model calls while waiting.
- Up to 8 steps per run, 60-second hard limit per model call, bounded retries with backoff, a daily call cap.
- Escalates to a human when stuck, denied repeatedly or out of budget.
- Works without AI too: **Manual** mode and a clearly labelled **Fixture replay** mode.

### 3.3 Submission and verification
| Feature | What it does |
| --- | --- |
| Evidence pack | Frozen, versioned: cover summary, original files, `manifest.json`, source-linked HTML index, short remark built only from verified facts. |
| Pre-submit safety rules | Deadline open, pack current, no contradictions, no open review, file limits respected. Rechecked immediately before every write. |
| Submit, then verify | "Verified" is shown only when an independent status read and the simulator's receipt match the exact submission. |
| Timeout reconciliation | Lost responses and timeouts are reconciled before any retry; never submits twice. |
| POD rejection repair | One correction round using Paytm's exact reason. A repeat rejection, expired deadline, missing reason or unchanged evidence goes to a person. |
| Human authority | Only a reviewer can concede, with a confirmation that expires after 15 minutes and is single-use. |
| Refund guard | The refund check is a dry run and denies while a dispute is open. It never writes anything. |

### 3.4 Paytm simulator
- Status and Action endpoints with the full result-code tables.
- Dispute lifecycle: `NEW → POD_UPLOAD → POD_REJECT → WON / LOST`.
- Fault injection: timeouts, lost responses, upload failures, stale status.

### 3.5 Optional extras
- **Voice notes:** staff upload audio, transcribed locally (faster-whisper). Transcripts are labelled testimony that staff confirm or correct; they never count as proof.
- **n8n reminders:** the backend starts a workflow that waits, then calls back for one reminder. It is cancelled if staff replied, the round changed or the deadline passed. Needs Docker.

### 3.6 User interface
- Pages: `/cases` (queue), `/cases/:id` (workspace), `/evaluation` (results).
- Workspace: status banner, key-steps timeline, full audit log, source preview that jumps to cited text, side-by-side mismatch view, reviewer panel.
- Demo drawer: staff inbox, fault injector, identity switcher, seed/reset, provider readiness, resume pending work.
- Always-visible labels: "Synthetic data", "Paytm simulator", and the actual reasoning mode. Keyboard accessible; Devanagari renders correctly.

### 3.7 Testing and evaluation
- 280 backend tests, 24 frontend tests and a browser end-to-end test.
- A 40-case synthetic corpus with separately stored answers, plus a harness that drives a running server as the simulated staff and Paytm.
- Result: 40 of 40 correct on live Gemini, with no unsafe actions and no duplicate submissions. This is on our own synthetic set; two first attempts that exposed bugs were re-run after fixes and are listed on the evaluation page.

## 4. Demo runbook (verified 2026-10-31)

Before presenting:
1. Start the backend (`cd backend && uv run uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8000 --workers 1`) and the frontend (`cd frontend && npm run dev`).
2. Re-run the live-agent smoke test: `cd backend && uv run python -m app.cli smoke-reasoner` (1–4 model calls; lasts 24 h). The badge must read "Reasoning: Gemini — …".
3. Open http://127.0.0.1:5173, open the case, and in the demo drawer use **Seed / reset** for a fresh hero case.

Live demo (the agent decides; you play staff):
1. Click **Run agent / resume**. Banner: "Waiting for staff evidence"; a Marathi request appears in the staff inbox.
2. Drawer → **Upload delivery receipt wrong order**. Banner: "Submission blocked: contradiction found", with both order IDs side by side; a second Marathi message asks for the right receipt.
3. Drawer → **Upload delivery receipt correct**. Banner: "Submission verified — dispute outcome pending", with the receipt ID and pack hash.
4. Show `/evaluation`.

Backup if the model fails on stage (say it is replay): in the drawer, click **Fixture replay** to start, then again after each upload, and wait for the banner to change before the next step. It reaches the same verified end state with no model calls and every run labelled "Fixture replay (not AI)".

Optional n8n reminders need Docker Desktop running and `python n8n/setup.py --write-backend-env`, then a backend restart; otherwise leave reminders out of the demo.

## 5. Not built

| Item | Reason |
| --- | --- |
| Sarvam speech adapter | No key available |
| Live Paytm or WhatsApp | Out of scope by design |
| Local Gemma fallback, Cognee (M8) | Optional, not built |
| Real merchant pilot or measured production performance | Not claimed |

## 6. Ideas for later (not committed)
- **Prevention mode:** collect delivery proof when the order ships, so defences are one click.
- **Dispute radar:** spot patterns (courier, pincode) across cases.
- Image OCR with source bounding boxes.
- More dispute categories.
