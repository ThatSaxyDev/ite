import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from ite.agent.agent import Agent
from ite.agent.events import AgentEventType
from ite.client.response import StreamEvent, StreamEventType, TextDelta, TokenUsage
from ite.commands import CommandContext
from ite.commands.session import cmd_save
from ite.config.config import Config


class _DummyTUI:
    pass


class MemoryLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_path = Path(self.temp_dir.name)
        patcher = patch("ite.memory.manager.get_data_dir", return_value=self.base_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_cmd_save_records_workspace_scoped_episode(self) -> None:
        workspace = self.base_path / "ws-save"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        agent.session.context_manager.add_user_message("hello")
        agent.session.turn_count = 1

        ctx = CommandContext(
            config=agent.config,
            agent=agent,
            tui=_DummyTUI(),
            console=Console(file=StringIO()),
        )

        with patch("ite.agent.session_manager.get_data_dir", return_value=self.base_path):
            await cmd_save(ctx, [])

        episodes = agent.session.memory_manager.list_episodes()
        self.assertTrue(any("Session saved (1 turns): hello" in ep["summary"] for ep in episodes))

    async def test_session_initialize_is_not_degraded_when_dependencies_are_available(self) -> None:
        workspace = self.base_path / "ws-healthy-startup"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        self.assertFalse(agent.session.is_degraded())
        self.assertEqual(agent.session.runtime_status.disabled_capabilities, [])
        self.assertEqual(agent.session.runtime_summary(), "")

    async def test_context_compaction_records_episode(self) -> None:
        workspace = self.base_path / "ws-compact"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(8):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        session.client.chat_completion = self._fake_chat_completion  # type: ignore[method-assign]

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\nkeep going", TokenUsage(total_tokens=10)

        session.chat_compactor.compact = fake_compact  # type: ignore[method-assign]
        session.context_manager.needs_compression = lambda: True  # type: ignore[method-assign]

        events = []
        async for event in agent.run("trigger compaction"):
            events.append(event.type)

        self.assertIn(AgentEventType.CONTEXT_COMPACTED, events)
        episodes = session.memory_manager.list_episodes()
        self.assertTrue(
            any(
                "Context compacted after" in ep["summary"]
                and "trigger compaction" in ep["summary"]
                for ep in episodes
            )
        )

    async def test_context_overflow_retries_after_compaction(self) -> None:
        workspace = self.base_path / "ws-overflow-retry"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        for idx in range(8):
            session.context_manager.add_user_message(f"user message {idx}")
            session.context_manager.add_assistant_message(f"assistant message {idx}")

        call_count = 0

        async def fake_chat_completion(messages, tools=None, stream=True):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=(
                        "The model provider returned an API error.\n"
                        "- Status: 400\n"
                        "- prompt too long; exceeded max context length by 1397 tokens"
                    ),
                )
                return
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Recovered."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def fake_compact(_context_manager):
            return "## ORIGINAL GOAL\ncontinue", TokenUsage(total_tokens=10)

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]
        session.chat_compactor.compact = fake_compact  # type: ignore[method-assign]

        events = []
        async for event in agent.run("trigger overflow retry"):
            events.append(event.type)

        self.assertEqual(call_count, 2)
        self.assertIn(AgentEventType.CONTEXT_COMPACTED, events)
        self.assertIn(AgentEventType.TEXT_COMPLETE, events)

    async def test_low_value_exit_prompt_is_not_used_as_focus(self) -> None:
        workspace = self.base_path / "ws-low-value-focus"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session
        session.context_manager.add_user_message("How do I like my responses?")

        summary = session.build_lifecycle_summary("Session exited")
        self.assertEqual(summary, "Session exited")

    async def test_session_initialize_degrades_when_memory_persistence_fails(self) -> None:
        workspace = self.base_path / "ws-degraded-startup"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None

        with patch(
            "ite.memory.manager.MemoryManager._memory_root",
            side_effect=PermissionError("storage unavailable"),
        ):
            await agent.session.initialize()

        session = agent.session
        self.assertTrue(session.is_degraded())
        self.assertIn("persistent_memory", session.runtime_status.disabled_capabilities)
        self.assertIsNotNone(session.context_manager)
        self.assertIn("persistent memory unavailable", session.runtime_summary().lower())

    async def test_session_initialize_degrades_when_mcp_fails(self) -> None:
        workspace = self.base_path / "ws-mcp-failure"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None

        with patch.object(
            agent.session.mcp_manager,
            "initialize",
            side_effect=RuntimeError("mcp boot failed"),
        ):
            await agent.session.initialize()

        session = agent.session
        self.assertTrue(session.is_degraded())
        self.assertIn("mcp", session.runtime_status.disabled_capabilities)
        self.assertIsNotNone(session.context_manager)
        self.assertIn("mcp unavailable", session.runtime_summary().lower())

    async def _fake_chat_completion(self, messages, tools=None, stream=True):
        yield StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            text_delta=TextDelta("Done."),
        )
        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


if __name__ == "__main__":
    unittest.main()
