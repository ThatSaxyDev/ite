import unittest
from pathlib import Path

from rich.table import Table
from rich.text import Text

from ite.ui.reup.tool_views import normalize_unified_diff_paths
from ite.ui.reup.tool_views import render_subagent_payload
from ite.ui.reup.tool_views import render_git_log_output


class ReupToolViewsTests(unittest.TestCase):
    def test_normalize_unified_diff_paths_makes_paths_relative(self) -> None:
        cwd = Path("/tmp/workspace")
        raw = (
            "--- /tmp/workspace/lib/app.dart\n"
            "+++ /tmp/workspace/lib/app.dart\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

        normalized = normalize_unified_diff_paths(raw, cwd=cwd)

        self.assertIn("--- lib/app.dart", normalized)
        self.assertIn("+++ lib/app.dart", normalized)

    def test_render_git_log_output_returns_table_for_commits(self) -> None:
        rendered = render_git_log_output(
            {
                "commits": [
                    {
                        "short_sha": "abc1234",
                        "date": "2026-03-20",
                        "author": "Kiishi",
                        "subject": "feat: improve git cards",
                    }
                ]
            }
        )

        self.assertIsInstance(rendered, Table)

    def test_render_subagent_payload_uses_metadata_trace_on_failure(self) -> None:
        blocks, was_truncated = render_subagent_payload(
            output='{"summary":"Investigated tools","termination":"error","tools_used":["grep"],"findings":["One"]}',
            metadata={
                "subagent_result": {
                    "summary": "Investigated tools",
                    "termination": "error",
                    "tools_used": ["grep"],
                    "findings": ["One"],
                    "actions": [],
                },
                "subagent_trace": {
                    "child_session_id": "child-session-1",
                    "duration_ms": 142,
                    "child_turn_count": 3,
                },
            },
            success=False,
            error="Sub-agent 'codebase_investigator' failed",
        )

        self.assertFalse(was_truncated)
        text_blocks = [block.plain for block in blocks if isinstance(block, Text)]
        joined = "\n".join(text_blocks)
        self.assertIn("child-session-1", joined)
        self.assertIn("142 ms", joined)
        self.assertIn("3 turns", joined)
        self.assertIn("termination=error", joined)
        self.assertIn("Findings", joined)
        self.assertIn("Failure", joined)


if __name__ == "__main__":
    unittest.main()
