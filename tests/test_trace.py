"""Unit tests for ui/trace.py.

Tool call/output items are constructed by hand with SimpleNamespace, the
same lightweight pattern tests/test_evals.py uses to stand in for the
Agents SDK's ToolCallItem/ToolCallOutputItem — no SDK runtime or network
call involved.
"""

import unittest
from types import SimpleNamespace

import tools
from ui.trace import derive_action_cards, extract_tool_events, trace_line


def _call_item(call_id: str, tool: str, arguments: str):
    return SimpleNamespace(
        type="tool_call_item",
        tool_name=tool,
        call_id=call_id,
        raw_item={"call_id": call_id, "arguments": arguments},
    )


def _output_item(call_id: str, output: dict):
    return SimpleNamespace(
        type="tool_call_output_item",
        call_id=call_id,
        raw_item={"call_id": call_id},
        output=output,
    )


class SearchPolicyTraceTests(unittest.TestCase):
    def test_successful_search_policy_call_is_not_dropped(self):
        # Regression test: search_policy used to be missing from
        # KNOWN_TOOLS, so extract_tool_events silently discarded it before
        # _summary() ever ran, and it never appeared in "View agent
        # activity". This confirms that gap is closed.
        result = SimpleNamespace(new_items=[
            _call_item("c1", "search_policy", '{"query": "What shipping options do you offer?"}'),
            _output_item("c1", {
                "success": True,
                "reason": None,
                "query": "What shipping options do you offer?",
                "matches": [{"topic": "shipping", "content": {}, "source": "Bookly shipping policy"}],
            }),
        ])

        events = extract_tool_events(result)

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["tool"], "search_policy")
        self.assertTrue(event["success"])
        self.assertEqual(event["kind"], "lookup")

    def test_successful_search_policy_summary_names_the_matched_topic(self):
        # Uses the real tool output (not a hand-built fixture) so this test
        # can't silently drift from what search_policy actually returns —
        # the summary now comes straight from the centralized
        # customer_message (messages.py), not trace.py's own composition.
        real_output = tools.search_policy("shipping")
        result = SimpleNamespace(new_items=[
            _call_item("c1", "search_policy", '{"query": "shipping"}'),
            _output_item("c1", real_output),
        ])

        event = extract_tool_events(result)[0]

        self.assertIn("shipping", event["summary"])
        self.assertEqual(event["summary"], real_output["customer_message"])

    def test_unmatched_search_policy_summary_reports_not_found(self):
        real_output = tools.search_policy("do you sell concert tickets")
        result = SimpleNamespace(new_items=[
            _call_item("c1", "search_policy", '{"query": "do you sell concert tickets"}'),
            _output_item("c1", real_output),
        ])

        event = extract_tool_events(result)[0]

        self.assertFalse(event["success"])
        self.assertEqual(event["summary"], real_output["customer_message"])
        self.assertNotIn("policy_not_found", event["summary"])

    def test_search_policy_never_produces_an_action_card(self):
        # search_policy is a lookup, not an action — it must never get a
        # customer-facing action card even though it's now a known tool.
        events = [{
            "tool": "search_policy",
            "arguments": {},
            "success": True,
            "output": {"success": True, "matches": [{"topic": "shipping"}]},
            "summary": "Policy information found (shipping)",
            "kind": "lookup",
        }]

        self.assertEqual(derive_action_cards(events), [])

    def test_search_policy_trace_line_reveals_no_raw_query_text(self):
        # The raw customer-typed query may contain anything the customer
        # typed (in principle including PII); the collapsed trace must
        # show only the tool name and the safe summary, never the query.
        events = [{
            "tool": "search_policy",
            "arguments": {},
            "success": True,
            "output": {"success": True, "matches": [{"topic": "shipping"}]},
            "summary": "Policy information found (shipping)",
            "kind": "lookup",
        }]

        call, result = trace_line(events[0])

        self.assertEqual(call, "search_policy()")
        self.assertIn("shipping", result)


class VerifyIdentityAndPasswordResetTraceTests(unittest.TestCase):
    def test_verify_identity_is_an_action_with_a_success_card(self):
        events = [{
            "tool": "verify_identity",
            "arguments": {},
            "success": True,
            "output": {"success": True, "customer_id": "C1001", "status": "identity_verified"},
            "summary": "Identity verified",
            "kind": "action",
        }]

        cards = derive_action_cards(events)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["state"], "success")

    def test_send_password_reset_failure_produces_a_blocked_card(self):
        events = [{
            "tool": "send_password_reset",
            "arguments": {},
            "success": False,
            "output": {"success": False, "status": "verification_required", "reason": "identity_verification_required"},
            "summary": "Identity verification required",
            "kind": "action",
        }]

        cards = derive_action_cards(events)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["state"], "blocked")


if __name__ == "__main__":
    unittest.main()
