from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
import shutil

from ite.agent.change_history import ChangeSet
from ite.tools.base import FileDiff

_BINARY_BASELINE = "[Binary file contents omitted]\n"
_BINARY_ADDED = "[Binary file added]\n"
_BINARY_STAGED = "[Binary file staged in index]\n"
_BINARY_WORKTREE = "[Binary file modified in working tree]\n"


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


@dataclass
class GitOutboundState:
    branch: str
    upstream: str | None
    remote_name: str | None
    ahead_count: int = 0
    behind_count: int = 0

    @property
    def has_upstream(self) -> bool:
        return bool(self.upstream)

    @property
    def has_remote(self) -> bool:
        return bool(self.remote_name)

    @property
    def has_outgoing(self) -> bool:
        return self.ahead_count > 0

    @property
    def needs_attention(self) -> bool:
        return self.needs_publish or self.has_outgoing

    @property
    def needs_publish(self) -> bool:
        return not self.has_upstream

    @property
    def needs_remote_setup(self) -> bool:
        return self.needs_publish and not self.has_remote

    @property
    def action_label(self) -> str:
        return "publish" if self.needs_publish else "push"

    @property
    def target_label(self) -> str:
        if self.upstream:
            return self.upstream
        if self.remote_name:
            return f"{self.remote_name}/{self.branch}"
        if self.needs_publish:
            return "configure a remote"
        return self.branch


def _run_git(
    cwd: Path, *args: str, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            start_new_session=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        result = subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="git not found")
        return result
    except subprocess.TimeoutExpired as exc:
        result = subprocess.CompletedProcess(
            args,
            returncode=124,
            stdout=str(exc.stdout or ""),
            stderr="git command timed out",
        )
        return result


def _run_git_bytes(
    cwd: Path, *args: str, timeout: float | None = None
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            check=False,
            start_new_session=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        result = subprocess.CompletedProcess(args, returncode=1, stdout=b"", stderr=b"git not found")
        return result
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
        result = subprocess.CompletedProcess(
            args,
            returncode=124,
            stdout=stdout,
            stderr=b"git command timed out",
        )
        return result


def _git_output(cwd: Path, *args: str, timeout: float | None = None) -> str:
    result = _run_git(cwd, *args, timeout=timeout)
    if result.returncode != 0:
        return ""
    return result.stdout


def _head_has_path(cwd: Path, path: str, *, timeout: float | None = None) -> bool:
    result = _run_git(cwd, "cat-file", "-e", f"HEAD:{path}", timeout=timeout)
    return result.returncode == 0


def _looks_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _git_blob_content(
    cwd: Path,
    pathspec: str,
    *,
    binary_placeholder: str = _BINARY_BASELINE,
    timeout: float | None = None,
) -> str:
    result = _run_git_bytes(cwd, "show", pathspec, timeout=timeout)
    if result.returncode != 0:
        return ""
    if _looks_binary(result.stdout):
        return binary_placeholder
    return result.stdout.decode("utf-8", errors="replace")


def _head_content(
    cwd: Path,
    path: str,
    *,
    binary_placeholder: str = _BINARY_BASELINE,
    timeout: float | None = None,
) -> str:
    return _git_blob_content(
        cwd,
        f"HEAD:{path}",
        binary_placeholder=binary_placeholder,
        timeout=timeout,
    )


def _index_has_path(cwd: Path, path: str, *, timeout: float | None = None) -> bool:
    result = _run_git(cwd, "cat-file", "-e", f":{path}", timeout=timeout)
    return result.returncode == 0


def _index_content(
    cwd: Path,
    path: str,
    *,
    binary_placeholder: str = _BINARY_BASELINE,
    timeout: float | None = None,
) -> str:
    return _git_blob_content(
        cwd,
        f":{path}",
        binary_placeholder=binary_placeholder,
        timeout=timeout,
    )


def _parse_status_entries(cwd: Path, *, timeout: float | None = None) -> list[tuple[str, str]]:
    result = _run_git(cwd, "status", "--porcelain", "-z", timeout=timeout)
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


def _expand_untracked_directory(
    cwd: Path, relative_dir: str, *, timeout: float | None = None
) -> list[str]:
    result = _run_git(
        cwd,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        relative_dir,
        timeout=timeout,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _read_worktree_content(path: Path, *, binary_placeholder: str = _BINARY_BASELINE) -> str:
    data = path.read_bytes()
    if _looks_binary(data):
        return binary_placeholder
    return data.decode("utf-8", errors="replace")


def _message_for(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def _friendly_push_error(message: str) -> str:
    text = (message or "").strip()
    lowered = text.lower()
    if "index.lock" in text:
        return "Git is locked by another process. Close the other git operation or remove the stale .git/index.lock file, then try again."
    if "could not read from remote repository" in lowered or "permission denied" in lowered:
        return "Push failed because Git could not authenticate with the remote repository."
    if "repository not found" in lowered:
        return "Push failed because the remote repository could not be found."
    if "set the remote as upstream" in lowered or "no upstream branch" in lowered:
        return "This branch is not published yet. Publish it first so Git can track the remote branch."
    if "non-fast-forward" in lowered or "fetch first" in lowered or "rejected" in lowered:
        return "Push was rejected because the remote branch has newer commits. Pull or rebase first, then push again."
    if "network" in lowered or "could not resolve host" in lowered or "failed to connect" in lowered:
        return "Push failed because the remote could not be reached."
    return text or "Push failed."


def git_outbound_state(cwd: Path, *, timeout: float | None = None) -> GitOutboundState | None:
    try:
        branch = _git_output(
            cwd, "rev-parse", "--abbrev-ref", "HEAD", timeout=timeout
        ).strip()
    except FileNotFoundError:
        return None
    if not branch or branch == "HEAD":
        return None

    remotes = [
        line.strip()
        for line in _git_output(cwd, "remote", timeout=timeout).splitlines()
        if line.strip()
    ]
    upstream_result = _run_git(
        cwd,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{u}",
        timeout=timeout,
    )
    upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else None
    remote_name: str | None = None
    ahead = 0
    behind = 0

    if upstream:
        remote_name = upstream.split("/", 1)[0]
        counts = _git_output(
            cwd,
            "rev-list",
            "--left-right",
            "--count",
            f"HEAD...{upstream}",
            timeout=timeout,
        ).strip()
        if counts:
            left, right = (counts.split() + ["0", "0"])[:2]
            try:
                ahead = int(left)
            except ValueError:
                ahead = 0
            try:
                behind = int(right)
            except ValueError:
                behind = 0
    elif remotes:
        remote_name = "origin" if "origin" in remotes else remotes[0]
        local_only = _git_output(
            cwd,
            "rev-list",
            "--count",
            "HEAD",
            "--not",
            "--remotes",
            timeout=timeout,
        ).strip()
        try:
            ahead = int(local_only)
        except ValueError:
            ahead = 0

    return GitOutboundState(
        branch=branch,
        upstream=upstream,
        remote_name=remote_name,
        ahead_count=ahead,
        behind_count=behind,
    )


def outbound_commit_subjects(cwd: Path, *, limit: int = 8) -> list[str]:
    outbound = git_outbound_state(cwd)
    if outbound is None or limit <= 0:
        return []

    if outbound.has_upstream:
        result = _run_git(cwd, "log", "--format=%s", f"{outbound.upstream}..HEAD", f"-n{limit}")
    else:
        result = _run_git(cwd, "log", "--format=%s", "HEAD", "--not", "--remotes", f"-n{limit}")

    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


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
    untracked_paths: list[str] = []
    for status, raw_path in _parse_status_entries(cwd):
        if status != "??":
            continue
        rel_path = raw_path.rstrip("/")
        abs_path = (cwd / rel_path).resolve()
        if raw_path.endswith("/") or abs_path.is_dir():
            untracked_paths.extend(_expand_untracked_directory(cwd, raw_path))
        else:
            untracked_paths.append(rel_path)

    tracked_restore = _run_git(cwd, "restore", "--source=HEAD", "--staged", "--worktree", "--", ".")

    remove_errors: list[str] = []
    seen: set[str] = set()
    for rel_path in untracked_paths:
        if rel_path in seen:
            continue
        seen.add(rel_path)
        abs_path = (cwd / rel_path).resolve()
        try:
            _remove_path(abs_path)
        except Exception as exc:
            remove_errors.append(f"{rel_path}: {exc}")

    if tracked_restore.returncode != 0 and remove_errors:
        return GitActionResult(
            False,
            (
                (_message_for(tracked_restore) or "Failed to discard tracked changes.")
                + " Also failed to remove some untracked files: "
                + "; ".join(remove_errors)
            ),
        )
    if tracked_restore.returncode != 0:
        return GitActionResult(False, _message_for(tracked_restore) or "Failed to discard tracked changes.")
    if remove_errors:
        return GitActionResult(False, "Failed to remove some untracked files: " + "; ".join(remove_errors))
    return GitActionResult(True, "Discarded all changes.")


def _has_staged_changes(cwd: Path) -> bool:
    result = _run_git(cwd, "diff", "--cached", "--quiet", "--exit-code")
    return result.returncode == 1


def commit_changes(
    cwd: Path,
    *,
    message: str,
    include_unstaged: bool = False,
    push: bool = False,
) -> GitActionResult:
    commit_message = message.strip() or "Update files"

    if include_unstaged:
        stage_result = _run_git(cwd, "add", "-A", "--", ".")
        if stage_result.returncode != 0:
            return GitActionResult(
                False,
                _message_for(stage_result) or "Failed to stage working tree changes before commit.",
            )

    if not _has_staged_changes(cwd):
        return GitActionResult(False, "No staged changes to commit.")

    commit_result = _run_git(cwd, "commit", "-m", commit_message)
    if commit_result.returncode != 0:
        return GitActionResult(
            False,
            _message_for(commit_result) or "Failed to create commit.",
        )

    if push:
        push_result = _run_git(cwd, "push")
        if push_result.returncode != 0:
            return GitActionResult(
                False,
                _message_for(push_result) or "Commit created, but push failed.",
            )
        return GitActionResult(True, "Committed and pushed changes.")

    return GitActionResult(True, "Committed changes.")


def push_current_branch(cwd: Path) -> GitActionResult:
    outbound = git_outbound_state(cwd)
    if outbound is None:
        return GitActionResult(False, "Cannot push from a detached HEAD.")
    if not outbound.has_remote:
        return GitActionResult(False, "No git remote is configured for this repository.")
    if outbound.has_upstream:
        result = _run_git(cwd, "push")
        if result.returncode != 0:
            return GitActionResult(False, _friendly_push_error(_message_for(result)))
        count = outbound.ahead_count
        noun = "commit" if count == 1 else "commits"
        return GitActionResult(True, f"Pushed {count} {noun} from {outbound.branch}.")

    result = _run_git(cwd, "push", "-u", outbound.remote_name or "origin", "HEAD")
    if result.returncode != 0:
        return GitActionResult(False, _friendly_push_error(_message_for(result)))
    count = outbound.ahead_count
    noun = "commit" if count == 1 else "commits"
    return GitActionResult(True, f"Published {outbound.branch} to {outbound.remote_name} with {count} {noun}.")


def _build_combined_diff(
    cwd: Path, rel_path: str, abs_path: Path, *, timeout: float | None = None
) -> FileDiff | None:
    in_head = _head_has_path(cwd, rel_path, timeout=timeout)
    exists_now = abs_path.exists()

    if not in_head and exists_now:
        return FileDiff(
            path=abs_path,
            old_content="",
            new_content=_read_worktree_content(abs_path, binary_placeholder=_BINARY_ADDED),
            is_new_file=True,
            is_deletion=False,
        )

    old_content = _head_content(cwd, rel_path, timeout=timeout) if in_head else ""
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
        new_content=_read_worktree_content(abs_path, binary_placeholder=_BINARY_WORKTREE),
        is_new_file=not in_head,
        is_deletion=False,
    )


def _build_staged_diff(
    cwd: Path,
    rel_path: str,
    abs_path: Path,
    status_x: str,
    *,
    timeout: float | None = None,
) -> FileDiff | None:
    if status_x in {" ", "?"}:
        return None

    in_head = _head_has_path(cwd, rel_path, timeout=timeout)
    in_index = _index_has_path(cwd, rel_path, timeout=timeout)
    if not in_index and status_x != "D":
        return None

    old_content = _head_content(cwd, rel_path, timeout=timeout) if in_head else ""

    if status_x == "D":
        return FileDiff(
            path=abs_path,
            old_content=old_content,
            new_content="",
            is_new_file=False,
            is_deletion=True,
        )

    new_content = _index_content(
        cwd,
        rel_path,
        binary_placeholder=_BINARY_STAGED,
        timeout=timeout,
    )
    return FileDiff(
        path=abs_path,
        old_content=old_content,
        new_content=new_content,
        is_new_file=not in_head,
        is_deletion=False,
    )


def _build_unstaged_diff(
    cwd: Path,
    rel_path: str,
    abs_path: Path,
    status_y: str,
    status: str,
    *,
    timeout: float | None = None,
) -> FileDiff | None:
    is_untracked = status == "??"
    if status_y == " " and not is_untracked:
        return None

    if is_untracked:
        if abs_path.is_dir() or not abs_path.exists():
            return None
        return FileDiff(
            path=abs_path,
            old_content="",
            new_content=_read_worktree_content(abs_path, binary_placeholder=_BINARY_ADDED),
            is_new_file=True,
            is_deletion=False,
        )

    in_index = _index_has_path(cwd, rel_path, timeout=timeout)
    old_content = _index_content(cwd, rel_path, timeout=timeout) if in_index else ""

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
        new_content=_read_worktree_content(abs_path, binary_placeholder=_BINARY_WORKTREE),
        is_new_file=not in_index,
        is_deletion=False,
    )


def working_tree_change_set(
    cwd: Path, *, timeout: float | None = None
) -> GitWorkingTreeChangeSet | None:
    entries = _parse_status_entries(cwd, timeout=timeout)
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
            candidate_paths = (
                _expand_untracked_directory(cwd, raw_path.strip(), timeout=timeout)
                or []
            )

        for rel_path in candidate_paths:
            if not rel_path or rel_path in seen:
                continue
            seen.add(rel_path)
            abs_path = (cwd / rel_path).resolve()
            if abs_path.is_dir():
                continue

            combined = _build_combined_diff(
                cwd, rel_path, abs_path, timeout=timeout
            )
            if combined is not None:
                combined_changes.append(combined)

            status_x = status[0]
            status_y = status[1]

            staged = _build_staged_diff(
                cwd, rel_path, abs_path, status_x, timeout=timeout
            )
            if staged is not None:
                staged_changes.append(staged)

            unstaged = _build_unstaged_diff(
                cwd, rel_path, abs_path, status_y, status, timeout=timeout
            )
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
