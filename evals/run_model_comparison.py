"""Step 16: controlled model/reasoning comparison.

Does NOT modify agent.py, prompts.py, tools.py, policies.py,
evals/cases.py, or evals/graders.py. Every comparison agent is a fresh
clone built through evals/harness.py's build_eval_agent(case, model=...,
model_settings=...) — the production `agent` object in agent.py is never
constructed with a different model and is never mutated by this script.

Configurations (verified live against the API before use, not assumed):
  gpt-4-baseline   model="gpt-4",   no reasoning param (gpt-4 rejects it —
                                     confirmed: passing reasoning.effort to
                                     gpt-4 raises a 400 BadRequestError)
  gpt-5.6-medium   model="gpt-5.6", ModelSettings(reasoning=Reasoning(effort="medium"))
  gpt-5.6-low      model="gpt-5.6", ModelSettings(reasoning=Reasoning(effort="low"))

Reasoning effort is set via agents.ModelSettings(reasoning=openai.types.shared.Reasoning(effort=...)),
confirmed against the installed SDK (Reasoning.effort accepts
'none'|'minimal'|'low'|'medium'|'high'|'xhigh'|'max').

Runs the same 16-case dev split used by Step 15's finalized baseline
(evals.cases.by_split("dev")), the same grader model (BOOKLY_GRADER_MODEL),
the same evaluation-context-injection and tool-override logic
(evals.harness — untouched), and mode="full" (deterministic + qualitative
grading) every time, so results are comparable to Step 15's numbers.
Held-out cases are never touched by this script.

Usage (one (configuration, repeat) pair per invocation, so each run stays
well under any single command's time budget):

    .venv/bin/python -m evals.run_model_comparison --config gpt-4-baseline --repeat 1
    .venv/bin/python -m evals.run_model_comparison --config gpt-5.6-medium --repeat 1
    .venv/bin/python -m evals.run_model_comparison --config gpt-5.6-low --repeat 1
    ... (repeat 2 and 3 for each)

Cost estimates use real, currently-documented per-token pricing (checked
live, not guessed): gpt-4-0613 — the versioned model the bare "gpt-4"
alias resolves to — $30/M input, $60/M output tokens; gpt-5.6 (the
flagship "Sol" tier, which is what the bare "gpt-5.6" alias in this
account resolves to) — $4/M input, $20/M output tokens.
"""

import argparse
import asyncio
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agents import ModelSettings, Runner
from agents.exceptions import ModelBehaviorError
from openai.types.shared import Reasoning

from evals import graders
from evals.cases import CASES, by_split
from evals.harness import build_eval_agent, run_conversation, run_conversation_with_context
from tools import reset_state

RESULTS_DIR = Path(__file__).parent / "results"

DEV_CASES = by_split("dev")
assert len(DEV_CASES) == 16, f"expected the finalized 16-case dev split, got {len(DEV_CASES)}"

PRICING_PER_MILLION = {
    # (input_usd, output_usd) — see module docstring for sourcing.
    "gpt-4": (30.0, 60.0),
    "gpt-5.6": (4.0, 20.0),
}

CONFIGURATIONS = {
    "gpt-4-baseline": {"model": "gpt-4", "reasoning": None},
    "gpt-5.6-medium": {"model": "gpt-5.6", "reasoning": "medium"},
    "gpt-5.6-low": {"model": "gpt-5.6", "reasoning": "low"},
}


def model_settings_for(config: dict) -> ModelSettings:
    if config["reasoning"] is None:
        return ModelSettings(tool_choice="auto")
    return ModelSettings(tool_choice="auto", reasoning=Reasoning(effort=config["reasoning"]))


def estimate_cost_usd(model: str, usage: dict) -> float | None:
    rates = PRICING_PER_MILLION.get(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    return round(
        usage["input_tokens"] / 1_000_000 * input_rate
        + usage["output_tokens"] / 1_000_000 * output_rate,
        6,
    )


def _sum_usage(usages: list) -> dict:
    total = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for u in usages:
        for k in total:
            total[k] += u.get(k, 0)
    return total


async def run_case(case: dict, model: str, model_settings: ModelSettings, grader_model: str) -> dict:
    reset_state()
    eval_agent = build_eval_agent(case, model=model, model_settings=model_settings)
    start = time.perf_counter()
    try:
        trace = await run_conversation(eval_agent, case, session_id=f"cmp-{case['case_id']}-{model}")
    except ModelBehaviorError as exc:
        # Reasoning-effort/tool-call quirks on a new model surface here
        # rather than crashing the whole comparison run.
        return {
            "case_id": case["case_id"], "grader_type": case["grader_type"], "status": "not_scored",
            "category": "grader_or_harness_error", "error": str(exc),
            "latency_seconds": round(time.perf_counter() - start, 3),
            "usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }
    latency = round(time.perf_counter() - start, 3)

    deterministic = graders.grade_deterministic(case, trace)
    qualitative = None
    if "llm" in case["grader_type"]:
        qualitative = await graders.grade_qualitative(case, trace, deterministic, model)

    if not deterministic["passed"]:
        status = "failed"
    elif "llm" not in case["grader_type"]:
        status = "passed"
    elif qualitative and qualitative.get("status") == "scored":
        status = "passed" if qualitative.get("passed") else "failed"
    else:
        status = "not_scored"

    category = None
    if status == "failed":
        category = deterministic["category"] or "poor_judgement"

    return {
        "case_id": case["case_id"],
        "grader_type": case["grader_type"],
        "status": status,
        "category": category,
        "latency_seconds": latency,
        "hard_failures": deterministic["hard_failures"],
        "qualitative": qualitative,
        "trace": trace,
        "usage": trace["usage"],
    }


async def run_j2_03(model: str, model_settings: ModelSettings) -> dict:
    case = next(c for c in CASES if c["case_id"] == "J2-03")
    reset_state()
    eval_agent = build_eval_agent(case, model=model, model_settings=model_settings)
    start = time.perf_counter()
    run_a = await run_conversation_with_context(
        eval_agent, case["conversation"], "Evaluation context: the current order for this test is B1001.",
        f"cmp-J2-03-a-{model}",
    )
    reset_state()
    run_b = await run_conversation_with_context(
        eval_agent, case["conversation"], "Evaluation context: the current order for this test is B1002.",
        f"cmp-J2-03-b-{model}",
    )
    latency = round(time.perf_counter() - start, 3)

    def decision_of(trace):
        succeeded = {c["tool"] for c in trace["tool_calls"] if c.get("tool") in graders.ACTION_TOOLS and c.get("success")}
        return succeeded or {"no_action"}

    passed = decision_of(run_a) != decision_of(run_b)
    usage = _sum_usage([run_a["usage"], run_b["usage"]])

    return {
        "case_id": "J2-03",
        "grader_type": case["grader_type"],
        "status": "passed" if passed else "failed",
        "category": None if passed else "poor_judgement",
        "latency_seconds": latency,
        "hard_failures": [],
        "qualitative": None,
        "trace": {"run_a": run_a, "run_b": run_b},
        "usage": usage,
    }


async def main(config_key: str, repeat: int) -> None:
    config = CONFIGURATIONS[config_key]
    model = config["model"]
    settings = model_settings_for(config)

    ok, grader_model_or_reason = graders.check_grader_model_configured(model)
    if not ok:
        raise SystemExit(f"Cannot run Step 16 comparison: {grader_model_or_reason}")
    grader_model = grader_model_or_reason

    label = f"step16-{config_key}-run{repeat}"
    print(f"=== Step 16 comparison [{label}] — model={model} reasoning={config['reasoning']} — "
          f"{len(DEV_CASES)} dev cases — grader={grader_model} ===\n")

    results = []
    for case in DEV_CASES:
        if case["case_id"] == "J2-03":
            result = await run_j2_03(model, settings)
        else:
            result = await run_case(case, model, settings, grader_model)
        results.append(result)
        mark = result["status"].upper()
        cat = f" [{result['category']}]" if result.get("category") else ""
        print(f"--- {result['case_id']} — {mark}{cat} — {result['latency_seconds']}s, "
              f"{result['usage']['total_tokens']} tokens ---")

    passed = sum(1 for r in results if r["status"] == "passed")
    failed = sum(1 for r in results if r["status"] == "failed")
    not_scored = sum(1 for r in results if r["status"] == "not_scored")

    hard_policy_failures = [r["case_id"] for r in results if any(
        "executed" in (h.get("condition", "") if isinstance(h, dict) else "") or
        "success" in (h.get("condition", "") if isinstance(h, dict) else "")
        for h in r.get("hard_failures", []) or []
    )]
    tool_use_failures = [r["case_id"] for r in results if r["status"] == "failed" and r.get("category") in
                          {"wrong_tool", "wrong_tool_arguments", "tool_order_failure", "duplicate_action"}]
    hero_case_ids = {"J1-06", "J2-02"}
    hero_regressions = [r["case_id"] for r in results if r["case_id"] in hero_case_ids and r["status"] != "passed"]

    total_usage = _sum_usage([r["usage"] for r in results])
    total_latency = round(sum(r["latency_seconds"] for r in results), 3)
    estimated_cost = estimate_cost_usd(model, total_usage)

    print(f"\n=== Summary [{label}] ===")
    print(f"passed={passed} failed={failed} not_scored={not_scored} (of {len(DEV_CASES)})")
    print(f"hard-policy-failure cases: {hard_policy_failures}")
    print(f"tool-use-failure cases: {tool_use_failures}")
    print(f"hero-journey regressions (J1-06, J2-02): {hero_regressions}")
    print(f"total latency: {total_latency}s | total tokens: {total_usage['total_tokens']} "
          f"(in={total_usage['input_tokens']}, out={total_usage['output_tokens']})")
    print(f"estimated cost: {'$' + format(estimated_cost, '.6f') if estimated_cost is not None else 'unavailable'}")

    run_record = {
        "label": label,
        "step": 16,
        "config_key": config_key,
        "repeat": repeat,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "reasoning_effort": config["reasoning"],
        "grader_model": grader_model,
        "split": "dev",
        "mode": "full",
        "case_count": len(DEV_CASES),
        "results": results,
        "summary": {
            "passed": passed, "failed": failed, "not_scored": not_scored,
            "hard_policy_failure_cases": hard_policy_failures,
            "tool_use_failure_cases": tool_use_failures,
            "hero_journey_regressions": hero_regressions,
            "total_latency_seconds": total_latency,
            "total_usage": total_usage,
            "estimated_cost_usd": estimated_cost,
        },
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{run_id}_{label}.json"
    out_path.write_text(json.dumps(run_record, indent=2, default=str))

    history_path = RESULTS_DIR / "history.csv"
    prompt_hash = hashlib.sha256(f"{model}:{config['reasoning']}".encode()).hexdigest()[:12]
    with history_path.open("a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            run_record["timestamp"], label, "dev", "full", model, grader_model, prompt_hash,
            len(DEV_CASES), passed, failed, not_scored, 0, out_path.name,
        ])

    print(f"\nSaved: {out_path}")
    print(f"Appended to: {history_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Step 16 model/reasoning comparison — one (config, repeat) per invocation.")
    parser.add_argument("--config", required=True, choices=list(CONFIGURATIONS.keys()))
    parser.add_argument("--repeat", type=int, required=True, help="Repeat number (1, 2, 3, ...) — used only in the label.")
    args = parser.parse_args()
    asyncio.run(main(args.config, args.repeat))
