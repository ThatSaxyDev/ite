from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ite.agent.change_history import ChangeSet
from ite.tools.base import FileDiff


@dataclass
class GitWorkingTreeChangeSet:
    id: str
    label: str
    changes: list[FileDiff] = field(default_factory=list)
    staged_changes: list[FileDiff] = field(default_factory=list)
    unstaged_changes: list[FileDiff] = field(default_factory=list)
    untracked_changes: list[FileDiff] = field(default_factory=list)

    def stage_label_for(self, path: Path) -> str:
        rel = str(path)
        has_staged = any(str(diff.path) == rel for diff in self.staged_changes)
        has_unstaged = any(str(diff.path) == rel for diff in self.unstaged_changes)
        if has_staged and has_unstaged:
            return "staged + unstaged"
        if has_staged:
            return "staged"
        if has_unstaged:
            return "unstaged"
        return "working tree"

    @property
    def staged_count(self) -> int:
        return len(self.staged_changes)

    @property
    def unstaged_count(self) -> int:
        return len(self.unstaged_changes)

    @property
    def untracked_count(self) -> int:
        return len(self.untracked_changes)


@dataclass
class GitActionResult:
    ok: bool
    message: str


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _git_output(cwd: Path, *args: str) -> str:
    result = _run_git(cwd, *args)
    if result.returncode != 0:
        return ""
    return result.stdout


def _head_has_path(cwd: Path, path: str) -> bool:
    result = _run_git(cwd, "cat-file", "-e", f"HEAD:{path}")
    return result.returncode == 0


def _head_content(cwd: Path, path: str) -> str:
    return _git_output(cwd, "show", f"HEAD:{path}")


def _index_has_path(cwd: Path, path: str) -> bool:
    result = _run_git(cwd, "cat-file", "-e", f":{path}")
    return result.returncode == 0


def _index_content(cwd: Path, path: str) -> str:
    return _git_output(cwd, "show", f":{path}")


def _parse_status_entries(cwd: Path) -> list[tuple[str, str]]:
    result = _run_git(cwd, "status", "--porcelain", "-z")
    if result.returncode != 0 or not result.stdout:
        return []

    parts = result.stdout.split("\x00")
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        index += 1
        if not part:
            continue
        status = part[:2]
        path = part[3:]
        if status.startswith("R") or status.startswith("C"):
            if index < len(parts):
                path = parts[index]
                index += 1
        entries.append((status, path))
    return entries


def _expand_untracked_directory(cwd: Path, relative_dir: str) -> list[str]:
    result = _run_git(cwd, "ls-files", "--others", "--exclude-standard", "--", relative_dir)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _read_worktree_content(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _message_for(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def stage_path(cwd: Path, rel_path: str) -> GitActionResult:
    result = _run_git(cwd, "add", "-A", "--", rel_path)
    if result.returncode != 0:
        return GitActionResult(False, _message_for(result) or f"Failed to stage {rel_path}.")
    return GitActionResult(True, f"Staged {rel_path}.")


def unstage_path(cwd: Path, rel_path: str) -> GitActionResult:
    result = _run_git(cwd, "restore", "--staged", "--", rel_path)
    if result.returncode != 0:
        return GitActionResult(False, _message_for(result) or f"Failed to unstage {rel_path}.")
    return GitActionResult(True, f"Unstaged {rel_path}.")


def discard_path(cwd: Path, rel_path: str) -> GitActionResult:
    abs_path = (cwd / rel_path).resolve()
    if abs_path.exists() and not _head_has_path(cwd, rel_path) and not _index_has_path(cwd, rel_path):
        try:
            abs_path.unlink()
        except Exception as exc:
            return GitActionResult(False, f"Failed to remove {rel_path}: {exc}")
        return GitActionResult(True, f"Discarded {rel_path}.")

    result = _run_git(cwd, "restore", "--source=HEAD", "--staged", "--worktree", "--", rel_path)
    if result.returncode != 0:
        return GitActionResult(False, _message_for(result) or f"Failed to discard {rel_path}.")
    return GitActionResult(True, f"Discarded {rel_path}.")


def stage_all(cwd: Path) -> GitActionResult:
    result = _run_git(cwd, "add", "-A", "--", ".")
    if result.returncode != 0:
        return GitActionResult(False, _message_for(result) or "Failed to stage all changes.")
    return GitActionResult(True, "Staged all changes.")


def unstage_all(cwd: Path) -> GitActionResult:
    result = _run_git(cwd, "restore", "--staged", "--", ".")
    if result.returncode != 0:
        return GitActionResult(False, _message_for(result) or "Failed to unstage changes.")
    return GitActionResult(True, "Unstaged staged changes.")


def discard_all(cwd: Path) -> GitActionResult:
    restore = _run_git(cwd, "restore", "--source=HEAD", "--staged", "--worktree", "--", ".")
    if restore.returncode != 0:
        return GitActionResult(False, _message_for(restore) or "Failed to discard tracked changes.")
    clean = _run_git(cwd, "clean", "-fd", "--", ".")
    if clean.returncode != 0:
        return GitActionResult(False, _message_for(clean) or "Failed to remove untracked files.")
    return GitActionResult(True, "Discarded all changes.")


def _build_combined_diff(cwd: Path, rel_path: str, abs_path: Path) -> FileDiff | None:
    in_head = _head_has_path(cwd, rel_path)
    exists_now = abs_path.exists()

    if not in_head and exists_now:
        return FileDiff(
            path=abs_path,
            old_content="",
            new_content=_read_worktree_content(abs_path),
            is_new_file=True,
            is_deletion=False,
        )

    old_content = _head_content(cwd, rel_path) if in_head else ""
    if not exists_now:
        return FileDiff(
            path=abs_path,
            old_content=old_content,
            new_content="",
            is_new_file=False,
            is_deletion=True,
        )

    return FileDiff(
        path=abs_path,
        old_content=old_content,
        new_content=_read_worktree_content(abs_path),
        is_new_file=not in_head,
        is_deletion=False,
    )


def _build_staged_diff(cwd: Path, rel_path: str, abs_path: Path, status_x: str) -> FileDiff | None:
    if status_x in {" ", "?"}:
        return None

    in_head = _head_has_path(cwd, rel_path)
    in_index = _index_has_path(cwd, rel_path)
    if not in_index and status_x != "D":
        return None

    old_content = _head_content(cwd, rel_path) if in_head else ""

    if status_x == "D":
        return FileDiff(
            path=abs_path,
            old_content=old_content,
            new_content="",
            is_new_file=False,
            is_deletion=True,
        )

    new_content = _index_content(cwd, rel_path)
    return FileDiff(
        path=abs_path,
        old_content=old_content,
        new_content=new_content,
        is_new_file=not in_head,
        is_deletion=False,
    )


def _build_unstaged_diff(cwd: Path, rel_path: str, abs_path: Path, status_y: str, status: str) -> FileDiff | None:
    is_untracked = status == "??"
    if status_y == " " and not is_untracked:
        return None

    if is_untracked:
        if abs_path.is_dir() or not abs_path.exists():
            return None
        return FileDiff(
            path=abs_path,
            old_content="",
            new_content=_read_worktree_content(abs_path),
            is_new_file=True,
            is_deletion=False,
        )

    in_index = _index_has_path(cwd, rel_path)
    old_content = _index_content(cwd, rel_path) if in_index else ""

    if status_y == "D" or not abs_path.exists():
        return FileDiff(
            path=abs_path,
            old_content=old_content,
            new_content="",
            is_new_file=False,
            is_deletion=True,
        )

    return FileDiff(
        path=abs_path,
        old_content=old_content,
        new_content=_read_worktree_content(abs_path),
        is_new_file=not in_index,
        is_deletion=False,
    )


def working_tree_change_set(cwd: Path) -> GitWorkingTreeChangeSet | None:
    entries = _parse_status_entries(cwd)
    if not entries:
        return None

    combined_changes: list[FileDiff] = []
    staged_changes: list[FileDiff] = []
    unstaged_changes: list[FileDiff] = []
    untracked_changes: list[FileDiff] = []
    seen: set[str] = set()

    for status, raw_path in entries:
        candidate_paths = [raw_path.strip()]
        if status == "??" and raw_path.endswith("/"):
            candidate_paths = _expand_untracked_directory(cwd, raw_path.strip()) or []

        for rel_path in candidate_paths:
            if not rel_path or rel_path in seen:
                continue
            seen.add(rel_path)
            abs_path = (cwd / rel_path).resolve()
            if abs_path.is_dir():
                continue

            combined = _build_combined_diff(cwd, rel_path, abs_path)
            if combined is not None:
                combined_changes.append(combined)

            status_x = status[0]
            status_y = status[1]

            staged = _build_staged_diff(cwd, rel_path, abs_path, status_x)
            if staged is not None:
                staged_changes.append(staged)

            unstaged = _build_unstaged_diff(cwd, rel_path, abs_path, status_y, status)
            if unstaged is not None:
                unstaged_changes.append(unstaged)
                if status == "??":
                    untracked_changes.append(unstaged)

    if not combined_changes:
        return None

    return GitWorkingTreeChangeSet(
        id="working-tree",
        label="Working tree",
        changes=combined_changes,
        staged_changes=staged_changes,
        unstaged_changes=unstaged_changes,
        untracked_changes=untracked_changes,
    )
