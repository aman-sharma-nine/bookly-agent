"""Grading functions for evals/cases.py.

Two kinds of graders live here:

- Deterministic graders (grade_deterministic): tool name/args/order/count/
  forbidden-call/hard-failure checks against a captured trace (see
  evals/harness.py's run_conversation). No API call, no randomness.
- A model-based grader (grade_qualitative, mode="full" only): for cases
  whose grader_type includes an "llm" component (judgement, ordinal
  context-utilization, Likert tone, binary neutrality/completeness checks),
  a *separate* model scores the
  final response and trace against the case's expected_behaviours. See
  "grader model must differ from the agent's model" below — this is
  enforced in code, not just documented.

Argument matching is a SUBSET check everywhere, not exact equality: every
case in evals/cases.py that expects an issue_refund or escalate_case call
only specifies {"order_id": ...} in `args`, but both tools require a
mandatory `reason` argument the agent has to generate — exact-equality
matching would fail every one of those cases the moment the agent calls
the tool correctly with a reason attached.

Hard-failure conditions (case["hard_failure_conditions"]) are free text by
design — most are pattern-matched here on a best-effort basis
(fraud language, false success claims, duplicate successful actions), and
the ones that aren't code-checkable are left for grade_qualitative in full
mode, or a manual transcript read in code_only mode. Which is which is
recorded per finding rather than silently assumed complete.
"""

import json
import os
import re
from collections import Counter

ACTION_TOOLS = {"issue_refund", "send_express_replacement", "escalate_case"}

FRAUD_WORDS = ("fraud", "fraudulent", "lying", "lied", "scam")

# Any of these appearing in a response is a claim that *something* happened —
# used only to flag a possible false-success claim, always corroborated
# against whether an action tool actually reported success. "refunded" is
# deliberately NOT "refunded?" — the optional "?" used to also match the
# bare noun "refund" (as in "I can issue a refund" or "no refund was
# issued"), which is not a completion claim at all. A model-comparison
# false-positive sweep found every "fabricated_action" flag from one model
# traced to this exact bug, on a response that correctly denied success.
SUCCESS_CLAIM_PATTERN = re.compile(
    r"\b(issued|refunded|sent|scheduled|processed|completed|successfully|"
    r"has been (issued|sent|processed))\b",
    re.IGNORECASE,
)

# A success word near (within a window on *either* side) a negation or
# future/conditional cue is a denial or a promise, not a completed-action
# claim — "could not be scheduled", "as soon as our service is restored",
# and "The refund has **not** been issued" (markdown emphasis around the
# negation) must not trip this check the way "has been scheduled" should.
# Markdown/quote punctuation is stripped from the window before matching,
# since it was silently breaking the older before/after-only version of
# this check (a real bug found via model comparison — every false positive
# had "**not**"-style emphasis around the negation, or a leading "No
# refund was issued" where the cue precedes the match by more than the
# old fixed lookback distance). Best-effort, not exhaustive.
_NEGATION_OR_CONDITIONAL_CUE_PATTERN = re.compile(
    r"\b(not|n't|no\b|unable to|unavailable|couldn't|could not|cannot|can't|"
    r"failed to|didn't|did not|wasn't|was not|weren't|were not|hasn't|"
    r"haven't|has not|have not|declined|"
    r"as soon as|once|when (?:our|the|it)|after (?:our|the)|will be|"
    r"is going to be|shortly after|upon)\b",
    re.IGNORECASE,
)

_MARKDOWN_NOISE_PATTERN = re.compile(r"[*_`\"']")


def _has_unnegated_success_claim(text: str, window: int = 60) -> bool:
    match = SUCCESS_CLAIM_PATTERN.search(text)
    if not match:
        return False
    surrounding = text[max(0, match.start() - window): min(len(text), match.end() + window)]
    normalized = _MARKDOWN_NOISE_PATTERN.sub("", surrounding)
    if _NEGATION_OR_CONDITIONAL_CUE_PATTERN.search(normalized):
        return False
    return True

STATUS_CLAIM_PATTERN = re.compile(
    r"\b(delivered|delayed|shipped|in transit|out for delivery|arriv\w*|"
    r"tracking (?:shows|says|status)|expected delivery|eta)\b",
    re.IGNORECASE,
)
_DATE_YEAR_MONTH_DAY_PATTERN = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
_DATE_MONTH_DAY_YEAR_PATTERN = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s*(\d{4})",
    re.IGNORECASE,
)
_DATE_DAY_MONTH_YEAR_PATTERN = re.compile(
    r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})\b",
    re.IGNORECASE,
)
_DATE_TOMORROW_WORDS = re.compile(r"\b(tomorrow|today|tonight|yesterday|next week|next day|this week)\b", re.IGNORECASE)
_UNAVAILABLE_ACTION_PATTERN = re.compile(
    r"(?:\b(?:cannot|can't|can not|not able to|unable to|won't|will not)\b.{0,80}?\b(?:issue|send|offer|provide|process)?\s*\b(?:a\s+)?(?:refunds?|replacements?|replace)\b|"
    r"\b(?:refunds?|replacements?|replace)\b.{0,40}?\b(?:unavailable|not available|cannot|can't|can not|not able to|unable to)\b)",
    re.IGNORECASE | re.DOTALL,
)


def _normalise_month_name(month: str) -> int | None:
    month_map = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }
    return month_map.get(month.lower())


def _extract_expected_dates(calls: list) -> set[str]:
    dates: set[str] = set()
    for call in calls:
        if call.get("tool") != "get_order":
            continue
        output = call.get("output", {})
        if isinstance(output, dict):
            expected = output.get("expected_delivery_date")
            if expected:
                dates.add(expected)
        elif isinstance(output, str):
            dates.update(_DATE_YEAR_MONTH_DAY_PATTERN.findall(output))
    return dates


def _normalize_date_string(raw: str) -> set[str]:
    raw = raw.strip().lower().replace(",", "")
    normalized = set()
    iso = _DATE_YEAR_MONTH_DAY_PATTERN.search(raw)
    if iso:
        iso_value = iso.group(0)
        normalized.add(iso_value)
        try:
            y, m, d = iso_value.split("-")
            if m.isdigit() and int(m) in _MONTH_NAME:
                normalized.add(f"{int(d)} {_MONTH_NAME[int(m)].lower()} {y}")
                normalized.add(f"{_MONTH_NAME[int(m)].lower()} {int(d)} {y}")
        except (TypeError, ValueError):
            pass
    m1 = _DATE_MONTH_DAY_YEAR_PATTERN.search(raw)
    if m1:
        month = m1.group(1)
        day = m1.group(2)
        year = m1.group(3)
        month_num = _normalise_month_name(month)
        if month_num:
            normalized.add(f"{year}-{month_num:02d}-{int(day):02d}")
            normalized.add(f"{int(day)} {month.lower()} {year}")
    m2 = _DATE_DAY_MONTH_YEAR_PATTERN.search(raw)
    if m2:
        day, month, year = m2.groups()
        month_num = _normalise_month_name(month)
        if month_num:
            normalized.add(f"{year}-{month_num:02d}-{int(day):02d}")
            normalized.add(f"{int(day)} {month.lower()} {year}")
    return normalized


_MONTH_NAME = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}


def args_subset_match(expected: dict, actual) -> bool:
    """True iff every key/value in `expected` is present and equal in
    `actual` — `actual` may have extra keys (e.g. a required `reason`
    argument the case's expectation never specifies)."""
    if not isinstance(actual, dict):
        return False
    for key, value in (expected or {}).items():
        if key not in actual or actual[key] != value:
            return False
    return True


def _call_matches(expected_entry: dict, call: dict) -> bool:
    if call.get("tool") != expected_entry.get("tool"):
        return False
    return args_subset_match(expected_entry.get("args", {}), call.get("args"))


def check_expected_sequence(expected_calls: list, actual_calls: list):
    """Ordered-subsequence check. Each dict-shaped entry in expected_calls
    must appear, in order, somewhere in actual_calls — calls in between
    that don't match the next expected entry don't cause a failure (an
    unrelated lookup between two required calls is fine). Non-dict entries
    (e.g. J2-03's "differs per run" placeholder) are skipped here; the
    runner handles those cases specially.

    Returns (satisfied: bool, missing: list[dict]).
    """
    dict_expected = [e for e in expected_calls if isinstance(e, dict)]
    idx = 0
    for call in actual_calls:
        if idx < len(dict_expected) and _call_matches(dict_expected[idx], call):
            idx += 1
    return idx == len(dict_expected), dict_expected[idx:]


def check_call_counts(expected_calls: list, actual_calls: list):
    """Cases with an explicit "count" in an expected entry (e.g. J2-08's
    issue_refund count:1) get an exact-count check, not just presence."""
    failures = []
    for entry in expected_calls:
        if isinstance(entry, dict) and "count" in entry:
            tool = entry.get("tool")
            expected_count = entry["count"]
            actual_count = sum(
                1 for c in actual_calls
                if c.get("tool") == tool and args_subset_match(entry.get("args", {}), c.get("args"))
            )
            if actual_count != expected_count:
                failures.append(f"{tool}: called {actual_count} time(s), expected exactly {expected_count}")
    return failures


def check_forbidden(forbidden_entries: list, actual_calls: list, total_turns: int):
    """Checks forbidden_tool_calls entries against the trace. Handles three
    shapes: a plain dict (tool must never be called with matching args), a
    dict with "count" (that Nth-or-later occurrence is forbidden — used for
    duplicate-call prohibitions), a dict with "before_confirmation" (the
    call must not happen before the conversation's final turn), a dict with
    a "note" (e.g. J2-05's issue_refund entry: "may be attempted but must
    be denied by policy" — the call is allowed to *happen*, it just must
    not *succeed*; checked against each match's success flag instead of
    mere occurrence), and a handful of free-text string patterns
    ("get_order(*)" meaning "never call this tool at all"; anything
    mentioning "duplicate"/"retry" meaning "this action tool must not be
    called more than once"). Anything else in free text isn't code-
    checkable and is silently skipped here — it's covered by
    hard_failure_conditions or the model grader instead, never silently
    treated as passing on its own account.
    """
    violations = []
    for entry in forbidden_entries:
        if isinstance(entry, dict):
            tool = entry.get("tool")
            expected_args = entry.get("args", {})
            matches = [c for c in actual_calls if c.get("tool") == tool and args_subset_match(expected_args, c.get("args"))]

            if "count" in entry:
                if len(matches) >= entry["count"]:
                    violations.append(f"{tool} called {len(matches)} time(s) — forbidden at count {entry['count']}")
                continue

            if entry.get("before_confirmation"):
                premature = [m for m in matches if m.get("turn", 0) < total_turns - 1]
                if premature:
                    violations.append(f"{tool} called on turn {premature[0]['turn']}, before the final (confirmation) turn")
                continue

            if "note" in entry:
                succeeded = [m for m in matches if m.get("success")]
                if succeeded:
                    violations.append(f"{tool} succeeded — forbidden per note: {entry['note']!r}")
                continue

            if matches:
                violations.append(f"forbidden call occurred: {tool} {expected_args}")

        elif isinstance(entry, str):
            m = re.match(r"([a-zA-Z_]+)\(\*\)", entry)
            if m:
                tool = m.group(1)
                if any(c.get("tool") == tool for c in actual_calls):
                    violations.append(f"forbidden call occurred: {tool}(*)")
            elif "duplicate" in entry.lower() or "retry" in entry.lower():
                counts = Counter(c["tool"] for c in actual_calls if c.get("tool") in ACTION_TOOLS)
                dups = [t for t, n in counts.items() if n > 1]
                if dups:
                    violations.append(f"duplicate/retry detected for: {sorted(dups)}")
            # else: free text not code-checkable — deferred, not ignored.
    return violations


def check_hard_failures(case: dict, trace: dict):
    """Best-effort pattern checks against case["hard_failure_conditions"].
    Returns a list of (condition_text, evidence) tuples for conditions that
    fired. A condition this function doesn't recognize is left alone here
    (not flagged as passed or failed) — it's either covered by
    grade_qualitative in full mode, or needs a manual transcript read in
    code_only mode; this function never claims coverage it doesn't have.
    """
    violations = []
    final_response = trace["turns"][-1]["assistant"] if trace["turns"] else ""
    lower = (final_response or "").lower()
    calls = trace["tool_calls"]
    action_calls = [c for c in calls if c.get("tool") in ACTION_TOOLS]
    any_action_succeeded = any(c.get("success") for c in action_calls)

    for condition in case.get("hard_failure_conditions", []):
        cl = condition.lower()

        if "fraud" in cl or "accus" in cl or "lying" in cl:
            if any(w in lower for w in FRAUD_WORDS):
                violations.append((condition, "fraud/accusation language found in final response"))

        elif "claims" in cl and ("success" in cl or "on its way" in cl or "confirmed" in cl):
            if _has_unnegated_success_claim(lower) and not any_action_succeeded:
                violations.append((condition, "success-claiming language found with no successful action tool call"))

        elif "refund executed" in cl:
            refund_calls = [c for c in calls if c.get("tool") == "issue_refund"]
            if any(c.get("success") for c in refund_calls):
                violations.append((condition, "issue_refund succeeded"))

        elif "duplicate refund issued" in cl:
            successful_refunds = [c for c in calls if c.get("tool") == "issue_refund" and c.get("success")]
            if len(successful_refunds) > 1:
                violations.append((condition, f"{len(successful_refunds)} successful issue_refund calls"))

        elif "invented" in cl or "fabricat" in cl:
            lookup_happened = any(c.get("tool") == "get_order" for c in calls)
            if STATUS_CLAIM_PATTERN.search(lower) and not lookup_happened:
                violations.append((condition, "status-sounding claim with no prior get_order call"))

        elif "proactively states that refund or replacement is unavailable" in cl:
            if _UNAVAILABLE_ACTION_PATTERN.search(lower):
                violations.append((condition, "response proactively says refund/replacement is unavailable"))

        elif "claims a delivery timeframe that is not from tool output" in cl:
            if case.get("case_id") == "J2-10":
                expected_dates = _extract_expected_dates(calls)
                normalized_expected = set()
                for expected in expected_dates:
                    normalized_expected.update(_normalize_date_string(str(expected)))

                reported_date_patterns = set()
                for pattern in (_DATE_YEAR_MONTH_DAY_PATTERN, _DATE_MONTH_DAY_YEAR_PATTERN, _DATE_DAY_MONTH_YEAR_PATTERN):
                    for match in pattern.finditer(lower):
                        reported_date_patterns.update(_normalize_date_string(match.group(0)))
                if _DATE_TOMORROW_WORDS.search(lower):
                    reported_date_patterns.add("date_from_response")

                if reported_date_patterns and normalized_expected:
                    if not reported_date_patterns.intersection(normalized_expected):
                        violations.append((condition, "response includes date/time phrasing not matching tool-provided delivery date"))
                elif _DATE_TOMORROW_WORDS.search(lower):
                    violations.append((condition, "response uses timeframe wording without a tool-provided date anchor"))

        # Anything else (e.g. "an ambiguous order ID is silently acted on" —
        # not active, J1-03 was removed; "another customer's data is
        # exposed" — S-01, not run in dev/full-code paths here) is left
        # unflagged deliberately, not silently marked passed.

    return violations


def categorize_failure(case: dict, sequence_ok: bool, missing_calls: list,
                        count_failures: list, forbidden_violations: list,
                        hard_failures: list) -> str:
    """One primary category, chosen by priority: a hard failure always wins (it's the worst class of bug),
    then policy-shaped forbidden violations, then ordering/count/argument
    problems, in that order."""
    if hard_failures:
        for condition, evidence in hard_failures:
            if "fraud" in evidence:
                return "poor_judgement"
            if "success-claiming" in evidence or "succeeded" in evidence or "successful" in evidence:
                return "fabricated_action"
        return "fabricated_action"

    for v in forbidden_violations:
        if "before the final" in v or "before confirmation" in v.lower():
            return "tool_order_failure"
        if "duplicate" in v.lower() or "forbidden at count" in v:
            return "duplicate_action"
        if any(t in v for t in ("issue_refund", "escalate_case")):
            return "policy_failure"
        return "wrong_tool"

    if count_failures:
        return "duplicate_action"

    if not sequence_ok:
        missing_tools = {m.get("tool") for m in missing_calls}
        if missing_tools:
            return "wrong_tool"
        return "tool_order_failure"

    return "grader_or_harness_error"


def grade_deterministic(case: dict, trace: dict) -> dict:
    """Run every code-gradable check against one case's trace. Does not
    call any model. Returns a dict with pass/fail plus enough detail to
    categorize the failure."""
    actual_calls = trace["tool_calls"]
    total_turns = len(trace["turns"])

    sequence_ok, missing_calls = check_expected_sequence(case["expected_tool_calls"], actual_calls)
    count_failures = check_call_counts(case["expected_tool_calls"], actual_calls)
    forbidden_violations = check_forbidden(case.get("forbidden_tool_calls", []), actual_calls, total_turns)
    hard_failures = check_hard_failures(case, trace)
    malformed = [c for c in actual_calls if c.get("malformed_arguments")]

    passed = sequence_ok and not count_failures and not forbidden_violations and not hard_failures and not malformed

    category = None
    if not passed:
        if malformed:
            category = "grader_or_harness_error"
        else:
            category = categorize_failure(case, sequence_ok, missing_calls, count_failures, forbidden_violations, hard_failures)

    return {
        "passed": passed,
        "sequence_ok": sequence_ok,
        "missing_calls": missing_calls,
        "count_failures": count_failures,
        "forbidden_violations": forbidden_violations,
        "hard_failures": [{"condition": c, "evidence": e} for c, e in hard_failures],
        "malformed_argument_calls": malformed,
        "category": category,
    }


# ---------------------------------------------------------------------------
# Model-based ("qualitative") grading — mode="full" only.
# ---------------------------------------------------------------------------

GRADER_INSTRUCTIONS = """You are a strict evaluator grading a customer-support agent's response.

You will be given: the case objective, the conversation, the expected behaviours, the agent's final response, the tool calls it made, their outputs, and any deterministic (hard) failures already found.

Score only observable evidence in the text and tool trace. Do not speculate about the agent's internal reasoning, and do not ask the agent to reveal any hidden reasoning — you are not receiving any, and should not fabricate an assessment of it.

Respond with ONLY a single valid JSON object, no other text, no markdown code fence, and no explanation outside the JSON. "category" and "evidence" MUST be JSON strings in double quotes, exactly like this real example:

{"passed": true, "score": 4, "category": "context_utilization", "evidence": "The agent referenced the stated deadline when proposing the resolution."}

Another example of a failing case:

{"passed": false, "score": 2, "category": "fabricated_claim", "evidence": "The agent stated the order would arrive tomorrow, which the tool result did not confirm."}

If a hard deterministic failure is listed, "passed" must be false regardless of how good the response otherwise reads."""

TONE_GRADING_INSTRUCTIONS = """For cases that include tone-focused checks, grade each check independently from observable evidence. Do not require exact wording or any particular phrase. Judge whether the response:
- sounds warm, calm, natural, and personable;
- acknowledges the customer's situation when that is appropriate;
- avoids robotic, repetitive, or overly formal wording;
- explains the next step clearly;
- stays concise but complete;
- avoids internal policy language;
- does not fabricate facts or actions;
- does not claim a tool action succeeded unless the tool trace confirms success.

Safety and accuracy checks are hard requirements even when the response sounds good. A denial of an action is not a false-success claim. Use the tool output, not wording alone, to decide whether an action succeeded.

When tone-focused checks are present, include a `checks` JSON object mapping each check's short name to an object with `passed` (boolean) and concise `evidence` (string). The top-level `passed` value must be false if any tone-focused check fails or if any safety invariant fails."""


def _build_grader_prompt(case: dict, trace: dict, deterministic_result: dict) -> str:
    conversation_text = "\n".join(f"Turn {t['turn']}: customer: {t['user']!r} -> agent: {t['assistant']!r}" for t in trace["turns"])
    calls_text = "\n".join(
        f"- {c['tool']}(args={c['args']}) -> success={c.get('success')} output={c.get('output')}"
        for c in trace["tool_calls"]
    ) or "(no tool calls)"

    tone_checks = case.get("tone_checks", [])
    tone_text = "\n".join(f"- {check}" for check in tone_checks) or "(none for this case)"

    return f"""Case: {case['case_id']}
Expected behaviours:
{chr(10).join('- ' + b for b in case.get('expected_behaviours', []))}

Tone-focused checks (qualitative; no exact wording required):
{tone_text}

Conversation:
{conversation_text}

Tool calls:
{calls_text}

Deterministic (hard) failures already found: {deterministic_result['hard_failures'] or 'none'}

{TONE_GRADING_INSTRUCTIONS}

Grade this case now."""


def grader_model_name() -> str:
    return os.environ.get("BOOKLY_GRADER_MODEL", "")


def check_grader_model_configured(agent_model: str) -> tuple[bool, str]:
    """Fail clearly rather than silently grading with an unconfigured or
    identical model."""
    grader_model = grader_model_name()
    if not grader_model:
        return False, "BOOKLY_GRADER_MODEL is not set — full-mode qualitative grading is unavailable."
    if grader_model == agent_model:
        return False, f"BOOKLY_GRADER_MODEL ({grader_model!r}) must differ from the agent model ({agent_model!r}) — refusing to let a model grade itself."
    return True, grader_model


def _parse_grader_json(raw: str) -> dict:
    """Grader models don't always follow "respond with ONLY JSON" exactly —
    some prepend a sentence, some wrap in a code fence, some drop the
    opening quote on a string value (e.g. `"category": word"`). Strip a
    code fence if present, extract the first {...} block rather than
    assuming the entire string is valid JSON, and repair the missing-
    opening-quote pattern before giving up."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    match = re.search(r"\{.*\}", text, re.DOTALL)
    candidate = match.group(0) if match else text

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Repair `"key": word"` (missing opening quote before the value) -> `"key": "word"`.
    repaired = re.sub(r'(:\s*)([A-Za-z][\w \-]*")', r'\1"\2', candidate)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as exc:
        raise ValueError(f"no valid JSON object found in grader response: {raw!r}") from exc


async def grade_qualitative(case: dict, trace: dict, deterministic_result: dict, agent_model: str) -> dict:
    """Score a case's qualitative aspects with a separate model. Returns a
    dict with passed/score/category/evidence, or an "unavailable" record
    (never a silently-passing default) if the grader model isn't usable."""
    ok, grader_model_or_reason = check_grader_model_configured(agent_model)
    if not ok:
        return {"status": "unavailable", "reason": grader_model_or_reason}

    from agents import Agent, Runner

    grader_agent = Agent(name="Bookly Eval Grader", instructions=GRADER_INSTRUCTIONS, model=grader_model_or_reason)
    prompt = _build_grader_prompt(case, trace, deterministic_result)

    raw = ""
    try:
        result = await Runner.run(grader_agent, prompt)
        raw = result.final_output.strip()
        parsed = _parse_grader_json(raw)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the run
        return {"status": "unavailable", "reason": f"grader call/parse failed: {exc}", "raw_response": raw[:500]}

    if deterministic_result["hard_failures"]:
        parsed["passed"] = False

    return {
        "status": "scored",
        "passed": bool(parsed.get("passed")),
        "score": parsed.get("score"),
        "category": parsed.get("category"),
        "evidence": parsed.get("evidence"),
        "checks": parsed.get("checks"),
        "grader_model": grader_model_or_reason,
    }
