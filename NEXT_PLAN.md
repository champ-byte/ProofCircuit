# Next plan: role-based demo, plain language, live activity drawer

Pick this up in a new chat. Read [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) first, then [CLAUDE.md](CLAUDE.md) (build rules and agent spec) and the last two BUILD_LOG.md entries ("Multi-language UI, Phase 1" and "Clearer flow, Phase 2").

Written 2026-10-31, branch `claude/stoic-pasteur-3b0gu1`.

**State at handover:** i18n Phase 1 and Phase 2 are finished and **not committed**. Checks: 42 frontend tests, the E2E, build and lint all pass. Ask the user before committing.

## Why this plan

The user's feedback after Phase 2:

1. **Too hard to follow:** the demo is a single page with an 11-account "Viewing as" dropdown, including test accounts. Every role sees every panel.
2. **Too much text:** there is too much to read, and too many technical words.
3. **No view of the activity:** they want a **side drawer that shows, interactively and live, what the agent is doing step by step, and what n8n is doing** (reminders), explained in plain words.

The voice assistant is **dropped for now** (user decision, 2026-10-31). Do not build it.

## Rules that still apply

- One phase at a time. After each phase, stop and report to the user, and update BUILD_LOG.md (commands, test counts, open issues).
- Never claim something works without a passing test or a real run. The user wants **real runs** (live Gemini on the real uvicorn server, real n8n) as well as unit tests.
- Keep all user decisions:
  - Gemini 3.x only, on free-tier caps.
  - Synthetic data and the Paytm simulator only.
  - The agent has no concede or refund tool.
  - Local faster-whisper only.
- Pause and ask the user before working around any problem.
- **Translations: English only for this plan** (user decision: editing the 10 language files costs too many edits).
  - Add new strings to `frontend/src/i18n/locales/en.json` only, and use `t()` everywhere so other languages fall back to English automatically.
  - Do not edit the other 9 locale files. In `src/i18n/locales.test.ts`, put every non-English language in `PARTIAL` (it keeps checking that no unknown keys exist and placeholders match).
  - Renamed labels (Phase B) change the English value only. Existing translations keep their current wording until a separate, optional translation pass.
- Keep the E2E (`frontend/e2e/hero.e2e.mjs`) passing: `E2E_ALLOW_LIVE=1 npm run e2e` with the backend on :8000 and Vite running. It resets demo data.

## Phase A: separate users (role-based sign-in)

**Goal:** each person signs in as one role and sees only their own screens.

1. **Sign-in screen** (`/signin`, also the first-visit screen after the language step of the existing `Welcome.tsx`):
   - Three cards: Shop owner (Asha), Staff (Sanjay / Meera), Reviewer (Ravi). Reuse the role copy already in `welcome.*` keys.
   - No passwords (demo). Signing in calls the existing `api.createSession(mid, handle)`.
   - Persist the identity under `proofsaathi.identity`, as today (`App.tsx`).
2. **Header:** replace the "Viewing as" `<select>` (`HeaderIdentity` in `App.tsx`) with "Asha · Shop owner" and a **Switch user** button that goes to `/signin`.
   - Show only MID-DEMO-001 people.
   - Never list Eval… / Other Owner / Demo Operator (they are test accounts).
3. **Role homes and route guards:**
   - Owner → `/cases` and `/cases/:id`. Keep the current tabs, but hide the reviewer panel.
   - Staff → `/staff` (exists, `pages/StaffPage.tsx`). Redirect staff away from `/cases*`.
   - Reviewer → new `/review`: only cases with open review tasks or `NEEDS_HUMAN_REVIEW`. Opening one shows a reviewer case view: `ReviewerPanel` first, then the evidence. Reviewers cannot run owner actions; the server already enforces this.
   - Nav links change per role.
4. **Operator page** `/operator`, linked quietly from the footer ("Demo controls"):
   - Move the `DemoDrawer.tsx` tabs here: fault injector, seed/reset, providers, resume, staff inbox for any staff member.
   - Move the evaluation link here too.
   - The case page no longer carries the demo drawer. Keep a small "Demo controls" link for the presenter.
5. **E2E update:** sign in through `/signin` instead of the dropdown. Use `/operator` for reset and fault injection (or keep a hidden drawer just for E2E; choose and record). The reviewer part signs in as Ravi.

**Done when:**
- Each role sees only its pages.
- Test accounts never appear in the UI.
- A vitest covers the route guards and sign-in.
- The E2E passes.
- A real browser run passes for each role.

## Phase B: plain language and less text

**Goal:** a shop owner can follow the case without reading paragraphs.

1. **Simple view by default.** A header toggle switches between "Simple view" and "Detailed view", stored in localStorage. Simple view hides:
   - hashes, code points, rule IDs, model/provider names
   - the reconciliation trail and tool names
   - the 7-step journey (`CaseJourney.tsx`, keep it only in Detailed view or under History)
   - extracted-facts tables and "simulator" sub-labels (keep the Synthetic data badge)
2. **One message, not two:** merge `StatusBanner` and `CaseGuide` into a single "next step" card with **one primary button**.
   - Keep `data-testid="status-banner"` on it, because the E2E reads the banner text.
3. **Rename** (English values only; see the translation rule above):

   | Current | Plain |
   | --- | --- |
   | Submit defense | Send response |
   | Evidence pack | Response file |
   | Validation findings | Problems found |
   | Concede | Accept customer's claim |
   | Testimony | Staff voice note |
   | Reasoning: Gemini — model | Assistant: on |
   | Reconciliation | (hidden in simple view) |

   - Update E2E selectors and tests that match the old English labels: `Submit defense (simulator)`, `Build evidence pack`, `Request delivery proof from staff`, `Step 1/2` concession labels, and key-step labels in `.steps`.
4. **Copy rules:** one or two sentences per card, under about 20 words each. No internal state names (`WAITING_FOR_EVIDENCE`, `POD_UPLOAD`). Numbers and names over adjectives.

**Done when:**
- In simple view, the case page shows no technical words (check by reading the rendered text in each language).
- Tests and the E2E pass with the new labels.

## Phase C: live activity drawer (agent flow + n8n)

**Goal:** a side drawer, open from any case page, that explains live what is happening and who is doing it.

**Layout:** a right-side drawer, toggled by an "Activity" button with a pulse while something runs. On phones it is full screen. It has two tabs or lanes.

**1. Assistant lane (agent flow)**

- **Data:** `GET /api/cases/{id}/runs` (`api.runs`, `RunView` with `tool_calls[]`: `step`, `tool`, `arguments`, `rationale`, `status` ok/denied/error, `result`), plus the event feed already followed every 1.5 s in `CaseWorkspace.tsx`.
- **Relevant events:** `agent.run_started`, `agent.run_failed`, `agent.idle`, `agent.invalid_output`, `agent.reasoner_unavailable`, `agent.reasoner_fallback`, `agent.not_run`.
- **Show each run as a vertical stepper:** Woke up (trigger, e.g. "staff replied") → Read the case → Decided: plain tool name → System check: allowed / blocked + why → Result → Waiting for X / Done.
- **Per step:**
  - Plain-language label (reuse `panels.action.*` / `panels.explain.*`).
  - The model's own reason (`rationale`).
  - Green / amber / red status.
  - Time.
  - "Details" expands the raw arguments and result (Detailed view only).
- **Live while running:** an animated "thinking" row for the current step. Show the call budget (step n of 8; run time limit 180 s) and the pacing between calls (4 s), in plain words.
- **Safety callouts:** when a step is denied, say which rule stopped it (deadline, contradiction, open review, role). The backend result already carries the reason.

**2. Reminders lane (n8n)**

- **Data:** the inbox tasks' `reminder` (`TaskReminderView`):
  - `trigger`: `pending` / `delivered` / `skipped` / `failed` / `paused`, plus `remind_at`, `attempts`, `error`.
  - `reminders[]`: `queued` / `sent` / `skipped`, plus `reason`, `reminder_number`, `created_at`.
- **Relevant events:** `reminder.trigger_created`, `reminder.trigger_retry`, `reminder.queued`, `reminder.sent`, `reminder.skipped`.
- **Show the real path as a flow diagram with the current position highlighted:** ProofSaathi asks staff → asks n8n to wait (trigger) → n8n waits until `remind_at` (countdown) → n8n calls back → ProofSaathi checks "has staff already replied?" → reminder sent to the inbox, or skipped with a reason.
- **States to cover:**
  - n8n off: "Reminders are off; staff can still reply."
  - Trigger failed: show the retry button (already exists via `api.retryReminderTrigger`, operator token).
  - Early reply: skipped `task_responded`.
  - Duplicate callback ignored.
- **Make clear:** n8n only schedules; the backend decides and sends; messages go only to the in-app inbox.

**3. Combined timeline (optional, if time allows):** one merged, time-ordered list of agent steps, reminder events and staff actions (who: Assistant / n8n / Sanjay / Asha / Paytm).

**Implementation notes**

- New components: `components/ActivityDrawer.tsx`, `AgentFlow.tsx`, `ReminderFlow.tsx`.
- Reuse the existing polling. **Do not add backend polling.** If something is missing from the API, ask before adding an endpoint.
- Check first whether `RunView` exposes per-step timestamps and the trigger. If not, a small read-only addition to the runs API may be needed (backend tests then required).
- Respect `prefers-reduced-motion`.
- The drawer must not block E2E clicks (closed by default, or non-modal).

**Done when:**
- A **real run** on the live backend works: press "Let the assistant check" on the hero case and watch the drawer step through `request_evidence` → waiting.
- With **n8n running** (Docker Desktop on, `python n8n/setup.py`, backend started with `REMINDERS_ENABLED=true` and the n8n env as in BUILD_LOG M6), the reminders lane shows the trigger, the countdown, and then sent or skipped. Repeat with an early staff reply, which should be skipped.
- Unit tests cover state mapping for runs (ok/denied/error, waiting, failed) and reminders (each trigger and reminder status).
- The E2E still passes.

## Known facts for the next session

- **Servers:**
  - Backend: started by the user's request in Terminal tab "backend" (`uv run uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8000 --workers 1` in `backend/`). Live Gemini, **reminders off**, ephemeral secrets.
  - Frontend: Vite runs on **5174** (user) and 5173 (earlier session).
  - n8n: **not running** (port 5678 closed).
- **Demo data:** fresh reset. Hero case DSP-DEMO-001 has an open Marathi delivery-record request to Sanjay.
- **Uncommitted work:** i18n setup and 10 locale files, `PROJECT_CONTEXT.md`, Phase 2 components (`Welcome`, `CaseProgress`, `Assistant`, `StaffInbox`, `Tour`, `LanguageSwitcher`, `StaffPage`, `guide.ts`), the E2E update, BUILD_LOG entries, regenerated E2E screenshots in `docs/`.
- **Ask the user first:** whether to commit Phases 1–2 before starting Phase A. The locale files cannot be left out of that commit, because `src/i18n/index.ts` imports all 10.

## Suggested order

A (sign-in + role pages) → B (plain language) → C (activity drawer, with a real n8n run).

Optional later: a translation pass for the new English strings (hi, mr, bn, gu, kn, ml, pa, ta, te) as its own small task.

Each phase ends with tests, the E2E, a real browser check, a BUILD_LOG entry and a stop to report.
