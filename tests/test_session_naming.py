import unittest
import asyncio
from pathlib import Path

from ite.agent.session import Session
from ite.agent.session_naming import sanitize_model_session_title
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

    def test_auto_name_refreshes_at_later_milestones(self) -> None:
        self.session.turn_count = 1
        self.session.set_auto_name("Initial Title")
        self.assertFalse(self.session.should_refresh_auto_name())

        self.session.turn_count = 3
        self.assertTrue(self.session.should_refresh_auto_name())

        self.session.set_auto_name("Better Title")
        self.assertFalse(self.session.should_refresh_auto_name())
        self.assertEqual(self.session.name, "Better Title")

        self.session.turn_count = 6
        self.assertTrue(self.session.should_refresh_auto_name())

        self.session.mark_auto_name_attempt()
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

    def test_name_generation_context_summarizes_first_turn_tools(self) -> None:
        asyncio.run(self.session.initialize())
        assert self.session.context_manager is not None

        self.session.context_manager.add_user_message("Why is session naming stuck?")
        self.session.context_manager.add_assistant_message(
            "I will inspect the runtime naming path.",
            [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "grep",
                        "arguments": '{"pattern":"should_refresh_auto_name"}',
                    },
                }
            ],
        )
        self.session.context_manager.add_tool_result(
            "call_1",
            "Found should_refresh_auto_name in session.py and app.py.",
            tool_ui={
                "name": "grep",
                "success": True,
                "output": "src/ite/agent/session.py:330:def should_refresh_auto_name",
            },
        )
        self.session.context_manager.add_assistant_message(
            "The first title is being saved before refinement has enough context."
        )
        self.session.context_manager.add_user_message("Now fix the first turn naming.")

        context = self.session.name_generation_context()

        self.assertIn("User: Why is session naming stuck?", context["first_turn"])
        self.assertIn("Tool call: grep", context["first_turn"])
        self.assertIn("Tool result: grep ok", context["first_turn"])
        self.assertIn("The first title is being saved", context["first_turn"])
        self.assertNotIn("Now fix the first turn naming.", context["first_turn"])
        self.assertEqual(context["turn_count"], "0")

    def test_model_session_title_sanitizer_rejects_generic_titles(self) -> None:
        self.assertEqual(sanitize_model_session_title('"Improve Session Naming."'), "Improve Session Naming")
        self.assertEqual(sanitize_model_session_title("New chat"), "")
