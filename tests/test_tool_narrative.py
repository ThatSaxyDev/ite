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

    def test_run_tests_has_specific_narrative_and_title(self) -> None:
        self.assertEqual(
            activity_title("run_tests", stage="complete", success=True),
            "Test results ready",
        )
        self.assertEqual(
            describe_tool_activity(
                "run_tests",
                {"command": "python3 -m unittest discover -s tests"},
                stage="complete",
                success=True,
            ),
            "Finished tests: `python3 -m unittest discover -s tests`.",
        )

    def test_shell_session_tools_have_specific_narratives_and_titles(self) -> None:
        self.assertEqual(
            activity_title("shell_start", stage="complete", success=True),
            "Shell session started",
        )
        self.assertEqual(
            describe_tool_activity(
                "shell_start",
                {"command": "npm run dev", "cwd": "/repo/app"},
                stage="complete",
                success=True,
            ),
            "Started shell session for `npm run dev` in /repo/app.",
        )
        self.assertEqual(
            activity_title("shell_send", stage="complete", success=True),
            "Shell input sent",
        )
        self.assertEqual(
            describe_tool_activity(
                "shell_send",
                {"session_id": "sh_123", "input": "pwd"},
                stage="complete",
                success=True,
            ),
            "Sent `pwd` to shell session `sh_123`.",
        )
        self.assertEqual(
            activity_title("shell_poll", stage="complete", success=True),
            "Shell session updated",
        )
        self.assertEqual(
            describe_tool_activity(
                "shell_poll",
                {"session_id": "sh_123"},
                {"status": "running"},
                stage="complete",
                success=True,
            ),
            "Updated shell session `sh_123` (running).",
        )
        self.assertEqual(
            activity_title("shell_stop", stage="complete", success=True),
            "Shell session stopped",
        )
        self.assertEqual(
            describe_tool_activity(
                "shell_stop",
                {"session_id": "sh_123"},
                stage="complete",
                success=True,
            ),
            "Stopped shell session `sh_123`.",
        )

    def test_policy_redirect_uses_neutral_title_and_narrative(self) -> None:
        metadata = {"policy_blocked": True, "redirect_to": "read_json"}
        self.assertEqual(
            activity_title("read_file", stage="complete", success=False, metadata=metadata),
            "Switching tools",
        )
        self.assertEqual(
            describe_tool_activity(
                "read_file",
                {"path": "package.json"},
                metadata,
                stage="complete",
                success=False,
            ),
            "`read_json` fits this step better, so continuing there.",
        )


if __name__ == "__main__":
    unittest.main()
