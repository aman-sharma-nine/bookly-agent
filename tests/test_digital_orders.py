"""Regression coverage: digital orders (ebooks, audiobooks) must never
display physical-shipment logistics — no carrier, no parcel, no delivery
ETA — and must never be able to trigger a physical-shipment workflow like
an express replacement.

See data.py's normalize_digital_orders() for the centralized, deterministic
rule these tests are pinning down, and policies.py's digital-format guards
in refund_allowed/replacement_allowed for the independent enforcement layer.
"""

import unittest

import tools
from data import BOOKLY_DATA, DIGITAL_FORMATS
from policies import replacement_allowed


def _digital_order_ids():
    books = BOOKLY_DATA["books"]
    return [
        order_id
        for order_id, order in BOOKLY_DATA["orders"].items()
        if books.get(order["book_id"], {}).get("format") in DIGITAL_FORMATS
    ]


class DigitalOrdersHaveNoPhysicalShippingFields(unittest.TestCase):
    def setUp(self):
        self.digital_order_ids = _digital_order_ids()
        # Sanity check the fixture actually covers both digital formats
        # this suite claims to test.
        self.assertGreaterEqual(len(self.digital_order_ids), 2)

    def test_no_digital_order_has_a_physical_shipping_method(self):
        physical_methods = set(BOOKLY_DATA["policies"]["shipping_methods"])
        for order_id in self.digital_order_ids:
            with self.subTest(order_id=order_id):
                order = BOOKLY_DATA["orders"][order_id]
                self.assertIsNone(order["shipping_method"])
                self.assertNotIn(order["shipping_method"], physical_methods)

    def test_no_digital_order_has_carrier_tracking_or_a_delivery_eta(self):
        for order_id in self.digital_order_ids:
            with self.subTest(order_id=order_id):
                order = BOOKLY_DATA["orders"][order_id]
                self.assertEqual(order["tracking_status"], "not_applicable")
                self.assertIsNone(order["expected_delivery"])
                self.assertIsNone(order["express_replacement_eta"])
                self.assertFalse(order["express_replacement_available"])

    def test_b1005_no_longer_reports_physical_shipment_fields(self):
        order = BOOKLY_DATA["orders"]["B1005"]
        self.assertNotEqual(order["shipping_method"], "Economy Parcel")
        self.assertNotEqual(order["tracking_status"], "label_created")
        self.assertIsNone(order["shipping_method"])
        self.assertEqual(order["tracking_status"], "not_applicable")

    def test_b1005_get_order_does_not_claim_a_physical_delivery(self):
        result = tools.get_order("B1005")
        self.assertTrue(result["success"])
        self.assertEqual(result["format"], "ebook")
        self.assertIsNone(result["expected_delivery"])
        self.assertEqual(result["tracking_status"], "not_applicable")
        self.assertNotIn(result["fulfillment_status"], {"shipped", "delivered"})
        self.assertFalse(result["express_replacement_available"])
        self.assertIsNone(result["express_replacement_eta"])


class PhysicalOrdersRetainExistingShippingBehavior(unittest.TestCase):
    def test_b1001_still_has_full_physical_shipment_fields(self):
        result = tools.get_order("B1001")
        self.assertTrue(result["success"])
        self.assertEqual(result["format"], "paperback")
        self.assertEqual(result["expected_delivery"], "2026-08-26")
        self.assertEqual(result["tracking_status"], "carrier_delay")
        self.assertTrue(result["express_replacement_available"])
        self.assertEqual(result["express_replacement_eta"], "2026-08-23")

        order = BOOKLY_DATA["orders"]["B1001"]
        self.assertEqual(order["shipping_method"], "Economy Parcel")

    def test_b1004_delivered_physical_order_unchanged(self):
        order = BOOKLY_DATA["orders"]["B1004"]
        self.assertEqual(order["fulfillment_status"], "delivered")
        self.assertEqual(order["tracking_status"], "delivered")
        self.assertEqual(order["shipping_method"], "Express Air")
        self.assertEqual(order["delivered_date"], "2026-08-14")


class DigitalOrdersCannotTriggerPhysicalShipmentWorkflows(unittest.TestCase):
    def setUp(self):
        tools.reset_state()

    def test_replacement_allowed_denies_every_digital_order(self):
        books = BOOKLY_DATA["books"]
        for order_id in _digital_order_ids():
            with self.subTest(order_id=order_id):
                order = BOOKLY_DATA["orders"][order_id]
                book = books[order["book_id"]]
                allowed, reason = replacement_allowed(order, book)
                self.assertFalse(allowed)
                self.assertEqual(reason, "digital_item_not_shippable")

    def test_replacement_allowed_denies_digital_item_even_if_fields_are_forged(self):
        # Defense in depth: even if a digital order's own
        # express_replacement_available/eta fields were somehow set to look
        # shippable, the format-level guard must still block it.
        order, book = BOOKLY_DATA["orders"]["B1005"], BOOKLY_DATA["books"]["BK1005"]
        forged_order = dict(order, express_replacement_available=True, express_replacement_eta="2026-08-23")
        allowed, reason = replacement_allowed(forged_order, book)
        self.assertFalse(allowed)
        self.assertEqual(reason, "digital_item_not_shippable")

    def test_send_express_replacement_rejects_b1005(self):
        result = tools.send_express_replacement("B1005")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "digital_item_not_shippable")
        self.assertNotIn("eta", result)
        self.assertNotIn("B1005", tools._REPLACEMENTS)

    def test_send_express_replacement_rejects_b1010_audiobook(self):
        result = tools.send_express_replacement("B1010")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "digital_item_not_shippable")


if __name__ == "__main__":
    unittest.main()
