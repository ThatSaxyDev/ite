from __future__ import annotations
from pydantic import field_validator, model_validator
from typing import Any, ClassVar
import os
import socket
import re
from pathlib import Path
from pydantic import BaseModel, Field
from enum import Enum

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_API_KEY = "ollama"
DEFAULT_MODEL_NAME = "minimax-m2.7:cloud"
DEFAULT_CLOUD_API_URL = "https://ite-cloud-api.onrender.com"
DEFAULT_CLOUD_CLIENT_ID = "ite-cli"


def default_cloud_device_name() -> str:
    hostname = str(socket.gethostname() or "").strip()
    if hostname:
        return hostname
    return DEFAULT_CLOUD_CLIENT_ID


class ModelConfig(BaseModel):
    name: str = Field(default=DEFAULT_MODEL_NAME)
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
    auto_connect: bool = False
    startup_timeout_sec: float = 10
    context_resolution: dict[str, list[str]] = Field(default_factory=dict)

    # stdio transport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Path | None = None

    # http/sse transport
    url: str | None = None
    transport: str = "auto"
    headers: dict[str, str] = Field(default_factory=dict)
    auth: str | None = None
    sse_read_timeout_sec: float | None = None
    oauth_timeout_sec: float = 300
    oauth_scopes: list[str] = Field(default_factory=list)
    oauth_client_name: str = "iTE MCP Client"
    oauth_callback_port: int | None = None

    _ENV_VAR_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))"
    )

    @field_validator("command", "url", "auth", mode="before")
    @classmethod
    def expand_string_env_vars(cls, value: Any) -> Any:
        if isinstance(value, str):
            return os.path.expandvars(value)
        return value

    @field_validator("args", mode="before")
    @classmethod
    def expand_list_env_vars(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return [os.path.expandvars(item) if isinstance(item, str) else item for item in value]

    @field_validator("env", "headers", mode="before")
    @classmethod
    def expand_mapping_env_vars(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {
            str(key): os.path.expandvars(item) if isinstance(item, str) else item
            for key, item in value.items()
        }

    @field_validator("context_resolution", mode="before")
    @classmethod
    def normalize_context_resolution(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized: dict[str, list[str]] = {}
        for key, item in value.items():
            if isinstance(item, list):
                normalized[str(key)] = [str(part) for part in item if str(part).strip()]
            elif isinstance(item, str) and item.strip():
                normalized[str(key)] = [item.strip()]
        return normalized

    @field_validator("cwd", mode="before")
    @classmethod
    def expand_cwd_env_vars(cls, value: Any) -> Any:
        if isinstance(value, str):
            return Path(os.path.expandvars(value))
        return value

    @property
    def effective_transport(self) -> str:
        if self.transport != "auto":
            return self.transport
        if self.command:
            return "stdio"
        if self.url and self.url.rstrip("/").endswith("/sse"):
            return "sse"
        return "streamable_http"

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

        transport = self.effective_transport
        if has_command and transport != "stdio":
            raise ValueError(
                "MCP Server using 'command' must use transport 'stdio' or 'auto'"
            )
        if has_url and transport not in {"sse", "streamable_http", "ws"}:
            raise ValueError(
                "MCP Server using 'url' must use transport 'sse', "
                "'streamable_http', 'ws', or 'auto'"
            )
        if transport == "ws" and (self.headers or self.auth):
            raise ValueError(
                "WebSocket MCP transport does not support configured headers or auth"
            )
        if self.auth == "oauth" and not has_url:
            raise ValueError("OAuth MCP auth requires a URL-based MCP server")
        if self.auth != "oauth" and (
            self.oauth_scopes or self.oauth_callback_port is not None
        ):
            raise ValueError(
                "OAuth-specific MCP settings require auth = 'oauth'"
            )

        return self

    def unresolved_env_vars(self) -> list[str]:
        names: set[str] = set()
        for value in [self.command, self.url, self.auth, *(self.args or [])]:
            names.update(self._extract_unresolved_env_var_names(value))
        for mapping in (self.env, self.headers):
            for item in mapping.values():
                names.update(self._extract_unresolved_env_var_names(item))
        if self.cwd is not None:
            names.update(self._extract_unresolved_env_var_names(str(self.cwd)))
        return sorted(names)

    @classmethod
    def _extract_unresolved_env_var_names(cls, value: Any) -> set[str]:
        if not isinstance(value, str):
            return set()
        names: set[str] = set()
        for match in cls._ENV_VAR_PATTERN.finditer(value):
            names.add(match.group(1) or match.group(2) or "")
        names.discard("")
        return names


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
    approval: ApprovalPolicy = ApprovalPolicy.AUTO

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
    cloud_auth_enabled: bool = True
    cloud_api_url: str | None = DEFAULT_CLOUD_API_URL
    cloud_client_id: str = DEFAULT_CLOUD_CLIENT_ID
    cloud_device_name: str = Field(default_factory=default_cloud_device_name)
    onboarding_completed: bool = False

    @model_validator(mode="after")
    def resolve_credentials(self) -> "Config":
        """Env vars override config file values."""
        if env_key := os.environ.get("API_KEY"):
            self.api_key = env_key
        if env_url := os.environ.get("BASE_URL"):
            self.base_url = env_url
        if env_cloud_enabled := os.environ.get("ITE_CLOUD_AUTH_ENABLED"):
            self.cloud_auth_enabled = env_cloud_enabled.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        if env_cloud_api := os.environ.get("ITE_CLOUD_API_URL"):
            self.cloud_api_url = env_cloud_api
        if env_cloud_client := os.environ.get("ITE_CLOUD_CLIENT_ID"):
            self.cloud_client_id = env_cloud_client
        if env_cloud_device := os.environ.get("ITE_CLOUD_DEVICE_NAME"):
            self.cloud_device_name = env_cloud_device
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
        if not self.base_url:
            errors.append("missing_base_url")
        if not self.model.name:
            errors.append("missing_model")

        if not self.cwd.exists():
            errors.append(f"Working directory does not exist: {self.cwd}")

        return errors

    @property
    def needs_setup(self) -> bool:
        """True if essential credentials are missing."""
        return not self.api_key or not self.base_url or not self.model.name

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
