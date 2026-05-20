from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Input, TextArea

from ite.config.config import Config
from ite.ui.reup.app import ReupApp
from ite.ui.reup.app import insert_voice_text_into_widget, redact_sensitive_command_text
from ite.voice.transcription import _is_hallucination


class VoiceConfigTests(unittest.TestCase):
    def test_voice_is_disabled_by_default(self) -> None:
        config = Config(api_key="key", base_url="http://example.test")

        self.assertFalse(config.voice.enabled)
        self.assertIsNone(config.voice.groq_api_key)

    def test_voice_env_vars_override_config(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ITE_VOICE_ENABLED": "true",
                "ITE_VOICE_GROQ_API_KEY": "gsk-test",
            },
        ):
            config = Config(api_key="key", base_url="http://example.test")

        self.assertTrue(config.voice.enabled)
        self.assertEqual(config.voice.groq_api_key, "gsk-test")


class VoiceCopySafetyTests(unittest.TestCase):
    def test_redacts_voice_setup_key_from_history(self) -> None:
        self.assertEqual(
            redact_sensitive_command_text("/voice setup gsk_secret_value"),
            "/voice setup [redacted]",
        )

    def test_leaves_other_voice_commands_readable(self) -> None:
        self.assertEqual(redact_sensitive_command_text("/voice status"), "/voice status")


class VoiceInputApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Input(value="commit: ", id="commit")


class VoiceCommandRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_setup_command_opens_interactive_modal_and_escape_closes(
        self,
    ) -> None:
        app = ReupApp(Config(api_key="key", base_url="http://example.test"))
        app._queue_session_tabs_refresh = lambda: None  # type: ignore[method-assign]

        async with app.run_test() as pilot:
            app.run_worker(app.run_command("/voice setup"), exclusive=False)
            await pilot.pause()

            widget = app.screen.query_one("#voice-groq-api-key", Input)
            await pilot.press("g", "s", "k", "_", "r", "o", "u", "t", "e")

            self.assertEqual(widget.value, "gsk_route")

            await pilot.press("escape")
            await pilot.pause()

            self.assertNotEqual(type(app.screen).__name__, "VoiceSetupModal")


class VoiceComposerMetaTests(unittest.TestCase):
    def test_send_control_renders_after_flow_control(self) -> None:
        app = ReupApp(Config(api_key="key", base_url="http://example.test"))
        app.config.voice.enabled = True
        app.config.voice.groq_api_key = "gsk-test"

        rendered = app._composer_meta_text()

        self.assertIn("send", rendered.plain)
        self.assertIn("flow", rendered.plain)
        self.assertGreater(app._composer_send_hitbox[1], app._composer_send_hitbox[0])
        self.assertGreater(rendered.plain.index("send"), rendered.plain.index("flow"))

    def test_flow_control_is_hidden_until_flow_is_enabled(self) -> None:
        app = ReupApp(Config(api_key="key", base_url="http://example.test"))

        rendered = app._composer_meta_text()

        self.assertNotIn("flow", rendered.plain)
        self.assertEqual(app._composer_flow_hitbox, (0, 0))

    def test_flow_control_renders_after_activity_when_enabled(self) -> None:
        app = ReupApp(Config(api_key="key", base_url="http://example.test"))
        app.config.voice.enabled = True
        app.config.voice.groq_api_key = "gsk-test"

        rendered = app._composer_meta_text()

        self.assertIn("activity", rendered.plain)
        self.assertIn("flow", rendered.plain)
        self.assertGreater(rendered.plain.index("flow"), rendered.plain.index("activity"))
        self.assertGreater(app._composer_flow_hitbox[1], app._composer_flow_hitbox[0])

    def test_flow_control_click_uses_voice_toggle_action(self) -> None:
        app = ReupApp(Config(api_key="key", base_url="http://example.test"))
        app._composer_attach_hitbox = (0, 0)
        app._composer_model_hitbox = (0, 0)
        app._composer_branch_hitbox = (0, 0)
        app._composer_usage_hitbox = None
        app._composer_context_hitbox = (0, 0)
        app._composer_activity_hitbox = (0, 0)
        app._composer_plan_hitbox = (0, 0)
        app._composer_flow_hitbox = (10, 20)
        event = SimpleNamespace(x=12, stopped=False)
        event.stop = lambda: setattr(event, "stopped", True)

        with patch.object(app, "action_toggle_voice_input") as toggle:
            app.on_composer_meta_line_click(event)

        toggle.assert_called_once_with()
        self.assertTrue(event.stopped)

    def test_send_control_click_uses_send_stop_action(self) -> None:
        app = ReupApp(Config(api_key="key", base_url="http://example.test"))
        app._composer_attach_hitbox = (0, 0)
        app._composer_model_hitbox = (0, 0)
        app._composer_branch_hitbox = (0, 0)
        app._composer_usage_hitbox = None
        app._composer_context_hitbox = (0, 0)
        app._composer_activity_hitbox = (0, 0)
        app._composer_plan_hitbox = (0, 0)
        app._composer_send_hitbox = (10, 20)
        app._composer_flow_hitbox = (0, 0)
        event = SimpleNamespace(x=12, stopped=False)
        event.stop = lambda: setattr(event, "stopped", True)

        with patch.object(app, "run_worker") as run_worker, patch.object(
            app, "_activate_send_stop_control", return_value=None
        ) as activate:
            app.on_composer_meta_line_click(event)

        run_worker.assert_called_once()
        activate.assert_called_once_with()
        self.assertTrue(event.stopped)

    def test_recording_tick_advances_flow_frame_and_refreshes_meta(self) -> None:
        app = ReupApp(Config(api_key="key", base_url="http://example.test"))
        app._voice_recorder = object()  # type: ignore[assignment]

        with patch.object(app, "_update_composer_meta_line") as update_meta:
            app._tick_top_indicator()

        self.assertEqual(app._flow_meta_frame, 1)
        update_meta.assert_called_once_with()

    def test_running_turn_tick_advances_send_frame_and_refreshes_meta(self) -> None:
        app = ReupApp(Config(api_key="key", base_url="http://example.test"))
        app._is_turn_running = True

        with patch.object(app, "_update_composer_meta_line") as update_meta:
            app._tick_top_indicator()

        self.assertEqual(app._send_meta_frame, 1)
        update_meta.assert_called_once_with()


class VoiceInsertionTests(unittest.IsolatedAsyncioTestCase):
    def test_inserts_into_text_area_at_cursor(self) -> None:
        widget = TextArea()
        widget.text = "fix "

        inserted = insert_voice_text_into_widget(widget, "the tests")

        self.assertTrue(inserted)
        self.assertEqual(widget.text, "the testsfix ")

    async def test_inserts_into_input_at_cursor(self) -> None:
        async with VoiceInputApp().run_test() as pilot:
            widget = pilot.app.query_one("#commit", Input)
            widget.cursor_position = len(widget.value)

            inserted = insert_voice_text_into_widget(widget, "wire voice typing")

            self.assertTrue(inserted)
            self.assertEqual(widget.value, "commit: wire voice typing")


class VoiceTranscriptionTests(unittest.TestCase):
    def test_filters_known_silence_hallucination_with_no_speech_prob(self) -> None:
        self.assertTrue(
            _is_hallucination(
                text="Thank you.",
                payload={"segments": [{"no_speech_prob": 0.42}]},
            )
        )

    def test_keeps_phrase_when_no_speech_prob_is_low(self) -> None:
        self.assertFalse(
            _is_hallucination(
                text="Thank you.",
                payload={"segments": [{"no_speech_prob": 0.01}]},
            )
        )
