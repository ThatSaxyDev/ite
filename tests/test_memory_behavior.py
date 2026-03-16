import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ite.agent.agent import Agent
from ite.commands import CommandContext
from ite.commands.info import cmd_memory
from ite.agent.events import AgentEventType
from ite.client.response import StreamEvent, StreamEventType, TextDelta, TokenUsage
from ite.config.config import Config
from ite.ui.tui import TUI
from rich.console import Console


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

    async def test_explicit_memory_instruction_bypasses_model_turn(self) -> None:
        workspace = self.base_path / "ws-explicit"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        async def fail_if_called(*args, **kwargs):
            raise AssertionError("LLM should not be called for explicit memory capture")
            yield  # pragma: no cover

        agent.session.client.chat_completion = fail_if_called  # type: ignore[method-assign]

        response = await self._collect_text(
            agent.run("For this session only, remember the phrase: mango submarine velvet.")
        )
        self.assertIn("stored", response.lower())
        self.assertIn("mango submarine velvet", response.lower())

    async def test_exact_session_phrase_recall_bypasses_model_turn(self) -> None:
        workspace = self.base_path / "ws-exact-recall"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        await self._drain(
            agent.run("For this session only, remember the phrase: mango submarine velvet.")
        )

        async def fail_if_called(*args, **kwargs):
            raise AssertionError("LLM should not be called for exact session phrase recall")
            yield  # pragma: no cover

        agent.session.client.chat_completion = fail_if_called  # type: ignore[method-assign]
        response = await self._collect_text(
            agent.run("What phrase should you remember for this session only?")
        )
        self.assertEqual(response.strip(), "mango submarine velvet")

    async def test_long_term_preferences_are_rendered_as_active_controls(self) -> None:
        workspace = self.base_path / "ws-controls"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        agent.session.client.chat_completion = self._fake_chat_completion  # type: ignore[method-assign]

        await self._drain(agent.run("From now on, keep answers short and avoid bullet lists."))
        response = await self._collect_text(agent.run("Explain the architecture of this repo."))
        self.assertIn("short answer", response.lower())
        system_prompt = agent.session.context_manager.get_messages()[0]["content"]
        self.assertIn("active response controls", system_prompt.lower())
        self.assertIn("keep answers short by default.", system_prompt.lower())
        self.assertIn(
            "avoid bullet lists unless the user explicitly asks for them.",
            system_prompt.lower(),
        )

    async def test_bullets_are_flattened_when_avoid_bullets_preference_is_active(self) -> None:
        workspace = self.base_path / "ws-bullets"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        async def stubborn_bullets(messages, tools=None, stream=True):
            latest_user = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    latest_user = str(msg.get("content", ""))
                    break
            if "explain the architecture of this repo." in latest_user.lower():
                text = "Detailed answer:\n- sessions\n- tools\n- context"
            else:
                text = "Stored."
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(text),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        agent.session.client.chat_completion = stubborn_bullets  # type: ignore[method-assign]

        await self._drain(agent.run("From now on, keep answers short and avoid bullet lists."))
        response = await self._collect_text(agent.run("Explain the architecture of this repo."))
        self.assertNotIn("\n-", response)
        self.assertNotIn("\n*", response)
        self.assertIn("sessions; tools; context", response.lower())

    async def test_memory_command_shows_active_controls(self) -> None:
        workspace = self.base_path / "ws-memory-command"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        await self._drain(agent.run("From now on, keep answers short and avoid bullet lists."))
        console = Console(record=True, file=StringIO())
        ctx = CommandContext(
            config=agent.config,
            agent=agent,
            tui=TUI(config=agent.config, console=console),
            console=console,
        )

        await cmd_memory(ctx, [])
        rendered = console.export_text()
        self.assertIn("active controls", rendered.lower())
        self.assertIn("answer length", rendered.lower())
        self.assertIn("short", rendered.lower())
        self.assertIn("bullet style", rendered.lower())
        self.assertIn("avoid", rendered.lower())

    async def test_memory_prompt_command_shows_selected_bundle(self) -> None:
        workspace = self.base_path / "ws-memory-prompt"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        await self._drain(agent.run("Remember this for this workspace: use pytest for tests."))
        await self._drain(agent.run("From now on, keep answers short and avoid bullet lists."))

        console = Console(record=True, file=StringIO())
        ctx = CommandContext(
            config=agent.config,
            agent=agent,
            tui=TUI(config=agent.config, console=console),
            console=console,
        )

        await cmd_memory(ctx, ["prompt", "What", "test", "tool", "should", "we", "use", "here?"])
        rendered = console.export_text().lower()
        self.assertIn("prompt memory debug", rendered)
        self.assertIn("selected controls", rendered)
        self.assertIn("selected workspace memory", rendered)
        self.assertIn("pytest", rendered)

    async def test_memory_command_drops_superseded_preferences(self) -> None:
        workspace = self.base_path / "ws-memory-supersede"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()

        await self._drain(agent.run("From now on, keep answers short and avoid bullet lists."))
        await self._drain(
            agent.run("From now on, give detailed answers with bullet lists when helpful.")
        )

        console = Console(record=True, file=StringIO())
        ctx = CommandContext(
            config=agent.config,
            agent=agent,
            tui=TUI(config=agent.config, console=console),
            console=console,
        )

        await cmd_memory(ctx, [])
        rendered = console.export_text().lower()
        self.assertIn("detailed", rendered)
        self.assertIn("helpful", rendered)
        self.assertNotIn("keep answers short and avoid bullet lists", rendered)

    async def test_conditional_preferences_change_controls_by_query(self) -> None:
        workspace = self.base_path / "ws-conditional"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        agent.session.client.chat_completion = self._fake_chat_completion  # type: ignore[method-assign]

        await self._drain(
            agent.run(
                "Remember this preference: for debugging, keep answers short; for architecture, give detailed answers."
            )
        )

        debug_response = await self._collect_text(
            agent.run("We have a failing auth test. What should I check first?")
        )
        architecture_response = await self._collect_text(
            agent.run("Explain the architecture of this repo.")
        )
        self.assertIn("short answer", debug_response.lower())
        self.assertIn("detailed answer", architecture_response.lower())

        debug_prompt = agent.session.context_manager.get_messages()[0]["content"]
        self.assertIn("matches: architecture", debug_prompt.lower())

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

        if "we have a failing auth test. what should i check first?" in user_text:
            if "keep answers short by default." in prompt_text:
                return "Short answer: check the failing assertion and auth setup."
            return "Detailed answer:\n- inspect auth setup\n- inspect assertion"

        if "explain the architecture of this repo." in user_text:
            if (
                "give detailed answers by default." in prompt_text
                or "matches: architecture" in prompt_text
            ):
                return "Detailed answer:\n- sessions\n- tools\n- context"
            if (
                "keep answers short by default." in prompt_text
                and "avoid bullet lists unless the user explicitly asks for them." in prompt_text
            ):
                return "Short answer: session, tools, context."
            return "The architecture uses sessions, tools, and context."

        if "remember" in user_text:
            return "Stored."

        return "No relevant memory."


if __name__ == "__main__":
    unittest.main()
