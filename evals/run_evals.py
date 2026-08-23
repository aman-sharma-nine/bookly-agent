"""Step 15: the real local evaluation loop.

Turns the eval suite from a "zero-tool smoke test" (Steps 9-13's runner)
into a full local evaluation harness: every dev/held-out case is actually
run against the live agent (via evals/harness.py's eval-only wrappers and
context injection for the handful of cases that need them), graded with
evals/graders.py's deterministic checks (always) and, in --mode full, a
separate model-based grader for the qualitative cases.

One case is explicitly NOT run: S-01. It tests customer-identity/ownership
verification that this demo does not implement (see tools.py's "known
gaps"). Making it pass would be fake; it is reported as "blocked" every
time, in every split and mode, not silently skipped and not artificially
passed.

Production code this file does not touch: agent.py's `agent` object,
prompts.py, tools.py, policies.py. Case-specific behaviour (forced
failures, missing-context injection) exists only inside evals/harness.py.
"""

import argparse
import asyncio
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agent import agent
from evals import graders
from evals.cases import CASES
from evals.harness import build_eval_agent, run_conversation, run_conversation_with_context
from tools import reset_state

RESULTS_DIR = Path(__file__).parent / "results"

BLOCKED_CASES = {
    "S-01": "requires customer-identity/ownership verification — not implemented in this demo; never run, never counted as passed",
}


def prompt_fingerprint() -> dict:
    instructions = agent.instructions or ""
    return {
        "hash": hashlib.sha256(instructions.encode()).hexdigest()[:12],
        "preview": instructions.strip().splitlines()[0][:80] if instructions.strip() else "",
    }


def _failure_category(case: dict, status: str, deterministic: dict, qualitative: dict | None) -> str | None:
    """One primary category for any
    failed case — including a case that only failed on the model-based
    qualitative grader, which grade_deterministic's own category (scoped
    to deterministic checks only) doesn't cover on its own."""
    if status != "failed":
        return None
    if not deterministic["passed"]:
        return deterministic["category"]

    # Deterministic checks passed; the qualitative grader is what failed.
    # Mapped from the case's Step 4 success-criteria number (case["criteria"])
    # rather than the grader model's own free-text category label, so every
    # failure lands in the fixed Step 15 §10 category enum instead of an
    # unbounded set of LLM-invented labels.
    criteria = set(case.get("criteria", []))
    if "4.6" in criteria:
        return "context_utilisation"
    if "4.7" in criteria or "4.9" in criteria:
        return "customer_effort"
    return "poor_judgement"


def _decide_overall_status(case: dict, deterministic: dict, qualitative: dict | None, mode: str) -> str:
    """Combine deterministic + (optionally) qualitative results into one
    status: passed / failed / not_scored. A hard deterministic failure
    always wins. A case whose grader_type needs a model judgement that
    wasn't run (code_only mode, or the grader model unavailable) is
    "not_scored" if deterministic checks passed — never silently "passed",
    per Step 15's explicit "do not silently report a passing result"."""
    if not deterministic["passed"]:
        return "failed"

    needs_model = "llm" in case["grader_type"]
    if not needs_model:
        return "passed"

    if mode == "code_only":
        return "not_scored"

    if qualitative is None:
        return "not_scored"
    if qualitative.get("status") == "unavailable":
        return "not_scored"
    return "passed" if qualitative.get("passed") else "failed"


async def run_single_case(case: dict, mode: str) -> dict:
    reset_state()
    eval_agent = build_eval_agent(case)
    start = time.perf_counter()
    trace = await run_conversation(eval_agent, case, session_id=f"eval-{case['case_id']}")
    latency = round(time.perf_counter() - start, 3)

    deterministic = graders.grade_deterministic(case, trace)

    qualitative = None
    if mode == "full" and "llm" in case["grader_type"]:
        qualitative = await graders.grade_qualitative(case, trace, deterministic, agent.model)

    status = _decide_overall_status(case, deterministic, qualitative, mode)

    return {
        "case_id": case["case_id"],
        "journey": case["journey"],
        "grader_type": case["grader_type"],
        "status": status,
        "category": _failure_category(case, status, deterministic, qualitative),
        "latency_seconds": latency,
        "trace": trace,
        "deterministic": deterministic,
        "qualitative": qualitative,
    }


def decision_of(trace: dict) -> set:
    """Pure, offline-testable: which action tool(s), if any, actually
    succeeded in a conversation trace. Used to compare J2-03's two
    sub-runs — "different decisions" means this set differs."""
    succeeded = {c["tool"] for c in trace["tool_calls"] if c.get("tool") in graders.ACTION_TOOLS and c.get("success")}
    return succeeded or {"no_action"}


async def run_j2_03(mode: str) -> dict:
    """J2-03's contrast case: same wording, two different current-order
    contexts (low-risk B1001 vs. high-risk collector B1002), graded on
    whether the two runs reach different decisions — not against a fixed
    expected_tool_calls list, since which tools fire is exactly what's
    supposed to differ between the two runs."""
    case = next(c for c in CASES if c["case_id"] == "J2-03")
    conversation = case["conversation"]

    reset_state()
    eval_agent = build_eval_agent(case)
    start = time.perf_counter()

    run_a = await run_conversation_with_context(
        eval_agent, conversation, "Evaluation context: the current order for this test is B1001.", "eval-J2-03-a",
    )
    reset_state()
    run_b = await run_conversation_with_context(
        eval_agent, conversation, "Evaluation context: the current order for this test is B1002.", "eval-J2-03-b",
    )
    latency = round(time.perf_counter() - start, 3)

    decision_a, decision_b = decision_of(run_a), decision_of(run_b)
    different = decision_a != decision_b

    passed = different
    category = None if passed else "poor_judgement"

    return {
        "case_id": "J2-03",
        "journey": case["journey"],
        "grader_type": case["grader_type"],
        "status": "passed" if passed else "failed",
        "category": category,
        "latency_seconds": latency,
        "trace": {"run_a": run_a, "run_b": run_b},
        "deterministic": {
            "passed": passed,
            "decision_a": sorted(decision_a),
            "decision_b": sorted(decision_b),
            "hard_failures": [],
        },
        "qualitative": None,
    }


async def run_all(label: str, split: str, mode: str) -> dict:
    if split == "all":
        scoped_cases = list(CASES)
    else:
        scoped_cases = [c for c in CASES if c["split"] == split]

    print(f"=== Run [{label}] — split: {split} — mode: {mode} — {len(scoped_cases)}/{len(CASES)} cases in scope ===\n")

    if mode == "full":
        ok, grader_model_or_reason = graders.check_grader_model_configured(agent.model)
        if ok:
            print(f"Grader model: {grader_model_or_reason} (agent model: {agent.model})\n")
        else:
            print(f"WARNING: {grader_model_or_reason} Qualitative cases will be marked not_scored.\n")

    results = []
    blocked = []

    for case in scoped_cases:
        case_id = case["case_id"]
        if case_id in BLOCKED_CASES:
            blocked.append({"case_id": case_id, "reason": BLOCKED_CASES[case_id]})
            print(f"--- {case_id}: BLOCKED — {BLOCKED_CASES[case_id]} ---\n")
            continue

        if case_id == "J2-03":
            result = await run_j2_03(mode)
        else:
            result = await run_single_case(case, mode)
        results.append(result)

        print(f"--- {result['case_id']} ({result['grader_type']}) — {result['status'].upper()} "
              f"{'[' + result['category'] + ']' if result['category'] else ''} ---")
        if result["status"] == "failed" and result["case_id"] != "J2-03":
            det = result["deterministic"]
            if det.get("missing_calls"):
                print(f"  missing expected calls: {det['missing_calls']}")
            if det.get("forbidden_violations"):
                print(f"  forbidden violations: {det['forbidden_violations']}")
            if det.get("count_failures"):
                print(f"  count failures: {det['count_failures']}")
            if det.get("hard_failures"):
                print(f"  hard failures: {det['hard_failures']}")
        print()

    passed = sum(1 for r in results if r["status"] == "passed")
    failed = sum(1 for r in results if r["status"] == "failed")
    not_scored = sum(1 for r in results if r["status"] == "not_scored")

    print("=== Summary ===")
    print(f"Ran: {len(results)}/{len(scoped_cases)} in-scope cases  "
          f"(passed={passed}, failed={failed}, not_scored={not_scored}, blocked={len(blocked)})")

    failure_categories = {}
    for r in results:
        if r["status"] == "failed" and r["category"]:
            failure_categories[r["category"]] = failure_categories.get(r["category"], 0) + 1
    if failure_categories:
        print(f"Failure categories: {failure_categories}")

    run_record = {
        "label": label,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "split": split,
        "mode": mode,
        "agent_model": agent.model,
        "grader_model": graders.grader_model_name() if mode == "full" else None,
        "prompt": prompt_fingerprint(),
        "case_ids": [c["case_id"] for c in scoped_cases],
        "results": results,
        "blocked": blocked,
        "summary": {
            "total_in_scope": len(scoped_cases),
            "passed": passed,
            "failed": failed,
            "not_scored": not_scored,
            "blocked": len(blocked),
            "failure_categories": failure_categories,
        },
        "note": "token usage not recorded — not exposed by this SDK version's RunResult",
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{run_id}_{label}.json"
    out_path.write_text(json.dumps(run_record, indent=2, default=str))

    history_path = RESULTS_DIR / "history.csv"
    is_new = not history_path.exists()
    with history_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow([
                "timestamp", "label", "split", "mode", "agent_model", "grader_model", "prompt_hash",
                "total_in_scope", "passed", "failed", "not_scored", "blocked", "result_file",
            ])
        writer.writerow([
            run_record["timestamp"], label, split, mode, agent.model, run_record["grader_model"] or "",
            run_record["prompt"]["hash"], len(scoped_cases), passed, failed, not_scored, len(blocked), out_path.name,
        ])

    print(f"\nSaved: {out_path}")
    print(f"Appended to: {history_path}")
    return run_record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the local eval suite against the live agent.")
    parser.add_argument("--label", default="run", help="Short tag for this run. Used in the saved filename and history.csv.")
    parser.add_argument("--split", default="dev", choices=["dev", "held_out", "all"],
                         help="Which case split to run (default: dev). Per Step 5 §5.7, held_out should only run once "
                              "at deliberate final validation, not on every prompt-iteration run.")
    parser.add_argument("--mode", default="code_only", choices=["code_only", "full"],
                         help="code_only (default): deterministic graders only, no grader-model calls. "
                              "full: deterministic + model-based qualitative grading (requires BOOKLY_GRADER_MODEL). "
                              "Either mode still requires OPENAI_API_KEY for the agent itself.")
    args = parser.parse_args()
    asyncio.run(run_all(args.label, args.split, args.mode))
