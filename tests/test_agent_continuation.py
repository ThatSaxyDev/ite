import unittest
from pathlib import Path

from ite.agent.agent import Agent
from ite.agent.events import AgentEventType
from ite.client.response import StreamEvent, StreamEventType, TextDelta, TokenUsage
from ite.config.config import Config


class AgentContinuationTests(unittest.IsolatedAsyncioTestCase):
    def test_incomplete_response_heuristic_requires_heading_like_colon_line(self) -> None:
        agent = Agent(Config(cwd=Path("/tmp"), api_key="test"))

        self.assertTrue(agent._looks_incomplete_response("What You Need to Do:"))
        self.assertFalse(
            agent._looks_incomplete_response(
                "The root cause is the continuation heuristic repeating the same content:"
            )
        )

    def test_scored_continuation_policy_retries_on_truncation_but_not_conclusive_answer(self) -> None:
        agent = Agent(Config(cwd=Path("/tmp"), api_key="test"))

        should_retry, _reason, score = agent._should_retry_incomplete_response(
            text="What You Need to Do:",
            finish_reason="stop",
            retry_count=0,
            has_tool_calls=False,
            user_message="Explain what to do next.",
        )
        self.assertTrue(should_retry)
        self.assertGreaterEqual(score, 2)

        should_retry, _reason, score = agent._should_retry_incomplete_response(
            text="The safest path is to ship BYOK first. That should get you to production cleanly.",
            finish_reason="stop",
            retry_count=0,
            has_tool_calls=False,
            user_message="Explain what to ship.",
        )
        self.assertFalse(should_retry)
        self.assertLess(score, 2)

    def test_scored_continuation_policy_honors_single_retry_cap(self) -> None:
        agent = Agent(Config(cwd=Path("/tmp"), api_key="test"))

        should_retry, reason, score = agent._should_retry_incomplete_response(
            text="What You Need to Do:",
            finish_reason="length",
            retry_count=1,
            has_tool_calls=False,
            user_message="Explain what to do next.",
        )
        self.assertFalse(should_retry)
        self.assertEqual(reason, "retry cap reached")
        self.assertEqual(score, 0)

    async def test_incomplete_structured_response_continues_without_user_retry(self) -> None:
        agent = Agent(Config(cwd=Path("/tmp"), api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        call_count = 0

        async def fake_chat_completion(messages, tools=None, stream=True, visual_budget=None):
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

    async def test_incomplete_response_merge_does_not_duplicate_restarted_content(self) -> None:
        agent = Agent(Config(cwd=Path("/tmp"), api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        call_count = 0

        async def fake_chat_completion(messages, tools=None, stream=True, visual_budget=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta(
                        "Current Setup\n\nYou have two modes:\n1. direct\n2. ollama\n\nWhat You Need to Do:"
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
                    "Current Setup\n\nYou have two modes:\n1. direct\n2. ollama\n\nWhat You Need to Do:\n1. Set production env vars.\n2. Deploy the API."
                ),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        agent.session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]

        events = []
        async for event in agent.run("Explain the launch steps."):
            events.append(event)

        completed = [
            str(event.data.get("content", ""))
            for event in events
            if event.type == AgentEventType.TEXT_COMPLETE
        ]

        self.assertEqual(call_count, 2)
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].count("Current Setup"), 1)
        self.assertIn("Set production env vars.", completed[0])

    async def test_conclusive_answer_does_not_auto_retry_even_when_finish_reason_is_stop(self) -> None:
        agent = Agent(Config(cwd=Path("/tmp"), api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        call_count = 0

        async def fake_chat_completion(messages, tools=None, stream=True, visual_budget=None):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise AssertionError("Conclusive answer should not auto-retry.")
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(
                    "Ship the BYOK-first cut. Hosted auth plus /setup is enough for launch, and that should get you to production cleanly."
                ),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                finish_reason="stop",
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        agent.session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]

        events = []
        async for event in agent.run("What should we ship first?"):
            events.append(event)

        completed = [
            str(event.data.get("content", ""))
            for event in events
            if event.type == AgentEventType.TEXT_COMPLETE
        ]

        self.assertEqual(call_count, 1)
        self.assertEqual(len(completed), 1)
        self.assertIn("BYOK-first", completed[0])

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

        async def fake_chat_completion(messages, tools=None, stream=True, visual_budget=None):
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
