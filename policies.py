"""Deterministic business rules (the "Code" bucket from Step 6).

These are plain Python functions, unit-testable without running an agent
or a tool call. tools.py calls them before simulating any refund or
replacement — the LLM decides whether an action is *appropriate*, these
functions decide whether it's *permitted*, and tools.py is the only place
that actually performs the (simulated) action. Nothing here depends on
prompts.py or agent.py, and nothing in prompts.py should be relied on to
enforce what these functions already enforce independently.

Policy values themselves live in data.py (BOOKLY_DATA["policies"]) since
they're part of the demo dataset, not hardcoded business logic.
"""

from data import BOOKLY_DATA

_POLICIES = BOOKLY_DATA["policies"]

# NOTE: BOOKLY_DATA["policies"] also defines "human_approval_limit" (250.0).
# It is intentionally not referenced anywhere below. Nothing in the Step 3
# task table, the Step 5 eval suite, or Step 10's operational-policy prompt
# defines a distinct behavior for a $50-$250 middle tier — every stated
# rule and every boundary eval case (J2-04 at $50, J2-05 at $51) tests a
# single two-tier line: autonomous_refund_limit, plus an unconditional
# collector-edition override. This demo enforces exactly that two-tier
# rule. If a $50-$250 "additional review" tier becomes real, decide its
# behavior and add eval cases for it first, then wire it in here.


def refund_allowed(order: dict, book: dict) -> tuple[bool, str]:
    """Decide whether a refund may be issued autonomously.

    This does not perform the refund — it only answers whether tools.py's
    issue_refund is permitted to. Checked in this order: record validity,
    whether the order was already refunded, whether the order is still
    in transit, the collector-edition override, then the autonomous
    refund value limit.

    Args:
        order: The order record from BOOKLY_DATA["orders"] (or an
            equivalent dict — must contain at least "unit_price",
            "quantity", "refund_amount", "book_id", "fulfillment_status",
            and "tracking_status").
        book: The book record from BOOKLY_DATA["books"] for
            order["book_id"] (must contain at least
            "is_collector_edition").

    Returns:
        A (allowed, reason) tuple. reason is always a stable,
        machine-readable, customer-safe code — never a fraud accusation
        or anything that assumes bad faith on the customer's part.
    """
    if not _looks_like_refund_order(order) or not _looks_like_book(book):
        return False, "invalid_record"

    if order.get("refund_amount", 0) > 0:
        return False, "already_refunded"

    if _order_in_transit(order):
        return False, "order_in_transit"

    if _POLICIES["collector_edition_requires_review"] and book["is_collector_edition"]:
        return False, "collector_edition_requires_review"

    total_value = order["unit_price"] * order["quantity"]
    if total_value <= _POLICIES["autonomous_refund_limit"]:
        return True, "within_autonomous_refund_limit"

    return False, "exceeds_autonomous_refund_limit"


def replacement_allowed(order: dict, book: dict) -> tuple[bool, str]:
    """Decide whether a free express replacement may be sent autonomously.

    Deliberately has no price check — express-replacement eligibility is
    not a refund-value question, so autonomous_refund_limit is never
    reused here. Eligibility is driven by the order's own precomputed
    express_replacement_available/eta fields (this demo's stand-in for a
    real logistics/inventory check), the collector-edition override, and
    whether the order is still in transit.

    The in-transit check exists because express_replacement_available is
    demo data describing whether a replacement *could* be dispatched, not
    whether one *should* be — a package already shipped and moving toward
    the customer should not trigger a costly duplicate shipment just
    because that field happens to be true. A delayed order (fulfillment
    still stuck before it ever shipped) is a different, still-eligible
    case: see _order_in_transit.

    replacement_limit (BOOKLY_DATA["policies"]["replacement_limit"], currently
    1) is read here, not just assumed: if it's below 1, no autonomous
    replacement is allowed at all, regardless of order/book eligibility.
    Above that, "at most one replacement per order" is respected
    structurally rather than by counting here — tools.py's
    send_express_replacement caches its first successful send per order
    and returns that same result on every later call for that order, so
    at most one is ever actually created per order no matter how many
    times this function or the tool are called. This function does not
    currently support a replacement_limit value greater than 1 (e.g. "two
    replacements allowed per order") — that would need tools.py's cache
    to become a per-order counter, which nothing in this demo's data or
    eval suite currently calls for.

    Args:
        order: The order record from BOOKLY_DATA["orders"] (or an
            equivalent dict — must contain at least
            "express_replacement_available", "express_replacement_eta",
            and "book_id").
        book: The book record from BOOKLY_DATA["books"] for
            order["book_id"] (must contain at least
            "is_collector_edition").

    Returns:
        A (allowed, reason) tuple.
    """
    if not _looks_like_replacement_order(order) or not _looks_like_book(book):
        return False, "invalid_record"

    if _POLICIES["replacement_limit"] < 1:
        return False, "replacement_limit_reached"

    if _order_in_transit(order):
        return False, "order_in_transit"

    if _POLICIES["collector_edition_requires_review"] and book["is_collector_edition"]:
        return False, "collector_edition_requires_review"

    if not order.get("express_replacement_available") or not order.get("express_replacement_eta"):
        return False, "express_replacement_unavailable"

    return True, "express_replacement_available"


def _order_in_transit(order: dict) -> bool:
    """True once an order has actually shipped and is moving toward the
    customer — fulfillment_status "shipped" or tracking_status
    "in_transit" (checked independently since either alone is enough
    evidence the package is en route). A "delayed" order that never
    shipped in the first place (e.g. B1001, still carrier_delay before
    dispatch) does not count — that's the recoverable case an express
    replacement or refund can still legitimately address."""
    return order.get("fulfillment_status") == "shipped" or order.get("tracking_status") == "in_transit"


def _looks_like_refund_order(order: dict) -> bool:
    required = {"unit_price", "quantity", "refund_amount", "book_id"}
    return isinstance(order, dict) and required.issubset(order)


def _looks_like_replacement_order(order: dict) -> bool:
    required = {"express_replacement_available", "express_replacement_eta", "book_id"}
    return isinstance(order, dict) and required.issubset(order)


def _looks_like_book(book: dict) -> bool:
    return isinstance(book, dict) and "is_collector_edition" in book
