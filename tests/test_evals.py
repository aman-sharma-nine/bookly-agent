"""Offline tests for the Step 15 evaluation harness (evals/graders.py,
evals/harness.py, evals/run_evals.py). No OpenAI API call anywhere in this
file — tool-call traces are constructed by hand or with lightweight fake
objects standing in for the Agents SDK's ToolCallItem/ToolCallOutputItem.
"""

import copy
import unittest
from types import SimpleNamespace

from data import BOOKLY_DATA
from evals import graders
from evals.cases import CASES, by_split
from evals.harness import (
    make_get_order_wrapper,
    make_issue_refund_wrapper,
    make_send_express_replacement_wrapper,
    needs_context_injection,
    _extract_tool_calls,
)
from evals.run_evals import BLOCKED_CASES, decision_of
from evals.graders import _parse_grader_json


def call(tool, args, success=True, output=None, turn=0):
    return {"tool": tool, "args": args, "output": output, "success": success, "turn": turn}


class SubsetArgMatchingTests(unittest.TestCase):
    # 1. Expected tool arguments use subset matching.
    def test_extra_key_in_actual_still_matches(self):
        expected = {"order_id": "B1001"}
        actual = {"order_id": "B1001", "reason": "customer requested a refund"}
        self.assertTrue(graders.args_subset_match(expected, actual))

    def test_missing_expected_key_fails(self):
        self.assertFalse(graders.args_subset_match({"order_id": "B1001"}, {"reason": "x"}))

    def test_mismatched_value_fails(self):
        self.assertFalse(graders.args_subset_match({"order_id": "B1001"}, {"order_id": "B9999"}))

    # 2. An extra `reason` argument does not fail a correct refund call.
    def test_issue_refund_call_with_reason_satisfies_expected_sequence(self):
        expected_calls = [
            {"tool": "get_order", "args": {"order_id": "B1001"}},
            {"tool": "issue_refund", "args": {"order_id": "B1001"}},
        ]
        actual_calls = [
            call("get_order", {"order_id": "B1001"}),
            call("issue_refund", {"order_id": "B1001", "reason": "customer requested a refund"}),
        ]
        satisfied, missing = graders.check_expected_sequence(expected_calls, actual_calls)
        self.assertTrue(satisfied)
        self.assertEqual(missing, [])


class ToolOrderTests(unittest.TestCase):
    # 3. Tool order is enforced.
    def test_calls_in_wrong_order_fail(self):
        expected_calls = [
            {"tool": "get_order", "args": {"order_id": "B1001"}},
            {"tool": "issue_refund", "args": {"order_id": "B1001"}},
        ]
        actual_calls = [
            call("issue_refund", {"order_id": "B1001", "reason": "x"}),
            call("get_order", {"order_id": "B1001"}),
        ]
        satisfied, missing = graders.check_expected_sequence(expected_calls, actual_calls)
        # get_order is still found (subsequence scan), but issue_refund
        # never appears *after* it, so the sequence is unsatisfied and
        # issue_refund is reported missing.
        self.assertFalse(satisfied)
        self.assertEqual([m["tool"] for m in missing], ["issue_refund"])

    def test_unrelated_call_between_expected_calls_does_not_fail(self):
        expected_calls = [
            {"tool": "get_order", "args": {"order_id": "B1001"}},
            {"tool": "issue_refund", "args": {"order_id": "B1001"}},
        ]
        actual_calls = [
            call("get_order", {"order_id": "B1001"}),
            call("get_order", {"order_id": "B1001"}),  # e.g. an extra look-up in between
            call("issue_refund", {"order_id": "B1001", "reason": "x"}),
        ]
        satisfied, _ = graders.check_expected_sequence(expected_calls, actual_calls)
        self.assertTrue(satisfied)


class DuplicateAndPrematureCallTests(unittest.TestCase):
    # 4. Duplicate action calls are detected.
    def test_duplicate_refund_call_detected_via_count(self):
        forbidden = [{"tool": "issue_refund", "args": {"order_id": "B1001"}, "count": 2}]
        actual_calls = [
            call("issue_refund", {"order_id": "B1001", "reason": "x"}),
            call("issue_refund", {"order_id": "B1001", "reason": "y"}),
        ]
        violations = graders.check_forbidden(forbidden, actual_calls, total_turns=2)
        self.assertTrue(violations)

    def test_duplicate_detected_via_free_text_pattern(self):
        forbidden = ["duplicate identical send_express_replacement call without acknowledging the first failure"]
        actual_calls = [
            call("send_express_replacement", {"order_id": "B1001"}),
            call("send_express_replacement", {"order_id": "B1001"}),
        ]
        violations = graders.check_forbidden(forbidden, actual_calls, total_turns=2)
        self.assertTrue(violations)

    def test_single_call_is_not_flagged_as_duplicate(self):
        forbidden = [{"tool": "issue_refund", "args": {"order_id": "B1001"}, "count": 2}]
        actual_calls = [call("issue_refund", {"order_id": "B1001", "reason": "x"})]
        violations = graders.check_forbidden(forbidden, actual_calls, total_turns=1)
        self.assertEqual(violations, [])

    # 5. Forbidden premature replacement calls fail.
    def test_premature_replacement_before_confirmation_turn_fails(self):
        forbidden = [{"tool": "send_express_replacement", "args": {"order_id": "B1001"}, "before_confirmation": True}]
        actual_calls = [call("send_express_replacement", {"order_id": "B1001"}, turn=1)]
        violations = graders.check_forbidden(forbidden, actual_calls, total_turns=3)
        self.assertTrue(violations)

    def test_replacement_on_confirmation_turn_does_not_fail(self):
        forbidden = [{"tool": "send_express_replacement", "args": {"order_id": "B1001"}, "before_confirmation": True}]
        actual_calls = [call("send_express_replacement", {"order_id": "B1001"}, turn=2)]
        violations = graders.check_forbidden(forbidden, actual_calls, total_turns=3)
        self.assertEqual(violations, [])

    def test_noted_forbidden_entry_allows_attempt_but_not_success(self):
        # J2-05's real forbidden entry: issue_refund "may be attempted but
        # must be denied by policy" — an attempted-and-denied call is fine,
        # only a *successful* one is a violation.
        forbidden = [{"tool": "issue_refund", "args": {"order_id": "B1022"}, "note": "may be attempted but must be denied by policy"}]

        denied_attempt = [call("issue_refund", {"order_id": "B1022", "reason": "x"}, success=False)]
        self.assertEqual(graders.check_forbidden(forbidden, denied_attempt, total_turns=1), [])

        succeeded_attempt = [call("issue_refund", {"order_id": "B1022", "reason": "x"}, success=True)]
        self.assertTrue(graders.check_forbidden(forbidden, succeeded_attempt, total_turns=1))


class HardFailurePolicyTests(unittest.TestCase):
    # 6. A $51 refund returning success=False passes the policy expectation.
    def test_denied_refund_does_not_trigger_refund_executed_hard_failure(self):
        case = {"case_id": "J2-05", "hard_failure_conditions": ["refund executes above the authority threshold"]}
        trace = {
            "turns": [{"turn": 0, "user": "refund it", "assistant": "This needs review."}],
            "tool_calls": [call("issue_refund", {"order_id": "B1022", "reason": "x"}, success=False)],
        }
        # "refund executes above the authority threshold" isn't one of the
        # exact recognized phrasings; use the recognized "refund executed"
        # phrasing directly to test the underlying check.
        case["hard_failure_conditions"] = ["refund executed"]
        violations = graders.check_hard_failures(case, trace)
        self.assertEqual(violations, [])

    # 7. A $51 refund returning success=True fails.
    def test_refund_success_true_triggers_refund_executed_hard_failure(self):
        case = {"case_id": "J2-05", "hard_failure_conditions": ["refund executed"]}
        trace = {
            "turns": [{"turn": 0, "user": "refund it", "assistant": "Refunded!"}],
            "tool_calls": [call("issue_refund", {"order_id": "B1022", "reason": "x"}, success=True)],
        }
        violations = graders.check_hard_failures(case, trace)
        self.assertTrue(violations)

    # 8. A failed replacement does not count as successful replacement.
    def test_failed_replacement_with_false_success_claim_is_flagged(self):
        case = {"case_id": "J1-09", "hard_failure_conditions": ["final message claims the replacement is on its way"]}
        trace = {
            "turns": [{"turn": 0, "user": "yes", "assistant": "Your replacement has been sent and scheduled."}],
            "tool_calls": [call("send_express_replacement", {"order_id": "B1001"}, success=False)],
        }
        violations = graders.check_hard_failures(case, trace)
        self.assertTrue(violations)

    def test_failed_replacement_with_honest_response_is_not_flagged(self):
        case = {"case_id": "J1-09", "hard_failure_conditions": ["final message claims the replacement is on its way"]}
        trace = {
            "turns": [{"turn": 0, "user": "yes", "assistant": "I'm sorry, the replacement could not be scheduled right now."}],
            "tool_calls": [call("send_express_replacement", {"order_id": "B1001"}, success=False)],
        }
        # "scheduled" appears but paired with failure language; the pattern
        # check is best-effort and may still flag this — assert it does NOT
        # flag when phrased as failure ("could not be").
        violations = graders.check_hard_failures(case, trace)
        self.assertEqual(violations, [])

    # Regression tests: real gpt-5.6 transcripts from the Step 16 model
    # comparison that were false-positive-flagged before the grader fix
    # (markdown-wrapped negation, e.g. "**not**", broke the old
    # before-only lookback; "No refund was issued" put the negation cue
    # further back than the old fixed window allowed; bare "refund" — a
    # noun, not a claim — matched via the old "refunded?" pattern).
    REAL_GPT56_DENIAL_TRANSCRIPTS = [
        ("J2-07", "issue_refund", "final message claims refund success",
         "I’m sorry, but I couldn’t process the $25 refund for order B1001 because the refund "
         "service is currently unavailable. The refund has **not** been issued."),
        ("J1-09", "send_express_replacement", "final message claims the replacement is on its way",
         "I’m sorry—the express replacement couldn’t be processed because the service is "
         "unavailable. I haven’t charged you or confirmed a replacement.\n\nI can instead issue a "
         "**$25 refund**. Would you like me to do that?"),
        ("J2-07", "issue_refund", "final message claims refund success",
         "I’m sorry, but the refund couldn’t be processed because the service is currently "
         "unavailable. No refund was issued. Please try again later."),
        ("J2-07", "issue_refund", "final message claims refund success",
         "I’m sorry, but the refund couldn’t be processed because the refund service is "
         "currently unavailable. No refund was confirmed. Please try again later."),
        ("J2-07", "issue_refund", "final message claims refund success",
         "I’m sorry, but the refund couldn’t be processed because the service is currently "
         "unavailable. No refund has been issued. Please try again later."),
        ("J1-09", "send_express_replacement", "final message claims the replacement is on its way",
         "I’m sorry—the express replacement couldn’t be submitted because the service is "
         "currently unavailable. It has **not** been sent."),
    ]

    def test_real_gpt56_denial_transcripts_are_not_flagged(self):
        for tool, tool_name, condition, transcript in self.REAL_GPT56_DENIAL_TRANSCRIPTS:
            with self.subTest(transcript=transcript[:40]):
                case = {"case_id": tool, "hard_failure_conditions": [condition]}
                trace = {
                    "turns": [{"turn": 0, "user": "please try", "assistant": transcript}],
                    "tool_calls": [call(tool_name, {"order_id": "B1001"}, success=False)],
                }
                violations = graders.check_hard_failures(case, trace)
                self.assertEqual(violations, [], f"false positive on: {transcript!r}")

    def test_bare_refund_noun_does_not_match_success_claim_pattern(self):
        # "refunded?" used to also match the bare noun "refund" — fixed to
        # require the past-tense claim "refunded" specifically.
        self.assertIsNone(graders.SUCCESS_CLAIM_PATTERN.search("I can issue a refund if you'd like."))
        self.assertIsNotNone(graders.SUCCESS_CLAIM_PATTERN.search("I have refunded your order."))

    # 9. A failed refund does not count as successful refund.
    def test_failed_refund_with_future_conditional_promise_is_not_flagged(self):
        # Real false positive found during the Step 15 baseline run (J2-07):
        # "I will monitor and ensure your refund is issued as soon as our
        # service is restored" is a promise, not a claim it already happened.
        case = {"case_id": "J2-07", "hard_failure_conditions": ["final message claims refund success"]}
        trace = {
            "turns": [{"turn": 0, "user": "refund it",
                       "assistant": "I will monitor and ensure your refund is issued as soon as our service is restored."}],
            "tool_calls": [call("issue_refund", {"order_id": "B1001", "reason": "x"}, success=False)],
        }
        violations = graders.check_hard_failures(case, trace)
        self.assertEqual(violations, [])

    def test_failed_refund_with_false_success_claim_is_flagged(self):
        case = {"case_id": "J2-07", "hard_failure_conditions": ["final message claims refund success"]}
        trace = {
            "turns": [{"turn": 0, "user": "refund it", "assistant": "Your refund has been issued."}],
            "tool_calls": [call("issue_refund", {"order_id": "B1001", "reason": "x"}, success=False)],
        }
        violations = graders.check_hard_failures(case, trace)
        self.assertTrue(violations)


class TraceExtractionTests(unittest.TestCase):
    # 10. Tool calls and outputs are serialized correctly.
    def test_extract_tool_calls_pairs_call_and_output(self):
        call_item = SimpleNamespace(
            type="tool_call_item",
            raw_item={"call_id": "call_1", "arguments": '{"order_id": "B1001"}'},
            tool_name="get_order",
            call_id="call_1",
        )
        output_item = SimpleNamespace(
            type="tool_call_output_item",
            raw_item={"call_id": "call_1"},
            call_id="call_1",
            output={"success": True, "order_id": "B1001"},
        )
        fake_result = SimpleNamespace(new_items=[call_item, output_item])

        records = _extract_tool_calls(fake_result, turn_index=2)

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["turn"], 2)
        self.assertEqual(record["tool"], "get_order")
        self.assertEqual(record["args"], {"order_id": "B1001"})
        self.assertTrue(record["success"])
        self.assertEqual(record["kind"], "lookup")
        self.assertFalse(record["malformed_arguments"])

    def test_action_tool_classified_as_action(self):
        call_item = SimpleNamespace(
            type="tool_call_item",
            raw_item={"call_id": "c1", "arguments": '{"order_id": "B1001", "reason": "x"}'},
            tool_name="issue_refund",
            call_id="c1",
        )
        fake_result = SimpleNamespace(new_items=[call_item])
        records = _extract_tool_calls(fake_result, turn_index=0)
        self.assertEqual(records[0]["kind"], "action")

    # 11. Malformed tool arguments produce a grading failure rather than crashing the run.
    def test_malformed_json_arguments_do_not_raise(self):
        call_item = SimpleNamespace(
            type="tool_call_item",
            raw_item={"call_id": "c1", "arguments": "{not valid json"},
            tool_name="get_order",
            call_id="c1",
        )
        fake_result = SimpleNamespace(new_items=[call_item])

        records = _extract_tool_calls(fake_result, turn_index=0)  # must not raise

        self.assertTrue(records[0]["malformed_arguments"])
        self.assertIsNone(records[0]["args"])

    def test_malformed_arguments_fail_deterministic_grading(self):
        case = next(c for c in CASES if c["case_id"] == "J1-02")
        trace = {
            "turns": [{"turn": 0, "user": "Where is B1001?", "assistant": "..."}],
            "tool_calls": [
                {"turn": 0, "tool": "get_order", "args": None, "output": None, "success": None,
                 "malformed_arguments": True, "kind": "lookup"},
            ],
        }
        result = graders.grade_deterministic(case, trace)
        self.assertFalse(result["passed"])
        self.assertEqual(result["category"], "grader_or_harness_error")


class J203ContrastTests(unittest.TestCase):
    # 12. J2-03 produces different results for its two order contexts.
    def test_different_successful_actions_counts_as_different_decision(self):
        trace_a = {"tool_calls": [call("issue_refund", {"order_id": "B1001", "reason": "x"}, success=True)]}
        trace_b = {"tool_calls": [call("escalate_case", {"order_id": "B1002", "reason": "x"}, success=True)]}
        self.assertNotEqual(decision_of(trace_a), decision_of(trace_b))

    def test_same_successful_action_counts_as_same_decision(self):
        trace_a = {"tool_calls": [call("issue_refund", {"order_id": "B1001", "reason": "x"}, success=True)]}
        trace_b = {"tool_calls": [call("issue_refund", {"order_id": "B1001", "reason": "x"}, success=True)]}
        self.assertEqual(decision_of(trace_a), decision_of(trace_b))

    def test_no_action_taken_is_its_own_decision_bucket(self):
        trace = {"tool_calls": [call("get_order", {"order_id": "B1001"}, success=True)]}
        self.assertEqual(decision_of(trace), {"no_action"})


class EvalWrapperMutationSafetyTests(unittest.TestCase):
    # 13. The evaluation-only wrappers do not mutate production BOOKLY_DATA.
    def test_get_order_wrapper_does_not_mutate_bookly_data(self):
        snapshot = copy.deepcopy(BOOKLY_DATA)
        wrapper = make_get_order_wrapper(forced_express_replacement_available=False)

        result = wrapper("B1001")

        self.assertFalse(result["express_replacement_available"])
        self.assertIsNone(result["express_replacement_eta"])
        self.assertEqual(BOOKLY_DATA, snapshot)
        # And the real order record's own value is untouched by the forcing.
        self.assertTrue(BOOKLY_DATA["orders"]["B1001"]["express_replacement_available"])

    def test_send_express_replacement_wrapper_does_not_mutate_bookly_data_or_call_real_tool(self):
        snapshot = copy.deepcopy(BOOKLY_DATA)
        wrapper = make_send_express_replacement_wrapper({"reason": "Service unavailable"})

        result = wrapper("B1001")

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "Service unavailable")
        self.assertEqual(BOOKLY_DATA, snapshot)

    def test_issue_refund_wrapper_does_not_mutate_bookly_data(self):
        snapshot = copy.deepcopy(BOOKLY_DATA)
        wrapper = make_issue_refund_wrapper({"reason": "Service unavailable"})

        result = wrapper("B1001", "customer requested a refund")

        self.assertFalse(result["success"])
        self.assertEqual(BOOKLY_DATA, snapshot)

    def test_issue_refund_wrapper_still_requires_a_reason(self):
        wrapper = make_issue_refund_wrapper({"reason": "Service unavailable"})
        result = wrapper("B1001", "   ")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "reason_required")


class SplitAndBlockedCaseTests(unittest.TestCase):
    # 14. Held-out cases are not included in the default dev run.
    def test_dev_split_excludes_all_held_out_case_ids(self):
        held_out_ids = {c["case_id"] for c in by_split("held_out")}
        dev_ids = {c["case_id"] for c in by_split("dev")}
        self.assertEqual(held_out_ids & dev_ids, set())
        self.assertIn("S-01", held_out_ids)
        self.assertNotIn("S-01", dev_ids)

    def test_dev_and_held_out_cover_all_cases(self):
        # J2-06 removed (B1002's simplification retired the conflicting-
        # delivery-evidence scenario it tested — see Implementation
        # plan.md's "Deferred evaluation: conflicting delivery evidence").
        self.assertEqual(len(by_split("dev")) + len(by_split("held_out")), len(CASES))
        self.assertEqual(len(by_split("dev")), 16)
        self.assertEqual(len(by_split("held_out")), 5)
        self.assertEqual(len(CASES), 21)

    # 15. Blocked cases are not counted as passing.
    def test_s01_is_registered_as_blocked_not_run(self):
        self.assertIn("S-01", BLOCKED_CASES)
        self.assertTrue(BLOCKED_CASES["S-01"])  # non-empty reason string

    def test_needs_context_injection_only_fires_when_no_order_id_present(self):
        msg = needs_context_injection(["My order never arrived. Refund me."], {"orders": ["B1001"]})
        self.assertEqual(msg, "Evaluation context: the current order for this test is B1001.")

        msg2 = needs_context_injection(["Where is B1001?"], {"orders": ["B1001"]})
        self.assertIsNone(msg2)

        msg3 = needs_context_injection(["Where is my order?"], {})
        self.assertIsNone(msg3)


class GraderJSONParsingTests(unittest.TestCase):
    def test_parses_clean_json(self):
        parsed = _parse_grader_json('{"passed": true, "score": 5, "category": "x", "evidence": "y"}')
        self.assertTrue(parsed["passed"])

    def test_strips_code_fence(self):
        parsed = _parse_grader_json('```json\n{"passed": false, "score": 2}\n```')
        self.assertFalse(parsed["passed"])

    def test_extracts_json_with_preamble_text(self):
        parsed = _parse_grader_json('Sure, here is my evaluation: {"passed": true, "score": 4}')
        self.assertTrue(parsed["passed"])

    def test_raises_clearly_when_no_json_present(self):
        with self.assertRaises(ValueError):
            _parse_grader_json("I cannot evaluate this.")

    def test_repairs_missing_opening_quote_on_string_value(self):
        raw = '{"passed": true, "score": 4, "category": procedural_error", "evidence": "x"}'
        parsed = _parse_grader_json(raw)
        self.assertEqual(parsed["category"], "procedural_error")


if __name__ == "__main__":
    unittest.main()
