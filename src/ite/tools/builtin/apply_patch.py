from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from ite.tools.base import FileDiff
from ite.tools.base import Tool
from ite.tools.base import ToolConfirmation
from ite.tools.base import ToolInvocation
from ite.tools.base import ToolKind
from ite.tools.base import ToolMetadata
from ite.tools.base import ToolResult
from ite.tools.base import ToolRiskLevel
from ite.utils.paths import ensure_parent_dir
from ite.utils.paths import resolve_path


class ApplyPatchParams(BaseModel):
    patch: str = Field(
        ...,
        description=(
            "Patch text in Codex patch format with markers: "
            "*** Begin Patch ... *** End Patch."
        ),
    )
    dry_run: bool = Field(
        False,
        description="Validate and preview patch without writing files.",
    )


@dataclass
class PatchOperation:
    op: str
    path: str
    body_lines: list[str]


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = (
        "Apply multi-file patch edits atomically. Supports add/update/delete operations "
        "using patch blocks. Use this for coordinated edits across multiple files."
    )
    kind = ToolKind.WRITE
    schema = ApplyPatchParams

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        return ToolMetadata(
            mutating=True,
            risk_level=ToolRiskLevel.HIGH,
            allowed_in_plan_mode=False,
            supports_subagent_use=False,
            output_schema={
                "type": "object",
                "required": ["files", "dry_run", "applied"],
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}},
                    "dry_run": {"type": "boolean"},
                    "applied": {"type": "boolean"},
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["path", "action"],
                            "properties": {
                                "path": {"type": "string"},
                                "action": {"type": "string"},
                            },
                        },
                    },
                },
            },
        )

    async def get_confirmation(
        self,
        invocation: ToolInvocation,
    ) -> ToolConfirmation | None:
        params = ApplyPatchParams(**invocation.params)
        try:
            operations = self._parse_patch(params.patch)
        except ValueError as e:
            return ToolConfirmation(
                tool_name=self.name,
                description=f"Apply patch (invalid): {e}",
                params=invocation.params,
                is_dangerous=True,
            )

        affected = [resolve_path(invocation.cwd, op.path) for op in operations]
        return ToolConfirmation(
            tool_name=self.name,
            description=f"Apply patch touching {len(operations)} file(s)",
            params=invocation.params,
            affected_paths=affected,
            is_dangerous=True,
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ApplyPatchParams(**invocation.params)
        try:
            operations = self._parse_patch(params.patch)
        except ValueError as e:
            return ToolResult.error_result(f"Invalid patch: {e}")

        staged_actions: list[dict[str, Any]] = []
        file_diffs: list[FileDiff] = []
        writes: list[tuple[str, Path, str | None]] = []

        for op in operations:
            path = resolve_path(invocation.cwd, op.path)
            sandbox_error = self._sandbox_check(path, invocation.cwd)
            if sandbox_error:
                return sandbox_error

            if op.op == "add":
                if path.exists():
                    return ToolResult.error_result(f"Add failed: file already exists: {path}")
                new_content = self._render_added_content(op.body_lines)
                staged_actions.append({"path": str(path), "action": "add"})
                file_diffs.append(
                    FileDiff(
                        path=path,
                        old_content="",
                        new_content=new_content,
                        is_new_file=True,
                    )
                )
                writes.append(("add", path, new_content))
                continue

            if op.op == "delete":
                if not path.exists():
                    return ToolResult.error_result(f"Delete failed: file does not exist: {path}")
                old_content = path.read_text(encoding="utf-8")
                staged_actions.append({"path": str(path), "action": "delete"})
                file_diffs.append(
                    FileDiff(
                        path=path,
                        old_content=old_content,
                        new_content="",
                        is_deletion=True,
                    )
                )
                writes.append(("delete", path, None))
                continue

            if not path.exists():
                return ToolResult.error_result(f"Update failed: file does not exist: {path}")

            old_content = path.read_text(encoding="utf-8")
            try:
                new_content = self._apply_update(old_content, op.body_lines, str(path))
            except ValueError as e:
                return ToolResult.error_result(f"Update failed for {path}: {e}")

            staged_actions.append({"path": str(path), "action": "update"})
            file_diffs.append(
                FileDiff(
                    path=path,
                    old_content=old_content,
                    new_content=new_content,
                )
            )
            writes.append(("update", path, new_content))

        if not params.dry_run:
            for action, path, content in writes:
                if action in {"add", "update"}:
                    ensure_parent_dir(path)
                    path.write_text(content or "", encoding="utf-8")
                elif action == "delete":
                    path.unlink()

        output_lines = []
        for action in staged_actions:
            output_lines.append(f"{action['action']}: {action['path']}")
        output = "\n".join(output_lines) if output_lines else "No operations"

        metadata = {
            "files": [action["path"] for action in staged_actions],
            "dry_run": params.dry_run,
            "applied": not params.dry_run,
            "actions": staged_actions,
            "diffs": [d.to_diff() for d in file_diffs],
            "file_diff_payloads": [d.to_dict() for d in file_diffs],
        }
        return ToolResult.success_result(
            output,
            metadata=metadata,
            file_diffs=file_diffs,
        )

    def _parse_patch(self, patch_text: str) -> list[PatchOperation]:
        lines = patch_text.splitlines()
        if not lines or lines[0].strip() != "*** Begin Patch":
            raise ValueError("patch must start with '*** Begin Patch'")
        if lines[-1].strip() != "*** End Patch":
            raise ValueError("patch must end with '*** End Patch'")

        operations: list[PatchOperation] = []
        idx = 1
        while idx < len(lines) - 1:
            line = lines[idx]
            if line.startswith("*** Add File: "):
                path = line[len("*** Add File: ") :].strip()
                idx += 1
                body: list[str] = []
                while idx < len(lines) - 1 and not lines[idx].startswith("*** "):
                    body.append(lines[idx])
                    idx += 1
                operations.append(PatchOperation(op="add", path=path, body_lines=body))
                continue
            if line.startswith("*** Update File: "):
                path = line[len("*** Update File: ") :].strip()
                idx += 1
                body = []
                while idx < len(lines) - 1 and not lines[idx].startswith("*** "):
                    body.append(lines[idx])
                    idx += 1
                operations.append(PatchOperation(op="update", path=path, body_lines=body))
                continue
            if line.startswith("*** Delete File: "):
                path = line[len("*** Delete File: ") :].strip()
                operations.append(PatchOperation(op="delete", path=path, body_lines=[]))
                idx += 1
                continue
            if line.strip():
                raise ValueError(f"unexpected patch line: {line}")
            idx += 1

        if not operations:
            raise ValueError("patch contains no operations")
        return operations

    def _render_added_content(self, body_lines: list[str]) -> str:
        out: list[str] = []
        for line in body_lines:
            if not line.startswith("+"):
                raise ValueError("add file sections must contain only '+' lines")
            out.append(line[1:])
        if not out:
            return ""
        return "\n".join(out) + "\n"

    def _apply_update(self, old_content: str, body_lines: list[str], path: str) -> str:
        old_lines = old_content.splitlines()
        old_had_trailing_newline = old_content.endswith("\n")
        new_lines: list[str] = []
        old_idx = 0

        for raw in body_lines:
            if not raw:
                raise ValueError("update line missing diff prefix")
            if raw.startswith("@@"):
                continue
            if raw == r"\ No newline at end of file":
                continue

            prefix = raw[0]
            text = raw[1:]
            if prefix not in {" ", "+", "-"}:
                raise ValueError(f"invalid update line prefix in {path}: {raw}")

            if prefix in {" ", "-"}:
                if old_idx >= len(old_lines):
                    raise ValueError("hunk exceeds file length")
                if old_lines[old_idx] != text:
                    raise ValueError(
                        f"context mismatch at line {old_idx + 1}: expected '{old_lines[old_idx]}' got '{text}'"
                    )
                if prefix == " ":
                    new_lines.append(old_lines[old_idx])
                old_idx += 1
                continue

            # prefix == "+"
            new_lines.append(text)

        new_lines.extend(old_lines[old_idx:])
        if not new_lines:
            return ""
        rendered = "\n".join(new_lines)
        if old_had_trailing_newline or any(line.startswith("+") for line in body_lines):
            rendered += "\n"
        return rendered
