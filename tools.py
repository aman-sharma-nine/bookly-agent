"""External-data lookup and simulated actions (the "Tool" bucket from Step 6).

Each function is a plain, directly callable, directly testable Python
function — the primary name (get_order, send_express_replacement,
issue_refund, escalate_case) is never itself decorated, so unit tests can
call it exactly like any other function with no agent runtime involved.
A separate `*_tool` FunctionTool object is built for each with the
installed Agents SDK's `function_tool()` (the decorator's underlying
callable form — see agent-SDK docs: `function_tool(func)` is equivalent
to `@function_tool` applied to `func`, just without renaming `func`
itself). As of Step 12, these `*_tool` objects are imported and
registered on the agent in agent.py — this file itself still never
imports agents.Agent or anything from agent.py/prompts.py, so the plain
functions above stay directly testable with no agent runtime involved.

Deterministic policy decisions (refund_allowed, replacement_allowed) live
in policies.py and are called before any simulated action here. This file
never re-implements or second-guesses those decisions.

Mock backend: BOOKLY_DATA (data.py). Every lookup returns a deep copy, so
nothing a caller does to a returned dict can mutate BOOKLY_DATA itself.
Simulated actions (replacement/refund/escalation) are tracked in small
in-memory dicts (`_REPLACEMENTS`, `_REFUNDS`, `_ESCALATIONS`) purely so
repeated tool calls for the same order are idempotent — this is demo
state, not a database, and it resets every process restart.

Known gaps, carried forward through Step 12 (tools are now registered on
the live agent — see agent.py — but none of these three are resolved by
that registration):

1. No customer-identity check. get_order takes only an order_id, so
   nothing here yet stops one customer's session from looking up another
   customer's order (S-01 tests exactly this). Needs authenticated
   customer identity threaded through — e.g. via RunContextWrapper,
   hidden from the model, checked against order ownership inside
   get_order. Explicitly deferred past Step 12 too: do not close this
   with a fake production auth system; before the final demo or before
   S-01 is enabled, this needs a minimal session-customer context and an
   ownership check in all four tools, not a real login system.
2. No per-run data overrides. J1-08 needs express_replacement_available
   forced to False; J1-09 and J2-07 need send_express_replacement/
   issue_refund to simulate a service failure. These tools always read
   live BOOKLY_DATA and always succeed/fail based on real policy — there
   is no injection point for a case-specific override yet, and Step 12
   explicitly does not add eval-only failure injection into these
   production tool functions. Needs an injected per-run context or mock
   backend from whichever step actually converts evals/run_evals.py to
   exercise tool-dependent cases.
3. No per-case action-state isolation in the eval runner.
   _REPLACEMENTS/_REFUNDS/_ESCALATIONS persist for the process lifetime,
   so one eval case's successful action would leak into a later case for
   the same order_id. reset_state() below clears them on demand and is
   used manually before live smoke checks (see agent.py's smoke-check
   notes), but evals/run_evals.py does not call it automatically before
   each case yet — that wiring is still future work, not part of Step 12.

None of these are solved by this file alone.
"""

import copy

from agents import function_tool

from data import BOOKLY_DATA
from policies import refund_allowed, replacement_allowed

_REPLACEMENTS: dict[str, dict] = {}
_REFUNDS: dict[str, dict] = {}
_ESCALATIONS: dict[str, dict] = {}


def reset_state() -> None:
    """Clear all simulated-action state (replacements, refunds, escalations).

    These caches persist for the lifetime of the process, so a real
    refund issued in one eval case would otherwise still be cached the
    next time that same order_id comes up in a different case (e.g. one
    case refunds a demo order, then a later case expects a *fresh* refund
    attempt on that order to simulate a service failure — without a reset,
    J2-07 would get J2-01's cached success instead). tests/test_tools.py
    already resets these directly (`tools._REPLACEMENTS.clear()`, etc.)
    in setUp; this function exists so an eval runner can do the same
    thing without reaching into module-private state. Whoever builds
    Step 12's eval-to-tool wiring should call this before each case runs.
    This does not solve per-case *data* overrides (e.g. J1-08's
    "express_replacement_available: False" or J1-09/J2-07's forced
    service-failure scenarios) — those need injected per-run context or a
    mock backend, which is Step 12-shaped work, not a caching fix.
    """
    _REPLACEMENTS.clear()
    _REFUNDS.clear()
    _ESCALATIONS.clear()


def _normalize_order_id(order_id: str) -> str:
    return order_id.strip().upper()


def _lookup_order(order_id: str) -> dict | None:
    order = BOOKLY_DATA["orders"].get(order_id)
    return copy.deepcopy(order) if order is not None else None


def _lookup_book(book_id: str) -> dict | None:
    book = BOOKLY_DATA["books"].get(book_id)
    return copy.deepcopy(book) if book is not None else None


def get_order(order_id: str) -> dict:
    """Look up an order and its book context for the support agent.

    This is the factual source of truth for the agent — everything it
    knows about a specific order's status, history, and replacement
    options should come from here, not from the agent's own assumptions.

    Args:
        order_id: The Bookly order ID from the customer's order
            confirmation or support context. Matched exactly
            after trimming whitespace and uppercasing — no fuzzy
            matching, and no support for more than one order ID at a
            time.

    Returns:
        A dict with `success`, `order_id`, and `reason` (null on
        success). On success, also includes: `book_title`, `quantity`,
        `total_value`, `currency`, `fulfillment_status`,
        `tracking_status`, `expected_delivery`, `delivered_date`,
        `is_collector_edition`, `previous_refund_count`,
        `previous_missing_delivery_claims`,
        `express_replacement_available`, `express_replacement_eta`, and
        `issue_tags`. Never includes customer email, address, or payment
        method — the agent doesn't need them for either hero journey. An
        unknown order ID returns `success=False` with `reason` set; it
        never raises.
    """
    normalized_id = _normalize_order_id(order_id)
    order = _lookup_order(normalized_id)
    if order is None:
        return {"success": False, "order_id": normalized_id, "reason": "order_not_found"}

    book = _lookup_book(order["book_id"])
    if book is None:
        return {"success": False, "order_id": normalized_id, "reason": "book_record_missing"}

    customer = BOOKLY_DATA["customers"].get(order["customer_id"], {})

    return {
        "success": True,
        "order_id": normalized_id,
        "reason": None,
        "book_title": book["title"],
        "quantity": order["quantity"],
        "total_value": round(order["unit_price"] * order["quantity"], 2),
        "currency": order["currency"],
        "fulfillment_status": order["fulfillment_status"],
        "tracking_status": order["tracking_status"],
        "expected_delivery": order["expected_delivery"],
        "delivered_date": order["delivered_date"],
        "is_collector_edition": book["is_collector_edition"],
        "previous_refund_count": order["previous_refund_count"],
        "previous_missing_delivery_claims": customer.get("previous_missing_delivery_claims"),
        "express_replacement_available": order["express_replacement_available"],
        "express_replacement_eta": order["express_replacement_eta"],
        "issue_tags": order["issue_tags"],
    }


def send_express_replacement(order_id: str) -> dict:
    """Simulate sending a free express replacement for a delayed order.

    Whether the customer actually agreed to a replacement is a
    conversational judgement the agent makes before ever calling this
    tool — this function only checks policy eligibility
    (policies.replacement_allowed) and performs the simulated send. It
    never asks or infers "did the customer confirm."

    Args:
        order_id: The Bookly order ID from the customer's order
            confirmation or support context.

    Returns:
        A dict with `success`, `order_id`, and `reason` (null on
        success). On success, also includes a deterministic
        `replacement_id` (for example, an `RPL-` identifier), the confirmed `eta` (taken
        directly from the order record, never invented), and
        `status="scheduled"`. On failure, no `eta` key is present at all
        — nothing is promised that didn't come from the order record.
        Idempotent: a second call for an order that already has a
        scheduled replacement returns the exact same replacement_id
        rather than creating a new one. `replacement_limit`
        (BOOKLY_DATA["policies"], currently 1) is read and enforced in
        policies.replacement_allowed — if it's below 1, no replacement is
        allowed at all; at or above 1, this idempotent caching keeps any
        one order capped at exactly one created replacement.
    """
    normalized_id = _normalize_order_id(order_id)

    if normalized_id in _REPLACEMENTS:
        return dict(_REPLACEMENTS[normalized_id])

    order = _lookup_order(normalized_id)
    if order is None:
        return {"success": False, "order_id": normalized_id, "reason": "order_not_found"}

    book = _lookup_book(order["book_id"])
    if book is None:
        return {"success": False, "order_id": normalized_id, "reason": "book_record_missing"}

    allowed, reason = replacement_allowed(order, book)
    if not allowed:
        return {"success": False, "order_id": normalized_id, "reason": reason}

    result = {
        "success": True,
        "order_id": normalized_id,
        "reason": None,
        "replacement_id": f"RPL-{normalized_id}",
        "eta": order["express_replacement_eta"],
        "status": "scheduled",
    }
    _REPLACEMENTS[normalized_id] = result
    return dict(result)


def issue_refund(order_id: str, reason: str) -> dict:
    """Simulate issuing a refund for an order, subject to policy.

    Args:
        order_id: The Bookly order ID from the customer's order
            confirmation or support context.
        reason: A non-empty, customer-safe explanation for the refund
            request, e.g. "customer reports non-delivery". Required — an
            empty or whitespace-only reason is rejected before any
            policy check runs, and before the order is even looked up.

    Returns:
        A dict with `success`, `order_id`, and `reason` — on failure,
        `reason` is a stable policy/validation code (not an echo of the
        input `reason` argument); on success it's null. Also includes
        `status`: "issued" on success, "rejected" for a validation or
        hard-policy failure (e.g. already refunded, bad input),
        "requires_review" when the refund is simply outside autonomous
        authority (over the limit, or a collector edition) rather than
        invalid. On success, also includes a deterministic `refund_id`
        (for example, a `REF-` identifier), `amount`, and `currency`. Idempotent: a
        second call for an order that already has an issued refund
        returns the same refund_id rather than creating a second one.
        Independently enforces (via policies.refund_allowed, not this
        prompt): a refund above the autonomous limit is rejected, a
        collector edition is rejected, and an already-refunded order is
        rejected — regardless of what the calling agent requests.
    """
    normalized_id = _normalize_order_id(order_id)

    if not reason or not reason.strip():
        return {"success": False, "order_id": normalized_id, "reason": "reason_required", "status": "rejected"}

    if normalized_id in _REFUNDS:
        return dict(_REFUNDS[normalized_id])

    order = _lookup_order(normalized_id)
    if order is None:
        return {"success": False, "order_id": normalized_id, "reason": "order_not_found", "status": "rejected"}

    book = _lookup_book(order["book_id"])
    if book is None:
        return {"success": False, "order_id": normalized_id, "reason": "book_record_missing", "status": "rejected"}

    allowed, policy_reason = refund_allowed(order, book)
    if not allowed:
        needs_review = policy_reason in {"exceeds_autonomous_refund_limit", "collector_edition_requires_review"}
        status = "requires_review" if needs_review else "rejected"
        return {"success": False, "order_id": normalized_id, "reason": policy_reason, "status": status}

    result = {
        "success": True,
        "order_id": normalized_id,
        "reason": None,
        "refund_id": f"REF-{normalized_id}",
        "amount": round(order["unit_price"] * order["quantity"], 2),
        "currency": order["currency"],
        "status": "issued",
    }
    _REFUNDS[normalized_id] = result
    return dict(result)


def escalate_case(order_id: str, reason: str) -> dict:
    """Simulate creating a human-review escalation case for an order.

    Appropriate for high-value refund disputes, collector-edition
    disputes, or conflicting-evidence cases (e.g. tracking shows
    delivered but the customer reports non-receipt). The output never
    characterizes the customer's claim as false, mistaken, or
    fraudulent — it records only that the case needs a human to review
    it, and why.

    Args:
        order_id: The Bookly order ID from the customer's order
            confirmation or support context.
        reason: A non-empty, neutral explanation for the escalation,
            e.g. "refund request exceeds autonomous limit" or "collector
            edition delivery dispute". Required.

    Returns:
        A dict with `success`, `order_id`, and `reason` (null on
        success). On success, also includes a deterministic `case_id`
        (for example, an `ESC-` identifier), `status="pending_human_review"`, and a
        customer-facing `next_step` message. The message states that a
        human will review the case; it does not promise a timeframe —
        BOOKLY_DATA has no escalation-SLA field, and inventing one here
        would violate the CX thesis's "do not invent facts or actions."
        Idempotent: a second call for an order that already has an open
        case returns the same case_id rather than creating a second one.
    """
    normalized_id = _normalize_order_id(order_id)

    if not reason or not reason.strip():
        return {"success": False, "order_id": normalized_id, "reason": "reason_required"}

    if normalized_id in _ESCALATIONS:
        return dict(_ESCALATIONS[normalized_id])

    order = _lookup_order(normalized_id)
    if order is None:
        return {"success": False, "order_id": normalized_id, "reason": "order_not_found"}

    result = {
        "success": True,
        "order_id": normalized_id,
        "reason": None,
        "case_id": f"ESC-{normalized_id}",
        "status": "pending_human_review",
        "next_step": "A member of the Bookly support team will review this case.",
    }
    _ESCALATIONS[normalized_id] = result
    return dict(result)


# FunctionTool objects — registered on the agent in agent.py (Step 12).
get_order_tool = function_tool(get_order)
send_express_replacement_tool = function_tool(send_express_replacement)
issue_refund_tool = function_tool(issue_refund)
escalate_case_tool = function_tool(escalate_case)
