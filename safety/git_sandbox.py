"""Git-based sandboxing: isolate agent changes on a temporary branch."""

import subprocess
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class GitSandboxError(Exception):
    """Raised when a git sandbox operation fails."""
    pass


class GitSandbox:
    """Manages a git sandbox branch for isolating agent changes.

    When activated:
    - Stashes uncommitted changes
    - Creates an `ite/sandbox-{timestamp}` branch
    - All agent edits happen on this branch
    - User can review via diff, then accept (merge) or reject (delete)
    """

    def __init__(self, cwd: Path):
        self.cwd = cwd
        self.original_branch: str | None = None
        self.sandbox_branch: str | None = None
        self.stashed: bool = False
        self.active: bool = False

    def _run_git(self, *args: str, check: bool = True) -> str:
        """Run a git command and return stdout."""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if check and result.returncode != 0:
                raise GitSandboxError(
                    f"git {' '.join(args)} failed: {result.stderr.strip()}"
                )
            return result.stdout.strip()
        except FileNotFoundError:
            raise GitSandboxError("git is not installed or not in PATH")
        except subprocess.TimeoutExpired:
            raise GitSandboxError(f"git {' '.join(args)} timed out")

    def is_git_repo(self) -> bool:
        """Check if cwd is inside a git repository."""
        try:
            self._run_git("rev-parse", "--is-inside-work-tree")
            return True
        except GitSandboxError:
            return False

    def start(self) -> str:
        """Start the git sandbox: stash changes and create sandbox branch."""
        if self.active:
            raise GitSandboxError("Git sandbox is already active")

        if not self.is_git_repo():
            raise GitSandboxError(
                "Not a git repository. Git sandboxing requires a git repo."
            )

        # Get current branch
        self.original_branch = self._run_git(
            "rev-parse", "--abbrev-ref", "HEAD"
        )

        # Stash uncommitted changes if any
        status = self._run_git("status", "--porcelain")
        if status:
            self._run_git("stash", "push", "-m", "ite-sandbox: auto-stash before sandbox")
            self.stashed = True

        # Create sandbox branch
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.sandbox_branch = f"ite/sandbox-{timestamp}"
        self._run_git("checkout", "-b", self.sandbox_branch)

        self.active = True
        return self.sandbox_branch

    def diff(self) -> str:
        """Get diff of changes made on the sandbox branch vs original."""
        if not self.active:
            raise GitSandboxError("Git sandbox is not active")

        # Stage everything (including new untracked files) so they appear in diff
        self._run_git("add", "-A", check=False)

        # Show full diff between original branch and current staged state
        diff = self._run_git(
            "diff", "--staged", self.original_branch, "--", ".", check=False
        )

        # Unstage so we don't alter the working state
        self._run_git("reset", "HEAD", check=False)

        return diff or "No changes detected."

    def accept(self) -> str:
        """Accept sandbox changes: commit, switch back, merge, cleanup."""
        if not self.active:
            raise GitSandboxError("Git sandbox is not active")

        # Stage and commit any uncommitted changes
        status = self._run_git("status", "--porcelain")
        if status:
            self._run_git("add", "-A")
            self._run_git(
                "commit", "-m", f"ite sandbox: changes from {self.sandbox_branch}"
            )

        # Switch back to original branch and merge
        self._run_git("checkout", self.original_branch)
        self._run_git("merge", self.sandbox_branch)

        # Delete sandbox branch
        self._run_git("branch", "-d", self.sandbox_branch)

        # Pop stash if we stashed
        if self.stashed:
            self._run_git("stash", "pop", check=False)
            self.stashed = False

        branch = self.sandbox_branch
        self.active = False
        self.sandbox_branch = None
        return f"Merged {branch} into {self.original_branch}"

    def reject(self) -> str:
        """Reject sandbox changes: discard branch, return to original."""
        if not self.active:
            raise GitSandboxError("Git sandbox is not active")

        # Discard any uncommitted changes
        self._run_git("checkout", "--", ".", check=False)
        self._run_git("clean", "-fd", check=False)

        # Switch back to original branch
        self._run_git("checkout", self.original_branch)

        # Delete sandbox branch
        self._run_git("branch", "-D", self.sandbox_branch)

        # Pop stash if we stashed
        if self.stashed:
            self._run_git("stash", "pop", check=False)
            self.stashed = False

        branch = self.sandbox_branch
        self.active = False
        self.sandbox_branch = None
        return f"Discarded {branch}, returned to {self.original_branch}"

    def status(self) -> dict:
        """Get current sandbox status."""
        return {
            "active": self.active,
            "original_branch": self.original_branch,
            "sandbox_branch": self.sandbox_branch,
            "stashed": self.stashed,
        }
