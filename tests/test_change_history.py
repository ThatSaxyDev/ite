import tempfile
import unittest
from pathlib import Path

from ite.agent.change_history import ChangeConflictError
from ite.agent.change_history import ChangeHistory
from ite.agent.change_history import file_diffs_from_tool_result
from ite.config.config import Config
from ite.tools.base import FileDiff
from ite.tools.base import ToolInvocation
from ite.tools.builtin.apply_patch import ApplyPatchTool


class ChangeHistoryTests(unittest.TestCase):
    def test_undo_and_redo_restore_grouped_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            existing = cwd / "existing.txt"
            created = cwd / "created.txt"
            existing.write_text("before\n", encoding="utf-8")

            history = ChangeHistory(cwd)
            history.begin_batch("Implement feature")
            existing_diff = FileDiff(
                path=existing,
                old_content="before\n",
                new_content="after\n",
            )
            created_diff = FileDiff(
                path=created,
                old_content="",
                new_content="hello\n",
                is_new_file=True,
            )
            history.record_file_diffs([existing_diff, created_diff])

            existing.write_text("after\n", encoding="utf-8")
            created.write_text("hello\n", encoding="utf-8")
            history.finalize_batch()

            undone = history.undo()
            self.assertEqual(undone.label, "Implement feature")
            self.assertEqual(existing.read_text(encoding="utf-8"), "before\n")
            self.assertFalse(created.exists())

            redone = history.redo()
            self.assertEqual(redone.label, "Implement feature")
            self.assertEqual(existing.read_text(encoding="utf-8"), "after\n")
            self.assertEqual(created.read_text(encoding="utf-8"), "hello\n")

    def test_undo_detects_content_drift_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            target = cwd / "target.txt"
            target.write_text("old\n", encoding="utf-8")

            history = ChangeHistory(cwd)
            history.begin_batch("Edit target")
            history.record_file_diffs(
                [
                    FileDiff(
                        path=target,
                        old_content="old\n",
                        new_content="new\n",
                    )
                ]
            )
            target.write_text("new\n", encoding="utf-8")
            history.finalize_batch()

            target.write_text("manually changed\n", encoding="utf-8")

            with self.assertRaises(ChangeConflictError):
                history.undo()

            history.undo(force=True)
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")


class ApplyPatchDiffCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_patch_returns_structured_file_diffs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            target = cwd / "sample.txt"
            target.write_text("hello\nworld\n", encoding="utf-8")

            tool = ApplyPatchTool(Config(cwd=cwd, api_key="test"))
            patch = """*** Begin Patch
*** Update File: sample.txt
@@
 hello
-world
+there
*** End Patch
"""
            result = await tool.execute(
                ToolInvocation(params={"patch": patch, "dry_run": False}, cwd=cwd)
            )

            self.assertTrue(result.success, msg=result.error)
            diffs = file_diffs_from_tool_result(result)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0].old_content, "hello\nworld\n")
            self.assertEqual(diffs[0].new_content, "hello\nthere\n")


if __name__ == "__main__":
    unittest.main()
