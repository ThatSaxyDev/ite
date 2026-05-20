from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Input, TextArea

from ite.config.config import Config
from ite.ui.reup.app import insert_voice_text_into_widget
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


class VoiceInputApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Input(value="commit: ", id="commit")


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
