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
