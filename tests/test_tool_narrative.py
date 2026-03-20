import unittest

from ite.ui.tool_narrative import describe_tool_activity
from ite.ui.tool_narrative import activity_title


class ToolNarrativeTests(unittest.TestCase):
    def test_plan_question_has_specific_narrative(self) -> None:
        text = describe_tool_activity(
            "plan_question",
            {"question": "What category of tools would you like to add?"},
            stage="start",
        )

        self.assertIn("Asking a planning question", text)
        self.assertIn("What category of tools", text)

    def test_unknown_tool_uses_safe_fallback(self) -> None:
        self.assertEqual(
            describe_tool_activity("mystery_tool", stage="start"),
            "Running tool `mystery_tool`.",
        )
        self.assertEqual(
            describe_tool_activity("mystery_tool", stage="complete", success=True),
            "Completed tool `mystery_tool`.",
        )
        self.assertEqual(
            describe_tool_activity("mystery_tool", stage="complete", success=False),
            "Tool `mystery_tool` failed.",
        )

    def test_git_diff_has_specific_narrative_and_title(self) -> None:
        self.assertEqual(
            activity_title("git_diff", stage="complete", success=True),
            "Git diff ready",
        )
        self.assertEqual(
            describe_tool_activity(
                "git_diff",
                {"path": "lib/app.dart"},
                {"selection": "unstaged"},
                stage="complete",
                success=True,
            ),
            "Loaded unstaged diff for lib/app.dart.",
        )


if __name__ == "__main__":
    unittest.main()
