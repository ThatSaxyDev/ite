"""Learning status copy, themed hierarchy, and native file-link activation."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.widgets import Link

from ite.commands.help_catalog import COMMAND_VARIANTS
from ite.config.config import Config
from ite.ui.reup.app import ReupApp
from ite.ui.reup.widgets.learning_status import LearningStatusBody


class LearningStatusDisplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_readable_status_and_clickable_local_profile(self) -> None:
        with TemporaryDirectory(prefix="learn space ") as directory:
            path = Path(directory) / "learn.md"
            path.write_text("My learning preferences.")
            app = ReupApp(Config(cwd=Path(directory), cloud_auth_enabled=False))

            async def bootstrap():
                app._set_startup_state(False)
                app._set_loading_state("idle", busy=False)

            text = "Learning mode: ON · awaiting learner\nObjective: Build a website\nLoaded learn.md.\nLearning commands:\n"
            text += "\n".join(f"/learn {usage} — {description}" for usage, description in COMMAND_VARIANTS["/learn"])
            with patch.object(app, "_bootstrap_after_mount", bootstrap):
                async with app.run_test(size=(110, 40)) as pilot:
                    await pilot.pause()
                    body = LearningStatusBody(text, path)
                    await app.add_assistant_card("Learning mode", body, css_class="system")
                    await pilot.pause()
                    link = body.query_one(Link)
                    self.assertEqual(str(link.text), "learn.md")
                    self.assertEqual(link.url, path.resolve().as_uri())
                    link.scroll_visible(immediate=True)
                    await pilot.pause()
                    with patch.object(app, "open_url") as open_url:
                        await pilot.click(link)
                        open_url.assert_called_once_with(path.resolve().as_uri())
                    self.assertEqual(len(body.query(".learning-command-name")), 8)
                    self.assertIn("/learn review", [str(widget.content) for widget in body.query(".learning-command-name")])
                    for theme in ("textual-dark", "textual-light"):
                        app.theme = theme
                        await pilot.pause()
                        self.assertNotEqual(body.query_one(".learning-command-name").styles.color, body.query_one(".learning-command-description").styles.color)
                        app.save_screenshot(f"learning-status-{theme}.svg", path="/tmp/ite-learn-screenshots")
