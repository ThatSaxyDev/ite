"""Git-based sandboxing: isolate agent changes on a temporary branch."""

import hashlib
import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from ite.config.loader import get_data_dir

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

    State is persisted to the app data directory so orphan branches
    can be recovered after an unclean shutdown.
    """

    def __init__(self, cwd: Path):
        self.cwd = cwd
        self.original_branch: str | None = None
        self.sandbox_branch: str | None = None
        self.stashed: bool = False
        self.active: bool = False

        # Try to restore state from disk
        self._load_state()

    # ── State persistence ──────────────────────────────────────────

    def _state_path(self) -> Path:
        """Per-project state file in the app data directory."""
        cwd_hash = hashlib.sha256(str(self.cwd).encode()).hexdigest()[:12]
        return get_data_dir() / "sandbox" / f"{cwd_hash}.json"

    def _save_state(self) -> None:
        """Persist sandbox state to disk."""
        state = {
            "active": self.active,
            "original_branch": self.original_branch,
            "sandbox_branch": self.sandbox_branch,
            "stashed": self.stashed,
        }
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2))

    def _clear_state(self) -> None:
        """Remove persisted state file."""
        path = self._state_path()
        if path.exists():
            path.unlink()

    def _load_state(self) -> None:
        """Restore sandbox state from disk if available."""
        path = self._state_path()
        if not path.exists():
            return

        try:
            state = json.loads(path.read_text())
            self.active = state.get("active", False)
            self.original_branch = state.get("original_branch")
            self.sandbox_branch = state.get("sandbox_branch")
            self.stashed = state.get("stashed", False)

            # Validate: if state says active, verify the branch still exists
            if self.active and self.sandbox_branch:
                try:
                    branches = self._run_git(
                        "branch", "--list", self.sandbox_branch, check=False
                    )
                    if not branches.strip():
                        # Branch was deleted externally
                        logger.warning(
                            "Sandbox branch %s no longer exists, clearing state",
                            self.sandbox_branch,
                        )
                        self._reset_state()
                        self._clear_state()
                except GitSandboxError:
                    self._reset_state()
                    self._clear_state()
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load sandbox state: %s", e)
            self._reset_state()
            self._clear_state()

    def _reset_state(self) -> None:
        """Reset all in-memory state to defaults."""
        self.active = False
        self.original_branch = None
        self.sandbox_branch = None
        self.stashed = False

    # ── Git helpers ────────────────────────────────────────────────

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

    def _current_branch(self) -> str:
        """Get the name of the currently checked-out branch."""
        return self._run_git("rev-parse", "--abbrev-ref", "HEAD")

    def is_git_repo(self) -> bool:
        """Check if cwd is inside a git repository."""
        try:
            self._run_git("rev-parse", "--is-inside-work-tree")
            return True
        except GitSandboxError:
            return False

    # ── Recovery ───────────────────────────────────────────────────

    def check_recovery(self) -> dict | None:
        """Check if there's an orphan sandbox that needs recovery.

        Returns a dict with recovery info, or None if clean.
        """
        if not self.active:
            return None

        current = self._current_branch()

        # We have saved state — are we still on the sandbox branch?
        if current == self.sandbox_branch:
            return {
                "status": "active",
                "sandbox_branch": self.sandbox_branch,
                "original_branch": self.original_branch,
                "stashed": self.stashed,
                "message": (
                    f"Found active sandbox: {self.sandbox_branch} "
                    f"(branched from {self.original_branch}). "
                    "Use /sandbox accept, /sandbox reject, or /sandbox diff."
                ),
            }

        # We're NOT on the sandbox branch but state says active
        # This means someone manually switched branches
        return {
            "status": "orphaned",
            "sandbox_branch": self.sandbox_branch,
            "original_branch": self.original_branch,
            "current_branch": current,
            "stashed": self.stashed,
            "message": (
                f"Orphaned sandbox detected: {self.sandbox_branch} exists "
                f"but you're on {current}. "
                "Use /sandbox reject to clean up, or /sandbox accept to merge."
            ),
        }

    # ── Core operations ────────────────────────────────────────────

    def start(self) -> str:
        """Start the git sandbox: stash changes and create sandbox branch."""
        if self.active:
            raise GitSandboxError(
                f"Git sandbox is already active on {self.sandbox_branch}. "
                "Use /sandbox accept or /sandbox reject first."
            )

        if not self.is_git_repo():
            raise GitSandboxError(
                "Not a git repository. Git sandboxing requires a git repo."
            )

        # Prevent nesting: block if already on an ite/sandbox-* branch
        current = self._current_branch()
        if current.startswith("ite/sandbox-"):
            raise GitSandboxError(
                f"Already on sandbox branch {current}. "
                "Cannot nest sandboxes. Use /sandbox accept or /sandbox reject first."
            )

        # Get current branch
        self.original_branch = current

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
        self._save_state()
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
        self._reset_state()
        self._clear_state()
        return f"Merged {branch} into {self.original_branch}"

    def reject(self) -> str:
        """Reject sandbox changes: discard branch, return to original."""
        if not self.active:
            raise GitSandboxError("Git sandbox is not active")

        current = self._current_branch()

        # If we're on the sandbox branch, discard changes and switch back
        if current == self.sandbox_branch:
            self._run_git("checkout", "--", ".", check=False)
            self._run_git("clean", "-fd", check=False)
            self._run_git("checkout", self.original_branch)

        # Delete sandbox branch (force in case of unmerged changes)
        try:
            self._run_git("branch", "-D", self.sandbox_branch)
        except GitSandboxError:
            logger.warning("Could not delete branch %s", self.sandbox_branch)

        # Pop stash if we stashed
        if self.stashed:
            self._run_git("stash", "pop", check=False)
            self.stashed = False

        branch = self.sandbox_branch
        original = self.original_branch
        self._reset_state()
        self._clear_state()
        return f"Discarded {branch}, returned to {original}"

    def status(self) -> dict:
        """Get current sandbox status."""
        return {
            "active": self.active,
            "original_branch": self.original_branch,
            "sandbox_branch": self.sandbox_branch,
            "stashed": self.stashed,
        }
