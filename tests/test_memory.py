"""Offline tests for the session plumbing (agents.SQLiteSession).

These test the deterministic session storage mechanism itself — item
persistence, isolation between sessions — not model memory behaviour.
No OpenAI API call happens anywhere in this file. Live three-turn memory
behaviour (does the model actually use what the session hands it) is a
separate manual smoke test, not an offline unit test.
"""

import unittest
from unittest.mock import AsyncMock, patch

from agents import SQLiteSession


class SQLiteSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_session_retains_items(self):
        session = SQLiteSession("test-session")

        try:
            await session.add_items([
                {
                    "role": "user",
                    "content": "My book hasn't arrived.",
                },
                {
                    "role": "assistant",
                    "content": "What is your order number?",
                },
            ])

            items = await session.get_items()

            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["role"], "user")
            self.assertEqual(items[1]["role"], "assistant")
        finally:
            session.close()

    async def test_sessions_are_isolated(self):
        first = SQLiteSession("first-session")
        second = SQLiteSession("second-session")

        try:
            await first.add_items([
                {
                    "role": "user",
                    "content": "Private conversation one",
                },
            ])

            first_items = await first.get_items()
            second_items = await second.get_items()

            self.assertEqual(len(first_items), 1)
            self.assertEqual(second_items, [])
        finally:
            first.close()
            second.close()


class CreateSessionHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_session_returns_a_fresh_empty_sqlite_session(self):
        from agent import create_session

        session = create_session("helper-test-session")
        try:
            self.assertIsInstance(session, SQLiteSession)
            items = await session.get_items()
            self.assertEqual(items, [])
        finally:
            session.close()

    async def test_create_session_default_id_still_starts_empty(self):
        # A distinct default session_id from other tests' fixed ids, so
        # this doesn't collide with a session another test left items in
        # (each test still gets its own in-memory SQLiteSession instance
        # regardless of session_id — session_id namespaces rows within
        # one db_path, and every SQLiteSession() call here uses the
        # default in-memory db_path, which is not shared across
        # instances).
        from agent import create_session

        session = create_session()
        try:
            items = await session.get_items()
            self.assertEqual(items, [])
        finally:
            session.close()


class RunTurnPassesSessionTests(unittest.IsolatedAsyncioTestCase):
    """Confirms run_turn() forwards the same session object to
    Runner.run() — mocked, no network call, no API key required."""

    async def test_run_turn_calls_runner_run_with_the_given_session(self):
        import agent as agent_module

        session = SQLiteSession("plumbing-test-session")
        try:
            fake_result = object()
            with patch.object(agent_module.Runner, "run", new=AsyncMock(return_value=fake_result)) as mock_run:
                result = await agent_module.run_turn("B1001.", session)

            mock_run.assert_awaited_once_with(
                agent_module.agent,
                "B1001.",
                session=session,
            )
            self.assertIs(result, fake_result)
        finally:
            session.close()

    async def test_run_turn_does_not_manually_rebuild_history(self):
        # run_turn's contract is "send only the new message, let the
        # session supply history" — assert the message argument is the
        # literal string passed in, not a list (which is what a manual
        # `to_input_list()`-based history rebuild would look like).
        import agent as agent_module

        session = SQLiteSession("plumbing-test-session-2")
        try:
            with patch.object(agent_module.Runner, "run", new=AsyncMock(return_value=object())) as mock_run:
                await agent_module.run_turn("It's my daughter's birthday tomorrow.", session)

            _, args, kwargs = mock_run.mock_calls[0]
            message_arg = args[1]
            self.assertIsInstance(message_arg, str)
            self.assertEqual(message_arg, "It's my daughter's birthday tomorrow.")
            self.assertEqual(kwargs["session"], session)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
