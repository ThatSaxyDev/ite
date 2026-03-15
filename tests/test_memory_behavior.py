import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.agent.agent import Agent
from ite.agent.events import AgentEventType
from ite.client.response import StreamEvent, StreamEventType, TextDelta, TokenUsage
from ite.config.config import Config


class MemoryBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_path = Path(self.temp_dir.name)
        patcher = patch("ite.memory.manager.get_data_dir", return_value=self.base_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_session_memory_recall_and_new_session_isolation(self) -> None:
        workspace = self.base_path / "ws-a"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        agent.session.client.chat_completion = self._fake_chat_completion  # type: ignore[method-assign]

        await self._drain(agent.run("For this session only, remember the phrase: mango submarine velvet."))
        response = await self._collect_text(
            agent.run("What phrase should you remember for this session only?")
        )
        self.assertIn("mango submarine velvet", response.lower())

        fresh = Agent(Config(cwd=workspace, api_key="test"))
        assert fresh.session is not None
        await fresh.session.initialize()
        fresh.session.client.chat_completion = self._fake_chat_completion  # type: ignore[method-assign]

        isolated = await self._collect_text(
            fresh.run("What phrase should you remember for this session only?")
        )
        self.assertIn("no session phrase stored", isolated.lower())

    async def test_workspace_memory_persists_only_in_same_workspace(self) -> None:
        workspace_a = self.base_path / "ws-a"
        workspace_b = self.base_path / "ws-b"
        workspace_a.mkdir()
        workspace_b.mkdir()

        agent_a = Agent(Config(cwd=workspace_a, api_key="test"))
        assert agent_a.session is not None
        await agent_a.session.initialize()
        agent_a.session.client.chat_completion = self._fake_chat_completion  # type: ignore[method-assign]

        await self._drain(
            agent_a.run("Remember this for this workspace: use pytest for tests.")
        )

        same_workspace = Agent(Config(cwd=workspace_a, api_key="test"))
        assert same_workspace.session is not None
        await same_workspace.session.initialize()
        same_workspace.session.client.chat_completion = self._fake_chat_completion  # type: ignore[method-assign]

        same_response = await self._collect_text(
            same_workspace.run("What test tool should we use here?")
        )
        self.assertIn("pytest", same_response.lower())

        other_workspace = Agent(Config(cwd=workspace_b, api_key="test"))
        assert other_workspace.session is not None
        await other_workspace.session.initialize()
        other_workspace.session.client.chat_completion = self._fake_chat_completion  # type: ignore[method-assign]

        other_response = await self._collect_text(
            other_workspace.run("What test tool should we use here?")
        )
        self.assertIn("no workspace testing memory stored", other_response.lower())

    async def _collect_text(self, events) -> str:
        content = ""
        async for event in events:
            if event.type == AgentEventType.TEXT_COMPLETE:
                content = event.data.get("content", "")
        return content

    async def _drain(self, events) -> None:
        async for _ in events:
            pass

    async def _fake_chat_completion(self, messages, tools=None, stream=True):
        prompt = str(messages[0].get("content", "")) if messages else ""
        latest_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                latest_user = str(msg.get("content", ""))
                break

        response = self._select_response(prompt, latest_user)
        if response:
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(response),
            )
        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    def _select_response(self, system_prompt: str, latest_user: str) -> str:
        user_text = latest_user.lower()
        prompt_text = system_prompt.lower()

        if "what phrase should you remember for this session only?" in user_text:
            if "mango submarine velvet" in prompt_text:
                return "The phrase is mango submarine velvet."
            return "No session phrase stored."

        if "what test tool should we use here?" in user_text:
            if "pytest" in prompt_text:
                return "Use pytest for tests."
            return "No workspace testing memory stored."

        if "remember" in user_text:
            return "Stored."

        return "No relevant memory."


if __name__ == "__main__":
    unittest.main()
