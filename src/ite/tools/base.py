from __future__ import annotations
from dataclasses import field
from pydantic import ValidationError
from pathlib import Path
from dataclasses import dataclass
from typing import Any
import abc
from enum import Enum
from pydantic import BaseModel
from pydantic.json_schema import model_json_schema
from ite.config.config import Config


class ToolKind(Enum):
    READ = "read"
    WRITE = "write"
    SHELL = "shell"
    NETWORK = "network"
    MEMORY = "memory"
    MCP = "mcp"


class ToolRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ToolMetadata:
    mutating: bool
    risk_level: ToolRiskLevel
    allowed_in_plan_mode: bool
    supports_subagent_use: bool
    output_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutating": self.mutating,
            "risk_level": self.risk_level.value,
            "allowed_in_plan_mode": self.allowed_in_plan_mode,
            "supports_subagent_use": self.supports_subagent_use,
            "output_schema": self.output_schema,
        }


@dataclass
class FileDiff:
    path: Path
    old_content: str
    new_content: str

    is_new_file: bool = False
    is_deletion: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "old_content": self.old_content,
            "new_content": self.new_content,
            "is_new_file": self.is_new_file,
            "is_deletion": self.is_deletion,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FileDiff":
        return cls(
            path=Path(str(payload.get("path", ""))),
            old_content=str(payload.get("old_content", "")),
            new_content=str(payload.get("new_content", "")),
            is_new_file=bool(payload.get("is_new_file", False)),
            is_deletion=bool(payload.get("is_deletion", False)),
        )

    def to_diff(self) -> str:
        import difflib

        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)

        if old_lines and not old_lines[-1].endswith("\n"):
            old_lines[-1] += "\n"

        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        old_name = "/dev/null" if self.is_new_file else str(self.path)
        new_name = "/dev/null" if self.is_deletion else str(self.path)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=old_name,
            tofile=new_name,
        )

        return "".join(diff)


@dataclass
class ToolInvocation:
    params: dict[str, Any]
    cwd: Path


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    diff: FileDiff | None = None
    file_diffs: list[FileDiff] = field(default_factory=list)
    exit_code: int | None = None

    @classmethod
    def error_result(
        cls,
        error: str,
        output: str = "",
        **kwargs: Any,
    ):
        return cls(
            success=False,
            error=error,
            output=output,
            **kwargs,
        )

    @classmethod
    def success_result(
        cls,
        output: str,
        **kwargs: Any,
    ):
        return cls(
            success=True,
            output=output,
            error=None,
            **kwargs,
        )

    def to_model_output(self) -> str:
        if self.success:
            return self.output

        return f"Error: {self.error}\n\nOutput:\n{self.output}"


@dataclass
class ToolConfirmation:
    tool_name: str
    description: str
    params: dict[str, Any]
    diff: FileDiff | None = None
    affected_paths: list[Path] = field(default_factory=list)
    command: str | None = None
    is_dangerous: bool = False


class Tool(abc.ABC):
    name: str = "base_tool"
    description: str = "Base tool"
    kind: ToolKind = ToolKind.READ

    def __init__(self, config: Config) -> None:
        self.config = config

    @property
    def schema(self) -> dict[str, Any] | type[BaseModel]:
        raise NotImplementedError("Tool must define schema property or class attribute")

    @abc.abstractmethod
    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        pass

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        schema = self.schema
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                schema(**params)
            except ValidationError as e:
                errors = []
                for error in e.errors():
                    field = ".".join(str(x) for x in error.get("loc", []))
                    msg = error.get("msg", "Validation error")
                    errors.append(f"Parameter '{field}': {msg}")

                return errors
            except Exception as e:
                return [str(e)]

        return []

    def is_mutating(self, params: dict[str, Any]) -> bool:
        return self.kind in {
            ToolKind.WRITE,
            ToolKind.SHELL,
            ToolKind.NETWORK,
            ToolKind.MEMORY,
        }

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        mutating = self.is_mutating(params)
        risk_by_kind = {
            ToolKind.READ: ToolRiskLevel.LOW,
            ToolKind.WRITE: ToolRiskLevel.HIGH,
            ToolKind.SHELL: ToolRiskLevel.HIGH,
            ToolKind.NETWORK: ToolRiskLevel.MEDIUM,
            ToolKind.MEMORY: ToolRiskLevel.MEDIUM,
            ToolKind.MCP: ToolRiskLevel.HIGH,
        }
        risk_level = risk_by_kind.get(self.kind, ToolRiskLevel.MEDIUM)
        allowed_in_plan_mode = not mutating
        if self.name in {"memory", "todos", "plan_question"}:
            allowed_in_plan_mode = True

        return ToolMetadata(
            mutating=mutating,
            risk_level=risk_level,
            allowed_in_plan_mode=allowed_in_plan_mode,
            supports_subagent_use=True,
            output_schema={"type": "string"},
        )

    def _sandbox_check(self, path: Path, cwd: Path) -> ToolResult | None:
        """Validate path against sandbox policy. Returns error result if blocked, None if OK."""
        from ite.safety.sandbox import validate_path, SandboxViolation

        try:
            validate_path(path.resolve(), cwd, self.config.sandbox)
            return None
        except SandboxViolation:
            return ToolResult.error_result(
                f"Access denied: {path} is outside the project sandbox. "
                f"Use /sandbox allow <path> to grant access."
            )

    async def get_confirmation(
        self,
        invocation: ToolInvocation,
    ) -> ToolConfirmation | None:
        if not self.is_mutating(invocation.params):
            return None
        return ToolConfirmation(
            tool_name=self.name,
            description=f"Execute {self.name}",
            params=invocation.params,
        )

    def to_openai_schema(self) -> dict[str, Any]:
        schema = self.schema
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            json_schema = model_json_schema(schema, mode="serialization")
            return {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": json_schema.get("properties", {}),
                    "required": json_schema.get("required", []),
                },
            }

        if isinstance(schema, dict):
            result = {
                "name": self.name,
                "description": self.description,
            }

            if "parameters" in schema:
                result["parameters"] = schema["parameters"]
            else:
                result["parameters"] = schema

            return result

        raise ValueError(f"Invalid schema type for tool {self.name}: {type(schema)}")
