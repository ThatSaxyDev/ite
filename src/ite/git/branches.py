from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import re


@dataclass
class BranchInfo:
    name: str
    is_current: bool = False


@dataclass
class BranchResult:
    ok: bool
    message: str
    current_branch: str | None = None


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def is_git_repo(cwd: Path) -> bool:
    result = _run_git(cwd, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def current_branch(cwd: Path) -> str:
    symbolic = _run_git(cwd, "symbolic-ref", "--short", "HEAD")
    if symbolic.returncode == 0:
        return symbolic.stdout.strip()
    detached = _run_git(cwd, "rev-parse", "--short", "HEAD")
    if detached.returncode == 0:
        return f"detached:{detached.stdout.strip()}"
    return "unknown"


def list_local_branches(cwd: Path) -> list[BranchInfo]:
    result = _run_git(
        cwd,
        "for-each-ref",
        "refs/heads",
        "--sort=-committerdate",
        "--format=%(refname:short)\t%(HEAD)",
    )
    if result.returncode != 0:
        return []
    branches: list[BranchInfo] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        name = parts[0].strip()
        head_mark = parts[1].strip() if len(parts) > 1 else ""
        branches.append(BranchInfo(name=name, is_current=head_mark == "*"))
    return branches


def _is_valid_branch_name(name: str) -> bool:
    if not name or name != name.strip():
        return False
    if name in {".", ".."}:
        return False
    invalid_patterns = [
        r"\s",
        r"(^|/)\.",
        r"\.\.",
        r"@{",
        r"[~^:\?\*\[\\]",
        r"/$",
        r"\.lock$",
    ]
    return not any(re.search(pattern, name) for pattern in invalid_patterns)


def is_valid_branch_name(name: str) -> bool:
    return _is_valid_branch_name(name)


def checkout_branch(cwd: Path, branch: str) -> BranchResult:
    branch = branch.strip()
    if not _is_valid_branch_name(branch):
        return BranchResult(ok=False, message=f"Invalid branch name: {branch!r}")
    result = _run_git(cwd, "checkout", branch)
    if result.returncode != 0:
        return BranchResult(ok=False, message=(result.stderr or result.stdout).strip())
    return BranchResult(
        ok=True,
        message=f"Switched to branch '{branch}'",
        current_branch=current_branch(cwd),
    )


def create_and_checkout(cwd: Path, branch: str) -> BranchResult:
    branch = branch.strip()
    if not _is_valid_branch_name(branch):
        return BranchResult(ok=False, message=f"Invalid branch name: {branch!r}")
    result = _run_git(cwd, "checkout", "-b", branch)
    if result.returncode != 0:
        return BranchResult(ok=False, message=(result.stderr or result.stdout).strip())
    return BranchResult(
        ok=True,
        message=f"Created and switched to branch '{branch}'",
        current_branch=current_branch(cwd),
    )
