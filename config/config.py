from __future__ import annotations
from pydantic import model_validator
from typing import Any
import os
from pathlib import Path
from pydantic import BaseModel, Field
from enum import Enum


class ModelConfig(BaseModel):
    name: str = Field(default="gpt-4o-mini")
    temperature: float = Field(default=1, ge=0.0, le=2.0)
    context_window: int = 256_000


class ShellEnvironmentPolicy(BaseModel):
    ignore_default_excludes: bool = False
    exclude_patterns: list[str] = Field(
        default_factory=lambda: ["*KEY*", "*SECRET*", "*TOKEN*"]
    )

    set_vars: dict[str, str] = Field(default_factory=dict)


class MCPServerConfig(BaseModel):
    enabled: bool = True
    startup_timeout_sec: float = 10

    # stdio transport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Path | None = None

    # http/sse transport
    url: str | None = None

    @model_validator(mode="after")
    def validate_transport(self) -> MCPServerConfig:
        has_command = self.command is not None
        has_url = self.url is not None

        if not has_command and not has_url:
            raise ValueError(
                "MCP Server must have either 'command' (stdio) or 'url' (http/sse)"
            )

        if has_command and has_url:
            raise ValueError("MCP Server must have only one of command or url set")

        return self


class ApprovalPolicy(str, Enum):
    ON_REQUEST = "on_request"
    ON_FAILURE = "on_failure"
    AUTO = "auto"
    AUTO_EDIT = "auto_edit"
    NEVER = "never"
    YOLO = "yolo"


class HookTrigger(str, Enum):
    BEFORE_AGENT = "before_agent"
    AFTER_AGENT = "after_agent"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"


class HookConfig(BaseModel):
    name: str
    trigger: HookTrigger
    command: str | None = None
    script: str | None = None
    timeout_sec: float = 30
    enabled: bool = True

    @model_validator(mode="after")
    def validate_hook(self) -> HookConfig:
        if not self.command and not self.script:
            raise ValueError("Hook must have either 'command' or 'script'")

        return self


class SandboxPolicy(BaseModel):
    enabled: bool = True
    git_sandbox: bool = False
    allowed_paths: list[Path] = Field(default_factory=list)


class Config(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    cwd: Path = Field(default=Path.cwd())
    shell_environment: ShellEnvironmentPolicy = Field(
        default_factory=ShellEnvironmentPolicy
    )
    sandbox: SandboxPolicy = Field(default_factory=SandboxPolicy)
    hooks_enabled: bool = False
    hooks: list[HookConfig] = Field(default_factory=list)
    approval: ApprovalPolicy = ApprovalPolicy.ON_REQUEST

    max_turns: int = 100

    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)

    max_tool_output_tokens: int = 50_000

    allowed_tools: list[str] | None = Field(
        None,
        description="If set only these tools will be available to the agent",
    )

    developer_instructions: str | None = None
    user_instructions: str | None = None

    debug: bool = False

    # Credentials — loaded from config.toml, overridden by env vars / CLI flags
    api_key: str | None = None
    base_url: str | None = None

    @model_validator(mode="after")
    def resolve_credentials(self) -> "Config":
        """Env vars override config file values."""
        if env_key := os.environ.get("API_KEY"):
            self.api_key = env_key
        if env_url := os.environ.get("BASE_URL"):
            self.base_url = env_url
        return self

    @property
    def model_name(self) -> str:
        return self.model.name

    @model_name.setter
    def model_name(self, value: str) -> None:
        self.model.name = value

    @property
    def temperature(self) -> float:
        return self.model.temperature

    @temperature.setter
    def temperature(self, value: float) -> None:
        self.model.temperature = value

    def validate(self) -> list[str]:
        errors: list[str] = []

        if not self.api_key:
            errors.append("missing_api_key")

        if not self.cwd.exists():
            errors.append(f"Working directory does not exist: {self.cwd}")

        return errors

    @property
    def needs_setup(self) -> bool:
        """True if essential credentials are missing."""
        return not self.api_key

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
