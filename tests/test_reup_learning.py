"""Exercise the mounted Reup surface with learner commands and a fake provider."""

from __future__ import annotations

import os
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rich.console import Console
from textual.widgets import Select, Static, TextArea

from ite.agent.agent import Agent
from ite.agent.learning_profile import PACES, START
from ite.agent.session import Session
from ite.agent.session_manager import SessionManager
from ite.client.response import StreamEvent, StreamEventType, TextDelta, ToolCall
from ite.config.config import Config, ModelConfig
from ite.ui.reup.app import ReupApp
from ite.ui.reup.learning_setup import LearningSetupModal


class ReupLearningTests(unittest.IsolatedAsyncioTestCase):
    async def test_mounted_tui_toggle_profile_review_wait_and_resume(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "project"
            workspace.mkdir()
            (workspace / "attempt.py").write_text(
                "def count_items(items):\n    return len(items)\n"
            )
            config = Config(
                cwd=workspace,
                api_key="test",
                base_url="https://provider.example.test/v1",
                cloud_auth_enabled=False,
                model=ModelConfig(name="test-model", source_kind="custom"),
            )
            session = Session(config)
            await session.initialize()
            agent = Agent(config, session=session)
            self.addAsyncCleanup(session.client.close)
            provider_inputs = []
            completion_calls = 0

            async def completion(messages, **kwargs):
                nonlocal completion_calls
                completion_calls += 1
                provider_inputs.append(str(messages))
                if completion_calls == 1:
                    yield StreamEvent(
                        type=StreamEventType.TOOL_CALL_COMPLETE,
                        tool_call=ToolCall(
                            call_id="learning-progress-display",
                            name="learn_progress",
                            arguments={
                                "objective": "Learn Python edge cases.",
                                "current_step": "Try the missing input case.",
                            },
                        ),
                    )
                    yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE)
                    return
                yield StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta(
                        "Decide how count_items should handle missing input. Try that case yourself, "
                        "then share the error and what you expected."
                    ),
                )
                yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE)

            session.client.chat_completion = completion
            app = ReupApp(config)
            app.agent = agent
            notices = []
            intro_fragments = []
            original_add_card = app.add_assistant_card

            async def add_card(title, body, css_class="assistant", **kwargs):
                if "system" in css_class:
                    notices.append(str(getattr(body, "text", body)))
                if css_class == "assistant" and hasattr(body, "stream_fragment"):
                    original_fragment = body.stream_fragment

                    async def record_fragment(fragment):
                        intro_fragments.append(fragment)
                        await original_fragment(fragment)

                    body.stream_fragment = record_fragment
                return await original_add_card(
                    title, body, css_class=css_class, **kwargs
                )

            app.add_assistant_card = add_card

            async def bootstrap():
                await app.ensure_agent()
                app._set_startup_state(False)
                app._set_loading_state("idle", busy=False)
                app.query_one("#prompt", TextArea).focus()

            with (
                patch.object(app, "_bootstrap_after_mount", bootstrap),
                patch(
                    "ite.agent.session_manager.get_data_dir",
                    return_value=root / "sessions",
                ),
            ):
                async with app.run_test(size=(110, 34)) as pilot:
                    await pilot.pause()
                    prompt = app.query_one("#prompt", TextArea)
                    prompt.load_text("/le se")
                    await pilot.pause()
                    await pilot.press("enter")
                    await pilot.pause(0.25)
                    self.assertIsInstance(app.screen, LearningSetupModal)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertFalse((workspace / "learn.md").exists())
                    self.assertFalse(session.learning.enabled)
                    prompt.load_text("/learn on")
                    await pilot.press("enter")
                    await pilot.pause(0.25)
                    self.assertTrue(session.learning.enabled)
                    for _ in range(50):
                        if "learning goals and preferences." in "".join(
                            intro_fragments
                        ):
                            break
                        await pilot.pause(0.1)
                    self.assertGreater(len(intro_fragments), 1)
                    self.assertTrue(
                        all(len(fragment) == 1 for fragment in intro_fragments)
                    )
                    self.assertEqual(
                        "".join(intro_fragments),
                        session.context_manager.get_snapshot_messages()[-1]["content"],
                    )
                    self.assertFalse(
                        any(
                            "Hooks and delegation" in notice
                            or "Commands and tests" in notice
                            for notice in notices
                        )
                    )
                    self.assertTrue((workspace / "learn.md").exists())
                    self.assertTrue(
                        any(
                            "Created" in str(notice) and "learn.md" in str(notice)
                            for notice in notices
                        )
                    )
                    self.assertIn("learn your turn", app._composer_meta_text().plain)
                    self.assertEqual(len(app.query(".block.assistant")), 1)
                    feed_cards = list(app.query("#conversation > .block"))
                    self.assertTrue(feed_cards[-2].has_class("system"))
                    self.assertTrue(feed_cards[-1].has_class("assistant"))
                    self.assertLess(feed_cards[-2].region.y, feed_cards[-1].region.y)
                    self.assertFalse(
                        any("What would you like" in notice for notice in notices)
                    )
                    self.assertEqual(
                        session.context_manager.get_snapshot_messages()[-1]["role"],
                        "assistant",
                    )
                    self.assertIn(
                        "What would you like to build or understand?",
                        session.context_manager.get_snapshot_messages()[-1]["content"],
                    )
                    self.assertIsNotNone(
                        SessionManager().load_session(session.session_id)
                    )

                    (workspace / "learn.md").write_text("Prefer short explanations.")
                    prompt.load_text("/learn reload")
                    await pilot.press("enter")
                    await pilot.pause(0.25)
                    self.assertTrue((workspace / "learn.md").exists())
                    self.assertEqual(
                        session.learning.profile, "Prefer short explanations."
                    )

                    prompt.load_text("/learn setup")
                    await pilot.press("enter")
                    await pilot.pause(0.25)
                    self.assertIsInstance(app.screen, LearningSetupModal)
                    modal = app.screen
                    modal.query_one("#learn-setup-goal", TextArea).load_text(
                        "Learn Python edge cases."
                    )
                    await pilot.click("#learn-setup-next")
                    await pilot.pause(0.15)
                    modal.query_one("#learn-setup-experience", TextArea).load_text(
                        "I know functions; exceptions are unfamiliar."
                    )
                    await pilot.click("#learn-setup-next")
                    await pilot.pause(0.15)
                    modal.query_one("#learn-setup-pace", Select).value = PACES[2]
                    modal.query_one("#learn-setup-preferences", TextArea).load_text(
                        "Help me predict behavior before debugging."
                    )
                    await pilot.click("#learn-setup-next")
                    await pilot.pause(0.15)
                    await pilot.pause()
                    preview = modal.query_one("#learn-profile-preview", TextArea)
                    self.assertIn(
                        "Prefer short explanations.",
                        preview.text,
                        f"step={modal.step}, error={modal.query_one('#learn-setup-error', Static).render()}",
                    )
                    self.assertIn("Learn Python edge cases.", preview.text)
                    self.assertEqual(
                        (workspace / "learn.md").read_text(),
                        "Prefer short explanations.",
                    )
                    screenshots = os.environ.get("ITE_LEARN_SCREENSHOTS")
                    if screenshots:
                        Path(screenshots).mkdir(parents=True, exist_ok=True)
                        app.save_screenshot(
                            "learning-setup-review.svg", path=screenshots
                        )
                    await pilot.resize_terminal(110, 50)
                    await pilot.pause()
                    self.assertGreaterEqual(
                        modal.query_one(".learning-setup-shell").region.height, 46
                    )
                    self.assertGreater(preview.region.height, 30)
                    self.assertLessEqual(
                        modal.query_one("#learn-setup-next").region.bottom, 50
                    )
                    if screenshots:
                        app.save_screenshot("learning-setup-tall.svg", path=screenshots)
                    await pilot.resize_terminal(80, 24)
                    await pilot.pause()
                    save_button = modal.query_one("#learn-setup-next")
                    self.assertGreater(save_button.region.height, 0)
                    self.assertLessEqual(save_button.region.bottom, 24)
                    if screenshots:
                        app.save_screenshot(
                            "learning-setup-narrow.svg", path=screenshots
                        )
                    await pilot.click("#learn-setup-back")
                    self.assertEqual(
                        modal.query_one("#learn-setup-preferences", TextArea).text,
                        "Help me predict behavior before debugging.",
                    )
                    await pilot.click("#learn-setup-next")
                    await pilot.pause(0.15)
                    await pilot.click("#learn-setup-next")
                    await pilot.pause(0.15)
                    await pilot.pause(0.25)
                    self.assertNotIsInstance(app.screen, LearningSetupModal)
                    self.assertIn("Brief hints first", session.learning.profile)
                    self.assertEqual(
                        session.learning.objective, "Learn Python edge cases."
                    )
                    profile = (workspace / "learn.md").read_text()
                    prompt.load_text("/learn setup")
                    await pilot.press("enter")
                    await pilot.pause(0.25)
                    self.assertEqual(
                        app.screen.query_one("#learn-setup-goal", TextArea).text,
                        "Learn Python edge cases.",
                    )
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertEqual((workspace / "learn.md").read_text(), profile)
                    self.assertEqual(profile.count(START), 1)

                    prompt.load_text("/learn setup")
                    await pilot.press("enter")
                    await pilot.pause(0.25)
                    modal = app.screen
                    for _ in range(3):
                        await pilot.press("ctrl+enter")
                        await pilot.pause(0.15)
                    self.assertEqual(modal.step, 3)
                    preview = modal.query_one("#learn-profile-preview", TextArea)
                    preview.load_text(preview.text + "\nKeep feedback concrete.\n")
                    if screenshots:
                        app.theme = "textual-light"
                        await pilot.pause()
                        app.save_screenshot(
                            "learning-setup-light.svg", path=screenshots
                        )
                    await pilot.press("ctrl+enter")
                    await pilot.pause(0.25)
                    self.assertNotIsInstance(app.screen, LearningSetupModal)
                    profile = (workspace / "learn.md").read_text()
                    self.assertIn("Keep feedback concrete.", profile)
                    self.assertEqual(profile.count(START), 1)

                    prompt.load_text("/learn setup")
                    await pilot.press("enter")
                    await pilot.pause(0.25)
                    modal = app.screen
                    for _ in range(3):
                        await pilot.press("ctrl+enter")
                        await pilot.pause(0.15)
                    external_profile = profile + "\nChanged in my editor.\n"
                    (workspace / "learn.md").write_text(external_profile)
                    await pilot.press("ctrl+enter")
                    await pilot.pause(0.15)
                    self.assertIs(app.screen, modal)
                    self.assertIn(
                        "changed while setup was open",
                        str(modal.query_one("#learn-setup-error", Static).render()),
                    )
                    self.assertEqual(
                        (workspace / "learn.md").read_text(), external_profile
                    )
                    await pilot.press("escape")
                    await pilot.pause()
                    prompt.load_text("/learn reload")
                    await pilot.press("enter")
                    await pilot.pause(0.25)
                    profile = external_profile

                    prompt.load_text("/learn review")
                    await pilot.press("enter")
                    for _ in range(30):
                        await pilot.pause(0.1)
                        if session.turn_count > 0 and not app._is_turn_running:
                            break
                    self.assertGreater(session.turn_count, 0, repr(notices))
                    self.assertFalse(app._is_turn_running)
                    learning_card = app._tool_widgets["learning-progress-display"]
                    self.assertEqual(learning_card.title_text, "Learning step saved")
                    details = StringIO()
                    console = Console(file=details, width=80, color_system=None)
                    for block in learning_card._full_blocks:
                        console.print(block)
                    self.assertIn("Goal", details.getvalue())
                    self.assertIn("Next step", details.getvalue())
                    self.assertNotIn("learn_progress", details.getvalue())
                    self.assertNotIn("current_step", details.getvalue())
                    self.assertIn(
                        "Help me predict behavior before debugging.",
                        provider_inputs[-1],
                    )
                    self.assertEqual(session.learning.phase, "awaiting_learner")
                    self.assertIn("learn your turn", app._composer_meta_text().plain)
                    self.assertIn(
                        "missing input",
                        str(session.context_manager.get_snapshot_messages()),
                    )
                    self.assertEqual(
                        (workspace / "attempt.py").read_text(),
                        "def count_items(items):\n    return len(items)\n",
                    )
                    self.assertTrue(
                        app.query_one("#composer-meta-line", Static).display
                    )
                    screenshots = os.environ.get("ITE_LEARN_SCREENSHOTS")
                    if screenshots:
                        Path(screenshots).mkdir(parents=True, exist_ok=True)
                        app.save_screenshot("learning-review.svg", path=screenshots)
                    await pilot.resize_terminal(80, 24)
                    await pilot.pause()
                    self.assertIn("learn your turn", app._composer_meta_text().plain)
                    if screenshots:
                        app.save_screenshot(
                            "learning-review-narrow.svg", path=screenshots
                        )

                    snapshot = SessionManager().load_session(session.session_id)
                    self.assertTrue(snapshot.learning_state["enabled"])
                    session.set_learning_mode(False)
                    app._open_sessions.pop(session.session_id, None)
                    app._session_agents.pop(session.session_id, None)
                    fresh = Session(config)
                    await fresh.initialize()
                    app.agent = Agent(config, session=fresh)
                    await app._resume_snapshot(snapshot)
                    await pilot.pause(0.25)
                    self.assertTrue(app.agent.session.learning.enabled)
                    self.assertEqual(app.agent.session.learning.profile, profile)
                    self.assertIn("learn your turn", app._composer_meta_text().plain)

                    prompt.load_text("/learn off")
                    await pilot.press("enter")
                    await pilot.pause(0.25)
                    self.assertFalse(app.agent.session.learning.enabled)
                    self.assertIn("plan off", app._composer_meta_text().plain)
                    normal_session = app.agent.session
                    normal_session.client.chat_completion = completion
                    previous_turns = normal_session.turn_count
                    prompt.load_text(
                        "Explain how a Python function handles missing input."
                    )
                    await pilot.press("enter")
                    for _ in range(50):
                        await pilot.pause(0.1)
                        if (
                            normal_session.turn_count > previous_turns
                            and not app._is_turn_running
                        ):
                            break
                    self.assertGreater(normal_session.turn_count, previous_turns)
                    self.assertFalse(app._is_turn_running)
                    self.assertIsNone(app._streaming_widget)
                    self.assertNotIn(
                        "# Learning mode — runtime enforced", provider_inputs[-1]
                    )
                    self.assertIn(
                        "missing input",
                        str(normal_session.context_manager.get_snapshot_messages()),
                    )
