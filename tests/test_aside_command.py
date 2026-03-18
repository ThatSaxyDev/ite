import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from ite.agent.agent import Agent
from ite.client.response import StreamEvent, StreamEventType, TextDelta, TokenUsage
from ite.commands import CommandContext
from ite.commands.aside import cmd_aside, is_aside_command_text
from ite.config.config import Config
from ite.ui.tui import TUI


class AsideCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_path = Path(self.temp_dir.name)
        patcher = patch("ite.memory.manager.get_data_dir", return_value=self.base_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_aside_uses_session_context_without_mutating_history(self) -> None:
        workspace = self.base_path / "ws-aside"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session
        session.context_manager.add_user_message("We are building a planner.")
        session.context_manager.add_assistant_message("Use plan mode first.")

        original_messages = session.context_manager.get_messages()
        captured_messages: list[dict] = []

        async def fake_chat_completion(messages, tools=None, stream=True):
            captured_messages.extend(messages)
            self.assertIsNone(tools)
            self.assertTrue(stream)
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Short aside answer."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
            )

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]

        console = Console(record=True, file=StringIO())
        ctx = CommandContext(
            config=agent.config,
            agent=agent,
            tui=TUI(config=agent.config, console=console),
            console=console,
        )

        await cmd_aside(ctx, ["what", "is", "the", "current", "goal?"])

        rendered = console.export_text()
        self.assertIn("Short aside answer.", rendered)
        self.assertEqual(original_messages, session.context_manager.get_messages())
        self.assertEqual(session.context_manager.total_usage.total_tokens, 14)
        self.assertEqual(captured_messages[-1]["role"], "user")
        self.assertIn("transient /aside side question", captured_messages[-1]["content"])

    async def test_aside_inherits_plan_context_from_system_prompt(self) -> None:
        workspace = self.base_path / "ws-aside-plan"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session
        session.set_plan_mode(True)
        session.set_plan_phase("asking_questions")
        session.set_active_plan("## Plan\n- Build /aside")

        captured_messages: list[dict] = []

        async def fake_chat_completion(messages, tools=None, stream=True):
            captured_messages.extend(messages)
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Plan-aware aside."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            )

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]

        console = Console(record=True, file=StringIO())
        ctx = CommandContext(
            config=agent.config,
            agent=agent,
            tui=TUI(config=agent.config, console=console),
            console=console,
        )

        await cmd_aside(ctx, ["what", "part", "of", "the", "plan", "is", "riskiest?"])

        aside_prompt = str(captured_messages[-1]["content"]).lower()
        self.assertEqual(captured_messages[0]["role"], "system")
        self.assertIn("plan mode: on", aside_prompt)
        self.assertIn("plan phase: asking_questions", aside_prompt)
        self.assertIn("current plan:", aside_prompt)
        self.assertIn("build /aside", aside_prompt)

    async def test_aside_command_detection_helper(self) -> None:
        self.assertTrue(is_aside_command_text("/aside"))
        self.assertTrue(is_aside_command_text("/aside what changed?"))
        self.assertTrue(is_aside_command_text("  /aside summarize the risk  "))
        self.assertFalse(is_aside_command_text("/asidee"))
        self.assertFalse(is_aside_command_text("/plan"))

    async def test_aside_uses_tui_spinner_lifecycle(self) -> None:
        workspace = self.base_path / "ws-aside-spinner"
        workspace.mkdir()

        agent = Agent(Config(cwd=workspace, api_key="test"))
        assert agent.session is not None
        await agent.session.initialize()
        session = agent.session

        async def fake_chat_completion(messages, tools=None, stream=True):
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta("Spinner aside."),
            )
            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                usage=TokenUsage(prompt_tokens=4, completion_tokens=2, total_tokens=6),
            )

        session.client.chat_completion = fake_chat_completion  # type: ignore[method-assign]

        console = Console(record=True, file=StringIO())
        tui = TUI(config=agent.config, console=console)
        with (
            patch.object(tui, "start_spinner") as start_spinner,
            patch.object(tui, "stop_spinner") as stop_spinner,
        ):
            ctx = CommandContext(
                config=agent.config,
                agent=agent,
                tui=tui,
                console=console,
            )

            await cmd_aside(ctx, ["who", "am", "i"])

        start_spinner.assert_called_once_with("Thinking")
        stop_spinner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
