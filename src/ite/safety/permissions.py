"""Permission presets and conservative, invocation-scoped authorization.

This is application-level gating, not an operating-system process sandbox.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ite.config.config import ApprovalPolicy, Config, PermissionMode
from ite.safety.approval import ApprovalManager
from ite.safety.sandbox import SandboxViolation, validate_path
from ite.tools.base import Tool, ToolConfirmation, ToolKind

LABELS = {
    PermissionMode.ASK: "Ask for approval",
    PermissionMode.AUTOMATIC: "Automatic",
    PermissionMode.FULL: "Full access",
}
MODE_USAGE = {
    PermissionMode.ASK: "ask",
    PermissionMode.AUTOMATIC: "automatic",
    PermissionMode.FULL: "full access",
}

DESCRIPTIONS = {
    PermissionMode.ASK: "Ask before edits, commands, internet tools, and external file access.",
    PermissionMode.AUTOMATIC: "Allow workspace file tools. Ask before commands, internet tools, and external access.",
    PermissionMode.FULL: "Allow tools without iTE approval or filesystem restrictions.",
}
POLICIES = {
    PermissionMode.ASK: ApprovalPolicy.ON_REQUEST,
    PermissionMode.AUTOMATIC: ApprovalPolicy.AUTO,
    PermissionMode.FULL: ApprovalPolicy.YOLO,
}


def current_mode(config: Config) -> PermissionMode | None:
    mode = config.permissions
    if (
        mode is not None
        and config.approval == POLICIES[mode]
        and config.sandbox.enabled == (mode != PermissionMode.FULL)
    ):
        return mode
    return None


def apply_mode(config: Config, mode: PermissionMode) -> None:
    config.permissions = mode
    config.approval = POLICIES[mode]
    config.sandbox.enabled = mode != PermissionMode.FULL


def affected_paths(tool: Tool, params: dict[str, Any], cwd: Path) -> list[Path]:
    """Collect file operands before confirmation builders can read file contents."""
    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key
                    in {
                        "path",
                        "cwd",
                        "directory",
                        "source",
                        "destination",
                        "output_path",
                        "file_path",
                    }
                    or key.endswith("_path")
                ) and isinstance(item, str):
                    values.append(item)
                elif isinstance(item, (dict, list)):
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(params)
    if tool.name == "apply_patch":
        # Parsing is pure; get_confirmation does not read files for this tool.
        operations = tool._parse_patch(str(params.get("patch", "")))
        values.extend(operation.path for operation in operations)
    if tool.kind == ToolKind.SHELL and isinstance(params.get("command"), str):
        from ite.tools.builtin.shell import _extract_paths_from_command

        values.extend(
            str(path) for path in _extract_paths_from_command(params["command"])
        )
    command_cwd = Path(str(params.get("cwd") or cwd)).expanduser()
    if not command_cwd.is_absolute():
        command_cwd = cwd / command_cwd
    root = command_cwd if tool.kind == ToolKind.SHELL else cwd
    return list(
        dict.fromkeys(
            (
                Path(value).expanduser()
                if Path(value).expanduser().is_absolute()
                else root / Path(value).expanduser()
            ).resolve()
            for value in values
        )
    )


async def authorize_invocation(
    tool: Tool, params: dict[str, Any], cwd: Path, manager: ApprovalManager | None
) -> tuple[str | None, tuple[Path, ...]]:
    mode = tool.config.permissions
    if mode is None or mode == PermissionMode.FULL:
        return None, ()
    errors = tool.validate_params(params)
    if errors:
        return f"Invalid parameters: {'; '.join(errors)}", ()
    try:
        paths = affected_paths(tool, params, cwd)
    except (ValueError, OSError) as error:
        return f"Invalid file operands: {error}", ()
    external = []
    for path in paths:
        try:
            validate_path(path, cwd, tool.config.sandbox)
        except SandboxViolation:
            external.append(path)
    # Shells, arbitrary MCP calls, and child agents can escape simple path checks.
    # Ask for those capabilities explicitly; child registries enforce the same policy.
    capability = tool.kind in {
        ToolKind.SHELL,
        ToolKind.NETWORK,
        ToolKind.MCP,
    } or tool.name.startswith("subagent_")
    mutation = tool.is_mutating(params) and tool.name not in {
        "todos",
        "memory",
        "learn_progress",
    }
    confirm = (
        bool(external)
        or capability
        or (mode == PermissionMode.ASK and mutation)
        or tool.name in {"git_commit", "git_push"}
    )
    if not confirm:
        return None, ()
    reason = "Approve this action once."
    if capability:
        reason += " Commands and integrations are not isolated by an OS sandbox."
    if external:
        reason += " Access outside the workspace: " + ", ".join(
            str(path) for path in external
        )
    confirmation = ToolConfirmation(
        tool_name=tool.name,
        description=reason,
        params=params,
        affected_paths=paths,
        command=params.get("command"),
    )
    if manager is None or not await manager.request_confirmation(confirmation):
        return "Approval declined or unavailable. Operation was not executed.", ()
    return None, tuple(external)
