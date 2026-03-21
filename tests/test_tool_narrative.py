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

    def test_structured_config_tools_have_specific_narratives_and_titles(self) -> None:
        self.assertEqual(
            activity_title("read_toml", stage="complete", success=True),
            "TOML loaded",
        )
        self.assertEqual(
            describe_tool_activity(
                "read_toml",
                {"path": "pyproject.toml", "key_path": "project.version"},
                stage="complete",
                success=True,
            ),
            "Loaded TOML from pyproject.toml :: project.version.",
        )
        self.assertEqual(
            activity_title("write_yaml", stage="complete", success=True),
            "YAML updated",
        )
        self.assertEqual(
            describe_tool_activity(
                "write_yaml",
                {"path": "docker-compose.yml", "key_path": "services.api.image", "operation": "set"},
                stage="complete",
                success=True,
            ),
            "Applied YAML `set` at docker-compose.yml :: services.api.image.",
        )
        self.assertEqual(
            activity_title("read_env", stage="complete", success=True),
            "Env loaded",
        )
        self.assertEqual(
            describe_tool_activity(
                "read_env",
                {"path": ".env", "key": "API_KEY"},
                stage="complete",
                success=True,
            ),
            "Loaded env values from .env :: API_KEY.",
        )
        self.assertEqual(
            activity_title("write_env", stage="complete", success=True),
            "Env updated",
        )
        self.assertEqual(
            describe_tool_activity(
                "write_env",
                {"path": ".env", "key": "DEBUG", "operation": "set"},
                stage="complete",
                success=True,
            ),
            "Applied env `set` at .env :: DEBUG.",
        )

    def test_http_and_archive_tools_have_specific_narratives_and_titles(self) -> None:
        self.assertEqual(
            activity_title("http_request", stage="complete", success=True),
            "HTTP response ready",
        )
        self.assertEqual(
            describe_tool_activity(
                "http_request",
                {"method": "POST", "url": "https://example.com/api"},
                stage="complete",
                success=True,
            ),
            "Completed POST request to https://example.com/api.",
        )
        self.assertEqual(
            activity_title("list_archive", stage="complete", success=True),
            "Archive contents ready",
        )
        self.assertEqual(
            describe_tool_activity(
                "list_archive",
                {"path": "builds/release.zip"},
                stage="complete",
                success=True,
            ),
            "Loaded archive contents for builds/release.zip.",
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
            activity_title(
                "shell_poll",
                stage="complete",
                success=True,
                metadata={"running": False, "has_new_output": False},
            ),
            "Shell session finished",
        )
        self.assertEqual(
            describe_tool_activity(
                "shell_poll",
                {"session_id": "sh_123"},
                {"status": "exited", "has_new_output": False},
                stage="complete",
                success=True,
            ),
            "No new output from shell session `sh_123`. It has already finished.",
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
