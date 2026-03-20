from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ite.git.branches import (
    checkout_branch,
    create_and_checkout,
    current_branch,
    is_git_repo,
    list_local_branches,
)
from ite.git.working_tree import (
    commit_changes,
    git_outbound_state,
    push_current_branch,
    working_tree_change_set,
)
from ite.tools.base import (
    Tool,
    ToolConfirmation,
    ToolInvocation,
    ToolKind,
    ToolMetadata,
    ToolResult,
    ToolRiskLevel,
)


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _ensure_repo(cwd: Path) -> ToolResult | None:
    if not is_git_repo(cwd):
        return ToolResult.error_result("Current workspace is not a git repository.")
    return None


def _rel_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.resolve().relative_to(cwd.resolve()))
    except Exception:
        return str(path)


def _build_file_entries(change_set: Any | None, cwd: Path) -> list[dict[str, Any]]:
    if change_set is None:
        return []

    staged = {_rel_path(diff.path, cwd) for diff in getattr(change_set, "staged_changes", [])}
    unstaged = {_rel_path(diff.path, cwd) for diff in getattr(change_set, "unstaged_changes", [])}
    untracked = {_rel_path(diff.path, cwd) for diff in getattr(change_set, "untracked_changes", [])}
    combined = getattr(change_set, "changes", []) or []

    entries: list[dict[str, Any]] = []
    for diff in combined:
        rel = _rel_path(diff.path, cwd)
        if rel in staged and rel in unstaged:
            stage_label = "staged + unstaged"
        elif rel in staged:
            stage_label = "staged"
        elif rel in unstaged:
            stage_label = "unstaged"
        else:
            stage_label = "working tree"

        if rel in untracked:
            change_type = "untracked"
        elif getattr(diff, "is_new_file", False):
            change_type = "new"
        elif getattr(diff, "is_deletion", False):
            change_type = "deleted"
        else:
            change_type = "modified"

        entries.append(
            {
                "path": rel,
                "stage_label": stage_label,
                "change_type": change_type,
                "staged": rel in staged,
                "unstaged": rel in unstaged,
                "untracked": rel in untracked,
                "is_new_file": bool(getattr(diff, "is_new_file", False)),
                "is_deletion": bool(getattr(diff, "is_deletion", False)),
            }
        )
    return entries


class GitStatusParams(BaseModel):
    include_diff_summary: bool = Field(
        True,
        description="Include staged/unstaged/untracked file lists in the output.",
    )


class GitDiffParams(BaseModel):
    path: str | None = Field(
        None,
        description="Optional repo-relative path to limit the diff to a single file.",
    )
    staged_only: bool = Field(
        False,
        description="Only return the staged diff.",
    )
    unstaged_only: bool = Field(
        False,
        description="Only return the unstaged diff.",
    )

    @model_validator(mode="after")
    def _validate_flags(self) -> "GitDiffParams":
        if self.staged_only and self.unstaged_only:
            raise ValueError("staged_only and unstaged_only cannot both be true")
        return self


class GitLogParams(BaseModel):
    limit: int = Field(
        10,
        ge=1,
        le=50,
        description="Maximum number of commits to return.",
    )
    ref: str = Field(
        "HEAD",
        description="Git revision or ref to inspect.",
    )


class GitBranchParams(BaseModel):
    action: str = Field(
        "list",
        description="Branch action: list, switch, or create.",
    )
    branch: str | None = Field(
        None,
        description="Branch name for switch/create actions.",
    )

    @model_validator(mode="after")
    def _validate_branch_requirements(self) -> "GitBranchParams":
        action = self.action.strip().lower()
        if action not in {"list", "switch", "create"}:
            raise ValueError("action must be one of: list, switch, create")
        if action in {"switch", "create"} and not (self.branch or "").strip():
            raise ValueError("branch is required for switch/create actions")
        return self


class GitCommitParams(BaseModel):
    message: str = Field(
        ...,
        description="Commit message to create.",
    )
    include_unstaged: bool = Field(
        False,
        description="Stage all current working tree changes before committing.",
    )
    push: bool = Field(
        False,
        description="Push after creating the commit.",
    )


class GitPushParams(BaseModel):
    pass


class GitStatusTool(Tool):
    name = "git_status"
    description = "Inspect the current repository state including branch, upstream, and working tree changes."
    kind = ToolKind.READ
    schema = GitStatusParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=False,
            risk_level=ToolRiskLevel.LOW,
            allowed_in_plan_mode=True,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GitStatusParams(**invocation.params)
        cwd = invocation.cwd.resolve()

        sandbox_error = self._sandbox_check(cwd, invocation.cwd)
        if sandbox_error:
            return sandbox_error

        repo_error = _ensure_repo(cwd)
        if repo_error:
            return repo_error

        branch = current_branch(cwd)
        outbound = git_outbound_state(cwd)
        change_set = working_tree_change_set(cwd)
        file_entries = _build_file_entries(change_set, cwd)
        staged = [_rel_path(diff.path, cwd) for diff in getattr(change_set, "staged_changes", [])]
        unstaged = [_rel_path(diff.path, cwd) for diff in getattr(change_set, "unstaged_changes", [])]
        untracked = [_rel_path(diff.path, cwd) for diff in getattr(change_set, "untracked_changes", [])]
        clean = change_set is None

        lines = [f"Branch: {branch}"]
        if outbound and outbound.has_upstream:
            lines.append(
                f"Upstream: {outbound.upstream} (ahead {outbound.ahead_count}, behind {outbound.behind_count})"
            )
        elif outbound and outbound.has_remote:
            lines.append(f"Remote: {outbound.remote_name} (not published)")
        else:
            lines.append("Remote: none")

        if outbound and outbound.needs_publish:
            if outbound.needs_remote_setup:
                lines.append("Publish required: configure a remote for this repository")
            else:
                lines.append(f"Publish required: {outbound.target_label}")
        elif outbound and outbound.has_outgoing:
            lines.append(f"Push available: {outbound.ahead_count} outgoing commit(s)")

        if clean:
            lines.append("Working tree: clean")
        else:
            lines.append(
                f"Working tree: {len(staged)} staged, {len(unstaged)} unstaged, {len(untracked)} untracked"
            )
            if params.include_diff_summary:
                if staged:
                    lines.append("Staged:")
                    lines.extend(f"  - {path}" for path in staged)
                if unstaged:
                    lines.append("Unstaged:")
                    lines.extend(f"  - {path}" for path in unstaged)
                if untracked:
                    lines.append("Untracked:")
                    lines.extend(f"  - {path}" for path in untracked)

        metadata = {
            "branch": branch,
            "clean": clean,
            "upstream": outbound.upstream if outbound else None,
            "remote_name": outbound.remote_name if outbound else None,
            "ahead_count": outbound.ahead_count if outbound else 0,
            "behind_count": outbound.behind_count if outbound else 0,
            "has_remote": outbound.has_remote if outbound else False,
            "has_upstream": outbound.has_upstream if outbound else False,
            "needs_publish": outbound.needs_publish if outbound else False,
            "needs_remote_setup": outbound.needs_remote_setup if outbound else False,
            "has_outgoing": outbound.has_outgoing if outbound else False,
            "push_action": outbound.action_label if outbound else "push",
            "push_target": outbound.target_label if outbound else branch,
            "staged_files": staged,
            "unstaged_files": unstaged,
            "untracked_files": untracked,
            "files": file_entries,
        }
        return ToolResult.success_result("\n".join(lines), metadata=metadata)


class GitDiffTool(Tool):
    name = "git_diff"
    description = "Return working tree diffs with optional staged or unstaged filtering."
    kind = ToolKind.READ
    schema = GitDiffParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=False,
            risk_level=ToolRiskLevel.LOW,
            allowed_in_plan_mode=True,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GitDiffParams(**invocation.params)
        cwd = invocation.cwd.resolve()

        sandbox_error = self._sandbox_check(cwd, invocation.cwd)
        if sandbox_error:
            return sandbox_error

        repo_error = _ensure_repo(cwd)
        if repo_error:
            return repo_error

        change_set = working_tree_change_set(cwd)
        if change_set is None:
            return ToolResult.success_result(
                "No working tree changes.",
                metadata={"changed_files": [], "diff_count": 0},
            )

        if params.staged_only:
            diffs = list(change_set.staged_changes)
            selection = "staged"
        elif params.unstaged_only:
            diffs = list(change_set.unstaged_changes)
            selection = "unstaged"
        else:
            diffs = list(change_set.changes)
            selection = "combined"

        if params.path:
            requested = params.path.strip().lstrip("./")
            diffs = [diff for diff in diffs if _rel_path(diff.path, cwd) == requested]

        if not diffs:
            label = params.path.strip() if params.path else selection
            return ToolResult.success_result(
                f"No {selection} diff found for {label}.",
                metadata={"changed_files": [], "diff_count": 0, "selection": selection},
            )

        all_file_entries = {entry["path"]: entry for entry in _build_file_entries(change_set, cwd)}
        changed_files = [_rel_path(diff.path, cwd) for diff in diffs]
        selected_entries = [all_file_entries[path] for path in changed_files if path in all_file_entries]
        output = "\n\n".join(diff.to_diff().rstrip() for diff in diffs if diff.to_diff().strip())
        return ToolResult.success_result(
            output or "No diff output available.",
            metadata={
                "changed_files": changed_files,
                "diff_count": len(diffs),
                "selection": selection,
                "files": selected_entries,
            },
            file_diffs=diffs,
        )


class GitLogTool(Tool):
    name = "git_log"
    description = "Inspect recent commit history for the current repository."
    kind = ToolKind.READ
    schema = GitLogParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=False,
            risk_level=ToolRiskLevel.LOW,
            allowed_in_plan_mode=True,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GitLogParams(**invocation.params)
        cwd = invocation.cwd.resolve()

        sandbox_error = self._sandbox_check(cwd, invocation.cwd)
        if sandbox_error:
            return sandbox_error

        repo_error = _ensure_repo(cwd)
        if repo_error:
            return repo_error

        result = _run_git(
            cwd,
            "log",
            f"-n{params.limit}",
            "--date=short",
            "--format=%H%x1f%h%x1f%ad%x1f%an%x1f%s",
            params.ref,
        )
        if result.returncode != 0:
            return ToolResult.error_result((result.stderr or result.stdout).strip() or "Failed to read git history.")

        commits: list[dict[str, str]] = []
        lines = []
        for raw in result.stdout.splitlines():
            if not raw.strip():
                continue
            full_sha, short_sha, date, author, subject = (raw.split("\x1f") + ["", "", "", "", ""])[:5]
            commits.append(
                {
                    "sha": full_sha,
                    "short_sha": short_sha,
                    "date": date,
                    "author": author,
                    "subject": subject,
                }
            )
            lines.append(f"{short_sha}  {date}  {author}  {subject}")

        return ToolResult.success_result(
            "\n".join(lines) if lines else "No commits found.",
            metadata={"commits": commits, "count": len(commits), "ref": params.ref},
        )


class GitBranchTool(Tool):
    name = "git_branch"
    description = "List, create, or switch local git branches."
    kind = ToolKind.WRITE
    schema = GitBranchParams

    def is_mutating(self, params: dict[str, Any]) -> bool:
        try:
            payload = GitBranchParams(**params)
        except Exception:
            return True
        return payload.action.strip().lower() != "list"

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        mutating = self.is_mutating(params)
        return ToolMetadata(
            mutating=mutating,
            risk_level=ToolRiskLevel.MEDIUM if not mutating else ToolRiskLevel.HIGH,
            allowed_in_plan_mode=not mutating,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = GitBranchParams(**invocation.params)
        action = params.action.strip().lower()
        if action == "list":
            return None
        return ToolConfirmation(
            tool_name=self.name,
            description=f"Git branch {action}: {params.branch}",
            params=invocation.params,
            affected_paths=[invocation.cwd.resolve()],
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GitBranchParams(**invocation.params)
        cwd = invocation.cwd.resolve()

        sandbox_error = self._sandbox_check(cwd, invocation.cwd)
        if sandbox_error:
            return sandbox_error

        repo_error = _ensure_repo(cwd)
        if repo_error:
            return repo_error

        action = params.action.strip().lower()
        if action == "list":
            branches = list_local_branches(cwd)
            current = current_branch(cwd)
            lines = [f"Current branch: {current}"]
            lines.extend(
                f"{'*' if branch.is_current else ' '} {branch.name}" for branch in branches
            )
            return ToolResult.success_result(
                "\n".join(lines),
                metadata={
                    "current_branch": current,
                    "branches": [branch.name for branch in branches],
                },
            )

        if action == "switch":
            result = checkout_branch(cwd, params.branch or "")
        else:
            result = create_and_checkout(cwd, params.branch or "")

        if not result.ok:
            return ToolResult.error_result(
                result.message,
                metadata={
                    "action": action,
                    "branch": params.branch,
                },
            )

        return ToolResult.success_result(
            result.message,
            metadata={
                "action": action,
                "branch": params.branch,
                "current_branch": result.current_branch or current_branch(cwd),
            },
        )


class GitCommitTool(Tool):
    name = "git_commit"
    description = "Create a git commit from staged changes, optionally staging unstaged files and pushing afterwards."
    kind = ToolKind.WRITE
    schema = GitCommitParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=True,
            risk_level=ToolRiskLevel.HIGH,
            allowed_in_plan_mode=False,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = GitCommitParams(**invocation.params)
        push_suffix = " and push" if params.push else ""
        return ToolConfirmation(
            tool_name=self.name,
            description=f"Create git commit{push_suffix}: {params.message.strip() or 'Update files'}",
            params=invocation.params,
            affected_paths=[invocation.cwd.resolve()],
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GitCommitParams(**invocation.params)
        cwd = invocation.cwd.resolve()

        sandbox_error = self._sandbox_check(cwd, invocation.cwd)
        if sandbox_error:
            return sandbox_error

        repo_error = _ensure_repo(cwd)
        if repo_error:
            return repo_error

        result = commit_changes(
            cwd,
            message=params.message,
            include_unstaged=params.include_unstaged,
            push=params.push,
        )
        if not result.ok:
            return ToolResult.error_result(
                result.message,
                metadata={
                    "message": params.message,
                    "include_unstaged": params.include_unstaged,
                    "push": params.push,
                },
            )

        head_result = _run_git(cwd, "rev-parse", "HEAD")
        short_result = _run_git(cwd, "rev-parse", "--short", "HEAD")
        sha = head_result.stdout.strip() if head_result.returncode == 0 else None
        short_sha = short_result.stdout.strip() if short_result.returncode == 0 else None
        return ToolResult.success_result(
            result.message,
            metadata={
                "message": params.message.strip() or "Update files",
                "include_unstaged": params.include_unstaged,
                "push": params.push,
                "sha": sha,
                "short_sha": short_sha,
                "current_branch": current_branch(cwd),
            },
        )


class GitPushTool(Tool):
    name = "git_push"
    description = "Push or publish the current branch to its remote."
    kind = ToolKind.WRITE
    schema = GitPushParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=True,
            risk_level=ToolRiskLevel.HIGH,
            allowed_in_plan_mode=False,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        cwd = invocation.cwd.resolve()
        outbound = git_outbound_state(cwd)
        action = outbound.action_label if outbound else "push"
        target = outbound.target_label if outbound else current_branch(cwd)
        return ToolConfirmation(
            tool_name=self.name,
            description=f"Git {action} current branch to {target}",
            params=invocation.params,
            affected_paths=[cwd],
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        cwd = invocation.cwd.resolve()

        sandbox_error = self._sandbox_check(cwd, invocation.cwd)
        if sandbox_error:
            return sandbox_error

        repo_error = _ensure_repo(cwd)
        if repo_error:
            return repo_error

        outbound = git_outbound_state(cwd)
        result = push_current_branch(cwd)
        if not result.ok:
            return ToolResult.error_result(
                result.message,
                metadata={
                    "branch": outbound.branch if outbound else current_branch(cwd),
                    "upstream": outbound.upstream if outbound else None,
                    "remote_name": outbound.remote_name if outbound else None,
                },
            )

        refreshed = git_outbound_state(cwd)
        return ToolResult.success_result(
            result.message,
            metadata={
                "branch": refreshed.branch if refreshed else current_branch(cwd),
                "upstream": refreshed.upstream if refreshed else None,
                "remote_name": refreshed.remote_name if refreshed else None,
                "ahead_count": refreshed.ahead_count if refreshed else 0,
                "behind_count": refreshed.behind_count if refreshed else 0,
            },
        )
