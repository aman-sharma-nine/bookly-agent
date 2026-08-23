"""Unit tests for tools.py.

Every test resets tools.py's in-memory idempotency stores in setUp, so
tests don't leak state into each other through module-level dicts.
"""

import copy
import unittest

import tools
from data import BOOKLY_DATA

PII_KEYS = {"email", "address", "shipping_address_country", "payment_status",
            "first_name", "last_name", "customer_id"}


class ToolTestCase(unittest.TestCase):
    def setUp(self):
        tools._REPLACEMENTS.clear()
        tools._REFUNDS.clear()
        tools._ESCALATIONS.clear()


class GetOrderTests(ToolTestCase):
    def test_b1001_returns_expected_joined_context(self):
        result = tools.get_order("B1001")
        self.assertTrue(result["success"])
        self.assertEqual(result["order_id"], "B1001")
        self.assertIsNone(result["reason"])
        self.assertEqual(result["book_title"], "The Hobbit")
        self.assertEqual(result["quantity"], 1)
        self.assertEqual(result["total_value"], 25.0)
        self.assertEqual(result["currency"], "AUD")
        self.assertEqual(result["fulfillment_status"], "delayed")
        self.assertEqual(result["tracking_status"], "carrier_delay")
        self.assertEqual(result["expected_delivery"], "2026-08-26")
        self.assertIsNone(result["delivered_date"])
        self.assertFalse(result["is_collector_edition"])
        self.assertEqual(result["previous_refund_count"], 0)
        self.assertEqual(result["previous_missing_delivery_claims"], 0)
        self.assertTrue(result["express_replacement_available"])
        self.assertEqual(result["express_replacement_eta"], "2026-08-23")
        self.assertIn("delayed", result["issue_tags"])

    def test_order_id_is_normalized(self):
        result = tools.get_order("  b1001 ")
        self.assertTrue(result["success"])
        self.assertEqual(result["order_id"], "B1001")

    def test_unknown_order_returns_failure_not_exception(self):
        result = tools.get_order("B9999")
        self.assertFalse(result["success"])
        self.assertEqual(result["order_id"], "B9999")
        self.assertIsNotNone(result["reason"])

    def test_no_unnecessary_pii_in_result(self):
        result = tools.get_order("B1001")
        leaked = PII_KEYS.intersection(result)
        self.assertEqual(leaked, set())


class IssueRefundTests(ToolTestCase):
    def test_b1001_25_dollars_succeeds(self):
        result = tools.issue_refund("B1001", "customer reports non-delivery")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "issued")
        self.assertEqual(result["refund_id"], "REF-B1001")
        self.assertEqual(result["amount"], 25.0)
        self.assertEqual(result["currency"], "AUD")

    def test_b1021_fifty_dollars_succeeds(self):
        result = tools.issue_refund("B1021", "customer reports non-delivery")
        self.assertTrue(result["success"])
        self.assertEqual(result["amount"], 50.0)

    def test_b1022_fifty_one_dollars_fails(self):
        result = tools.issue_refund("B1022", "customer reports non-delivery")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "requires_review")

    def test_b1002_collector_edition_fails(self):
        result = tools.issue_refund("B1002", "customer reports non-delivery")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "collector_edition_requires_review")

    def test_already_refunded_order_fails(self):
        result = tools.issue_refund("B1007", "customer reports non-delivery")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "already_refunded")

    def test_empty_reason_fails(self):
        result = tools.issue_refund("B1001", "   ")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "reason_required")

    def test_unknown_order_fails_without_exception(self):
        result = tools.issue_refund("B9999", "customer reports non-delivery")
        self.assertFalse(result["success"])

    def test_never_returns_success_true_on_a_denied_case(self):
        for order_id in ("B1022", "B1002", "B1007"):
            with self.subTest(order_id=order_id):
                result = tools.issue_refund(order_id, "customer reports non-delivery")
                self.assertFalse(result["success"])

    def test_idempotent_repeated_call_same_refund_id(self):
        first = tools.issue_refund("B1001", "customer reports non-delivery")
        second = tools.issue_refund("B1001", "asking again")
        self.assertEqual(first["refund_id"], second["refund_id"])
        self.assertEqual(second["status"], "issued")

    # --- Step 14: issue_refund is the real enforcement point, not just
    # refund_allowed() in isolation — these confirm the full tool call
    # never reports success outside authority, and that a denied refund
    # leaves no trace in the idempotency cache (so a later legitimate
    # attempt for the same order isn't silently blocked by a phantom
    # "already handled" entry). ---------------------------------------

    def test_b1021_at_limit_succeeds(self):
        result = tools.issue_refund("B1021", "customer reports non-delivery")

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "issued")
        self.assertEqual(result["amount"], 50.0)

    def test_b1022_above_limit_requires_review(self):
        result = tools.issue_refund("B1022", "customer reports non-delivery")

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "requires_review")
        self.assertEqual(result["reason"], "exceeds_autonomous_refund_limit")

    def test_denied_refund_creates_no_cache_entry(self):
        tools.reset_state()

        result = tools.issue_refund("B1022", "customer reports non-delivery")

        self.assertFalse(result["success"])
        self.assertNotIn("B1022", tools._REFUNDS)

    def test_collector_edition_denial_creates_no_cache_entry(self):
        tools.reset_state()

        result = tools.issue_refund("B1002", "customer reports non-delivery")

        self.assertFalse(result["success"])
        self.assertNotIn("B1002", tools._REFUNDS)


class SendExpressReplacementTests(ToolTestCase):
    def test_b1001_succeeds_with_confirmed_eta(self):
        result = tools.send_express_replacement("B1001")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["replacement_id"], "RPL-B1001")
        self.assertEqual(result["eta"], "2026-08-23")

    def test_unavailable_replacement_fails(self):
        result = tools.send_express_replacement("B1021")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "express_replacement_unavailable")
        self.assertNotIn("eta", result)

    def test_collector_edition_fails(self):
        result = tools.send_express_replacement("B1002")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "collector_edition_requires_review")

    def test_unknown_order_fails_without_exception(self):
        result = tools.send_express_replacement("B9999")
        self.assertFalse(result["success"])

    def test_idempotent_repeated_call_same_replacement_id(self):
        first = tools.send_express_replacement("B1001")
        second = tools.send_express_replacement("B1001")
        self.assertEqual(first["replacement_id"], second["replacement_id"])
        self.assertEqual(len(tools._REPLACEMENTS), 1)


class EscalateCaseTests(ToolTestCase):
    def test_b1002_creates_pending_review_case(self):
        result = tools.escalate_case("B1002", "collector edition refund dispute requires human review")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "pending_human_review")
        self.assertEqual(result["case_id"], "ESC-B1002")
        self.assertIn("next_step", result)

    def test_unknown_order_fails(self):
        result = tools.escalate_case("B9999", "some reason")
        self.assertFalse(result["success"])

    def test_empty_reason_fails(self):
        result = tools.escalate_case("B1002", "")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "reason_required")

    def test_output_contains_no_fraud_accusation(self):
        result = tools.escalate_case("B1002", "collector edition refund dispute requires human review")
        blob = str(result).lower()
        for word in ("fraud", "fraudulent", "lying", "lied", "scam"):
            self.assertNotIn(word, blob)

    def test_idempotent_repeated_call_same_case_id(self):
        first = tools.escalate_case("B1002", "first reason")
        second = tools.escalate_case("B1002", "second reason")
        self.assertEqual(first["case_id"], second["case_id"])

    def test_next_step_does_not_invent_an_sla(self):
        # Regression test: BOOKLY_DATA has no escalation-SLA field, so the
        # message must not promise a specific timeframe ("1-2 business
        # days" etc.) — that would be an invented fact.
        result = tools.escalate_case("B1002", "collector edition refund dispute requires human review")
        next_step = result["next_step"].lower()
        for phrase in ("business day", "hour", "24 hours", "within 1", "within 2"):
            self.assertNotIn(phrase, next_step)


class ResetStateTests(ToolTestCase):
    def test_reset_state_clears_all_caches_and_allows_a_fresh_attempt(self):
        tools.issue_refund("B1001", "customer reports non-delivery")
        tools.send_express_replacement("B1001")
        tools.escalate_case("B1002", "collector edition dispute")
        self.assertTrue(tools._REFUNDS)
        self.assertTrue(tools._REPLACEMENTS)
        self.assertTrue(tools._ESCALATIONS)

        tools.reset_state()

        self.assertEqual(tools._REFUNDS, {})
        self.assertEqual(tools._REPLACEMENTS, {})
        self.assertEqual(tools._ESCALATIONS, {})


class BooklyDataImmutabilityTests(ToolTestCase):
    def test_bookly_data_unchanged_after_a_full_pass_of_tool_calls(self):
        snapshot = copy.deepcopy(BOOKLY_DATA)

        tools.get_order("B1001")
        tools.get_order("B9999")
        tools.send_express_replacement("B1001")
        tools.send_express_replacement("B1001")
        tools.issue_refund("B1021", "customer reports non-delivery")
        tools.issue_refund("B1022", "customer reports non-delivery")
        tools.issue_refund("B1002", "customer reports non-delivery")
        tools.escalate_case("B1002", "collector edition refund dispute requires human review")

        self.assertEqual(BOOKLY_DATA, snapshot)


if __name__ == "__main__":
    unittest.main()
