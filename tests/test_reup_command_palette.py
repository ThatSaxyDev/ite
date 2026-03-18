import unittest
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, PropertyMock, patch
from types import SimpleNamespace

from ite.config.config import Config
from ite.ui.reup.app import ReupApp


class ReupCommandPaletteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def _app(self) -> ReupApp:
        return ReupApp(Config(cwd=self.cwd, api_key="test-key"))

    def test_extract_slash_query_only_when_editing_first_token(self) -> None:
        self.assertEqual(ReupApp._extract_slash_query("/ap"), "/ap")
        self.assertEqual(ReupApp._extract_slash_query("   /ap"), "/ap")
        self.assertIsNone(ReupApp._extract_slash_query("hello"))
        self.assertIsNone(ReupApp._extract_slash_query("/approval auto"))
        self.assertIsNone(ReupApp._extract_slash_query("/approval\nauto"))

    def test_filtered_command_palette_matches_registry_commands(self) -> None:
        app = self._app()

        slash_only = app._filtered_command_palette("/")
        filtered = app._filtered_command_palette("/ap")

        self.assertTrue(slash_only)
        self.assertEqual(slash_only, sorted(slash_only, key=lambda entry: entry.name.lower()))
        self.assertGreater(len(slash_only), 8)
        self.assertEqual(slash_only[0].name, "/approval")
        self.assertEqual([entry.name for entry in filtered], ["/approval"])
        self.assertEqual(filtered[0].description, "Show or change approval mode")

    def test_palette_selection_clamps_at_bounds(self) -> None:
        app = self._app()
        app._filtered_command_palette_options = app._filtered_command_palette("/")
        app._command_palette_index = 0

        app._move_command_palette_selection(-1)
        self.assertEqual(app._command_palette_index, 0)

        app._command_palette_index = len(app._filtered_command_palette_options) - 1
        app._move_command_palette_selection(1)
        self.assertEqual(
            app._command_palette_index,
            len(app._filtered_command_palette_options) - 1,
        )

    def test_plan_render_dedupe_tracks_last_rendered_text(self) -> None:
        app = self._app()

        self.assertTrue(app._should_render_plan_text("Plan body"))
        app._last_rendered_plan_text = app._normalize_plan_text("Plan body")
        self.assertFalse(app._should_render_plan_text("Plan body"))
        self.assertFalse(app._should_render_plan_text("  Plan body  "))

    def test_plan_ready_enter_is_not_implicit_approval(self) -> None:
        app = self._app()

        class DummyEvent:
            def __init__(self, key: str) -> None:
                self.key = key
                self.stopped = False
                self.default_prevented = False

            def stop(self) -> None:
                self.stopped = True

            def prevent_default(self) -> None:
                self.default_prevented = True

        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        app._plan_ready_future = loop.create_future()

        event = DummyEvent("enter")
        with patch.object(ReupApp, "focused", new_callable=PropertyMock, return_value=None):
            app.on_key(event)  # type: ignore[arg-type]

        self.assertFalse(event.stopped)
        self.assertFalse(app._plan_ready_future.done())

    def test_plan_question_choice_only_shows_status_for_custom_answer(self) -> None:
        app = self._app()
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)

        class DummyButton:
            def __init__(self) -> None:
                self.disabled = False
                self.variant = "default"
                self.classes = set()

            def add_class(self, name: str) -> None:
                self.classes.add(name)

        class DummyStatus:
            def __init__(self) -> None:
                self.display = False
                self.value = ""

            def update(self, value: str) -> None:
                self.value = value

        app._plan_question_future = loop.create_future()
        option_buttons = [DummyButton(), DummyButton()]
        app._plan_question_option_buttons = option_buttons
        app._plan_question_custom_input = SimpleNamespace(disabled=False)
        app._plan_question_custom_submit = DummyButton()
        app._plan_question_status = DummyStatus()

        loop.run_until_complete(
            app._resolve_plan_question_choice(
                selected_index=0,
                selected_option="Option A",
                free_text="",
            )
        )

        self.assertEqual(option_buttons[0].variant, "primary")

        app._plan_question_future = loop.create_future()
        app._plan_question_option_buttons = [DummyButton(), DummyButton()]
        app._plan_question_custom_input = SimpleNamespace(disabled=False)
        app._plan_question_custom_submit = DummyButton()
        status = DummyStatus()
        app._plan_question_status = status

        loop.run_until_complete(
            app._resolve_plan_question_choice(
                selected_index=None,
                selected_option="",
                free_text="Custom path",
            )
        )

        self.assertTrue(status.display)
        self.assertIn("Custom answer", status.value)

    def test_recommended_suffix_can_be_present_without_primary_styling(self) -> None:
        recommended_index = 1
        options = ["First", "Second"]
        labels = [
            f"{idx + 1}. {option}{' (recommended)' if recommended_index == idx else ''}"
            for idx, option in enumerate(options)
        ]

        self.assertEqual(labels[0], "1. First")
        self.assertEqual(labels[1], "2. Second (recommended)")

    def test_handle_send_asks_for_resolution_instead_of_auto_cancel(self) -> None:
        app = self._app()
        app._is_turn_running = True

        class DummyPrompt:
            def __init__(self, text: str) -> None:
                self.text = text

        prompt = DummyPrompt("follow up message")

        async def scenario() -> None:
            with (
                patch.object(app, "query_one", return_value=prompt),
                patch.object(app, "_resolve_active_turn_send", new=AsyncMock(return_value=True)) as resolve,
                patch.object(app, "cancel_active_turn", new=AsyncMock()) as cancel,
            ):
                await app.handle_send()
                resolve.assert_awaited_once()
                cancel.assert_not_called()

        asyncio.run(scenario())

    def test_run_agent_message_auto_dispatches_queued_payload_after_clean_finish(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(session=None)
        app._queued_turn_payload = {"message": "next", "attachments": []}

        async def scenario() -> None:
            with (
                patch.object(app, "ensure_agent", new=AsyncMock()),
                patch.object(app, "add_user_message", new=AsyncMock()),
                patch.object(app, "_agent_turn", new=AsyncMock()),
                patch.object(app, "auto_save", new=AsyncMock()),
                patch.object(app, "_progress_state_label", return_value="thinking"),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_dispatch_queued_payload_if_ready", new=AsyncMock()) as dispatch_queued,
                patch.object(app, "_restore_queued_payload_after_unsuccessful_turn") as restore_queued,
            ):
                await app.run_agent_message("hello")
                dispatch_queued.assert_awaited_once()
                restore_queued.assert_not_called()

        asyncio.run(scenario())

    def test_run_agent_message_restores_queued_payload_after_error(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(session=None)
        app._queued_turn_payload = {"message": "next", "attachments": []}

        async def fake_agent_turn(_message: str) -> None:
            app._turn_had_error = True

        async def scenario() -> None:
            with (
                patch.object(app, "ensure_agent", new=AsyncMock()),
                patch.object(app, "add_user_message", new=AsyncMock()),
                patch.object(app, "_agent_turn", new=fake_agent_turn),
                patch.object(app, "auto_save", new=AsyncMock()),
                patch.object(app, "_progress_state_label", return_value="thinking"),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_dispatch_queued_payload_if_ready", new=AsyncMock()) as dispatch_queued,
                patch.object(app, "_restore_queued_payload_after_unsuccessful_turn") as restore_queued,
            ):
                await app.run_agent_message("hello")
                dispatch_queued.assert_not_called()
                restore_queued.assert_called_once()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
