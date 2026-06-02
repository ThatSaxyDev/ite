import unittest
import asyncio
from pathlib import Path

from ite.agent.session import Session
from ite.agent.session_naming import local_session_title, sanitize_model_session_title
from ite.config.config import Config


class SessionNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = Session(Config(cwd=Path("/tmp"), api_key="test"))

    def test_manual_name_locks_session_title(self) -> None:
        self.session.turn_count = 2
        self.session.set_manual_name("Manual Title")

        self.assertEqual(self.session.name, "Manual Title")
        self.assertEqual(self.session.name_source, "manual")
        self.assertTrue(self.session.name_locked)

    def test_auto_name_can_refresh_once_after_turn_three(self) -> None:
        self.session.turn_count = 1
        self.session.set_auto_name("Initial Title")
        self.assertFalse(self.session.should_refresh_auto_name())

        self.session.turn_count = 3
        self.assertTrue(self.session.should_refresh_auto_name())

        self.session.set_auto_name("Better Title")
        self.assertFalse(self.session.should_refresh_auto_name())
        self.assertEqual(self.session.name, "Better Title")

    def test_name_generation_context_uses_full_transcript_after_compaction(self) -> None:
        asyncio.run(self.session.initialize())
        assert self.session.context_manager is not None

        self.session.context_manager.add_user_message("Audit the context runtime architecture.")
        self.session.context_manager.add_assistant_message("I will inspect the runtime and compare it.")
        self.session.context_manager.add_user_message("Now map the gaps against csrc.")
        self.session.context_manager.add_assistant_message("I will compare the systems.")
        self.session.context_manager.replace_with_summary(
            "## ORIGINAL GOAL\nContinue the architecture comparison.",
            boundary_metadata={"trigger_reason": "threshold"},
            preserved_messages=self.session.context_manager.select_compaction_tail(max_messages=2),
        )

        context = self.session.name_generation_context()

        self.assertEqual(
            context["first_user"],
            "Audit the context runtime architecture."[:200],
        )
        self.assertIn("Now map the gaps against csrc.", context["latest_user"])

    def test_local_session_title_removes_filler_without_inference(self) -> None:
        title = local_session_title(
            {
                "first_user": "Hey, can you fix the composer usage display in the runtime?",
                "latest_user": "",
                "focus_hint": "",
            }
        )

        self.assertEqual(title, "Fix Composer Usage Display Runtime")

    def test_model_session_title_sanitizer_rejects_generic_titles(self) -> None:
        self.assertEqual(sanitize_model_session_title('"Improve Session Naming."'), "Improve Session Naming")
        self.assertEqual(sanitize_model_session_title("New chat"), "")
