"""Unit tests for the static agent configuration built in agent.py.

Importing `agent` constructs the Agent object (tool list, model_settings,
instructions) but makes no network call and needs no OPENAI_API_KEY —
Agent() is just configuration. These tests inspect that configuration
only. They never call Runner.run() and never touch the network; live
behaviour is covered separately by manual smoke checks (see agent.py's
module docstring / the Step 12 report), not by this file.
"""

import hashlib
import unittest

from agent import agent
from prompts import BASELINE_PROMPT, THESIS_PROMPT

# Recorded the first time evals/run_evals.py ran against the untouched
# Step 9 BASELINE_PROMPT (evals/results/history.csv, label "baseline",
# prompt_hash column — same hashlib.sha256(...).hexdigest()[:12] scheme
# as run_evals.py's own prompt_fingerprint()). Using the value the repo
# already recorded rather than re-hardcoding the full prompt string here.
RECORDED_BASELINE_PROMPT_HASH = "b73879d92c6c"

EXPECTED_TOOL_NAMES = {
    "get_order",
    "send_express_replacement",
    "issue_refund",
    "escalate_case",
}


class RegisteredToolsTests(unittest.TestCase):
    def test_exactly_the_four_expected_tools_are_registered(self):
        names = [t.name for t in agent.tools]
        self.assertEqual(set(names), EXPECTED_TOOL_NAMES)

    def test_no_tool_is_registered_twice(self):
        names = [t.name for t in agent.tools]
        self.assertEqual(len(names), len(set(names)), f"duplicate tool registration: {names}")

    def test_no_unexpected_fifth_tool(self):
        self.assertEqual(len(agent.tools), 4)


class ToolChoiceTests(unittest.TestCase):
    def test_tool_choice_is_auto(self):
        self.assertEqual(agent.model_settings.tool_choice, "auto")


class ToolSchemaTests(unittest.TestCase):
    def _schema_for(self, name):
        matches = [t for t in agent.tools if t.name == name]
        self.assertEqual(len(matches), 1, f"expected exactly one tool named {name}")
        return matches[0].params_json_schema

    def test_get_order_requires_order_id(self):
        required = set(self._schema_for("get_order").get("required", []))
        self.assertIn("order_id", required)

    def test_send_express_replacement_requires_order_id(self):
        required = set(self._schema_for("send_express_replacement").get("required", []))
        self.assertIn("order_id", required)

    def test_issue_refund_requires_order_id_and_reason(self):
        required = set(self._schema_for("issue_refund").get("required", []))
        self.assertTrue({"order_id", "reason"}.issubset(required))

    def test_escalate_case_requires_order_id_and_reason(self):
        required = set(self._schema_for("escalate_case").get("required", []))
        self.assertTrue({"order_id", "reason"}.issubset(required))


class ToolDescriptionTests(unittest.TestCase):
    def test_every_registered_tool_has_a_non_empty_description(self):
        for tool in agent.tools:
            with self.subTest(tool=tool.name):
                self.assertTrue(tool.description)
                self.assertTrue(tool.description.strip())


class PromptPreservationTests(unittest.TestCase):
    def test_thesis_prompt_includes_the_tool_use_section(self):
        self.assertIn("# Tool use", THESIS_PROMPT)
        self.assertIn("get_order", THESIS_PROMPT)

    def test_baseline_prompt_matches_the_recorded_fingerprint(self):
        # Uses the fingerprint the repo already recorded (see
        # RECORDED_BASELINE_PROMPT_HASH above) rather than a second
        # hardcoded copy of the full prompt string.
        actual_hash = hashlib.sha256(BASELINE_PROMPT.encode()).hexdigest()[:12]
        self.assertEqual(actual_hash, RECORDED_BASELINE_PROMPT_HASH)

    def test_baseline_prompt_has_no_step_12_additions(self):
        self.assertNotIn("# Tool use", BASELINE_PROMPT)
        self.assertNotIn("# CX thesis", BASELINE_PROMPT)
        self.assertNotIn("# Operational policy", BASELINE_PROMPT)

    def test_baseline_and_thesis_prompts_are_distinct(self):
        self.assertNotEqual(BASELINE_PROMPT, THESIS_PROMPT)


if __name__ == "__main__":
    unittest.main()
