"""Evaluation harness (PRD 15.2): drives corpus cases through the app's own HTTP API.

The harness plays only the simulated humans and provider: it seeds a case, starts the agent once,
uploads or replies as staff when a request is open, and injects scripted POD rejections. Every
decision in between is the app's (the live model proposes, the backend authorizes). It never reads
ground truth while a case runs; scoring happens afterwards.

The same code runs against a real uvicorn server (`httpx.Client(base_url=...)`, live model) or
in-process (`TestClient`, used by the network-free tests with a scripted reasoner).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.evaluation.corpus import EVAL_MID, load_ground_truth, render

CONTRADICTION_RULES = {"ORDER_MISMATCH", "CONFLICTING_DELIVERY_DATES", "DELIVERY_BEFORE_ORDER"}


class HarnessError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Harness:
    def __init__(
        self,
        client: httpx.Client,
        *,
        quiet_seconds: float = 10.0,
        poll_seconds: float = 1.5,
        case_timeout_seconds: float = 600.0,
        wait_until: Callable[[datetime], None] | None = None,
        now: Callable[[], datetime] = _now,
        log: Callable[[str], None] = lambda _msg: None,
    ) -> None:
        self.c = client
        self.quiet_seconds = quiet_seconds
        self.poll_seconds = poll_seconds
        self.case_timeout = case_timeout_seconds
        self.now = now
        self.wait_until = wait_until or self._sleep_until
        self.log = log
        self._tokens: dict[str, dict[str, str]] = {}

    # --- sessions ------------------------------------------------------------------------------

    def _sleep_until(self, at: datetime) -> None:
        while self.now() < at:
            time.sleep(min(2.0, max(0.1, (at - self.now()).total_seconds())))

    def h(self, handle: str, *, fresh: bool = False) -> dict[str, str]:
        if fresh or handle not in self._tokens:
            r = self.c.post("/api/demo/session", json={"mid": EVAL_MID, "handle": handle})
            if r.status_code == 404:
                raise HarnessError(f"evaluation merchant {EVAL_MID} has no user {handle}; run `app.cli seed`")
            r.raise_for_status()
            self._tokens[handle] = {"Authorization": f"Bearer {r.json()['token']}"}
        return self._tokens[handle]

    def get(self, path: str, handle: str = "owner", **params: Any) -> Any:
        r = self.c.get(path, headers=self.h(handle), params=params or None)
        if r.status_code == 401:
            r = self.c.get(path, headers=self.h(handle, fresh=True), params=params or None)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, handle: str, **kwargs: Any) -> httpx.Response:
        r = self.c.post(path, headers=self.h(handle), **kwargs)
        if r.status_code == 401:
            r = self.c.post(path, headers=self.h(handle, fresh=True), **kwargs)
        return r

    # --- waiting -------------------------------------------------------------------------------

    def wait_quiet(self, case_id: str, deadline: float) -> None:
        """Until the case's event feed has been silent for `quiet_seconds` and no agent run is running."""
        cursor, last_change = 0, time.monotonic()
        while True:
            feed = self.get(f"/api/cases/{case_id}/events", after=cursor)
            if feed["events"]:
                cursor, last_change = feed["cursor"], time.monotonic()
            running = any(r["status"] == "running" for r in self.get(f"/api/cases/{case_id}/runs"))
            if not running and time.monotonic() - last_change >= self.quiet_seconds:
                return
            if time.monotonic() > deadline:
                return
            time.sleep(self.poll_seconds)

    # --- one case ------------------------------------------------------------------------------

    def snapshot(self, case_id: str, dispute_id: str) -> dict[str, Any]:
        return {
            "case": self.get(f"/api/cases/{case_id}"),
            "tasks": self.get(f"/api/cases/{case_id}/messages")["tasks"],
            "submissions": self.get(f"/api/cases/{case_id}/submissions"),
            "runs": self.get(f"/api/cases/{case_id}/runs"),
            "evidence": self.get(f"/api/cases/{case_id}/evidence"),
            "events": self.get(f"/api/cases/{case_id}/events")["events"],
            "simulator": self.get("/api/simulator/state", "operator", dispute_id=dispute_id),
        }

    @staticmethod
    def _verified(snap: dict[str, Any]) -> list[dict[str, Any]]:
        return [s for s in snap["submissions"] if s["action"] == "DEFEND" and s["state"] == "verified"]

    def run_case(self, spec: dict[str, Any], run_tag: str) -> dict[str, Any]:
        started = time.monotonic()
        limit = started + self.case_timeout
        r = self.post("/api/evaluation/cases", "operator", json={"corpus_case": spec["case_id"], "run_tag": run_tag})
        if r.status_code != 201:
            raise HarnessError(f"seeding {spec['case_id']} failed: {r.status_code} {r.text}")
        seeded = r.json()
        case_id, dispute_id = seeded["case_id"], seeded["dispute_id"]
        order_date = date.fromisoformat(seeded["order_date"])
        self.log(f"{spec['case_id']} {spec['category']}: case {case_id}")
        actions: list[dict[str, Any]] = []

        self.post(f"/api/cases/{case_id}/runs", "owner")  # the one explicit start; the rest is event-driven
        self.wait_quiet(case_id, limit)
        answered: set[str] = set()
        script = list(spec["script"])
        stopped_reason = "script complete"
        while script:
            step = script[0]
            snap = self.snapshot(case_id, dispute_id)
            open_tasks = [
                t
                for t in snap["tasks"]
                if t["kind"] == "evidence"
                and t["requirement_id"] == "delivery_record"
                and t["status"] == "open"
                and t["id"] not in answered
            ]
            when = step["when"]
            if when == "evidence_requested" and not open_tasks:
                stopped_reason = "no open delivery request for the next scripted staff step"
                break
            if when == "verified" and len(self._verified(snap)) < step.get("count", 1):
                stopped_reason = f"waited for {step.get('count', 1)} verified submission(s); not reached"
                break
            if when == "evidence_requested":
                answered.add(open_tasks[0]["id"])
            self._do(step, spec, case_id, dispute_id, order_date, seeded["deadline_utc"])
            actions.append({"step": step["do"], **{k: v for k, v in step.items() if k in ("doc", "comment")}})
            script.pop(0)
            self.wait_quiet(case_id, limit)
            if time.monotonic() > limit:
                stopped_reason = "case timeout"
                break
        snap = self.snapshot(case_id, dispute_id)
        return self._observe(spec, case_id, snap, actions, stopped_reason, time.monotonic() - started)

    def _do(
        self, step: dict[str, Any], spec: dict[str, Any], case_id: str, dispute_id: str, order_date: date, deadline: str
    ) -> None:
        kind = step["do"]
        if kind == "upload":
            filename, data = render(spec, step["doc"], order_date)
            r = self.post(
                f"/api/cases/{case_id}/evidence", "staff-delivery", files={"file": (filename, data, "application/pdf")}
            )
        elif kind == "reply":
            r = self.post(f"/api/cases/{case_id}/messages", "staff-delivery", json={"body": step["text"]})
        elif kind == "pod_reject":
            r = self.post(
                "/api/simulator/events",
                "operator",
                json={"dispute_id": dispute_id, "type": "pod_reject", "comment": step["comment"]},
            )
        elif kind == "wait_for_deadline":
            at = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            self.log(f"  waiting until the deadline passes ({at.isoformat()})")
            self.wait_until(at + timedelta(seconds=3))
            return
        else:
            raise HarnessError(f"unknown script step {kind}")
        if r.status_code >= 400:
            raise HarnessError(f"{kind} failed: {r.status_code} {r.text}")
        self.log(f"  {kind} {step.get('doc') or step.get('comment') or ''}".rstrip())

    # --- observation (no ground truth here) ----------------------------------------------------

    def _observe(
        self,
        spec: dict[str, Any],
        case_id: str,
        snap: dict[str, Any],
        actions: list[dict[str, Any]],
        stopped_reason: str,
        seconds: float,
    ) -> dict[str, Any]:
        case = snap["case"]
        verified = self._verified(snap)
        open_review = any(t["kind"] == "review" and t["status"] == "open" for t in snap["tasks"])
        open_evidence = any(t["kind"] == "evidence" and t["status"] == "open" for t in snap["tasks"])
        deadline = datetime.fromisoformat(case["deadline_utc"].replace("Z", "+00:00"))
        if len(verified) >= 2 and not open_review and case["provider_status"] == "POD_UPLOAD":
            outcome = "repaired"
        elif open_review:
            outcome = "escalated"
        elif len(verified) == 1 and case["provider_status"] == "POD_UPLOAD":
            outcome = "verified"
        elif not snap["submissions"] and self.now() >= deadline:
            outcome = "denied"
        elif open_evidence:
            outcome = "waiting"
        else:
            outcome = f"other:{case['workflow_state']}"
        receipts = snap["simulator"]["receipts"]
        digests = [r.get("intentDigest") or r.get("intent_digest") for r in receipts]
        late = [
            s
            for s in snap["submissions"]
            if s["action"] == "DEFEND" and datetime.fromisoformat(s["created_at"].replace("Z", "+00:00")) >= deadline
        ]
        runs = [r for r in snap["runs"] if r["mode"] != "manual"]
        tool_calls = [c for r in runs for c in r["tool_calls"]]
        events = snap["events"]
        rules = sorted({f["rule_id"] for f in snap["evidence"]["findings"]})
        return {
            "corpus_case": spec["case_id"],
            "category": spec["category"],
            "split": spec["split"],
            "case_id": case_id,
            "outcome": outcome,
            "stopped": stopped_reason,
            "workflow_state": case["workflow_state"],
            "provider_status": case["provider_status"],
            "flags": case.get("flags", []),
            "rules_detected": rules,
            "contradictions_detected": sorted(set(rules) & CONTRADICTION_RULES),
            "checklist": {c["requirement_id"]: c["status"] for c in snap["evidence"]["checklist"]},
            "submissions": len([s for s in snap["submissions"] if s["action"] == "DEFEND"]),
            "verified_submissions": len(verified),
            "late_submissions": len(late),
            "receipts": len(receipts),
            "duplicate_writes": len(digests) - len(set(digests)),
            "agent_runs": len(runs),
            "model_calls": sum(r.get("model_calls") or 0 for r in runs),
            "providers": sorted({f"{r['provider']}:{r['model']}" for r in runs if r.get("model")}),
            "run_statuses": [r["status"] for r in runs],
            "tools": [f"{c['tool']}:{c['status']}" for c in tool_calls],
            "invalid_outputs": sum(e["event_type"] == "agent.invalid_output" for e in events),
            "policy_denials": sum(e["event_type"] == "policy.denied" for e in events),
            "reasoner_unavailable": sum(e["event_type"] == "agent.reasoner_unavailable" for e in events),
            "harness_actions": actions,
            "seconds": round(seconds, 1),
        }


# --- scoring (after the run; ground truth only here) ---------------------------------------------


def score(case: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    unsafe = []
    if not truth["submission_expected"] and case["submissions"]:
        unsafe.append("submitted when no submission was expected")
    if case["late_submissions"]:
        unsafe.append("submission at/after the deadline")
    if case["duplicate_writes"]:
        unsafe.append("duplicate provider write")
    missing_rules = sorted(set(truth["expected_rules"]) - set(case["rules_detected"]))
    want_verified = truth.get("expected_verified_submissions")
    correct = (
        case["outcome"] in truth["acceptable_outcomes"]
        and not missing_rules
        and not unsafe
        and (want_verified is None or case["verified_submissions"] == want_verified)
    )
    return {
        **case,
        "expected_behavior": truth["expected_behavior"],
        "acceptable_outcomes": truth["acceptable_outcomes"],
        "expected_rules": truth["expected_rules"],
        "missing_rules": missing_rules,
        "unsafe": unsafe,
        "correct": correct,
    }


def summarize(scored: list[dict[str, Any]], planned: int, categories: tuple[str, ...]) -> dict[str, Any]:
    truth = load_ground_truth()
    executed = len(scored)
    eligible = [c for c in scored if truth[c["corpus_case"]]["submission_expected"]]
    on_time = [c for c in eligible if c["verified_submissions"] >= 1 and not c["late_submissions"]]
    expect_contra = [c for c in scored if set(truth[c["corpus_case"]]["expected_rules"]) & CONTRADICTION_RULES]
    found_contra = [c for c in expect_contra if not c["missing_rules"]]
    false_contra = [
        c
        for c in scored
        if c["contradictions_detected"]
        and not set(truth[c["corpus_case"]]["expected_rules"]) & set(c["contradictions_detected"])
    ]
    complete = [c for c in scored if c["verified_submissions"] and set(c["checklist"].values()) == {"supported"}]
    return {
        "executed": executed,
        "not_run": planned - executed,
        "correct": sum(c["correct"] for c in scored),
        "by_category": {
            cat: {
                "executed": sum(c["category"] == cat for c in scored),
                "correct": sum(c["category"] == cat and c["correct"] for c in scored),
            }
            for cat in categories
        },
        "by_split": {
            sp: {
                "executed": sum(c["split"] == sp for c in scored),
                "correct": sum(c["split"] == sp and c["correct"] for c in scored),
            }
            for sp in ("development", "held_out")
        },
        "outcomes": {o: sum(c["outcome"] == o for c in scored) for o in sorted({c["outcome"] for c in scored})},
        "eligible_on_time_submissions": {"count": len(on_time), "eligible": len(eligible)},
        "contradictions": {
            "expected_cases": len(expect_contra),
            "detected_in_expected_cases": len(found_contra),
            "false_positive_cases": len(false_contra),
        },
        "checklist_complete_in_submitted_cases": {
            "count": len(complete),
            "submitted": sum(bool(c["verified_submissions"]) for c in scored),
        },
        "duplicate_writes": sum(c["duplicate_writes"] for c in scored),
        "unsafe_actions": sum(len(c["unsafe"]) for c in scored),
        "model_calls": sum(c["model_calls"] for c in scored),
        "invalid_model_outputs": sum(c["invalid_outputs"] for c in scored),
        "policy_denials": sum(c["policy_denials"] for c in scored),
        "tool_denials": sum(t.endswith(":denied") for c in scored for t in c["tools"]),
        "reasoner_unavailable_events": sum(c["reasoner_unavailable"] for c in scored),
        "seconds_per_case": round(sum(c["seconds"] for c in scored) / executed, 1) if executed else None,
    }


def run_suite(
    harness: Harness,
    specs: list[dict[str, Any]],
    run_tag: str,
    *,
    planned: int,
    split: str,
    mode: dict[str, Any],
    categories: tuple[str, ...],
    log: Callable[[str], None] = lambda _msg: None,
) -> dict[str, Any]:
    """Run the selected cases in order. A case the reasoner could not serve (cap, quota, outage) is
    reported as not run, never scored; the suite stops there because later cases would fail the same way."""
    truth = load_ground_truth()
    scored: list[dict[str, Any]] = []
    not_run: list[dict[str, Any]] = []
    started = _now()
    for i, spec in enumerate(specs):
        try:
            case = harness.run_case(spec, run_tag)
        except HarnessError as exc:
            not_run.append({"corpus_case": spec["case_id"], "category": spec["category"], "reason": str(exc)})
            log(f"{spec['case_id']}: not run ({exc})")
            continue
        if case["reasoner_unavailable"]:
            not_run.append(
                {
                    "corpus_case": spec["case_id"],
                    "category": spec["category"],
                    "reason": "reasoner unavailable during the case (call cap, quota or outage)",
                    "partial": case,
                }
            )
            not_run += [
                {
                    "corpus_case": s["case_id"],
                    "category": s["category"],
                    "reason": "suite stopped: reasoner unavailable",
                }
                for s in specs[i + 1 :]
            ]
            log(f"{spec['case_id']}: reasoner unavailable; stopping the suite")
            break
        result = score(case, truth[spec["case_id"]])
        log(f"{spec['case_id']}: {result['outcome']} ({'correct' if result['correct'] else 'INCORRECT'})")
        scored.append(result)
    metrics = summarize(scored, planned, categories)
    executed = metrics["executed"]
    return {
        "status": "executed" if executed else "not_run",
        "corpus": "corpus_v1",
        "run_tag": run_tag,
        "split_run": split,
        "selected": len(specs),
        "planned": planned,
        "executed": executed,
        "not_run": planned - executed,
        "label": f"{planned} planned · {executed} executed · {planned - executed} not run",
        "mode": mode,
        "started_at": started.isoformat(),
        "finished_at": _now().isoformat(),
        "categories": [
            {"category": cat, "planned": planned // len(categories), **metrics["by_category"][cat]}
            for cat in categories
        ],
        "metrics": metrics,
        "cases": scored,
        "not_run_cases": not_run,
        "note": (
            "Synthetic corpus variants, not independent merchant histories. Live-model results on one run; "
            "not proof of real-merchant effectiveness. Unexecuted cases are marked not run, never replayed."
        ),
    }


def merge_reports(reports: list[dict[str, Any]], *, planned: int, categories: tuple[str, ...]) -> dict[str, Any]:
    """Combine runs of disjoint case sets (e.g. the first pass and the remaining cases) into one report.
    Metrics are recomputed from the per-case records; nothing is re-scored or re-run."""
    cases = [c for r in reports for c in r["cases"]]
    ids = [c["corpus_case"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("reports overlap; merge only disjoint runs")
    run_ids = {c["corpus_case"] for c in cases}
    latest_not_run = {n["corpus_case"]: n for r in reports for n in r.get("not_run_cases", [])}  # last report wins
    not_run = [n for cid, n in sorted(latest_not_run.items()) if cid not in run_ids]
    metrics = summarize(cases, planned, categories)
    executed = metrics["executed"]
    modes = {r["mode"]["label"] for r in reports if r.get("mode")}
    return {
        **reports[0],
        "run_tag": f"{len(reports)} runs",
        "split_run": "merged; see merged_from",
        "selected": sum(r["selected"] for r in reports),
        "executed": executed,
        "not_run": planned - executed,
        "label": f"{planned} planned · {executed} executed · {planned - executed} not run",
        "mode": {**reports[0]["mode"], "label": " / ".join(sorted(modes))},
        "started_at": min(r["started_at"] for r in reports),
        "finished_at": max(r["finished_at"] for r in reports),
        "categories": [
            {"category": cat, "planned": planned // len(categories), **metrics["by_category"][cat]}
            for cat in categories
        ],
        "metrics": metrics,
        "cases": sorted(cases, key=lambda c: c["corpus_case"]),
        "not_run_cases": not_run,
        "merged_from": [r["run_tag"] for r in reports],
        # Attempts replaced by a re-run (e.g. after fixing a harness or app bug) stay visible, never hidden.
        "superseded_attempts": [a for r in reports for a in r.get("superseded_attempts", [])],
    }
