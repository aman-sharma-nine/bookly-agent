import json
import re

from agents import Agent, ModelSettings, Runner, SQLiteSession, function_tool
from agents.usage import Usage

import tools as tools_module
from agent import agent as production_agent

ACTION_TOOLS = {"issue_refund", "send_express_replacement", "escalate_case"}
LOOKUP_TOOLS = {"get_order"}

_ORDER_ID_PATTERN = re.compile(r"\bB1\d{3}\b")


def make_get_order_wrapper(forced_express_replacement_available: bool):
    """Return a plain, directly-testable wrapper function for get_order
    that forces express_replacement_available to a fixed test value.
    Delegates to the real tools.get_order for everything else — never
    touches BOOKLY_DATA directly, so it inherits that function's
    immutability guarantee."""

    def get_order(order_id: str) -> dict:
        """Look up an order and its book context for the support agent.

        Eval-only wrapper: identical to the production tool except
        express_replacement_available is forced to a fixed test value, to
        exercise a scenario the real dataset doesn't currently contain.

        Args:
            order_id: The Bookly order ID, e.g. "B1001".

        Returns:
            Same shape as tools.get_order.
        """
        result = tools_module.get_order(order_id)
        if result.get("success"):
            result = dict(result)
            result["express_replacement_available"] = forced_express_replacement_available
            if not forced_express_replacement_available:
                result["express_replacement_eta"] = None
        return result

    return get_order


def make_send_express_replacement_wrapper(forced_result: dict):
    """Return a plain, directly-testable wrapper for send_express_replacement
    that returns a fixed test result instead of calling the real tool —
    never touches tools.py's state or BOOKLY_DATA at all."""

    def send_express_replacement(order_id: str) -> dict:
        """Simulate sending a free express replacement for a delayed order.

        Eval-only wrapper: returns a fixed test result instead of calling
        the real tool, to simulate a service failure the real (working)
        mock backend can't otherwise produce. Does not touch tools.py's
        real state.

        Args:
            order_id: The Bookly order ID, e.g. "B1001".

        Returns:
            The forced test result, with order_id filled in.
        """
        normalized_id = order_id.strip().upper()
        return {"success": False, "order_id": normalized_id, **{k: v for k, v in forced_result.items() if k != "order_id"}}

    return send_express_replacement


def make_issue_refund_wrapper(forced_result: dict):
    """Return a plain, directly-testable wrapper for issue_refund that
    returns a fixed test result instead of calling the real tool — still
    enforces the non-empty-reason requirement, matching the production
    contract, and never touches tools.py's state or BOOKLY_DATA."""

    def issue_refund(order_id: str, reason: str) -> dict:
        """Simulate issuing a refund for an order, subject to policy.

        Eval-only wrapper: returns a fixed test result instead of calling
        the real tool, to simulate a service failure. Still requires a
        non-empty reason, matching the production tool's contract, so the
        agent's tool-call arguments are graded the same way either way.

        Args:
            order_id: The Bookly order ID, e.g. "B1001".
            reason: A non-empty explanation for the refund request.

        Returns:
            The forced test result, with order_id filled in.
        """
        normalized_id = order_id.strip().upper()
        if not reason or not reason.strip():
            return {"success": False, "order_id": normalized_id, "reason": "reason_required", "status": "rejected"}
        return {"success": False, "order_id": normalized_id, **{k: v for k, v in forced_result.items() if k != "order_id"}}

    return issue_refund


def build_eval_agent(case: dict, model: str | None = None, model_settings: ModelSettings | None = None) -> Agent:
    """Return an Agent to run this case against.

    Same model + instructions as production `agent` in every case, unless
    overridden (see below). Tools are the real production *_tool objects
    unless this case's available_context["override"] calls for one to be
    wrapped — in which case a fresh FunctionTool is built from a wrapper
    function that has the same name as the original (so the schema the
    model sees, and the tool name graders match against, are unchanged)
    and delegates to the real tools.py function for everything except the
    overridden result.

    Args:
        case: The eval case dict.
        model: model-comparison hook. When given, the returned Agent uses
            this model instead of production's — a fresh clone, never
            agent.py's own `agent` object, so the production agent is
            never mutated by a comparison run. None (default) preserves
            every other call site's exact prior behavior.
        model_settings: Paired with `model` — e.g. ModelSettings(tool_choice="auto",
            reasoning=Reasoning(effort="medium")) for a reasoning-effort
            comparison. None (default) falls back to the same
            ModelSettings(tool_choice="auto") every case already used.
    """
    override = case.get("available_context", {}).get("override", {})
    needs_clone = bool(override) or model is not None or model_settings is not None
    if not needs_clone:
        return production_agent

    tools = [
        tools_module.get_order_tool,
        tools_module.send_express_replacement_tool,
        tools_module.issue_refund_tool,
        tools_module.escalate_case_tool,
    ]

    if "express_replacement_available" in override:
        tools[0] = function_tool(make_get_order_wrapper(override["express_replacement_available"]))

    if "send_express_replacement_result" in override:
        tools[1] = function_tool(make_send_express_replacement_wrapper(override["send_express_replacement_result"]))

    if "issue_refund_result" in override:
        tools[2] = function_tool(make_issue_refund_wrapper(override["issue_refund_result"]))

    return Agent(
        name=production_agent.name,
        instructions=production_agent.instructions,
        model=model or production_agent.model,
        tools=tools,
        model_settings=model_settings or ModelSettings(tool_choice="auto"),
    )


def needs_context_injection(conversation: list, available_context: dict) -> str | None:
    """Return an eval-only context message to send before the scored
    conversation, or None if the conversation already supplies an order ID.

    Several cases (J2-01, J2-03, J2-08) describe an order in
    available_context that the customer's actual message never states
    explicitly — real customers do sometimes just say "refund me" with an
    order already on file/selected in a UI the demo doesn't have, and the
    hero-journey design assumes that context can exist. Rather than
    rewriting those cases' conversation text (which would drift them from
    the eval suite's design), a single evaluation-only message is sent
    first, clearly labeled as evaluation context, giving the agent the order ID
    the way a real UI's "current order" context would. This message is
    never sent in production — it only exists inside this harness.
    """
    if any(_ORDER_ID_PATTERN.search(turn) for turn in conversation):
        return None
    orders = available_context.get("orders")
    if not orders:
        return None
    return f"Evaluation context: the current order for this test is {orders[0]}."


def _extract_tool_calls(result, turn_index: int) -> list:
    """Pull structured tool-call records out of one Runner.run() result,
    pairing each ToolCallItem with its ToolCallOutputItem by call_id.
    Safe against malformed/unparseable arguments — a parse failure is
    recorded as a distinct record rather than raising, so one bad tool
    call doesn't crash the whole eval run.
    """
    calls_by_id = {}
    order = []
    for item in result.new_items:
        item_type = getattr(item, "type", None)
        if item_type == "tool_call_item":
            raw_item = item.raw_item
            call_id = getattr(item, "call_id", None) or (raw_item.get("call_id") if isinstance(raw_item, dict) else None)
            args_raw = raw_item.get("arguments") if isinstance(raw_item, dict) else getattr(raw_item, "arguments", None)
            tool_name = item.tool_name

            malformed = False
            args = None
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                if not isinstance(args, dict):
                    malformed = True
                    args = None
            except (TypeError, ValueError):
                malformed = True

            record = {
                "turn": turn_index,
                "tool": tool_name,
                "call_id": call_id,
                "args": args,
                "raw_arguments": args_raw,
                "malformed_arguments": malformed,
                "output": None,
                "success": None,
                "kind": "action" if tool_name in ACTION_TOOLS else ("lookup" if tool_name in LOOKUP_TOOLS else "unknown"),
            }
            calls_by_id[call_id] = record
            order.append(call_id)
        elif item_type == "tool_call_output_item":
            raw_item = item.raw_item
            call_id = getattr(item, "call_id", None) or (raw_item.get("call_id") if isinstance(raw_item, dict) else None)
            if call_id in calls_by_id:
                output = item.output
                calls_by_id[call_id]["output"] = output
                if isinstance(output, dict):
                    calls_by_id[call_id]["success"] = bool(output.get("success"))

    return [calls_by_id[cid] for cid in order]


def _usage_dict(usage) -> dict:
    return {
        "requests": usage.requests,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


async def run_conversation(eval_agent: Agent, case: dict, session_id: str) -> dict:
    """Run one case's conversation (with any needed eval-only context
    message prepended) on a fresh SQLiteSession, and return the full trace:
    per-turn user/assistant text plus every tool call/output across the
    whole conversation, each tagged with the turn it happened on, plus
    token usage totaled across every Runner.run call in the conversation
    (context_wrapper.usage is per-call, not cumulative across separate
    Runner.run calls sharing a session, so it's summed here explicitly).
    """
    conversation = case["conversation"]
    context_message = needs_context_injection(conversation, case.get("available_context", {}))

    session = SQLiteSession(session_id)
    turns = []
    tool_calls = []
    total_usage = Usage()
    try:
        if context_message:
            ctx_result = await Runner.run(eval_agent, context_message, session=session)
            total_usage.add(ctx_result.context_wrapper.usage)

        for turn_index, user_message in enumerate(conversation):
            result = await Runner.run(eval_agent, user_message, session=session)
            total_usage.add(result.context_wrapper.usage)
            turns.append({
                "turn": turn_index,
                "user": user_message,
                "assistant": result.final_output,
            })
            tool_calls.extend(_extract_tool_calls(result, turn_index))
    finally:
        session.close()

    return {
        "case_id": case["case_id"],
        "context_message": context_message,
        "turns": turns,
        "tool_calls": tool_calls,
        "usage": _usage_dict(total_usage),
    }


async def run_conversation_with_context(eval_agent: Agent, conversation: list, context_message: str, session_id: str) -> dict:
    """Like run_conversation, but the context message is given explicitly
    rather than derived from the case — used for J2-03's two forced-context
    sub-runs (same conversation text, two different current-order contexts).
    """
    session = SQLiteSession(session_id)
    turns = []
    tool_calls = []
    total_usage = Usage()
    try:
        if context_message:
            ctx_result = await Runner.run(eval_agent, context_message, session=session)
            total_usage.add(ctx_result.context_wrapper.usage)
        for turn_index, user_message in enumerate(conversation):
            result = await Runner.run(eval_agent, user_message, session=session)
            total_usage.add(result.context_wrapper.usage)
            turns.append({
                "turn": turn_index,
                "user": user_message,
                "assistant": result.final_output,
            })
            tool_calls.extend(_extract_tool_calls(result, turn_index))
    finally:
        session.close()

    return {"context_message": context_message, "turns": turns, "tool_calls": tool_calls, "usage": _usage_dict(total_usage)}
