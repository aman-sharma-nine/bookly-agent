"""Centralized, customer-safe wording for every tool result in tools.py.

Single source of truth for the text a customer actually sees when a tool
succeeds, fails, or needs human review — no individual branch in tools.py
(or, downstream, ui/trace.py) writes its own ad hoc customer-facing
phrasing. build_result() attaches a `customer_message` (always) and a
`next_step` (where one exists) on top of a result dict tools.py has
already fully decided — it never adds, removes, or renames any
machine-readable field (`success`, `reason`, `status`, IDs, amounts, ...)
that tests or evals depend on.

Tone rules encoded directly in the strings below, not just documented:
- describe the item, order, or policy state — never the customer's
  motivation, honesty, or character;
- never say "simply", "just", "you should have", "not entitled to", or
  attribute a rejection to what the customer wants/likes;
- never accuse the customer of fraud or bad faith;
- never invent a processing time, SLA, or delivery promise BOOKLY_DATA
  doesn't actually have;
- clearly distinguish "request created" from "review required" from
  "action rejected" from "action completed" — a review-required message
  never reads like an approval;
- never echo an internal reason code, keyword-match mechanism, or
  database term back to the customer.
"""

from __future__ import annotations

_MONEY_SYMBOLS = {"USD": "$", "AUD": "A$", "CAD": "CA$", "GBP": "£", "EUR": "€"}


def format_money(amount, currency="AUD") -> str:
    """Render an amount the same way everywhere a customer sees money."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return ""
    code = str(currency or "AUD").upper()
    prefix = _MONEY_SYMBOLS.get(code, f"{code} ")
    return f"{prefix}{value:,.2f}"


# Shared by every tool whose first steps are "find the order, find the book".
_ORDER_LOOKUP_OUTCOMES = {
    "order_not_found": {
        "customer_message": "I couldn't find an order with that number. Please check the order number in your confirmation email.",
        "next_step": "If you have the order number from your confirmation email, share it and I'll take another look.",
    },
    "book_record_missing": {
        "customer_message": "I found the order, but some book details are currently unavailable. This needs further support review.",
        "next_step": "I'll flag this for the support team to look into.",
    },
    "invalid_record": {
        "customer_message": "I wasn't able to check this order right now.",
        "next_step": "Please try again, or let me know if this keeps happening.",
    },
}

# Used only if a tool/outcome pair isn't mapped below — should stay
# unreachable for every real code path, but a tool must never surface a
# blank or missing customer_message, so this is the last resort.
_FALLBACK = {
    "customer_message": "I wasn't able to complete that just now.",
    "next_step": "Please try again, or let me know if you'd like to try something else.",
}

TOOL_MESSAGES: dict[str, dict[str, dict]] = {
    "get_order": {
        "success": {"customer_message": "I found your order details."},
        **_ORDER_LOOKUP_OUTCOMES,
    },
    "send_express_replacement": {
        "success": {"customer_message": "Your express replacement has been scheduled."},
        "express_replacement_unavailable": {
            "customer_message": "An express replacement isn't available for this order right now.",
            "next_step": "I can look at other options, like a refund, if you'd like.",
        },
        "digital_item_not_shippable": {
            "customer_message": "This is a digital item, so there's no physical parcel to replace.",
            "next_step": "I can help with another question about the order.",
        },
        "order_in_transit": {
            "customer_message": "This order is already moving through the carrier network, so I wasn't able to create a duplicate replacement.",
            "next_step": "I can share the latest tracking status instead.",
        },
        "collector_edition_requires_review": {
            "customer_message": "This item needs specialist review before a replacement can be arranged.",
            "next_step": "I can send this to a Bookly specialist for review.",
        },
        **_ORDER_LOOKUP_OUTCOMES,
    },
    "issue_refund": {
        # "success" is intentionally an empty mapping, not omitted: the
        # real customer_message is always supplied dynamically (needs the
        # real refund amount — see issue_refund_success_message() below),
        # and this empty-but-present entry stops build_result from falling
        # through to _FALLBACK's next_step, which doesn't apply here.
        "success": {},
        "reason_required": {
            "customer_message": "I need a brief reason for the refund request before I can continue.",
            "next_step": "Once you share the reason, I can continue.",
        },
        "already_refunded": {
            "customer_message": "This order has already been refunded.",
            "next_step": "The original refund confirmation still applies to this order.",
        },
        # This rejection is terminal in the sense that it can't be issued
        # autonomously right now, but it's disputable, not settled — the
        # package could still turn into a lost-shipment claim. Escalation
        # is never automatic (see tools.py's escalation_mode="optional"
        # for this reason); this wording only offers, it doesn't promise.
        "order_in_transit": {
            "customer_message": "This order is still in transit, so I wasn't able to issue an autonomous refund yet.",
            "next_step": "I can share the latest tracking status, or ask a specialist to take a look if you'd like.",
        },
        # escalation_mode="required" for this reason: the agent is expected
        # to call escalate_case for this (see prompts.py), not ask
        # permission — but issue_refund itself hasn't escalated anything
        # yet, so this next_step describes what's required, not a
        # completed action (escalate_case's own success message is what
        # confirms the case was actually opened).
        "collector_edition_requires_review": {
            "customer_message": "This collector edition needs specialist review before a refund can be issued.",
            "next_step": "This needs to go to a Bookly specialist for review.",
        },
        # Terminal (escalation_mode="none"): digital items are never
        # return/refund eligible, so there is nothing a human review would
        # change — no specialist-review language belongs here.
        "item_not_return_eligible": {
            "customer_message": "This item isn't eligible for a refund under Bookly's returns policy.",
            "next_step": "Digital books and audiobooks aren't eligible for return; I can help with another question about the order.",
        },
        # escalation_mode="required" — same rationale as collector edition
        # above: describe what's required, not a completed escalation.
        "exceeds_autonomous_refund_limit": {
            "customer_message": "This refund amount needs human review before it can be issued.",
            "next_step": "This needs to go to a Bookly specialist for review.",
        },
        # Not a policy decision — a transient failure. escalation_mode=
        # "optional": never automatic, but retry or specialist review may
        # be offered.
        "service_unavailable": {
            "customer_message": "I wasn't able to reach the refund service right now, so I couldn't complete this request.",
            "next_step": "I can try again, or ask a specialist to take a look if you'd like.",
        },
        **_ORDER_LOOKUP_OUTCOMES,
    },
    "escalate_case": {
        "success": {
            "customer_message": "I've sent this case to a Bookly specialist for review.",
            "next_step": "A member of the Bookly support team will review this case.",
        },
        "reason_required": {"customer_message": "I need a little more detail about the issue before I can send it for review."},
        **_ORDER_LOOKUP_OUTCOMES,
    },
    "request_return": {
        "success": {
            "customer_message": "Your return request has been created.",
            "next_step": "Bookly will provide return instructions for this request.",
        },
        "reason_required": {"customer_message": "I need a brief reason for the return request before I can continue."},
        "already_returned_or_refunded": {"customer_message": "This order has already been returned or refunded."},
        "order_not_delivered": {"customer_message": "A return can only be requested after the order has been delivered."},
        "item_not_return_eligible": {
            "customer_message": "Digital books and audiobooks aren't eligible for return under Bookly's returns policy.",
            "next_step": "I can help with anything else about this order.",
        },
        "return_window_expired": {
            "customer_message": "The return window for this order has ended.",
            "next_step": "I can help with anything else about this order.",
        },
        # next_step for this one is filled dynamically from the
        # escalate_case call request_return makes internally — see
        # tools.request_return — so it's intentionally absent here.
        "return_requires_review": {"customer_message": "This return needs specialist review before it can be approved."},
        **_ORDER_LOOKUP_OUTCOMES,
    },
    "search_policy": {
        # "success" is intentionally empty, not omitted — see the
        # "issue_refund" comment above for why. The real customer_message
        # is always supplied dynamically by search_policy_success_message().
        "success": {},
        "policy_not_found": {"customer_message": "I couldn't find an approved Bookly policy covering that question, so I don't want to guess."},
        "query_required": {"customer_message": "What Bookly policy would you like me to check?"},
    },
    "verify_identity": {
        "success": {"customer_message": "I was able to verify the account details provided."},
        "identity_not_found": {"customer_message": "I wasn't able to verify an account from those details."},
        "email_required": {"customer_message": "Please provide the email address associated with the Bookly account."},
    },
    "send_password_reset": {
        "success": {"customer_message": "A password-reset link has been sent using Bookly's approved account-recovery process."},
        "identity_verification_required": {"customer_message": "I need to verify the account before I can send a password-reset link."},
    },
}


def _outcome_key(result: dict) -> str:
    if result.get("success"):
        return "success"
    return result.get("reason") or "unexpected_error"


def build_result(tool: str, result: dict, *, dynamic_message: str | None = None) -> dict:
    """Return a copy of `result` with a centralized `customer_message`
    (and, for outcomes that have one, a `next_step`) attached.

    Never touches any field `result` already has — no reason/status/ID is
    added, removed, or renamed, and an existing `next_step` (e.g.
    request_return's requires_review branch forwarding escalate_case's own
    next_step) is left exactly as the caller set it.

    `dynamic_message` is for the handful of outcomes that need a real
    value from this specific call (a refund amount, a matched policy
    topic) — the caller composes it from `result`'s own data via one of
    the *_success_message helpers below, so even the dynamic text is
    sourced from this module rather than written ad hoc in tools.py.
    """
    mapping = TOOL_MESSAGES.get(tool, {}).get(_outcome_key(result))
    if mapping is None:
        # No entry at all for this tool/outcome pair — as opposed to an
        # intentionally empty {} entry (issue_refund/search_policy
        # "success", handled entirely via dynamic_message) — falls back to
        # the generic message so customer_message is never blank.
        mapping = _FALLBACK
    updated = dict(result)
    updated["customer_message"] = dynamic_message if dynamic_message is not None else mapping.get("customer_message", _FALLBACK["customer_message"])
    if "next_step" not in updated and mapping.get("next_step") is not None:
        updated["next_step"] = mapping["next_step"]
    return updated


def issue_refund_success_message(amount, currency) -> str:
    formatted = format_money(amount, currency)
    return f"Your refund of {formatted} has been issued." if formatted else "Your refund has been issued."


def search_policy_success_message(matches: list) -> str:
    sources = []
    for match in matches or []:
        source = match.get("source") if isinstance(match, dict) else None
        if source and source not in sources:
            sources.append(source)
    if len(sources) == 1:
        return f"I found the relevant {sources[0]}."
    if sources:
        return "I found relevant Bookly policy information covering: " + ", ".join(sources) + "."
    return "I found relevant Bookly policy information."
