"""Commands help through the mounted Reup panel, including narrow layouts."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.widgets import Collapsible, Static, TextArea

from ite.commands import Command, CommandRegistry
from ite.config.config import Config
from ite.ui.reup.app import ReupApp
from ite.ui.reup.widgets.side_panels import CommandsSidePanel


class CommandsPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_help_wraps_expands_resizes_and_closes(self) -> None:
        with TemporaryDirectory() as directory:
            app = ReupApp(Config(cwd=Path(directory), cloud_auth_enabled=False))

            async def bootstrap():
                app._set_startup_state(False)
                app._set_loading_state("idle", busy=False)
                app.query_one("#prompt", TextArea).focus()

            with patch.object(app, "_bootstrap_after_mount", bootstrap):
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    prompt = app.query_one("#prompt", TextArea)
                    prompt.load_text("/help")
                    await pilot.press("enter")
                    await pilot.pause()
                    panel = app.query_one(CommandsSidePanel)
                    self.assertFalse(panel.query(".commands-panel-subtitle"))
                    descriptions = panel.query(".commands-panel-description")
                    self.assertTrue(any(widget.size.height > 1 for widget in descriptions))
                    body = panel.query_one("#commands-panel-table")
                    self.assertEqual(body.max_scroll_x, 0)
                    app.save_screenshot(filename="commands-list-narrow.svg", path="/tmp/ite-learn-screenshots")
                    learn_row = next(
                        row for row in panel.query(".commands-panel-row")
                        if str(row.query_one(".commands-panel-name", Static).content) == "/learn"
                    )
                    options = learn_row.query_one(Collapsible)
                    options.scroll_visible(immediate=True)
                    await pilot.pause()
                    await pilot.click(options.query_one("CollapsibleTitle"))
                    await pilot.pause()
                    self.assertFalse(options.collapsed)
                    usages = "\n".join(str(widget.content) for widget in options.query(Static))
                    for usage in ("/learn on", "/learn setup", "/learn reload", "/learn review"):
                        self.assertIn(usage, usages)
                    self.assertTrue(all(widget.size.height > 0 for widget in options.query(".commands-panel-option")))
                    app.save_screenshot(filename="commands-narrow.svg", path="/tmp/ite-learn-screenshots")
                    await pilot.resize_terminal(140, 42)
                    app.theme = "textual-light"
                    await pilot.pause()
                    self.assertEqual(body.max_scroll_x, 0)
                    self.assertFalse(options.collapsed)
                    app.save_screenshot(filename="commands-wide-light.svg", path="/tmp/ite-learn-screenshots")
                    await pilot.click("#commands-panel-close")
                    await pilot.pause()
                    self.assertFalse(app.query(CommandsSidePanel))
                    self.assertIs(app.focused, prompt)

    def test_catalog_and_custom_command_options(self) -> None:
        registry = CommandRegistry()
        registry.register(Command("/learn", "Learn", None))
        self.assertIn("setup", dict(registry.get("/learn").variants))
        custom = Command("/learn", "Custom", None, variants=(("custom", "Custom option"),))
        registry.register(custom)
        self.assertEqual(custom.variants, (("custom", "Custom option"),))
