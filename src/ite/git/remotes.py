from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ite.git.working_tree import GitActionResult


@dataclass(frozen=True)
class GitRemoteInfo:
    name: str
    url: str


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        result = subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="git not found")
        return result


def _message_for(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def list_remotes(cwd: Path) -> list[GitRemoteInfo]:
    names_result = _run_git(cwd, "remote")
    if names_result.returncode != 0:
        return []

    remotes: list[GitRemoteInfo] = []
    for raw_name in names_result.stdout.splitlines():
        name = raw_name.strip()
        if not name:
            continue
        url_result = _run_git(cwd, "remote", "get-url", name)
        if url_result.returncode != 0:
            continue
        url = url_result.stdout.strip()
        if url:
            remotes.append(GitRemoteInfo(name=name, url=url))
    return remotes


def remote_exists(cwd: Path, name: str) -> bool:
    target = name.strip()
    if not target:
        return False
    return any(remote.name == target for remote in list_remotes(cwd))


def get_remote_url(cwd: Path, name: str) -> str | None:
    target = name.strip()
    if not target:
        return None
    result = _run_git(cwd, "remote", "get-url", target)
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    return url or None


def add_remote(cwd: Path, name: str, url: str) -> GitActionResult:
    remote_name = name.strip()
    remote_url = url.strip()
    if not remote_name:
        return GitActionResult(False, "Remote name is required.")
    if not remote_url:
        return GitActionResult(False, "Remote URL is required.")
    if remote_exists(cwd, remote_name):
        return GitActionResult(False, f"Remote {remote_name} already exists.")

    result = _run_git(cwd, "remote", "add", remote_name, remote_url)
    if result.returncode != 0:
        return GitActionResult(
            False,
            _message_for(result) or f"Failed to add remote {remote_name}.",
        )
    return GitActionResult(True, f"Added remote {remote_name}.")


def set_remote_url(cwd: Path, name: str, url: str) -> GitActionResult:
    remote_name = name.strip()
    remote_url = url.strip()
    if not remote_name:
        return GitActionResult(False, "Remote name is required.")
    if not remote_url:
        return GitActionResult(False, "Remote URL is required.")
    if not remote_exists(cwd, remote_name):
        return GitActionResult(False, f"Remote {remote_name} does not exist.")

    result = _run_git(cwd, "remote", "set-url", remote_name, remote_url)
    if result.returncode != 0:
        return GitActionResult(
            False,
            _message_for(result) or f"Failed to update remote {remote_name}.",
        )
    return GitActionResult(True, f"Updated remote {remote_name}.")


def upsert_remote(cwd: Path, name: str, url: str) -> GitActionResult:
    remote_name = name.strip()
    remote_url = url.strip()
    if not remote_name:
        return GitActionResult(False, "Remote name is required.")
    if not remote_url:
        return GitActionResult(False, "Remote URL is required.")

    current_url = get_remote_url(cwd, remote_name)
    if current_url == remote_url:
        return GitActionResult(True, f"Remote {remote_name} is already configured.")
    if current_url is not None:
        return set_remote_url(cwd, remote_name, remote_url)
    return add_remote(cwd, remote_name, remote_url)
