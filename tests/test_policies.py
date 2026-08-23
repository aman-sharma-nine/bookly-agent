"""Unit tests for policies.py — pure functions, no agent involved."""

import copy
import unittest

from data import BOOKLY_DATA
from policies import refund_allowed, replacement_allowed


def order_and_book(order_id):
    order = BOOKLY_DATA["orders"][order_id]
    book = BOOKLY_DATA["books"][order["book_id"]]
    return order, book


class RefundAllowedTests(unittest.TestCase):
    def test_b1001_within_limit_allowed(self):
        order, book = order_and_book("B1001")
        allowed, reason = refund_allowed(order, book)
        self.assertTrue(allowed)
        self.assertEqual(reason, "within_autonomous_refund_limit")

    def test_b1021_exactly_at_fifty_allowed(self):
        order, book = order_and_book("B1021")
        self.assertEqual(order["unit_price"] * order["quantity"], 50.0)
        allowed, reason = refund_allowed(order, book)
        self.assertTrue(allowed)

    def test_b1022_fifty_one_rejected(self):
        order, book = order_and_book("B1022")
        self.assertEqual(order["unit_price"] * order["quantity"], 51.0)
        allowed, reason = refund_allowed(order, book)
        self.assertFalse(allowed)
        self.assertEqual(reason, "exceeds_autonomous_refund_limit")

    def test_collector_edition_rejected_regardless_of_price(self):
        order, book = order_and_book("B1002")
        self.assertTrue(book["is_collector_edition"])
        allowed, reason = refund_allowed(order, book)
        self.assertFalse(allowed)
        self.assertEqual(reason, "collector_edition_requires_review")

    def test_already_refunded_rejected(self):
        order, book = order_and_book("B1007")
        self.assertGreater(order["refund_amount"], 0)
        allowed, reason = refund_allowed(order, book)
        self.assertFalse(allowed)
        self.assertEqual(reason, "already_refunded")

    def test_malformed_records_rejected(self):
        self.assertEqual(refund_allowed({}, {}), (False, "invalid_record"))
        self.assertEqual(refund_allowed(None, None), (False, "invalid_record"))
        self.assertEqual(refund_allowed({"unit_price": 10}, {"is_collector_edition": False}), (False, "invalid_record"))

    # --- Precise cent-level boundary coverage, via copied records
    # rather than mutating BOOKLY_DATA (B1021/B1022 above already cover the
    # $50/$51 whole-dollar case using real dataset records; these isolate
    # the exact <=/> boundary independent of which real order happens to
    # sit on which side of it). -------------------------------------------

    def test_forty_nine_dollars_allowed(self):
        order, book = order_and_book("B1021")
        order_49 = copy.deepcopy(order)
        order_49["unit_price"] = 49.0

        allowed, reason = refund_allowed(order_49, book)

        self.assertTrue(allowed)
        self.assertEqual(reason, "within_autonomous_refund_limit")

    def test_exactly_fifty_dollars_allowed_via_copied_record(self):
        order, book = order_and_book("B1021")
        order_50 = copy.deepcopy(order)
        order_50["unit_price"] = 50.0

        allowed, reason = refund_allowed(order_50, book)

        self.assertTrue(allowed)
        self.assertEqual(reason, "within_autonomous_refund_limit")

    def test_fifty_dollars_and_one_cent_rejected(self):
        order, book = order_and_book("B1021")
        order_50_01 = copy.deepcopy(order)
        order_50_01["unit_price"] = 50.01

        allowed, reason = refund_allowed(order_50_01, book)

        self.assertFalse(allowed)
        self.assertEqual(reason, "exceeds_autonomous_refund_limit")

    def test_b1003_in_transit_rejected_even_within_limit(self):
        # Regression test: B1003 is $32 (within autonomous_refund_limit)
        # and not a collector edition, but fulfillment_status="shipped"/
        # tracking_status="in_transit" — the package is already moving
        # toward the customer, so a refund must still be denied.
        order, book = order_and_book("B1003")
        self.assertEqual(order["fulfillment_status"], "shipped")
        self.assertEqual(order["tracking_status"], "in_transit")
        self.assertLessEqual(order["unit_price"] * order["quantity"], BOOKLY_DATA["policies"]["autonomous_refund_limit"])

        allowed, reason = refund_allowed(order, book)

        self.assertFalse(allowed)
        self.assertEqual(reason, "order_in_transit")

    def test_delayed_order_not_treated_as_in_transit(self):
        # B1001 is "delayed"/"carrier_delay" — stuck before ever shipping,
        # not moving toward the customer — so it must NOT be caught by the
        # in-transit check.
        order, book = order_and_book("B1001")
        allowed, reason = refund_allowed(order, book)
        self.assertTrue(allowed)
        self.assertNotEqual(reason, "order_in_transit")

    def test_collector_edition_below_limit_still_requires_review(self):
        # Precedence check: a $25 collector edition must be blocked for
        # being a collector edition, not slip through because it's under
        # the $50 limit. Uses B1002's book (a real collector edition) with
        # a copied, cheaper order — never mutates BOOKLY_DATA.
        cheap_order, collector_book = order_and_book("B1002")
        cheap_order = copy.deepcopy(cheap_order)
        cheap_order["unit_price"] = 25.0

        self.assertTrue(collector_book["is_collector_edition"])
        self.assertLess(cheap_order["unit_price"], BOOKLY_DATA["policies"]["autonomous_refund_limit"])

        allowed, reason = refund_allowed(cheap_order, collector_book)

        self.assertFalse(allowed)
        self.assertEqual(reason, "collector_edition_requires_review")


class ReplacementAllowedTests(unittest.TestCase):
    def test_b1001_available_allowed(self):
        order, book = order_and_book("B1001")
        allowed, reason = replacement_allowed(order, book)
        self.assertTrue(allowed)
        self.assertEqual(reason, "express_replacement_available")

    def test_unavailable_rejected(self):
        order, book = order_and_book("B1021")
        self.assertFalse(order["express_replacement_available"])
        allowed, reason = replacement_allowed(order, book)
        self.assertFalse(allowed)
        self.assertEqual(reason, "express_replacement_unavailable")

    def test_collector_edition_rejected_even_if_available(self):
        order, book = order_and_book("B1002")
        override_order = dict(order, express_replacement_available=True, express_replacement_eta="2026-08-23")
        allowed, reason = replacement_allowed(override_order, book)
        self.assertFalse(allowed)
        self.assertEqual(reason, "collector_edition_requires_review")

    def test_b1003_in_transit_rejected_even_if_available(self):
        # Regression test: force express_replacement_available/eta True on
        # B1003's actual shipped/in_transit state — the in-transit check
        # must still block it, since express_replacement_available alone
        # doesn't mean a duplicate shipment is appropriate for a package
        # already moving toward the customer.
        order, book = order_and_book("B1003")
        override_order = dict(order, express_replacement_available=True, express_replacement_eta="2026-08-23")

        allowed, reason = replacement_allowed(override_order, book)

        self.assertFalse(allowed)
        self.assertEqual(reason, "order_in_transit")

    def test_price_never_gates_replacement(self):
        # $250 collector edition would fail on price if this function ever
        # silently reused autonomous_refund_limit — confirm it isn't the
        # reason even when available/eta are set on a non-collector item.
        order, book = order_and_book("B1002")
        non_collector_book = dict(book, is_collector_edition=False)
        override_order = dict(order, express_replacement_available=True, express_replacement_eta="2026-08-23")
        allowed, reason = replacement_allowed(override_order, non_collector_book)
        self.assertTrue(allowed)
        self.assertNotIn("limit", reason)

    def test_malformed_records_rejected(self):
        self.assertEqual(replacement_allowed({}, {}), (False, "invalid_record"))
        self.assertEqual(replacement_allowed(None, None), (False, "invalid_record"))

    def test_replacement_limit_is_actually_read_from_policy(self):
        # Regression test: replacement_allowed must consult
        # BOOKLY_DATA["policies"]["replacement_limit"], not just rely on
        # tools.py's idempotent caching to happen to cap sends at one.
        order, book = order_and_book("B1001")
        self.assertTrue(replacement_allowed(order, book)[0])  # sanity: normally allowed

        original_limit = BOOKLY_DATA["policies"]["replacement_limit"]
        try:
            BOOKLY_DATA["policies"]["replacement_limit"] = 0
            allowed, reason = replacement_allowed(order, book)
            self.assertFalse(allowed)
            self.assertEqual(reason, "replacement_limit_reached")
        finally:
            BOOKLY_DATA["policies"]["replacement_limit"] = original_limit

        # Confirm the temporary mutation didn't leak.
        self.assertEqual(BOOKLY_DATA["policies"]["replacement_limit"], original_limit)


if __name__ == "__main__":
    unittest.main()
