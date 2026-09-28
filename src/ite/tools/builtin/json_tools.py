from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ite.tools.base import FileDiff, Tool, ToolConfirmation, ToolInvocation, ToolKind, ToolResult
from ite.utils.paths import resolve_path


class ReadJsonParams(BaseModel):
    path: str = Field(
        ...,
        description="Path to the JSON file to read.",
    )
    json_path: str | None = Field(
        None,
        description="Optional dotted path like scripts.test or dependencies.requests.",
    )


class EditJsonParams(BaseModel):
    path: str = Field(
        ...,
        description="Path to the JSON file to edit.",
    )
    json_path: str = Field(
        "",
        description="Target JSON path, for example scripts.test or devDependencies.typescript.",
    )
    operation: str = Field(
        "set",
        description="Operation to perform: set, delete, or append.",
    )
    value: Any = Field(
        None,
        description="Value to set or append.",
    )
    create_missing: bool = Field(
        False,
        description="Create missing objects or arrays when walking the JSON path.",
    )

    @model_validator(mode="after")
    def _validate_operation(self) -> "EditJsonParams":
        action = self.operation.strip().lower()
        if action not in {"set", "delete", "append"}:
            raise ValueError("operation must be one of: set, delete, append")
        if action in {"set", "append"} and self.value is None:
            raise ValueError("value is required for set/append")
        return self


def _parse_json_path(path: str) -> list[str | int]:
    text = (path or "").strip()
    if not text:
        return []
    tokens: list[str | int] = []
    pattern = re.compile(r"([^[.\]]+)|\[(\d+)\]")
    for part in text.split("."):
        if not part:
            continue
        for match in pattern.finditer(part):
            key, index = match.groups()
            if key is not None:
                tokens.append(key)
            elif index is not None:
                tokens.append(int(index))
    return tokens


def _load_json_document(path: Path) -> tuple[Any, str]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text), text


def _render_json_document(data: Any, *, original_text: str) -> str:
    indent = 2
    indent_matches = re.findall(r"(?m)^(\s+)\"", original_text)
    if indent_matches:
        indent = min(len(match) for match in indent_matches if match) or 2
    rendered = json.dumps(data, indent=indent, ensure_ascii=False) + ("\n" if original_text.endswith("\n") else "")
    return rendered


def _navigate(data: Any, tokens: list[str | int], *, create_missing: bool) -> tuple[Any, str | int | None]:
    if not tokens:
        return data, None

    current = data
    for index, token in enumerate(tokens[:-1]):
        next_token = tokens[index + 1]
        if isinstance(token, int):
            if not isinstance(current, list):
                raise KeyError(f"Expected list at index {token}")
            if token >= len(current):
                if not create_missing:
                    raise KeyError(f"Index {token} out of range")
                while len(current) <= token:
                    current.append({} if isinstance(next_token, str) else [])
            current = current[token]
            continue

        if not isinstance(current, dict):
            raise KeyError(f"Expected object at key {token}")
        if token not in current:
            if not create_missing:
                raise KeyError(f"Missing key: {token}")
            current[token] = {} if isinstance(next_token, str) else []
        current = current[token]

    return current, tokens[-1]


def _read_value(data: Any, tokens: list[str | int]) -> Any:
    current = data
    for token in tokens:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise KeyError(f"Index {token} out of range")
            current = current[token]
            continue
        if not isinstance(current, dict) or token not in current:
            raise KeyError(f"Missing key: {token}")
        current = current[token]
    return current


class ReadJsonTool(Tool):
    name = "read_json"
    description = "Read a JSON file, optionally targeting a nested JSON path."
    kind = ToolKind.READ
    schema = ReadJsonParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ReadJsonParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        sandbox_error = self._sandbox_check(path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if not path.exists():
            return ToolResult.error_result(f"File not found: {path}")
        if not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        try:
            data, _ = _load_json_document(path)
        except Exception as exc:
            return ToolResult.error_result(f"Failed to read JSON file: {exc}")

        tokens = _parse_json_path(params.json_path or "")
        try:
            value = _read_value(data, tokens) if tokens else data
        except KeyError as exc:
            return ToolResult.error_result(str(exc), metadata={"path": str(path), "json_path": params.json_path})

        rendered = json.dumps(value, indent=2, ensure_ascii=False)
        return ToolResult.success_result(
            rendered,
            metadata={
                "path": str(path),
                "json_path": params.json_path or "",
                "value_type": type(value).__name__,
            },
        )


class EditJsonTool(Tool):
    name = "edit_json"
    description = "Edit a JSON file using structured JSON paths instead of raw text replacement."
    kind = ToolKind.WRITE
    schema = EditJsonParams

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = EditJsonParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        if not path.exists():
            return ToolConfirmation(
                tool_name=self.name,
                params=invocation.params,
                description=f"Create JSON file: {path}",
                affected_paths=[path],
            )

        try:
            _, original_text = _load_json_document(path)
        except Exception:
            original_text = path.read_text(encoding="utf-8")
        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"Edit JSON file: {path}",
            diff=FileDiff(path=path, old_content=original_text, new_content=original_text),
            affected_paths=[path],
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = EditJsonParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        sandbox_error = self._sandbox_check(path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if not path.exists():
            return ToolResult.error_result(f"File not found: {path}")
        if not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        try:
            data, original_text = _load_json_document(path)
        except Exception as exc:
            return ToolResult.error_result(f"Failed to read JSON file: {exc}")

        tokens = _parse_json_path(params.json_path)
        action = params.operation.strip().lower()
        try:
            if not tokens and action == "set":
                data = params.value
            elif not tokens:
                raise KeyError("json_path is required for delete/append operations")
            else:
                container, final_token = _navigate(
                    data,
                    tokens,
                    create_missing=params.create_missing,
                )
                if action == "set":
                    if final_token is None:
                        data = params.value
                    elif isinstance(final_token, int):
                        if not isinstance(container, list):
                            raise KeyError(f"Expected list at index {final_token}")
                        if final_token >= len(container):
                            if not params.create_missing:
                                raise KeyError(f"Index {final_token} out of range")
                            while len(container) <= final_token:
                                container.append(None)
                        container[final_token] = params.value
                    else:
                        if not isinstance(container, dict):
                            raise KeyError(f"Expected object at key {final_token}")
                        container[final_token] = params.value
                elif action == "delete":
                    if isinstance(final_token, int):
                        if not isinstance(container, list) or final_token >= len(container):
                            raise KeyError(f"Index {final_token} out of range")
                        container.pop(final_token)
                    else:
                        if not isinstance(container, dict) or final_token not in container:
                            raise KeyError(f"Missing key: {final_token}")
                        del container[final_token]
                else:
                    if isinstance(final_token, int):
                        raise KeyError("append targets must resolve to an array field, not an index")
                    if not isinstance(container, dict):
                        raise KeyError(f"Expected object at key {final_token}")
                    if final_token not in container:
                        if not params.create_missing:
                            raise KeyError(f"Missing key: {final_token}")
                        container[final_token] = []
                    if not isinstance(container[final_token], list):
                        raise KeyError(f"Target at {final_token} is not an array")
                    container[final_token].append(params.value)
        except KeyError as exc:
            return ToolResult.error_result(
                str(exc),
                metadata={
                    "path": str(path),
                    "json_path": params.json_path,
                    "operation": action,
                },
            )

        new_text = _render_json_document(data, original_text=original_text)
        if new_text == original_text:
            return ToolResult.success_result(
                "JSON file already matches the requested change.",
                metadata={
                    "path": str(path),
                    "json_path": params.json_path,
                    "operation": action,
                    "changed": False,
                },
            )

        path.write_text(new_text, encoding="utf-8")
        diff = FileDiff(path=path, old_content=original_text, new_content=new_text)
        return ToolResult.success_result(
            f"Updated JSON at {path}.",
            diff=diff,
            file_diffs=[diff],
            metadata={
                "path": str(path),
                "json_path": params.json_path,
                "operation": action,
                "changed": True,
            },
        )
