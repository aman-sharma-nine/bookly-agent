"""Tests for messages.py (the centralized customer-message helper) and,
representatively, for the tool-result wiring in tools.py that consumes it.

These tests check the *tone contract* itself — every handled outcome gets
a non-empty, neutral, blame-free, timeframe-free customer_message that
never echoes an internal reason code — not just that a few example
strings match verbatim.
"""

import unittest

import messages
import tools
from data import BOOKLY_DATA

BLAME_WORDS = (
    "simply", "just ", "you should have", "not entitled", "don't like it",
    "doesn't like it", "your fault", "unreasonable", "careless", "dishonest",
    "fraud", "fraudulent", "lying", "lied", "scam",
)

TIMEFRAME_WORDS = (
    "business day", "business days", "hour", "hours", "shortly",
    "you'll see it", "within 1", "within 2", "24 hours", "few days",
)

# Reason codes that must never leak verbatim into a customer_message.
INTERNAL_REASON_CODES = (
    "item_not_return_eligible", "return_window_expired",
    "identity_verification_required", "order_not_found",
    "collector_edition_requires_review", "exceeds_autonomous_refund_limit",
    "already_returned_or_refunded", "policy_not_found", "reason_required",
    "book_record_missing", "order_in_transit", "already_refunded",
    "email_required", "identity_not_found", "query_required",
)


class MessageToneContractTests(unittest.TestCase):
    """Walks every mapped (tool, outcome) pair in messages.TOOL_MESSAGES."""

    def _all_customer_messages(self):
        for tool, outcomes in messages.TOOL_MESSAGES.items():
            for outcome, mapping in outcomes.items():
                text = mapping.get("customer_message")
                if text:
                    yield tool, outcome, text
                next_step = mapping.get("next_step")
                if next_step:
                    yield tool, f"{outcome}.next_step", next_step

    def test_no_message_contains_blame_oriented_wording(self):
        for tool, outcome, text in self._all_customer_messages():
            with self.subTest(tool=tool, outcome=outcome):
                lowered = text.lower()
                for word in BLAME_WORDS:
                    self.assertNotIn(word, lowered, f"{tool}/{outcome} contains blame wording {word!r}: {text!r}")

    def test_no_message_contains_an_invented_timeframe(self):
        for tool, outcome, text in self._all_customer_messages():
            with self.subTest(tool=tool, outcome=outcome):
                lowered = text.lower()
                for phrase in TIMEFRAME_WORDS:
                    self.assertNotIn(phrase, lowered, f"{tool}/{outcome} invents a timeframe {phrase!r}: {text!r}")

    def test_no_message_exposes_an_internal_reason_code(self):
        for tool, outcome, text in self._all_customer_messages():
            with self.subTest(tool=tool, outcome=outcome):
                for code in INTERNAL_REASON_CODES:
                    self.assertNotIn(code, text, f"{tool}/{outcome} leaks raw reason code {code!r}: {text!r}")

    def test_static_entries_are_all_non_empty_strings(self):
        for tool, outcomes in messages.TOOL_MESSAGES.items():
            for outcome, mapping in outcomes.items():
                for key in ("customer_message", "next_step"):
                    if key in mapping:
                        with self.subTest(tool=tool, outcome=outcome, field=key):
                            self.assertIsInstance(mapping[key], str)
                            self.assertTrue(mapping[key].strip())


class BuildResultHelperTests(unittest.TestCase):
    def test_success_outcome_uses_the_success_mapping(self):
        result = messages.build_result("verify_identity", {"success": True, "reason": None})
        self.assertEqual(result["customer_message"], "I was able to verify the account details provided.")

    def test_failure_outcome_uses_reason_as_the_lookup_key(self):
        result = messages.build_result("request_return", {"success": False, "reason": "return_window_expired"})
        self.assertEqual(result["customer_message"], "The return window for this order has ended.")

    def test_dynamic_message_overrides_the_static_mapping(self):
        result = messages.build_result("issue_refund", {"success": True, "reason": None}, dynamic_message="custom text")
        self.assertEqual(result["customer_message"], "custom text")

    def test_dynamic_success_entry_does_not_leak_the_fallback_next_step(self):
        # Regression test: issue_refund/search_policy "success" entries are
        # intentionally {} (present but empty) so build_result doesn't fall
        # through to _FALLBACK, which has its own next_step that must never
        # attach to a plain success result.
        result = messages.build_result("issue_refund", {"success": True, "reason": None}, dynamic_message="x")
        self.assertNotIn("next_step", result)

    def test_existing_next_step_is_never_overwritten(self):
        result = messages.build_result("request_return", {"success": False, "reason": "return_requires_review", "next_step": "custom forwarded step"})
        self.assertEqual(result["next_step"], "custom forwarded step")

    def test_unmapped_tool_outcome_falls_back_to_a_non_empty_message(self):
        result = messages.build_result("some_future_tool", {"success": False, "reason": "unknown_outcome"})
        self.assertTrue(result["customer_message"])

    def test_build_result_never_removes_or_renames_existing_fields(self):
        base = {"success": True, "order_id": "B1012", "reason": None, "return_id": "RET-B1012", "status": "return_requested"}
        result = messages.build_result("request_return", base)
        for key, value in base.items():
            self.assertEqual(result[key], value)

    def test_format_money_matches_expected_currency_symbols(self):
        self.assertEqual(messages.format_money(25, "AUD"), "A$25.00")
        self.assertEqual(messages.format_money(25, "USD"), "$25.00")
        self.assertEqual(messages.format_money(None, "AUD"), "")


class SearchPolicySuccessMessageTests(unittest.TestCase):
    def test_single_topic_names_the_source(self):
        text = messages.search_policy_success_message([{"topic": "shipping", "source": "Bookly shipping policy"}])
        self.assertEqual(text, "I found the relevant Bookly shipping policy.")

    def test_no_matches_still_returns_non_empty_text(self):
        text = messages.search_policy_success_message([])
        self.assertTrue(text)


class RepresentativeToolWiringTests(unittest.TestCase):
    """One representative case per required category, calling the real
    tools.py functions (not messages.py in isolation) to prove the wiring
    actually reaches the customer-facing field."""

    def setUp(self):
        tools.reset_state()

    def test_get_order_failure_has_a_customer_safe_message(self):
        result = tools.get_order("B9999")
        self.assertTrue(result["customer_message"])
        self.assertNotIn("order_not_found", result["customer_message"])

    def test_send_express_replacement_success_has_a_confirmation(self):
        result = tools.send_express_replacement("B1001")
        self.assertTrue(result["success"])
        self.assertIn("scheduled", result["customer_message"].lower())

    def test_issue_refund_review_outcome_does_not_claim_success(self):
        result = tools.issue_refund("B1022", "customer reports non-delivery")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "requires_review")
        message = result["customer_message"].lower()
        # "needs review before it can be issued" is a correct conditional,
        # not a completed-action claim — only the completed-claim phrasing
        # ("has been issued"/"your refund has been issued") is forbidden.
        self.assertNotIn("has been issued", message)
        self.assertNotIn("was issued", message)

    def test_escalate_case_success_never_promises_a_timeframe(self):
        result = tools.escalate_case("B1002", "collector edition dispute")
        for phrase in TIMEFRAME_WORDS:
            self.assertNotIn(phrase, result["customer_message"].lower())
            self.assertNotIn(phrase, result["next_step"].lower())

    def test_request_return_review_outcome_does_not_say_approved(self):
        result = tools.request_return("B1025", "arrived damaged")
        self.assertFalse(result["success"])
        message = result["customer_message"].lower()
        # "needs specialist review before it can be approved" is a correct
        # conditional, not a claim of approval — only a completed-approval
        # claim is forbidden.
        self.assertNotIn("has been approved", message)
        self.assertNotIn("was approved", message)
        self.assertNotIn("return approved", message)
        self.assertIn("review", message)

    def test_search_policy_no_match_does_not_mention_keyword_matching(self):
        result = tools.search_policy("do you sell concert tickets")
        for term in ("keyword", "database", "match(es)", "matches:"):
            self.assertNotIn(term, result["customer_message"].lower())

    def test_verify_identity_failure_does_not_confirm_or_deny_a_specific_email_exists(self):
        result = tools.verify_identity("nobody@example.com")
        self.assertNotIn("nobody@example.com", result["customer_message"])
        self.assertNotIn("no account", result["customer_message"].lower())

    def test_send_password_reset_never_mentions_a_password(self):
        result = tools.send_password_reset("C1001")
        self.assertNotIn("password", result["customer_message"].lower().replace("password-reset", "").replace("password reset", ""))


class B1023RegressionTests(unittest.TestCase):
    """Dedicated regression coverage for the exact scenario called out in
    the CX review: a digital-item return rejection must explain the policy
    without ever characterizing the customer's motivation."""

    def setUp(self):
        tools.reset_state()

    def test_b1023_return_is_rejected(self):
        result = tools.request_return("B1023", "I changed my mind")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "item_not_return_eligible")
        self.assertEqual(result["status"], "rejected")

    def test_b1023_message_explains_digital_items_are_not_return_eligible(self):
        result = tools.request_return("B1023", "I changed my mind")
        message = result["customer_message"].lower()
        self.assertIn("digital", message)
        self.assertIn("return", message)

    def test_b1023_message_does_not_judge_the_customers_motivation(self):
        result = tools.request_return("B1023", "I changed my mind")
        message = result["customer_message"].lower()
        for phrase in ("don't like it", "doesn't like it", "you changed your mind", "simply", "just "):
            self.assertNotIn(phrase, message)
        for word in BLAME_WORDS:
            self.assertNotIn(word, message)

    def test_b1023_book_is_actually_an_ebook_in_the_dataset(self):
        # Sanity check that this test is exercising the scenario it claims
        # to — B1023 must really be a delivered (digital-fulfillment),
        # non-return-eligible ebook.
        order = BOOKLY_DATA["orders"]["B1023"]
        book = BOOKLY_DATA["books"][order["book_id"]]
        self.assertEqual(order["fulfillment_status"], "digital_delivered")
        self.assertIsNotNone(order["delivered_date"])
        self.assertFalse(book["return_eligible"])
        self.assertEqual(book["format"], "ebook")


if __name__ == "__main__":
    unittest.main()
