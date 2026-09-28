import unittest
from pathlib import Path

from rich.table import Table
from rich.text import Text

from ite.ui.reup.command_views import build_sandbox_command_renderable
from ite.ui.reup.tool_views import compact_tool_preview_blocks
from ite.ui.reup.tool_views import normalize_unified_diff_paths
from ite.ui.reup.tool_views import render_subagent_metrics_payload
from ite.ui.reup.tool_views import render_subagent_payload
from ite.ui.reup.tool_views import render_subagent_runtime_payload
from ite.ui.reup.tool_views import render_git_log_output


class ReupToolViewsTests(unittest.TestCase):
    def test_sandbox_command_summary_uses_allowed_path_plurality(self) -> None:
        one_path = build_sandbox_command_renderable(
            True,
            ["/tmp/one"],
            "/tmp/workspace",
        )
        many_paths = build_sandbox_command_renderable(
            True,
            ["/tmp/one", "/tmp/two"],
            "/tmp/workspace",
        )

        self.assertEqual(
            one_path.renderables[1].plain,
            "🔒  enabled  •  1 allowed path",
        )
        self.assertEqual(
            many_paths.renderables[1].plain,
            "🔒  enabled  •  2 allowed paths",
        )

    def test_compact_tool_preview_blocks_uses_first_useful_text_line(self) -> None:
        blocks = [
            Text(""),
            Text("Completed reading /tmp/project/app.py (lines 1-100 of 2370).\nSecond line"),
            Text("  1|from __future__ import annotations"),
        ]

        preview = compact_tool_preview_blocks(blocks, max_chars=80)

        self.assertEqual(len(preview), 1)
        self.assertIsInstance(preview[0], Text)
        self.assertEqual(
            preview[0].plain,
            "Completed reading /tmp/project/app.py (lines 1-100 of 2370).",
        )

    def test_compact_tool_preview_blocks_truncates_long_preview(self) -> None:
        preview = compact_tool_preview_blocks([Text("x" * 220)], max_chars=32)

        self.assertEqual(preview[0].plain, ("x" * 29) + "...")

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

    def test_render_subagent_payload_shows_retry_recovery_metadata(self) -> None:
        blocks, was_truncated = render_subagent_payload(
            output='{"summary":"Recovered audit","termination":"goal","tools_used":["grep"],"findings":[],"actions":[]}',
            metadata={
                "subagent_result": {
                    "summary": "Recovered audit",
                    "termination": "goal",
                    "tools_used": ["grep"],
                    "findings": [],
                    "actions": [],
                    "recovered_after_retry": True,
                },
                "subagent_trace": {
                    "child_session_id": "child-session-2",
                    "duration_ms": 220,
                    "child_turn_count": 8,
                    "attempt_count": 2,
                    "retries_used": 1,
                    "termination": "goal",
                },
            },
            success=True,
            error=None,
        )

        self.assertFalse(was_truncated)
        text_blocks = [block.plain for block in blocks if isinstance(block, Text)]
        joined = "\n".join(text_blocks)
        self.assertIn("2 attempts", joined)
        self.assertIn("1 retries", joined)
        self.assertIn("Recovered after retry.", joined)

    def test_render_subagent_runtime_payload_shows_run_states(self) -> None:
        blocks = render_subagent_runtime_payload(
            metadata={
                "reused_existing": True,
                "requested_subagent": "registry",
                "selected_subagent": "codebase_investigator",
                "runs": [
                    {
                        "run_id": "agent_001",
                        "status": "running",
                        "goal": "Inspect backend architecture",
                        "current_activity": "Searching code in src/ite.",
                        "last_update_at": "2026-03-22T00:00:00+00:00",
                        "activity_history": [
                            {
                                "at": "2026-03-22T00:00:00+00:00",
                                "message": "Starting specialist session.",
                            },
                            {
                                "at": "2026-03-22T00:00:01+00:00",
                                "message": "Searching code in src/ite.",
                            },
                        ],
                    },
                    {
                        "run_id": "agent_002",
                        "status": "completed",
                        "summary": "Reviewed frontend layout",
                    },
                ],
                "completed_run_ids": ["agent_002"],
                "pending_run_ids": ["agent_001"],
            }
        )

        self.assertGreaterEqual(len(blocks), 4)
        self.assertTrue(any(isinstance(block, Table) for block in blocks))
        text_blocks = [block.plain for block in blocks if isinstance(block, Text)]
        joined = "\n".join(text_blocks)
        self.assertIn("Reused matching active specialist run.", joined)
        self.assertIn("codebase_investigator", joined)
        self.assertIn("registry", joined)
        self.assertIn("Recent activity", joined)
        self.assertIn("Searching code in src/ite.", joined)
        self.assertIn("completed=1", joined)
        self.assertIn("pending=1", joined)

    def test_render_subagent_runtime_payload_shows_failure_text_without_runs(self) -> None:
        blocks = render_subagent_runtime_payload(
            metadata={
                "available_subagents": ["codebase_investigator", "code_reviewer"],
            },
            error="Unknown subagent 'registry'. Available subagents: codebase_investigator, code_reviewer",
            success=False,
        )

        text_blocks = [block.plain for block in blocks if isinstance(block, Text)]
        joined = "\n".join(text_blocks)
        self.assertIn("Available specialists:", joined)
        self.assertIn("Failure", joined)
        self.assertIn("Unknown subagent 'registry'", joined)

    def test_render_subagent_runtime_payload_shows_circuit_breaker_notice(self) -> None:
        blocks = render_subagent_runtime_payload(
            metadata={
                "circuit_open": True,
                "circuit_reopen_at": "2026-03-22T12:00:00+00:00",
                "failure_count": 3,
            },
            error="Subagent 'codebase_investigator' is temporarily paused after repeated failures.",
            success=False,
        )

        text_blocks = [block.plain for block in blocks if isinstance(block, Text)]
        joined = "\n".join(text_blocks)
        self.assertIn("Specialist circuit breaker is open.", joined)
        self.assertIn("3 recent failures/timeouts.", joined)
        self.assertIn("Retry after 2026-03-22T12:00:00+00:00.", joined)

    def test_render_subagent_runtime_payload_collapses_completed_wait_rows(self) -> None:
        blocks = render_subagent_runtime_payload(
            metadata={
                "runs": [
                    {
                        "run_id": "agent_001",
                        "status": "completed",
                        "summary": "Very long completed specialist report that should not be shown here.",
                        "activity_history": [
                            {"at": "2026-03-22T00:00:00+00:00", "message": "Specialist finished."}
                        ],
                    },
                    {
                        "run_id": "agent_002",
                        "status": "running",
                        "current_activity": "Reading src/ite/ui/reup/app.py",
                        "last_update_at": "2026-03-22T00:00:01+00:00",
                    },
                ]
            },
            collapse_completed=True,
        )

        text_blocks = [block.plain for block in blocks if isinstance(block, Text)]
        joined = "\n".join(text_blocks)
        self.assertNotIn("Very long completed specialist report", joined)
        self.assertNotIn("Recent activity", joined)
        table = next(block for block in blocks if isinstance(block, Table))
        self.assertEqual(len(table.rows), 2)

    def test_render_subagent_metrics_payload_labels_historical_and_live_state(self) -> None:
        blocks = render_subagent_metrics_payload(
            metadata={
                "restored_from_snapshot": True,
                "totals": {
                    "spawned_runs": 7,
                    "completed": 6,
                    "failed": 1,
                    "timeout": 0,
                    "cancelled": 0,
                    "retries_used": 2,
                    "recovered_after_retry": 1,
                    "active_runs": 0,
                    "retained_runs": 7,
                    "circuit_breaker_blocks": 0,
                    "circuit_breaker_trips": 0,
                },
                "open_circuits": {},
            },
            success=True,
        )

        tables = [block for block in blocks if isinstance(block, Table)]
        self.assertEqual(len(tables), 2)
        rendered = "\n".join(
            cell.plain if hasattr(cell, "plain") else str(cell)
            for table in tables
            for column in table.columns
            for cell in column.cells
        )
        self.assertIn("Historical session totals", rendered)
        self.assertIn("restored from saved session", rendered)
        self.assertIn("Live runtime state", rendered)
        self.assertIn("current process", rendered)


if __name__ == "__main__":
    unittest.main()
