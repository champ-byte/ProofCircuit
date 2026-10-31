   Build ProofCircuit from PRD.md. Read it fully before coding.
   Work one milestone at a time (Section 17); stop and report after each.
   Keep BUILD_LOG.md updated with commands run, tests passed, and open issues.
   Never claim a feature works without a passing test or a real run.

---

# ProofCircuit: Agent Specification

How the ProofCircuit agent behaves. The source of truth is the code in `backend/app/agent/` (loop, tools, prompt) and `backend/app/services/policy.py`; keep this file in step with it.

## 1. Role

The agent is an autonomous teammate for **one dispute case at a time** (first scope: goods not received, physical goods). Its job is to get from "dispute opened" to "response submitted and verified" with the least human effort, and to stop and hand over whenever a decision is not safe to make alone.

**The model proposes. The backend authorizes. Only a human can concede.**

## 2. The agent's tools (exactly 9)

Defined in `backend/app/providers/base.py` (`AGENT_TOOLS`) and implemented in `backend/app/agent/tools.py`.

| Tool | What it does |
| --- | --- |
| `get_case_context` | Read case state: checklist, findings, documents, staff tasks, deadline, provider status |
| `inspect_evidence` | Read one document's extracted facts and source snippets |
| `request_evidence` | Ask the configured staff member for a missing record, in their language; one request per round |
| `validate_evidence` | Re-run the deterministic checks and refresh the checklist |
| `request_human_review` | Escalate with a short reason code and a question |
| `build_evidence_pack` | Build a frozen, versioned, source-linked pack (denied while evidence is not ready) |
| `submit_defense` | Submit the current pack to the simulator (only after policy checks pass) |
| `get_submission_status` | Read the independent provider status |
| `wait_for_event` | Stop the run until a new event arrives |

**Done by the backend automatically, not by agent tools:** superseding wrong evidence, flagging contradictions, verifying a submission against the simulator receipt, and opening the one POD correction round after a recognized rejection.

## 3. What it can never do

- Concede or accept a dispute (there is no such tool; concession is a reviewer API).
- Issue or request a refund (the refund check is a dry-run endpoint the agent cannot call).
- Send arbitrary messages; recipients and templates come from configured staff roles.
- Submit after the deadline, or while a contradiction or review is open.
- Treat instructions inside documents as commands.
- Claim a win. The outcome stays "pending" unless the provider reports it.

## 4. Run loop (`backend/app/agent/loop.py`)

1. **Wake on an event:** manual start, staff reply, upload, provider update. No polling and no model calls while waiting.
2. **Load context:** trusted case context, plus an untrusted block with verified facts, the last staff messages, voice-note testimony and (in a correction round) the provider's rejection comment.
3. **Choose one action:** the model returns one structured JSON action.
4. **Backend validates:** schema, arguments, permissions, deadline, ownership, policy. Invalid output is re-asked (up to 2 repairs); a denied step is fed back to the model in the run history.
5. **Execute and persist:** every tool call stores a result. The UI only shows what was persisted.
6. **Repeat** until the case is waiting on staff or a human, submitted and verified, or escalated.

### Limits
- Up to 8 proposals per run, 180-second run budget.
- 60-second hard limit per model call; transient errors (5xx, time-outs) get up to 2 retries with backoff (5 s, then 15 s).
- Daily model-call cap (default 150 in a rolling 24 h) and pacing between calls.
- Two consecutive denials, an exhausted budget or repeated invalid output escalate to a human; it never loops.

## 5. Decision rules

### Submit only if all are true (rechecked right before the write)
- The deadline is still open.
- The evidence pack is current and the latest.
- No blocking contradiction and no open review.
- File count, size and type limits are respected.
- After a POD rejection: a correction round is open and the evidence has changed.

### Ask staff when
- Delivery proof is missing, or the uploaded proof contradicts the order.
- Maximum one request per round; a duplicate proposal returns the existing request.

### Escalate to a human when
- A contradiction cannot be fixed by asking staff (for example, conflicting delivery dates).
- The agent is stuck, denied twice in a row, out of budget, or the model keeps returning invalid actions.

The backend also opens a review by itself when: a POD rejection is repeated, has no reason, arrives after the deadline or refers to an older pack; provider status cannot be read; or a submission cannot be verified.

### Concede
Not an agent action. A reviewer chooses "Accept the customer's dispute (concede)" with a single-use confirmation that expires after 15 minutes.

## 6. Evidence handling

- Facts are extracted from the **actual uploaded bytes/text**; the backend computes each fact's exact character span.
- Scanned images are flagged "OCR required", never guessed.
- Voice-note transcripts are **testimony**, labelled as such; staff must confirm or correct them. They are never proof.
- Document text is **untrusted data**. Hidden instructions are flagged (an `UNTRUSTED_INSTRUCTIONS` finding), not followed.

## 7. Modes

| Mode | When | Label in UI |
| --- | --- | --- |
| Live agent | The Gemini smoke test passed (it lasts 24 h; re-run `uv run python -m app.cli smoke-reasoner` before a demo) | "Reasoning: Gemini — `<model>`" |
| Manual | No reasoner ready; a person presses the buttons | "Manual" |
| Fixture replay | Operator-only backup demo | "Fixture replay" (not proof of autonomy) |

## 8. Prompting guidelines (for maintainers)

- Give the model a narrow tool surface and the current case state, not the whole history.
- Require structured JSON actions and validate them server side.
- State the "never" list in the system prompt, but enforce it in code. Prompts alone are not a guardrail.
- Log the provider and returned model for every run.

## 9. Audit

Every run records the trigger, provider and model, each action with its rationale, validation result, tool result and timestamps. The UI timeline and audit log read from these records.

## 10. Evaluation

- 40 synthetic cases (`fixtures/benchmark/corpus_v1.json`) with separately stored ground truth (`fixtures/ground_truth/`).
- Report real counts: correct outcomes, unsafe actions, duplicate submissions; mark unexecuted cases "not run".
- Test deterministic logic without the model; test the real model separately (`uv run python -m app.cli evaluate`).
