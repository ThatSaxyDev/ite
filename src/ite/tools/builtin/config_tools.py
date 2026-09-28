from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ite.tools.base import FileDiff, Tool, ToolConfirmation, ToolInvocation, ToolKind, ToolResult
from ite.utils.paths import resolve_path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


class ReadTomlParams(BaseModel):
    path: str = Field(..., description="Path to the TOML file to read.")
    key_path: str | None = Field(
        None,
        description="Optional dotted key path like project.name or tool.ruff.line-length.",
    )


class WriteTomlParams(BaseModel):
    path: str = Field(..., description="Path to the TOML file to update.")
    key_path: str = Field(
        "",
        description="Target TOML path, for example project.version or tool.ruff.select.",
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
        description="Create missing tables or arrays when walking the key path.",
    )

    @model_validator(mode="after")
    def _validate_operation(self) -> "WriteTomlParams":
        action = self.operation.strip().lower()
        if action not in {"set", "delete", "append"}:
            raise ValueError("operation must be one of: set, delete, append")
        if action in {"set", "append"} and self.value is None:
            raise ValueError("value is required for set/append")
        return self


class ReadYamlParams(BaseModel):
    path: str = Field(..., description="Path to the YAML file to read.")
    key_path: str | None = Field(
        None,
        description="Optional dotted key path like jobs.build.steps[0].name.",
    )


class WriteYamlParams(BaseModel):
    path: str = Field(..., description="Path to the YAML file to update.")
    key_path: str = Field(
        "",
        description="Target YAML path, for example services.api.image.",
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
        description="Create missing objects or arrays when walking the key path.",
    )

    @model_validator(mode="after")
    def _validate_operation(self) -> "WriteYamlParams":
        action = self.operation.strip().lower()
        if action not in {"set", "delete", "append"}:
            raise ValueError("operation must be one of: set, delete, append")
        if action in {"set", "append"} and self.value is None:
            raise ValueError("value is required for set/append")
        return self


class ReadEnvParams(BaseModel):
    path: str = Field(..., description="Path to the .env file to read.")
    key: str | None = Field(
        None,
        description="Optional environment variable name to read.",
    )


class WriteEnvParams(BaseModel):
    path: str = Field(..., description="Path to the .env file to update.")
    key: str = Field(..., description="Environment variable name to update.")
    operation: str = Field(
        "set",
        description="Operation to perform: set or delete.",
    )
    value: str | None = Field(
        None,
        description="Value to set when operation is set.",
    )

    @model_validator(mode="after")
    def _validate_operation(self) -> "WriteEnvParams":
        action = self.operation.strip().lower()
        if action not in {"set", "delete"}:
            raise ValueError("operation must be one of: set, delete")
        if action == "set" and self.value is None:
            raise ValueError("value is required for set")
        return self


def _parse_key_path(path: str) -> list[str | int]:
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


def _apply_structured_operation(
    data: Any,
    *,
    key_path: str,
    operation: str,
    value: Any,
    create_missing: bool,
) -> Any:
    tokens = _parse_key_path(key_path)
    action = operation.strip().lower()
    if not tokens and action == "set":
        return value
    if not tokens:
        raise KeyError("key_path is required for delete/append operations")

    container, final_token = _navigate(data, tokens, create_missing=create_missing)

    if action == "set":
        if final_token is None:
            return value
        if isinstance(final_token, int):
            if not isinstance(container, list):
                raise KeyError(f"Expected list at index {final_token}")
            if final_token >= len(container):
                if not create_missing:
                    raise KeyError(f"Index {final_token} out of range")
                while len(container) <= final_token:
                    container.append(None)
            container[final_token] = value
        else:
            if not isinstance(container, dict):
                raise KeyError(f"Expected object at key {final_token}")
            container[final_token] = value
        return data

    if action == "delete":
        if isinstance(final_token, int):
            if not isinstance(container, list) or final_token >= len(container):
                raise KeyError(f"Index {final_token} out of range")
            container.pop(final_token)
        else:
            if not isinstance(container, dict) or final_token not in container:
                raise KeyError(f"Missing key: {final_token}")
            del container[final_token]
        return data

    if isinstance(final_token, int):
        raise KeyError("append targets must resolve to an array field, not an index")
    if not isinstance(container, dict):
        raise KeyError(f"Expected object at key {final_token}")
    if final_token not in container:
        if not create_missing:
            raise KeyError(f"Missing key: {final_token}")
        container[final_token] = []
    if not isinstance(container[final_token], list):
        raise KeyError(f"Target at {final_token} is not an array")
    container[final_token].append(value)
    return data


def _parse_toml_document(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}, text
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise ValueError("TOML document root must be a table")
    return data, text


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        raise ValueError("TOML does not support null values")
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise ValueError(f"Unsupported TOML value type: {type(value).__name__}")


def _render_toml_section(data: dict[str, Any], prefix: list[str], lines: list[str]) -> None:
    scalars: list[tuple[str, Any]] = []
    tables: list[tuple[str, dict[str, Any]]] = []
    array_tables: list[tuple[str, list[dict[str, Any]]]] = []

    for key, value in data.items():
        if isinstance(value, dict):
            tables.append((key, value))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            array_tables.append((key, value))
        else:
            scalars.append((key, value))

    for key, value in scalars:
        lines.append(f"{key} = {_toml_scalar(value)}")

    if scalars and (tables or array_tables):
        lines.append("")

    for index, (key, value) in enumerate(tables):
        if lines and lines[-1] != "":
            lines.append("")
        section_name = ".".join([*prefix, key])
        lines.append(f"[{section_name}]")
        _render_toml_section(value, [*prefix, key], lines)
        if index != len(tables) - 1 or array_tables:
            lines.append("")

    for array_index, (key, values) in enumerate(array_tables):
        for item_index, item in enumerate(values):
            if lines and lines[-1] != "":
                lines.append("")
            section_name = ".".join([*prefix, key])
            lines.append(f"[[{section_name}]]")
            _render_toml_section(item, [*prefix, key], lines)
            if item_index != len(values) - 1:
                lines.append("")
        if array_index != len(array_tables) - 1:
            lines.append("")


def _render_toml_document(data: dict[str, Any], *, original_text: str) -> str:
    lines: list[str] = []
    _render_toml_section(data, [], lines)
    rendered = "\n".join(line for line in lines).rstrip()
    if rendered:
        rendered += "\n"
    return rendered if original_text.endswith("\n") or rendered else rendered


def _load_yaml_module():
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is not installed. Add the `PyYAML` dependency to use YAML tools.") from exc
    return yaml


def _parse_yaml_document(path: Path) -> tuple[Any, str]:
    yaml = _load_yaml_module()
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}, text
    data = yaml.safe_load(text)
    return ({} if data is None else data), text


def _render_yaml_document(data: Any, *, original_text: str) -> str:
    yaml = _load_yaml_module()
    rendered = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return rendered if original_text.endswith("\n") or rendered.endswith("\n") else rendered + "\n"


_ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_env_document(path: Path) -> tuple[dict[str, str], list[dict[str, Any]], str]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    entries: list[dict[str, Any]] = []
    env: dict[str, str] = {}

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            entries.append({"kind": "blank", "raw": line})
            continue
        if stripped.startswith("#"):
            entries.append({"kind": "comment", "raw": line})
            continue

        export_prefix = ""
        content = line
        if content.startswith("export "):
            export_prefix = "export "
            content = content[len("export ") :]

        if "=" not in content:
            raise ValueError(f"Invalid .env line: {line}")

        key, raw_value = content.split("=", 1)
        key = key.strip()
        if not _ENV_KEY_PATTERN.match(key):
            raise ValueError(f"Invalid environment variable name: {key}")

        value = raw_value
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {'"', "'"}:
            value = raw_value[1:-1]

        env[key] = value
        entries.append(
            {
                "kind": "assignment",
                "key": key,
                "value": value,
                "quote": raw_value[:1] if raw_value[:1] in {'"', "'"} and raw_value[-1:] == raw_value[:1] else "",
                "export": bool(export_prefix),
            }
        )

    return env, entries, text


def _env_needs_quotes(value: str) -> bool:
    return value == "" or any(char.isspace() for char in value) or any(char in value for char in '#"\'')


def _render_env_value(value: str, *, quote: str = "") -> str:
    if quote not in {"", '"', "'"}:
        quote = ""
    if not quote and _env_needs_quotes(value):
        quote = '"'
    if quote == '"':
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if quote == "'":
        escaped = value.replace("'", "\\'")
        return f"'{escaped}'"
    return value


def _render_env_document(entries: list[dict[str, Any]], *, original_text: str) -> str:
    lines: list[str] = []
    for entry in entries:
        kind = entry.get("kind")
        if kind == "blank":
            lines.append(entry.get("raw", ""))
        elif kind == "comment":
            lines.append(entry.get("raw", ""))
        elif kind == "assignment":
            prefix = "export " if entry.get("export") else ""
            value = _render_env_value(str(entry.get("value", "")), quote=str(entry.get("quote", "")))
            lines.append(f"{prefix}{entry['key']}={value}")
    rendered = "\n".join(lines)
    return rendered + ("\n" if original_text.endswith("\n") or rendered else "")


class ReadTomlTool(Tool):
    name = "read_toml"
    description = "Read a TOML file, optionally targeting a nested key path."
    kind = ToolKind.READ
    schema = ReadTomlParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ReadTomlParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        sandbox_error = self._sandbox_check(path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if not path.exists():
            return ToolResult.error_result(f"File not found: {path}")
        if not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        try:
            data, _ = _parse_toml_document(path)
        except Exception as exc:
            return ToolResult.error_result(
                f"Failed to parse TOML file: {exc}",
                metadata={"path": str(path), "parse_error": True},
            )

        tokens = _parse_key_path(params.key_path or "")
        try:
            value = _read_value(data, tokens) if tokens else data
        except KeyError as exc:
            return ToolResult.error_result(str(exc), metadata={"path": str(path), "key_path": params.key_path})

        return ToolResult.success_result(
            json.dumps(value, indent=2, ensure_ascii=False),
            metadata={"path": str(path), "key_path": params.key_path or "", "value_type": type(value).__name__},
        )


class WriteTomlTool(Tool):
    name = "write_toml"
    description = "Update a TOML file using structured key paths."
    kind = ToolKind.WRITE
    schema = WriteTomlParams

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = WriteTomlParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        old_content = path.read_text(encoding="utf-8") if path.exists() else ""
        description = f"Edit TOML file: {path}" if path.exists() else f"Create TOML file: {path}"
        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=description,
            diff=FileDiff(path=path, old_content=old_content, new_content=old_content, is_new_file=not path.exists()),
            affected_paths=[path],
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WriteTomlParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        created_new = not path.exists()

        sandbox_error = self._sandbox_check(path.parent if not path.exists() else path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if path.exists() and not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        original_text = ""
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data, original_text = _parse_toml_document(path)
            except Exception as exc:
                return ToolResult.error_result(
                    f"Failed to parse TOML file: {exc}",
                    metadata={"path": str(path), "parse_error": True},
                )

        try:
            updated = _apply_structured_operation(
                data,
                key_path=params.key_path,
                operation=params.operation,
                value=params.value,
                create_missing=params.create_missing,
            )
            if not isinstance(updated, dict):
                return ToolResult.error_result("TOML document root must remain a table.")
        except (KeyError, ValueError) as exc:
            return ToolResult.error_result(
                str(exc),
                metadata={"path": str(path), "key_path": params.key_path, "operation": params.operation},
            )

        try:
            new_text = _render_toml_document(updated, original_text=original_text)
        except Exception as exc:
            return ToolResult.error_result(
                f"Failed to render TOML file: {exc}",
                metadata={"path": str(path), "render_error": True},
            )

        if new_text == original_text:
            return ToolResult.success_result(
                "TOML file already matches the requested change.",
                metadata={"path": str(path), "changed": False, "key_path": params.key_path},
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
        diff = FileDiff(path=path, old_content=original_text, new_content=new_text, is_new_file=created_new)
        return ToolResult.success_result(
            f"Updated TOML at {path}.",
            diff=diff,
            file_diffs=[diff],
            metadata={"path": str(path), "changed": True, "key_path": params.key_path, "operation": params.operation},
        )


class ReadYamlTool(Tool):
    name = "read_yaml"
    description = "Read a YAML file, optionally targeting a nested key path."
    kind = ToolKind.READ
    schema = ReadYamlParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ReadYamlParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        sandbox_error = self._sandbox_check(path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if not path.exists():
            return ToolResult.error_result(f"File not found: {path}")
        if not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        try:
            data, _ = _parse_yaml_document(path)
        except Exception as exc:
            return ToolResult.error_result(
                f"Failed to parse YAML file: {exc}",
                metadata={"path": str(path), "parse_error": True},
            )

        tokens = _parse_key_path(params.key_path or "")
        try:
            value = _read_value(data, tokens) if tokens else data
        except KeyError as exc:
            return ToolResult.error_result(str(exc), metadata={"path": str(path), "key_path": params.key_path})

        return ToolResult.success_result(
            json.dumps(value, indent=2, ensure_ascii=False),
            metadata={"path": str(path), "key_path": params.key_path or "", "value_type": type(value).__name__},
        )


class WriteYamlTool(Tool):
    name = "write_yaml"
    description = "Update a YAML file using structured key paths."
    kind = ToolKind.WRITE
    schema = WriteYamlParams

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = WriteYamlParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        old_content = path.read_text(encoding="utf-8") if path.exists() else ""
        description = f"Edit YAML file: {path}" if path.exists() else f"Create YAML file: {path}"
        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=description,
            diff=FileDiff(path=path, old_content=old_content, new_content=old_content, is_new_file=not path.exists()),
            affected_paths=[path],
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WriteYamlParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        created_new = not path.exists()

        sandbox_error = self._sandbox_check(path.parent if not path.exists() else path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if path.exists() and not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        original_text = ""
        data: Any = {}
        if path.exists():
            try:
                data, original_text = _parse_yaml_document(path)
            except Exception as exc:
                return ToolResult.error_result(
                    f"Failed to parse YAML file: {exc}",
                    metadata={"path": str(path), "parse_error": True},
                )

        try:
            updated = _apply_structured_operation(
                data,
                key_path=params.key_path,
                operation=params.operation,
                value=params.value,
                create_missing=params.create_missing,
            )
        except (KeyError, ValueError) as exc:
            return ToolResult.error_result(
                str(exc),
                metadata={"path": str(path), "key_path": params.key_path, "operation": params.operation},
            )

        try:
            new_text = _render_yaml_document(updated, original_text=original_text)
        except Exception as exc:
            return ToolResult.error_result(
                f"Failed to render YAML file: {exc}",
                metadata={"path": str(path), "render_error": True},
            )

        if new_text == original_text:
            return ToolResult.success_result(
                "YAML file already matches the requested change.",
                metadata={"path": str(path), "changed": False, "key_path": params.key_path},
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
        diff = FileDiff(path=path, old_content=original_text, new_content=new_text, is_new_file=created_new)
        return ToolResult.success_result(
            f"Updated YAML at {path}.",
            diff=diff,
            file_diffs=[diff],
            metadata={"path": str(path), "changed": True, "key_path": params.key_path, "operation": params.operation},
        )


class ReadEnvTool(Tool):
    name = "read_env"
    description = "Read a .env file, optionally targeting a single variable."
    kind = ToolKind.READ
    schema = ReadEnvParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ReadEnvParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        sandbox_error = self._sandbox_check(path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if not path.exists():
            return ToolResult.error_result(f"File not found: {path}")
        if not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        try:
            env, _, _ = _parse_env_document(path)
        except Exception as exc:
            return ToolResult.error_result(
                f"Failed to parse .env file: {exc}",
                metadata={"path": str(path), "parse_error": True},
            )

        if params.key:
            if params.key not in env:
                return ToolResult.error_result(
                    f"Missing key: {params.key}",
                    metadata={"path": str(path), "key": params.key},
                )
            value: Any = env[params.key]
        else:
            value = env

        return ToolResult.success_result(
            json.dumps(value, indent=2, ensure_ascii=False),
            metadata={"path": str(path), "key": params.key or "", "value_type": type(value).__name__},
        )


class WriteEnvTool(Tool):
    name = "write_env"
    description = "Set or delete variables in a .env file while preserving comments and order."
    kind = ToolKind.WRITE
    schema = WriteEnvParams

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = WriteEnvParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        old_content = path.read_text(encoding="utf-8") if path.exists() else ""
        description = f"Edit env file: {path}" if path.exists() else f"Create env file: {path}"
        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=description,
            diff=FileDiff(path=path, old_content=old_content, new_content=old_content, is_new_file=not path.exists()),
            affected_paths=[path],
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WriteEnvParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        created_new = not path.exists()

        sandbox_error = self._sandbox_check(path.parent if not path.exists() else path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if path.exists() and not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")
        if not _ENV_KEY_PATTERN.match(params.key):
            return ToolResult.error_result(f"Invalid environment variable name: {params.key}")

        try:
            _, entries, original_text = _parse_env_document(path)
        except Exception as exc:
            return ToolResult.error_result(
                f"Failed to parse .env file: {exc}",
                metadata={"path": str(path), "parse_error": True},
            )

        action = params.operation.strip().lower()
        changed = False
        matching_indices = [index for index, entry in enumerate(entries) if entry.get("kind") == "assignment" and entry.get("key") == params.key]

        if action == "delete":
            if matching_indices:
                entries = [entry for entry in entries if not (entry.get("kind") == "assignment" and entry.get("key") == params.key)]
                changed = True
        else:
            if matching_indices:
                last_index = matching_indices[-1]
                if entries[last_index].get("value") != params.value:
                    entries[last_index]["value"] = params.value
                    changed = True
            else:
                entries.append({"kind": "assignment", "key": params.key, "value": params.value, "quote": "", "export": False})
                changed = True

        new_text = _render_env_document(entries, original_text=original_text)
        if not changed or new_text == original_text:
            return ToolResult.success_result(
                ".env file already matches the requested change.",
                metadata={"path": str(path), "changed": False, "key": params.key, "operation": params.operation},
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
        diff = FileDiff(path=path, old_content=original_text, new_content=new_text, is_new_file=created_new)
        return ToolResult.success_result(
            f"Updated env file at {path}.",
            diff=diff,
            file_diffs=[diff],
            metadata={"path": str(path), "changed": True, "key": params.key, "operation": params.operation},
        )
