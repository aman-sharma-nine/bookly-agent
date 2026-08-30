"""Convert Agents SDK result items into safe, customer-facing UI data.

The SDK exposes tool calls and their outputs as separate items. This module
joins them by call id and deliberately returns plain dictionaries so the UI
never needs to render or understand raw SDK objects.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from messages import format_money as _money


ACTION_TOOLS = {"issue_refund", "send_express_replacement", "escalate_case", "request_return", "verify_identity", "send_password_reset"}
# search_policy is a lookup, not an action — it never changes customer or
# order state, so it stays out of ACTION_TOOLS (no action card), but it
# still needs to be a *known* tool so its calls survive extract_tool_events
# and show up in the collapsed "View agent activity" trace.
LOOKUP_TOOLS = {"get_order", "search_policy"}
KNOWN_TOOLS = {*LOOKUP_TOOLS, *ACTION_TOOLS}
_ORDER_ID_RE = re.compile(r"^[A-Z0-9-]{1,32}$")

_ICON_SVGS = {
    "replay": '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7.5A8 8 0 1 1 5.9 17"/><path d="M4 4v4h4"/><path d="M12 8.3v4l2.8 1.7"/></svg>',
    "local_shipping": '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3 6.5h10v9H3zM13 10h4l3 3v2.5h-7z"/><path d="M6.5 18.5a1.75 1.75 0 1 0 0-3.5 1.75 1.75 0 0 0 0 3.5ZM17.5 18.5a1.75 1.75 0 1 0 0-3.5 1.75 1.75 0 0 0 0 3.5Z"/></svg>',
    "support_agent": '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="8" r="3.2"/><path d="M5.5 19.5c.7-3.2 2.9-5 6.5-5s5.8 1.8 6.5 5M4.5 11.5v2.2a2 2 0 0 0 2 2h1M19.5 11.5v2.2a2 2 0 0 1-2 2h-1M4.5 11.5a7.5 7.5 0 0 1 15 0"/></svg>',
    "person_search": '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="10" cy="8" r="3"/><path d="M4.5 18c.6-2.8 2.4-4.3 5.5-4.3 1.3 0 2.4.3 3.3.8M16 15.2l3.5 3.5M15 13.8a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z"/></svg>',
    "package_2": '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m4 7 8-4 8 4-8 4-8-4Z"/><path d="M4 7v10l8 4 8-4V7M12 11v10M8 5l8 4"/></svg>',
    "error_outline": '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5M12 16.2v.3"/></svg>',
    "check": '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="m8 12.2 2.6 2.6 5.6-5.8"/></svg>',
}


def icon_svg(name: str) -> str:
    """Return a bundled icon; no font or external asset is required."""
    return _ICON_SVGS.get(name, _ICON_SVGS["check"])


def _raw_value(raw_item: Any, name: str) -> Any:
    if isinstance(raw_item, dict):
        return raw_item.get(name)
    return getattr(raw_item, name, None)


def _parse_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _safe_arguments(raw_arguments: Any) -> dict[str, str]:
    parsed = _parse_dict(raw_arguments) or {}
    safe: dict[str, str] = {}

    if isinstance(parsed.get("order_id"), str):
        order_id = parsed["order_id"].strip().upper()
        if _ORDER_ID_RE.match(order_id):
            safe["order_id"] = order_id

    # Reasons are customer-safe tool inputs, but still constrain their size
    # and whitespace before they reach the optional developer trace.
    if isinstance(parsed.get("reason"), str):
        reason = " ".join(parsed["reason"].split())[:120]
        if reason:
            safe["reason"] = reason

    return safe


def _reason_text(reason: Any) -> str:
    return str(reason or "").strip().lower()


def _card_body(output: dict[str, Any], default: str) -> str:
    """Prefer the centralized customer_message (see messages.py) for a
    failure/review card's body; fall back to `default` only if a result
    somehow has none (hand-built fixtures, or a tool not yet wired in)."""
    message = output.get("customer_message")
    return message if isinstance(message, str) and message.strip() else default


def _success_card_body(output: dict[str, Any], default: str) -> str:
    """For a success card, `next_step` ("what happens next") is more
    useful than repeating customer_message ("what happened"), since the
    card's title already announces success — but fall back to
    customer_message, then `default`, if no next_step exists for this
    outcome."""
    next_step = output.get("next_step")
    if isinstance(next_step, str) and next_step.strip():
        return next_step
    message = output.get("customer_message")
    return message if isinstance(message, str) and message.strip() else default


def _summary(tool: str, output: dict[str, Any] | None, arguments: dict[str, str]) -> str:
    if output is None:
        return "No result was returned"

    # customer_message (see messages.py) is the single centralized source
    # for what happened, in neutral customer-safe language — the trace
    # reuses it directly instead of composing its own separate wording, so
    # the collapsed activity trace and the agent's actual reply can never
    # drift into saying different things about the same tool result.
    customer_message = output.get("customer_message")
    if isinstance(customer_message, str) and customer_message.strip():
        return customer_message

    # Fallback only for a result that somehow has no customer_message
    # (e.g. hand-built test fixtures, or a future tool not yet wired into
    # messages.py) — never raw internal reason codes.
    success = bool(output.get("success"))
    return f"{tool} completed" if success else f"{tool} did not complete"


def _event_for_call(call: dict[str, Any], output: dict[str, Any] | None) -> dict[str, Any]:
    tool = call["tool"]
    arguments = call["arguments"]
    success = None if output is None or "success" not in output else bool(output["success"])
    return {
        "tool": tool,
        "arguments": arguments,
        "success": success,
        "output": output or {},
        "summary": _summary(tool, output, arguments),
        "kind": "action" if tool in ACTION_TOOLS else "lookup",
    }


def extract_tool_events(result: Any) -> list[dict[str, Any]]:
    """Extract the actual chronological tool activity from one SDK result."""
    calls_by_id: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []

    for item in getattr(result, "new_items", []) or []:
        item_type = getattr(item, "type", None)
        raw_item = getattr(item, "raw_item", None)

        if item_type == "tool_call_item":
            tool = getattr(item, "tool_name", None) or _raw_value(raw_item, "name")
            if tool not in KNOWN_TOOLS:
                continue
            call_id = getattr(item, "call_id", None) or _raw_value(raw_item, "call_id")
            raw_arguments = _raw_value(raw_item, "arguments")
            call = {"tool": tool, "arguments": _safe_arguments(raw_arguments), "output": None}
            calls_by_id[call_id] = call
            order.append(call_id)

        elif item_type == "tool_call_output_item":
            call_id = getattr(item, "call_id", None) or _raw_value(raw_item, "call_id")
            if call_id in calls_by_id:
                calls_by_id[call_id]["output"] = _parse_dict(getattr(item, "output", None))

    return [_event_for_call(calls_by_id[call_id], calls_by_id[call_id]["output"]) for call_id in order]


def _failure_card(event: dict[str, Any]) -> dict[str, Any]:
    output = event.get("output", {})
    reason = _reason_text(output.get("reason"))
    tool = event["tool"]

    if tool == "issue_refund" and (
        output.get("status") == "requires_review"
        or reason in {"collector_edition_requires_review", "exceeds_autonomous_refund_limit"}
    ):
        return {
            "state": "review",
            "icon": "person_search",
            "title": "Refund requires review",
            "body": _card_body(output, "This order needs a specialist to approve the refund."),
        }

    if tool == "request_return" and output.get("status") == "requires_review":
        return {
            "state": "review",
            "icon": "person_search",
            "title": "Return requires review",
            "body": _card_body(output, "This return needs a specialist to approve it."),
        }

    if tool == "send_express_replacement" and reason in {
        "express_replacement_unavailable",
        "collector_edition_requires_review",
        "digital_item_not_shippable",
    }:
        return {
            "state": "blocked",
            "icon": "package_2",
            "title": "Replacement unavailable",
            "body": _card_body(output, "We weren’t able to arrange the replacement through the current service."),
        }

    if tool == "verify_identity":
        return {
            "state": "blocked",
            "icon": "person_search",
            "title": "Identity not verified",
            "body": _card_body(output, "We couldn’t confirm the account from that information."),
        }

    if tool == "send_password_reset" and reason == "identity_verification_required":
        return {
            "state": "blocked",
            "icon": "person_search",
            "title": "Verification required",
            "body": _card_body(output, "We need to verify the account before a reset link can be sent."),
        }

    return {
        "state": "failed",
        "icon": "error_outline",
        "title": "Unable to complete the action",
        "body": _card_body(output, "The action could not be completed. Please try again or continue with the next available support option."),
    }


def derive_action_cards(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build cards strictly from successful or failed action-tool results."""
    cards: list[dict[str, Any]] = []
    for event in events:
        if event.get("kind") != "action" or event.get("success") is None:
            continue
        if not event.get("success"):
            cards.append(_failure_card(event))
            continue

        tool = event["tool"]
        output = event.get("output", {})
        if tool == "issue_refund":
            cards.append({
                "state": "success",
                "icon": "replay",
                "title": "Refund processed",
                "body": _success_card_body(output, "Original payment method"),
                "value": _money(output.get("amount"), output.get("currency")),
            })
        elif tool == "send_express_replacement":
            eta = output.get("eta")
            default_body = f"Express delivery · Expected {eta}" if eta else "Express delivery"
            cards.append({
                "state": "success",
                "icon": "local_shipping",
                "title": "Replacement arranged",
                "body": _success_card_body(output, default_body),
            })
        elif tool == "escalate_case":
            cards.append({
                "state": "success",
                "icon": "support_agent",
                "title": "Case sent for review",
                "body": _success_card_body(output, "A Bookly specialist will review this order."),
            })
        elif tool == "request_return":
            cards.append({
                "state": "success",
                "icon": "replay",
                "title": "Return request created",
                "body": _success_card_body(output, "Return instructions will be provided."),
            })
        elif tool == "verify_identity":
            cards.append({
                "state": "success",
                "icon": "person_search",
                "title": "Identity verified",
                "body": _success_card_body(output, "Confirmed using the account details provided."),
            })
        elif tool == "send_password_reset":
            cards.append({
                "state": "success",
                "icon": "support_agent",
                "title": "Reset link sent",
                "body": _success_card_body(output, "Use the link from Bookly to recover access."),
            })
    return cards


def trace_line(event: dict[str, Any]) -> tuple[str, str]:
    """Return safe display lines for the optional collapsed activity trace."""
    args = event.get("arguments") or {}
    parts = []
    for key in ("order_id", "reason"):
        if key in args:
            value = html.escape(str(args[key]), quote=True)
            parts.append(f"{key}={value}")
    call = f"{event['tool']}({', '.join(parts)})"
    marker = "✓" if event.get("success") is True else ("×" if event.get("success") is False else "•")
    return call, f"{marker} {event.get('summary', 'Result unavailable')}"
