import copy
from datetime import date

from agents import function_tool

import messages
from data import BOOKLY_DATA
from policies import refund_allowed, replacement_allowed

_REPLACEMENTS: dict[str, dict] = {}
_REFUNDS: dict[str, dict] = {}
_ESCALATIONS: dict[str, dict] = {}
_RETURNS: dict[str, dict] = {}
# Populated only by verify_identity() below, never by send_password_reset's
# caller directly — this is what keeps password-reset enforcement in code
# rather than in the model's own say-so. See send_password_reset's
# docstring for why this exists.
_VERIFIED_IDENTITIES: set[str] = set()


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
    thing without reaching into module-private state. An eval-to-tool
    wiring layer should call this before each case runs. This does not
    solve per-case *data* overrides (e.g. J1-08's
    "express_replacement_available: False" or J1-09/J2-07's forced
    service-failure scenarios) — those need injected per-run context or a
    mock backend, not just a caching fix.
    """
    _REPLACEMENTS.clear()
    _REFUNDS.clear()
    _ESCALATIONS.clear()
    _RETURNS.clear()
    _VERIFIED_IDENTITIES.clear()


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
        `express_replacement_available`, `express_replacement_eta`,
        `issue_tags`, `format`, and `return_eligible`. Never includes
        customer email, address, or payment
        method — the agent doesn't need them for either hero journey. An
        unknown order ID returns `success=False` with `reason` set; it
        never raises.
    """
    normalized_id = _normalize_order_id(order_id)
    order = _lookup_order(normalized_id)
    if order is None:
        return messages.build_result("get_order", {"success": False, "order_id": normalized_id, "reason": "order_not_found"})

    book = _lookup_book(order["book_id"])
    if book is None:
        return messages.build_result("get_order", {"success": False, "order_id": normalized_id, "reason": "book_record_missing"})

    customer = BOOKLY_DATA["customers"].get(order["customer_id"], {})

    return messages.build_result("get_order", {
        "success": True,
        "order_id": normalized_id,
        "reason": None,
        "book_title": book["title"],
        "format": book["format"],
        "return_eligible": book["return_eligible"],
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
    })


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
        return messages.build_result("send_express_replacement", {"success": False, "order_id": normalized_id, "reason": "order_not_found"})

    book = _lookup_book(order["book_id"])
    if book is None:
        return messages.build_result("send_express_replacement", {"success": False, "order_id": normalized_id, "reason": "book_record_missing"})

    allowed, reason = replacement_allowed(order, book)
    if not allowed:
        return messages.build_result("send_express_replacement", {"success": False, "order_id": normalized_id, "reason": reason})

    result = messages.build_result("send_express_replacement", {
        "success": True,
        "order_id": normalized_id,
        "reason": None,
        "replacement_id": f"RPL-{normalized_id}",
        "eta": order["express_replacement_eta"],
        "status": "scheduled",
    })
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
        return messages.build_result("issue_refund", {"success": False, "order_id": normalized_id, "reason": "reason_required", "status": "rejected"})

    if normalized_id in _REFUNDS:
        return dict(_REFUNDS[normalized_id])

    order = _lookup_order(normalized_id)
    if order is None:
        return messages.build_result("issue_refund", {"success": False, "order_id": normalized_id, "reason": "order_not_found", "status": "rejected"})

    book = _lookup_book(order["book_id"])
    if book is None:
        return messages.build_result("issue_refund", {"success": False, "order_id": normalized_id, "reason": "book_record_missing", "status": "rejected"})

    allowed, policy_reason = refund_allowed(order, book)
    if not allowed:
        needs_review = policy_reason in {"exceeds_autonomous_refund_limit", "collector_edition_requires_review"}
        status = "requires_review" if needs_review else "rejected"
        return messages.build_result("issue_refund", {"success": False, "order_id": normalized_id, "reason": policy_reason, "status": status})

    amount = round(order["unit_price"] * order["quantity"], 2)
    result = messages.build_result(
        "issue_refund",
        {
            "success": True,
            "order_id": normalized_id,
            "reason": None,
            "refund_id": f"REF-{normalized_id}",
            "amount": amount,
            "currency": order["currency"],
            "status": "issued",
        },
        dynamic_message=messages.issue_refund_success_message(amount, order["currency"]),
    )
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
        return messages.build_result("escalate_case", {"success": False, "order_id": normalized_id, "reason": "reason_required"})

    if normalized_id in _ESCALATIONS:
        return dict(_ESCALATIONS[normalized_id])

    order = _lookup_order(normalized_id)
    if order is None:
        return messages.build_result("escalate_case", {"success": False, "order_id": normalized_id, "reason": "order_not_found"})

    result = messages.build_result("escalate_case", {
        "success": True,
        "order_id": normalized_id,
        "reason": None,
        "case_id": f"ESC-{normalized_id}",
        "status": "pending_human_review",
    })
    _ESCALATIONS[normalized_id] = result
    return dict(result)


def request_return(order_id: str, reason: str) -> dict:
    """Create a demo return request for an eligible delivered order.

    This creates a return request only; it does not issue a refund.
    High-value and collector-edition cases are routed for review — and
    "routed" is literal, not just a status string: this function calls
    escalate_case itself (the same plain function escalate_case_tool
    wraps) so a real, idempotent human-review case is always opened
    whenever this returns status="requires_review". The model is never
    relied on to separately remember to call escalate_case for a return —
    the review case exists whether or not the model ever mentions it.
    """
    normalized_id = _normalize_order_id(order_id)
    if not reason or not reason.strip():
        return messages.build_result("request_return", {"success": False, "order_id": normalized_id, "reason": "reason_required", "status": "rejected"})
    if normalized_id in _RETURNS:
        return dict(_RETURNS[normalized_id])
    order = _lookup_order(normalized_id)
    if order is None:
        return messages.build_result("request_return", {"success": False, "order_id": normalized_id, "reason": "order_not_found", "status": "rejected"})
    book = _lookup_book(order["book_id"])
    if book is None:
        return messages.build_result("request_return", {"success": False, "order_id": normalized_id, "reason": "book_record_missing", "status": "rejected"})
    if order.get("refund_amount", 0) > 0 or order.get("fulfillment_status") == "returned":
        return messages.build_result("request_return", {"success": False, "order_id": normalized_id, "reason": "already_returned_or_refunded", "status": "rejected"})
    if order.get("fulfillment_status") != "delivered" or not order.get("delivered_date"):
        return messages.build_result("request_return", {"success": False, "order_id": normalized_id, "reason": "order_not_delivered", "status": "rejected"})
    if not book.get("return_eligible", False):
        return messages.build_result("request_return", {"success": False, "order_id": normalized_id, "reason": "item_not_return_eligible", "status": "rejected"})
    if order.get("return_window_ends") and date.fromisoformat(BOOKLY_DATA["as_of_date"]) > date.fromisoformat(order["return_window_ends"]):
        return messages.build_result("request_return", {"success": False, "order_id": normalized_id, "reason": "return_window_expired", "status": "rejected"})

    if book.get("is_collector_edition") or order["unit_price"] * order["quantity"] > BOOKLY_DATA["policies"]["autonomous_refund_limit"]:
        escalation_reason = (
            "collector edition return requires human review"
            if book.get("is_collector_edition")
            else "return value exceeds the autonomous review threshold"
        )
        # escalate_case is itself idempotent (keyed by order_id in
        # _ESCALATIONS), so a repeated request_return call for this same
        # order_id reuses the exact same case_id rather than opening a
        # second case — this function never writes its own cache entry
        # for the requires_review branch, mirroring issue_refund's
        # convention of not caching denied/review outcomes (see
        # test_denied_refund_creates_no_cache_entry). next_step is
        # forwarded verbatim from escalate_case's own centralized
        # wording (messages.py), not recomposed here.
        escalation = escalate_case(normalized_id, escalation_reason)
        return messages.build_result("request_return", {
            "success": False,
            "order_id": normalized_id,
            "reason": "return_requires_review",
            "status": "requires_review",
            "return_id": f"RET-{normalized_id}",
            "case_id": escalation.get("case_id"),
            "next_step": escalation.get("next_step"),
        })

    result = messages.build_result("request_return", {
        "success": True, "order_id": normalized_id, "reason": None,
        "return_id": f"RET-{normalized_id}", "status": "return_requested",
        "return_by": order.get("return_window_ends"),
    })
    _RETURNS[normalized_id] = result
    return dict(result)


def search_policy(query: str) -> dict:
    """Search the approved demo knowledge base without guessing."""
    normalized_query = (query or "").strip().lower()
    if not normalized_query:
        return messages.build_result("search_policy", {"success": False, "reason": "query_required", "matches": []})
    policies = BOOKLY_DATA["policies"]
    matches = []
    if any(term in normalized_query for term in ("ship", "shipping", "delivery", "postage")):
        matches.append({"topic": "shipping", "content": copy.deepcopy(policies["shipping_policy"]), "source": "Bookly shipping policy"})
    if any(term in normalized_query for term in ("return", "exchange", "send back")):
        matches.append({"topic": "returns", "content": policies["knowledge_base"]["returns"], "return_window_days": policies["standard_return_days"], "source": "Bookly returns policy"})
    if any(term in normalized_query for term in ("pay", "payment", "card", "paypal")):
        matches.append({"topic": "payments", "content": policies["knowledge_base"]["payments"], "source": "Bookly payments policy"})
    if any(term in normalized_query for term in ("password", "reset", "sign in", "login", "log in")):
        matches.append({"topic": "password_reset", "content": policies["knowledge_base"]["password_reset"], "source": "Bookly account-recovery policy"})
    if not matches:
        return messages.build_result("search_policy", {"success": False, "reason": "policy_not_found", "query": query, "matches": []})
    return messages.build_result(
        "search_policy",
        {"success": True, "reason": None, "query": query, "matches": matches},
        dynamic_message=messages.search_policy_success_message(matches),
    )


def verify_identity(email: str) -> dict:
    """Deterministically verify a customer's identity by their account email.

    DEMO-ONLY stand-in for a real identity-verification channel (e.g. an
    emailed/texted one-time code, or an authenticated logged-in session).
    This is not production-grade identity verification — it's a simple
    exact-match lookup against BOOKLY_DATA's customer records, chosen so
    that "is this customer verified" is a fact this function computes
    itself, never a claim the model can make on its own. On a match, the
    resolved customer_id is recorded in _VERIFIED_IDENTITIES so
    send_password_reset can check it independently — the model cannot
    fabricate this state by asserting an email or a customer_id; it must
    supply an email that actually matches a BOOKLY_DATA record.

    Args:
        email: The email address the customer states is on their Bookly
            account. Matched case-insensitively after trimming whitespace.

    Returns:
        A dict with `success`. On success, also includes the resolved
        `customer_id` and `status="identity_verified"`. On failure,
        `reason` is `email_required` (blank input) or `identity_not_found`
        (no matching account) — never an error that leaks which accounts
        exist beyond a plain match/no-match.
    """
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return messages.build_result("verify_identity", {"success": False, "reason": "email_required"})

    for customer_id, customer in BOOKLY_DATA["customers"].items():
        if customer.get("email", "").strip().lower() == normalized_email:
            _VERIFIED_IDENTITIES.add(customer_id)
            return messages.build_result("verify_identity", {"success": True, "reason": None, "customer_id": customer_id, "status": "identity_verified"})

    return messages.build_result("verify_identity", {"success": False, "reason": "identity_not_found"})


def send_password_reset(customer_id: str) -> dict:
    """Send a reset link only when this customer_id has already been
    confirmed by a successful verify_identity call in this conversation.

    Unlike the earlier version of this tool, `identity_verified` is not an
    argument the caller can set — whether this customer is verified is
    looked up in _VERIFIED_IDENTITIES, a cache this function never writes
    to itself (only verify_identity does). This closes the gap the CX
    review flagged: a model can no longer grant itself a "verified"
    customer merely by asserting a boolean or by treating a conversational
    identity claim as proof. A conversational claim never reaches this
    function as anything but a customer_id string; it is only trusted once
    verify_identity has independently matched it against BOOKLY_DATA.

    Args:
        customer_id: The Bookly customer ID returned by a prior successful
            verify_identity call. Matched exactly after trimming whitespace
            and uppercasing.

    Returns:
        A dict with `success`. On success, also includes `status`
        ("reset_link_sent") and a `message` with no invented timing or
        account details — the message never states how the link was sent
        or when it will arrive, since BOOKLY_DATA has no such field. On
        failure (`identity_verification_required`), still returns
        `success=False` — this tool can never report a reset as sent
        without a real verify_identity success behind it, regardless of
        password_reset_requires_identity_verification's on/off value in a
        given demo configuration.
    """
    normalized_id = (customer_id or "").strip().upper()
    requires_verification = BOOKLY_DATA["policies"]["password_reset_requires_identity_verification"]

    if requires_verification and normalized_id not in _VERIFIED_IDENTITIES:
        return messages.build_result("send_password_reset", {"success": False, "status": "verification_required", "reason": "identity_verification_required"})

    result = messages.build_result("send_password_reset", {"success": True, "reason": None, "status": "reset_link_sent"})
    # `message` is kept as a separate field for backward compatibility with
    # anything already reading it; it is always identical to
    # customer_message, sourced from the same single string in messages.py.
    result["message"] = result["customer_message"]
    return result


# FunctionTool objects — registered on the agent in agent.py.
get_order_tool = function_tool(get_order)
send_express_replacement_tool = function_tool(send_express_replacement)
issue_refund_tool = function_tool(issue_refund)
escalate_case_tool = function_tool(escalate_case)
request_return_tool = function_tool(request_return)
search_policy_tool = function_tool(search_policy)
verify_identity_tool = function_tool(verify_identity)
send_password_reset_tool = function_tool(send_password_reset)
