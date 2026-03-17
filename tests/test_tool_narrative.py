import unittest

from ite.ui.tool_narrative import describe_tool_activity


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


if __name__ == "__main__":
    unittest.main()
