import subprocess
import tempfile
import unittest
from pathlib import Path

from ite.config.config import Config
from ite.tools.base import ToolInvocation
from ite.tools.builtin.git_tools import (
    GitBranchTool,
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitPushTool,
    GitStatusTool,
)
from ite.tools.registry import create_default_registry


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(cwd: Path) -> None:
    _run_git(cwd, "init")
    _run_git(cwd, "config", "user.name", "ITE Tests")
    _run_git(cwd, "config", "user.email", "ite-tests@example.com")


def _commit_file(cwd: Path, path: str, content: str, message: str) -> None:
    file_path = cwd / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    _run_git(cwd, "add", "-A", "--", ".")
    _run_git(cwd, "commit", "-m", message)


class GitToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_git_status_reports_clean_repo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            _init_repo(cwd)
            _commit_file(cwd, "app.py", "print('hi')\n", "initial commit")

            tool = GitStatusTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(ToolInvocation(params={}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertIn("Working tree: clean", result.output)
            self.assertEqual(result.metadata.get("clean"), True)
            self.assertEqual(result.metadata.get("files"), [])

    async def test_git_status_reports_staged_unstaged_and_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            _init_repo(cwd)
            _commit_file(cwd, "tracked.py", "print('one')\n", "initial commit")

            tracked = cwd / "tracked.py"
            staged = cwd / "staged.py"
            untracked = cwd / "untracked.py"
            tracked.write_text("print('two')\n", encoding="utf-8")
            staged.write_text("print('staged')\n", encoding="utf-8")
            untracked.write_text("print('new')\n", encoding="utf-8")
            _run_git(cwd, "add", "-A", "--", "staged.py")

            tool = GitStatusTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(ToolInvocation(params={}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertIn("tracked.py", result.metadata.get("unstaged_files", []))
            self.assertIn("staged.py", result.metadata.get("staged_files", []))
            self.assertIn("untracked.py", result.metadata.get("untracked_files", []))
            files = {entry["path"]: entry for entry in result.metadata.get("files", [])}
            self.assertEqual(files["tracked.py"]["stage_label"], "unstaged")
            self.assertEqual(files["staged.py"]["stage_label"], "staged")
            self.assertEqual(files["untracked.py"]["change_type"], "untracked")

    async def test_git_diff_supports_path_and_stage_filters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            _init_repo(cwd)
            _commit_file(cwd, "tracked.py", "print('one')\n", "initial commit")

            tracked = cwd / "tracked.py"
            staged = cwd / "staged.py"
            tracked.write_text("print('two')\n", encoding="utf-8")
            staged.write_text("print('staged')\n", encoding="utf-8")
            _run_git(cwd, "add", "-A", "--", "staged.py")

            tool = GitDiffTool(Config(cwd=cwd, api_key="test"))

            unstaged = await tool.execute(
                ToolInvocation(params={"unstaged_only": True, "path": "tracked.py"}, cwd=cwd)
            )
            self.assertTrue(unstaged.success, msg=unstaged.error)
            self.assertIn("tracked.py", unstaged.output)
            self.assertEqual(unstaged.metadata.get("selection"), "unstaged")
            self.assertEqual(unstaged.metadata["files"][0]["path"], "tracked.py")
            self.assertEqual(unstaged.metadata["files"][0]["stage_label"], "unstaged")

            staged_only = await tool.execute(
                ToolInvocation(params={"staged_only": True, "path": "staged.py"}, cwd=cwd)
            )
            self.assertTrue(staged_only.success, msg=staged_only.error)
            self.assertIn("staged.py", staged_only.output)
            self.assertEqual(staged_only.metadata.get("selection"), "staged")
            self.assertEqual(staged_only.metadata["files"][0]["path"], "staged.py")
            self.assertEqual(staged_only.metadata["files"][0]["stage_label"], "staged")

    async def test_git_status_exposes_publish_intent_without_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            remote = cwd / "remote.git"
            _init_repo(cwd)
            _commit_file(cwd, "app.py", "print('one')\n", "initial commit")
            subprocess.run(["git", "init", "--bare", str(remote)], check=False, capture_output=True, text=True)
            _run_git(cwd, "remote", "add", "origin", str(remote))

            tool = GitStatusTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(ToolInvocation(params={}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(result.metadata.get("needs_publish"), True)
            self.assertEqual(result.metadata.get("push_action"), "publish")
            self.assertIn("Publish required", result.output)

    async def test_git_log_returns_recent_commits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            _init_repo(cwd)
            _commit_file(cwd, "app.py", "print('one')\n", "initial commit")
            _commit_file(cwd, "app.py", "print('two')\n", "second commit")

            tool = GitLogTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(ToolInvocation(params={"limit": 2}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(result.metadata.get("count"), 2)
            self.assertEqual(result.metadata["commits"][0]["subject"], "second commit")

    async def test_git_branch_lists_and_creates_branches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            _init_repo(cwd)
            _commit_file(cwd, "app.py", "print('one')\n", "initial commit")

            tool = GitBranchTool(Config(cwd=cwd, api_key="test"))

            listing = await tool.execute(ToolInvocation(params={"action": "list"}, cwd=cwd))
            self.assertTrue(listing.success, msg=listing.error)
            self.assertTrue(listing.metadata.get("branches"))

            created = await tool.execute(
                ToolInvocation(params={"action": "create", "branch": "feature/test"}, cwd=cwd)
            )
            self.assertTrue(created.success, msg=created.error)
            self.assertEqual(created.metadata.get("current_branch"), "feature/test")

    async def test_git_commit_creates_commit_and_reports_sha(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            _init_repo(cwd)
            _commit_file(cwd, "app.py", "print('one')\n", "initial commit")
            (cwd / "app.py").write_text("print('two')\n", encoding="utf-8")
            _run_git(cwd, "add", "-A", "--", ".")

            tool = GitCommitTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(params={"message": "update app"}, cwd=cwd)
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(result.metadata.get("message"), "update app")
            self.assertTrue(result.metadata.get("sha"))
            head = _run_git(cwd, "log", "-1", "--format=%s").stdout.strip()
            self.assertEqual(head, "update app")

    async def test_git_push_fails_cleanly_without_remote(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            _init_repo(cwd)
            _commit_file(cwd, "app.py", "print('one')\n", "initial commit")

            tool = GitPushTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(ToolInvocation(params={}, cwd=cwd))

            self.assertFalse(result.success)
            self.assertIn("no git remote", (result.error or "").lower())

    async def test_git_tools_are_registered_in_default_registry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            registry = create_default_registry(Config(cwd=cwd, api_key="test"))
            tool_names = {tool.name for tool in registry.get_tools()}

            self.assertTrue(
                {"git_status", "git_diff", "git_log", "git_branch", "git_commit", "git_push"}.issubset(tool_names)
            )

    async def test_git_tools_fail_cleanly_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tool = GitStatusTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(ToolInvocation(params={}, cwd=cwd))

            self.assertFalse(result.success)
            self.assertIn("not a git repository", (result.error or "").lower())


if __name__ == "__main__":
    unittest.main()
