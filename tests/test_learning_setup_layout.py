"""Verify the learning interview overlays the live Reup chat like other modals."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.widgets import Button, TextArea

from ite.config.config import Config
from ite.ui.reup.app import ReupApp
from ite.ui.reup.learning_setup import LearningSetupModal
from ite.ui.reup.modals import VoiceSetupModal


class LearningSetupLayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_scrim_and_slim_actions_in_both_themes(self) -> None:
        with TemporaryDirectory() as directory:
            app = ReupApp(Config(cwd=Path(directory), cloud_auth_enabled=False))

            async def bootstrap():
                app._set_startup_state(False)
                app._set_loading_state("idle", busy=False)

            with patch.object(app, "_bootstrap_after_mount", bootstrap):
                async with app.run_test(size=(110, 40)) as pilot:
                    await pilot.pause()
                    await app.add_user_message("I want to learn how to build a website.")
                    await pilot.pause()
                    chat_screen = app.screen
                    for theme in ("textual-dark", "textual-light"):
                        app.theme = theme
                        reference = VoiceSetupModal()
                        app.push_screen(reference)
                        await pilot.pause()
                        scrim = reference.styles.background
                        button_height = reference.query_one("#cancel", Button).size.height
                        reference.dismiss(None)
                        await pilot.pause()
                        modal = LearningSetupModal(
                            Path(directory) / "learn.md", None, require_idle=lambda: None
                        )
                        app.push_screen(modal)
                        await pilot.pause()
                        self.assertIs(app.screen_stack[-2], chat_screen)
                        self.assertEqual(modal.styles.background, scrim)
                        self.assertLess(modal.styles.background.a, 1)
                        self.assertEqual(button_height, 1)
                        for button in modal.query(Button):
                            self.assertEqual(button.size.height, button_height)
                        app.save_screenshot(f"learn-overlay-{theme}.svg", path="/tmp/ite-learn-screenshots")
                        for field_id, page_id in (
                            ("learn-setup-goal", "learn-goal-page"),
                            ("learn-setup-experience", "learn-experience-page"),
                            ("learn-setup-preferences", "learn-style-page"),
                        ):
                            for size in ((80, 24), (110, 40), (130, 65)):
                                await pilot.resize_terminal(*size)
                                await pilot.pause()
                                field = modal.query_one(f"#{field_id}", TextArea)
                                page = modal.query_one(f"#{page_id}")
                                actions = modal.query_one(".learning-actions")
                                self.assertGreaterEqual(field.region.height, 3)
                                self.assertEqual(field.region.bottom, page.region.bottom)
                                self.assertLessEqual(actions.region.y - field.region.bottom, 1)
                                self.assertLessEqual(actions.region.bottom, size[1])
                            await pilot.resize_terminal(110, 40)
                            await pilot.pause()
                            await pilot.click("#learn-setup-next")
                            await pilot.pause(0.15)
                        self.assertEqual(modal.step, 3)
                        self.assertGreaterEqual(modal.query_one(".learning-setup-shell").region.height, 37)
                        self.assertGreater(modal.query_one("#learn-profile-preview", TextArea).size.height, 25)
                        await pilot.resize_terminal(80, 24)
                        await pilot.pause()
                        for button in modal.query(Button):
                            self.assertEqual(button.size.height, 1)
                            self.assertLessEqual(button.region.bottom, 24)
                        app.save_screenshot(f"learn-overlay-review-{theme}.svg", path="/tmp/ite-learn-screenshots")
                        await pilot.press("escape")
                        await pilot.pause()
                        self.assertIs(app.screen, chat_screen)
                        self.assertFalse((Path(directory) / "learn.md").exists())
                        await pilot.resize_terminal(110, 40)
