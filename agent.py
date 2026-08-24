from dotenv import load_dotenv
from agents import Agent, ModelSettings, Runner, SQLiteSession
import asyncio
from openai.types.shared import Reasoning

from prompts import THESIS_PROMPT
from tools import (
    escalate_case_tool,
    get_order_tool,
    issue_refund_tool,
    request_return_tool,
    search_policy_tool,
    send_password_reset_tool,
    send_express_replacement_tool,
    verify_identity_tool,
)


load_dotenv()

agent = Agent(
    name="Bookly Agent",
    instructions=THESIS_PROMPT,
    model="gpt-5.6",
    tools=[
        get_order_tool,
        send_express_replacement_tool,
        issue_refund_tool,
        escalate_case_tool,
        request_return_tool,
        search_policy_tool,
        verify_identity_tool,
        send_password_reset_tool,
    ],
    model_settings=ModelSettings(
    tool_choice="auto",
    reasoning=Reasoning(effort="low"),
),
    )


def create_session(session_id: str = "bookly-demo") -> SQLiteSession:
    """Start one fresh, in-memory conversation.

    One SQLiteSession is one customer conversation — every turn in that
    conversation must reuse this same object (pass it to run_turn/
    Runner.run again), never create a new session per message. db_path
    defaults to ":memory:", so this session's history lives only for the
    lifetime of this Python process; it does not persist across restarts,
    and a fresh session_id (or a new process) starts with no prior turns.

    What this session is NOT, and does not become by existing: it does
    not authenticate the customer, does not enforce order ownership (any
    session can still ask get_order for any order_id — that gap is
    unchanged and still deferred, see tools.py), does not replace
    BOOKLY_DATA as the source of order facts, and does not create any
    long-term/cross-conversation customer memory — it is turn-to-turn
    memory for one conversation only. Not production-grade memory; for a
    real server-backed product, see OpenAI's Conversations API
    (https://developers.openai.com/api/reference/python/resources/conversations/methods/create),
    which is out of scope for this local demo.
    """
    return SQLiteSession(session_id)


async def run_turn(message: str, session: SQLiteSession):
    """Run one conversational turn, letting the SDK session supply history.

    Only the new user message is sent — the session (not a manually
    rebuilt history list) is what gives the model the prior turns.
    """
    return await Runner.run(
        agent,
        message,
        session=session,
    )


async def main() -> None:
    session = create_session("manual-demo")

    try:
        for message in [
            "My book hasn't arrived.",
            "B1001.",
            "It's my daughter's birthday tomorrow.",
        ]:
            print(f"\nCustomer: {message}")
            result = await run_turn(message, session)
            print(f"Bookly: {result.final_output}")
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())

