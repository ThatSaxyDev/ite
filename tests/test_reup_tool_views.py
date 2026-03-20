import unittest
from pathlib import Path

from rich.table import Table

from ite.ui.reup.tool_views import normalize_unified_diff_paths
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


if __name__ == "__main__":
    unittest.main()
