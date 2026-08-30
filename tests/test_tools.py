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
        tools._RETURNS.clear()
        tools._VERIFIED_IDENTITIES.clear()


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
        self.assertEqual(result["format"], "paperback")
        self.assertTrue(result["return_eligible"])
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

    def test_b1005_digital_item_refund_is_rejected(self):
        result = tools.issue_refund("B1005", "customer requests a refund")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "item_not_return_eligible")
        self.assertEqual(result["status"], "rejected")
        self.assertNotIn("B1005", tools._REFUNDS)

    def test_already_refunded_order_fails(self):
        result = tools.issue_refund("B1007", "customer reports non-delivery")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "already_refunded")

    def test_b1003_in_transit_fails_even_within_limit(self):
        # Regression test: B1003 is $32 (within the autonomous limit) and
        # not a collector edition, but it's already shipped and in transit
        # — a refund must be denied rather than issued autonomously.
        result = tools.issue_refund("B1003", "customer reports order is delayed")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "order_in_transit")
        self.assertEqual(result["status"], "rejected")

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

    # --- issue_refund is the real enforcement point, not just
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

    def test_b1003_in_transit_fails(self):
        # B1003 is already "shipped"/"in_transit" (express_replacement_
        # available is also False for it, but the in-transit check is
        # meant to gate this independently — see policies.py).
        result = tools.send_express_replacement("B1003")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "order_in_transit")
        self.assertNotIn("eta", result)

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


class RequestReturnTests(ToolTestCase):
    def test_successful_return_for_delivered_eligible_low_value_book(self):
        result = tools.request_return("B1012", "book is no longer needed")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "return_requested")
        self.assertEqual(result["return_id"], "RET-B1012")
        self.assertIn("return_by", result)

    def test_idempotent_repeated_call_same_return_id(self):
        first = tools.request_return("B1012", "book is no longer needed")
        second = tools.request_return("B1012", "asking again")
        self.assertEqual(first["return_id"], second["return_id"])

    def test_rejects_undelivered_order(self):
        result = tools.request_return("B1001", "book is no longer needed")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "order_not_delivered")
        self.assertEqual(result["status"], "rejected")

    def test_rejects_delivered_ebook_as_not_return_eligible(self):
        result = tools.request_return("B1023", "changed my mind")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "item_not_return_eligible")
        self.assertEqual(result["status"], "rejected")

    def test_rejects_delivered_order_past_the_return_window(self):
        result = tools.request_return("B1024", "found it in a drawer")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "return_window_expired")
        self.assertEqual(result["status"], "rejected")

    def test_collector_edition_return_creates_a_human_review_case(self):
        result = tools.request_return("B1025", "arrived damaged")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "return_requires_review")
        self.assertEqual(result["status"], "requires_review")
        self.assertEqual(result["case_id"], "ESC-B1025")
        self.assertIn("next_step", result)
        self.assertIn("B1025", tools._ESCALATIONS)

    def test_high_value_non_collector_return_creates_a_human_review_case(self):
        # B1008 is $75 (over the $50 autonomous limit) and not a collector
        # edition — the price-only branch of the review check.
        result = tools.request_return("B1008", "no longer wanted")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "return_requires_review")
        self.assertEqual(result["status"], "requires_review")
        self.assertEqual(result["case_id"], "ESC-B1008")
        self.assertIn("next_step", result)
        self.assertIn("B1008", tools._ESCALATIONS)

    def test_repeated_review_required_calls_reuse_the_same_escalation_case(self):
        first = tools.request_return("B1025", "arrived damaged")
        second = tools.request_return("B1025", "asking again")
        self.assertEqual(first["case_id"], second["case_id"])
        self.assertEqual(len(tools._ESCALATIONS), 1)

    def test_normal_low_value_return_does_not_create_an_escalation(self):
        tools.request_return("B1012", "no longer needed")
        self.assertNotIn("B1012", tools._ESCALATIONS)
        self.assertEqual(tools._ESCALATIONS, {})

    def test_denied_returns_do_not_create_an_escalation(self):
        for order_id in ("B1001", "B1023", "B1024", "B1013"):
            with self.subTest(order_id=order_id):
                tools.request_return(order_id, "some reason")
        self.assertEqual(tools._ESCALATIONS, {})

    def test_return_review_flow_never_issues_a_refund(self):
        tools.request_return("B1025", "arrived damaged")
        tools.request_return("B1008", "no longer wanted")
        self.assertEqual(tools._REFUNDS, {})

    def test_review_required_result_does_not_claim_approval_or_reason_echo(self):
        result = tools.request_return("B1025", "arrived damaged")
        self.assertFalse(result["success"])
        self.assertNotEqual(result["status"], "return_requested")

    def test_rejects_already_returned_order(self):
        result = tools.request_return("B1013", "book is no longer needed")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "already_returned_or_refunded")

    def test_empty_reason_fails(self):
        result = tools.request_return("B1012", "   ")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "reason_required")
        self.assertEqual(result["status"], "rejected")

    def test_unknown_order_fails_without_exception(self):
        result = tools.request_return("B9999", "book is no longer needed")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "order_not_found")


class SearchPolicyTests(ToolTestCase):
    def test_shipping_query_returns_concrete_shipping_facts(self):
        result = tools.search_policy("What shipping options do you offer?")
        self.assertTrue(result["success"])
        self.assertEqual(result["matches"][0]["topic"], "shipping")
        self.assertIn("Standard Tracked", result["matches"][0]["content"])

    def test_returns_query_matches_returns_topic(self):
        result = tools.search_policy("What's your return policy?")
        self.assertTrue(result["success"])
        self.assertEqual(result["matches"][0]["topic"], "returns")

    def test_payments_query_matches_payments_topic(self):
        result = tools.search_policy("What payment methods do you accept?")
        self.assertTrue(result["success"])
        self.assertEqual(result["matches"][0]["topic"], "payments")

    def test_password_reset_query_matches_password_reset_topic(self):
        result = tools.search_policy("I forgot my password.")
        self.assertTrue(result["success"])
        self.assertEqual(result["matches"][0]["topic"], "password_reset")

    def test_unknown_query_returns_policy_not_found_without_guessing(self):
        result = tools.search_policy("Do you sell concert tickets?")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "policy_not_found")
        self.assertEqual(result["matches"], [])

    def test_empty_query_is_rejected(self):
        result = tools.search_policy("   ")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "query_required")


class VerifyIdentityAndPasswordResetTests(ToolTestCase):
    def test_password_reset_blocked_without_prior_verification(self):
        result = tools.send_password_reset("C1001")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "identity_verification_required")
        self.assertEqual(result["status"], "verification_required")

    def test_password_reset_succeeds_after_matching_verify_identity_call(self):
        verification = tools.verify_identity("sarah.marlow@example.com")
        self.assertTrue(verification["success"])
        self.assertEqual(verification["customer_id"], "C1001")

        result = tools.send_password_reset(verification["customer_id"])
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "reset_link_sent")

    def test_password_reset_is_scoped_to_the_verified_customer_only(self):
        tools.verify_identity("sarah.marlow@example.com")  # verifies C1001
        result = tools.send_password_reset("C1002")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "identity_verification_required")

    def test_verify_identity_rejects_unmatched_email_without_exception(self):
        result = tools.verify_identity("nobody@example.com")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "identity_not_found")

    def test_verify_identity_rejects_empty_email(self):
        result = tools.verify_identity("")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "email_required")

    def test_a_boolean_can_no_longer_grant_verification(self):
        # Regression guard for the CX review's core finding: the tool no
        # longer accepts an identity_verified argument at all, so nothing
        # the caller passes can substitute for a real verify_identity call.
        self.assertNotIn("identity_verified", tools.send_password_reset.__code__.co_varnames)


class ResetStateTests(ToolTestCase):
    def test_reset_state_clears_all_caches_and_allows_a_fresh_attempt(self):
        tools.issue_refund("B1001", "customer reports non-delivery")
        tools.send_express_replacement("B1001")
        tools.escalate_case("B1002", "collector edition dispute")
        tools.request_return("B1012", "no longer needed")
        tools.verify_identity("sarah.marlow@example.com")
        self.assertTrue(tools._REFUNDS)
        self.assertTrue(tools._REPLACEMENTS)
        self.assertTrue(tools._ESCALATIONS)
        self.assertTrue(tools._RETURNS)
        self.assertTrue(tools._VERIFIED_IDENTITIES)

        tools.reset_state()

        self.assertEqual(tools._REFUNDS, {})
        self.assertEqual(tools._REPLACEMENTS, {})
        self.assertEqual(tools._ESCALATIONS, {})
        self.assertEqual(tools._RETURNS, {})
        self.assertEqual(tools._VERIFIED_IDENTITIES, set())

    def test_reset_state_revokes_a_previously_verified_identity(self):
        tools.verify_identity("sarah.marlow@example.com")
        tools.reset_state()

        result = tools.send_password_reset("C1001")

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "identity_verification_required")


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
        tools.request_return("B1012", "no longer needed")
        tools.request_return("B1023", "changed my mind")
        tools.request_return("B1024", "found it late")
        tools.request_return("B1025", "arrived damaged")
        tools.search_policy("What shipping options do you offer?")
        tools.search_policy("Do you sell concert tickets?")
        verification = tools.verify_identity("sarah.marlow@example.com")
        tools.verify_identity("nobody@example.com")
        tools.send_password_reset(verification["customer_id"])
        tools.send_password_reset("C1002")

        self.assertEqual(BOOKLY_DATA, snapshot)


if __name__ == "__main__":
    unittest.main()
