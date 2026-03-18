from __future__ import annotations

import subprocess
from pathlib import Path

from ite.agent.change_history import ChangeSet
from ite.tools.base import FileDiff


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


def working_tree_change_set(cwd: Path) -> ChangeSet | None:
    entries = _parse_status_entries(cwd)
    if not entries:
        return None

    changes: list[FileDiff] = []
    seen: set[str] = set()
    for status, raw_path in entries:
        candidate_paths = [raw_path.strip()]
        if status == "??" and raw_path.endswith("/"):
            candidate_paths = _expand_untracked_directory(cwd, raw_path.strip()) or []

        for path in candidate_paths:
            if not path or path in seen:
                continue
            seen.add(path)
            abs_path = (cwd / path).resolve()
            if abs_path.is_dir():
                continue

            in_head = _head_has_path(cwd, path)
            exists_now = abs_path.exists()

            if not in_head and exists_now:
                new_content = abs_path.read_text(encoding="utf-8", errors="replace")
                changes.append(
                    FileDiff(
                        path=abs_path,
                        old_content="",
                        new_content=new_content,
                        is_new_file=True,
                        is_deletion=False,
                    )
                )
                continue

            old_content = _head_content(cwd, path) if in_head else ""
            if not exists_now:
                changes.append(
                    FileDiff(
                        path=abs_path,
                        old_content=old_content,
                        new_content="",
                        is_new_file=False,
                        is_deletion=True,
                    )
                )
                continue

            new_content = abs_path.read_text(encoding="utf-8", errors="replace")
            changes.append(
                FileDiff(
                    path=abs_path,
                    old_content=old_content,
                    new_content=new_content,
                    is_new_file=not in_head,
                    is_deletion=False,
                )
            )

    if not changes:
        return None

    return ChangeSet(
        id="working-tree",
        label="Working tree",
        changes=changes,
    )
