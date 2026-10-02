"""Hierarchical slash completion through the mounted composer."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from textual.widgets import TextArea

from ite.commands import build_registry
from ite.config.config import Config
from ite.ui.reup.app import ReupApp
from ite.ui.reup.composer_views import (
    build_command_palette_options,
    filtered_command_palette,
)


class CommandCompletionTests(unittest.IsolatedAsyncioTestCase):
    def test_tree_filtering_aliases_and_required_arguments(self) -> None:
        options = build_command_palette_options(build_registry())

        def choices(text):
            return filtered_command_palette(text, command_palette_options=options)

        self.assertIn("/learn on", [choice.name for choice in choices("/lea")])
        self.assertIn("/learn setup", [choice.name for choice in choices("/learn ")])
        self.assertEqual([choice.name for choice in choices("/le se")], ["/learn setup"])
        self.assertEqual([choice.name for choice in choices("/mcp e se")], ["/mcp env set"])
        self.assertEqual([choice.name for choice in choices("/learn re")], ["/learn reload", "/learn review"])
        self.assertIn("/mcp env set", [choice.name for choice in choices("/mcp env ")])
        self.assertIn("/mcp env set", [choice.name for choice in choices("/mcp e")])
        create = choices("/branch --c")[0]
        self.assertTrue(create.requires_input)
        self.assertEqual(create.insert_text, "/branch --create")
        self.assertFalse(choices("/branch --create my-branch"))
        self.assertIn("/subagents list", [choice.name for choice in choices("/subagents ")])
        self.assertIn("/todos list planning", [choice.name for choice in choices("/todos list ")])
        self.assertFalse(choices("/learn\non"))
        self.assertFalse(choices("hello /learn"))

    async def test_keyboard_mouse_and_nested_selection(self) -> None:
        with TemporaryDirectory() as directory:
            app = ReupApp(Config(cwd=Path(directory), cloud_auth_enabled=False))

            async def bootstrap():
                app._set_startup_state(False)
                app._set_loading_state("idle", busy=False)
                app.query_one("#prompt", TextArea).focus()

            run_command = AsyncMock()
            with patch.object(app, "_bootstrap_after_mount", bootstrap), patch.object(app, "run_command", run_command):
                async with app.run_test(size=(110, 40)) as pilot:
                    await pilot.pause()
                    prompt = app.query_one("#prompt", TextArea)
                    prompt.load_text("/lea")
                    await pilot.pause()
                    self.assertEqual(prompt.text, "/lea")
                    run_command.assert_not_called()
                    self.assertIn("/learn setup", [option.name for option in app._filtered_command_palette_options])
                    self.assertIn("Show learning status", app._render_command_palette().plain)
                    app.save_screenshot("composer-learn-options.svg", path="/tmp/ite-learn-screenshots")
                    await pilot.press("down", "enter")
                    await pilot.pause()
                    run_command.assert_awaited_once_with("/learn on")
                    self.assertEqual(prompt.text, "")
                    run_command.reset_mock()

                    prompt.load_text("/learn rev")
                    await pilot.pause()
                    await pilot.press("tab")
                    self.assertEqual(prompt.text, "/learn review ")
                    run_command.assert_not_called()
                    await pilot.press("enter")
                    await pilot.pause()
                    run_command.assert_awaited_once_with("/learn review")
                    run_command.reset_mock()

                    prompt.load_text("/mcp e")
                    await pilot.pause()
                    self.assertIn("/mcp env set", [option.name for option in app._filtered_command_palette_options])
                    run_command.assert_not_called()
                    prompt.load_text("/mcp env se")
                    await pilot.pause()
                    await pilot.press("enter")
                    self.assertEqual(prompt.text, "/mcp env set ")
                    run_command.assert_not_called()
                    prompt.load_text("/branch --c")
                    await pilot.pause()
                    await pilot.press("enter")
                    self.assertEqual(prompt.text, "/branch --create ")
                    run_command.assert_not_called()

                    prompt.load_text("/learn ")
                    await pilot.pause()
                    await pilot.click("#command-palette", offset=(4, 3))
                    await pilot.pause()
                    run_command.assert_awaited_once_with("/learn on")
                    run_command.reset_mock()
                    prompt.focus()
                    prompt.load_text("/learn ")
                    await pilot.pause()
                    await pilot.press(*(["down"] * 8))
                    await pilot.click("#command-palette", offset=(4, 9))
                    await pilot.pause()
                    run_command.assert_awaited_once_with("/learn review")
                    run_command.reset_mock()
                    prompt.focus()
                    prompt.load_text("/learn ")
                    await pilot.pause()
                    await pilot.press("escape")
                    self.assertEqual(prompt.text, "/learn ")
                    self.assertFalse(app.query_one("#command-palette").display)
                    await pilot.press("backspace")
                    await pilot.pause()
                    self.assertTrue(app.query_one("#command-palette").display)
                    await pilot.resize_terminal(80, 24)
                    await pilot.pause()
                    app.save_screenshot("composer-command-narrow.svg", path="/tmp/ite-learn-screenshots")
                    self.assertLessEqual(app.query_one("#command-palette").region.bottom, 24,
                        f"app={app.size}, screen={app.screen.size}, rows={app._command_palette_rows}, palette={app.query_one('#command-palette').region}, composer={app.query_one('#composer').region}")
