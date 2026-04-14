import unittest
from pathlib import Path

from ite.agent.agent import Agent
from ite.agent.events import AgentEventType
from ite.client.response import StreamEvent, StreamEventType, TextDelta, TokenUsage
from ite.config.config import Config


class AgentContinuationTests(unittest.IsolatedAsyncioTestCase):
    async def test_incomplete_structured_response_continues_without_user_retry(self) -> None:
        agent = Agent(Config(cwd=Path("/tmp"), api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        call_count = 0

        async def fake_chat_completion(messages, tools=None, stream=True):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta(
                        "Gap Analysis Summary\n\nP0 - Must Fix:\n1. Missing continuation policy\n\nP1 - Should Fix:"
                    ),
                )
                yield StreamEvent(
                    type=StreamEventType.MESSAGE_COMPLETE,
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )
                return

            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(
                    "\n1. Add a completion-budget continuation heuristic.\n2. Avoid stopping on unfinished section headers."
                ),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        agent.session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]

        events = []
        async for event in agent.run("Investigate why the agent stops mid-task."):
            events.append(event)

        completed = [
            str(event.data.get("content", ""))
            for event in events
            if event.type == AgentEventType.TEXT_COMPLETE
        ]

        self.assertEqual(call_count, 2)
        self.assertEqual(len(completed), 1)
        self.assertIn("P1 - Should Fix:", completed[0])
        self.assertIn("completion-budget continuation heuristic", completed[0])

    async def test_read_only_repo_summary_does_not_continue_due_to_stale_execution_todos(self) -> None:
        agent = Agent(Config(cwd=Path("/tmp"), api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        agent.session.restore_todos_state(
            {
                "version": 1,
                "planning": [],
                "execution": [
                    {
                        "id": "todo-1",
                        "content": "Implement remaining widget cleanup",
                        "completed": False,
                        "created_at": "",
                        "updated_at": "",
                        "completed_at": None,
                    }
                ],
            }
        )

        call_count = 0

        async def fake_chat_completion(messages, tools=None, stream=True):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise AssertionError("Agent should not continue after a sufficient read-only summary.")
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(
                    "FOR_AGENT.md says this repo is in an active UI refinement phase and prefers direct implementation, tidy feature slices, and red-green validation with format and analyze before reporting back."
                ),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        agent.session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]

        events = []
        async for event in agent.run("Read FOR_AGENT.md and tell me what is in the codebase."):
            events.append(event)

        completed = [
            str(event.data.get("content", ""))
            for event in events
            if event.type == AgentEventType.TEXT_COMPLETE
        ]

        self.assertEqual(call_count, 1)
        self.assertEqual(len(completed), 1)
        self.assertIn("FOR_AGENT.md says", completed[0])
