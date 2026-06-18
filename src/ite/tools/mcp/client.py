from typing import Any
from dataclasses import field
from dataclasses import dataclass
import os
import shutil
import tempfile
from fastmcp.client.transports import (
    SSETransport,
    StdioTransport,
    StreamableHttpTransport,
)
try:
    from fastmcp.client.transports import WSTransport
except ImportError:
    WSTransport = None
from enum import Enum
from pathlib import Path
from ite.config.config import MCPServerConfig
from ite.config.loader import get_data_dir
from fastmcp import Client
import logging
from ite.tools.mcp.oauth import build_oauth_provider

logger = logging.getLogger(__name__)


MCPStatusCallback = Any


class MCPServerStatus(str, Enum):
    READY = "ready"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class MCPToolInfo:
    name: str
    description: str
    title: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""
    annotations: dict[str, Any] = field(default_factory=dict)


class MCPClient:
    def __init__(
        self,
        name: str,
        config: MCPServerConfig,
        cwd: Path,
    ) -> None:
        self.name = name
        self.config = config
        self.cwd = cwd
        self.status = MCPServerStatus.DISCONNECTED
        self.status_detail: str | None = None
        self.auth_phase: str | None = None
        self.last_error: str | None = None
        self._client: Client | None = None
        self._status_callback: MCPStatusCallback = None

        self._tools: dict[str, MCPToolInfo] = dict()
        self._resolved_stdio_log_path: Path | None = None

    def _prepare_runtime_dir(self, *parts: str) -> Path:
        candidates = [
            get_data_dir().joinpath(*parts),
            self.cwd.joinpath(".ite", *parts),
            Path(tempfile.gettempdir()).joinpath("ite", *parts),
        ]
        last_error: OSError | None = None
        for path in candidates:
            try:
                path.mkdir(parents=True, exist_ok=True)
                return path
            except OSError as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise OSError("Unable to prepare MCP runtime directory")

    def _stdio_log_path(self) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in self.name)
        if self._resolved_stdio_log_path is not None:
            return self._resolved_stdio_log_path
        return get_data_dir() / "logs" / "mcp" / f"{safe_name}.stderr.log"

    def _prepare_stdio_log_file(self) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in self.name)
        candidates = [
            get_data_dir() / "logs" / "mcp" / f"{safe_name}.stderr.log",
            self.cwd / ".ite" / "logs" / "mcp" / f"{safe_name}.stderr.log",
            Path(tempfile.gettempdir()) / "ite" / "logs" / "mcp" / f"{safe_name}.stderr.log",
        ]
        last_error: OSError | None = None
        for path in candidates:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
                self._resolved_stdio_log_path = path
                return path
            except OSError as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise OSError("Unable to create MCP stderr log file")

    def _read_stdio_log_tail(self, max_chars: int = 2000) -> str | None:
        if self.config.effective_transport != "stdio":
            return None
        path = self._stdio_log_path()
        if not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        if not content:
            return None
        if len(content) <= max_chars:
            return content
        return "..." + content[-max_chars:]

    def _apply_npm_runtime_env(self, env: dict[str, str]) -> None:
        command = str(self.config.command or "").strip().lower()
        if command not in {"npx", "npm"}:
            return
        if env.get("npm_config_cache"):
            return
        cache_dir = self._prepare_runtime_dir("cache", "npm")
        env["npm_config_cache"] = str(cache_dir)
        env.setdefault("npm_config_update_notifier", "false")

    @property
    def tools(self) -> list[MCPToolInfo]:
        return list(self._tools.values())

    def _create_transport(
        self,
    ) -> Any:
        transport = self.config.effective_transport
        auth = self._resolve_auth()
        if transport == "stdio":
            env = os.environ.copy()
            env.update(self.config.env)
            self._apply_npm_runtime_env(env)
            cwd = self.config.cwd if self.config.cwd is not None else self.cwd
            return StdioTransport(
                command=self.config.command,
                args=list(self.config.args),
                env=env,
                cwd=str(cwd),
                keep_alive=False,
                log_file=self._prepare_stdio_log_file(),
            )
        if transport == "sse":
            return SSETransport(
                url=self.config.url,
                headers=self.config.headers or None,
                auth=auth,
                sse_read_timeout=self.config.sse_read_timeout_sec,
            )
        if transport == "streamable_http":
            kwargs: dict[str, Any] = {
                "url": self.config.url,
                "headers": self.config.headers or None,
                "auth": auth,
            }
            return StreamableHttpTransport(**kwargs)
        if transport == "ws":
            if WSTransport is None:
                raise RuntimeError(
                    "Configured MCP server uses transport 'ws', but the installed "
                    "fastmcp package does not provide WSTransport. Upgrade fastmcp "
                    "or switch this server to 'streamable_http'."
                )
            return WSTransport(url=self.config.url)
        raise ValueError(f"Unsupported MCP transport: {transport}")

    def _resolve_auth(self) -> Any:
        if self.config.auth == "oauth":
            return build_oauth_provider(
                self.config,
                str(self.config.url),
                progress_reporter=self._oauth_progress,
            )
        return self.config.auth

    async def connect(self, status_callback: MCPStatusCallback = None) -> None:
        if self.status == MCPServerStatus.CONNECTED:
            return

        self._status_callback = status_callback
        missing_env = self.config.unresolved_env_vars()
        if missing_env:
            message = "Missing environment variables: " + ", ".join(missing_env)
            self.last_error = message
            await self._set_status(MCPServerStatus.ERROR, detail=message)
            raise RuntimeError(message)
        self._tools.clear()
        self.last_error = None
        self.auth_phase = None

        try:
            self._client = Client(transport=self._create_transport())

            await self._client.__aenter__()
            await self._set_status(
                MCPServerStatus.CONNECTING,
                detail="Discovering tools.",
            )

            tool_result = await self._client.list_tools()
            tools = (
                tool_result.tools
                if hasattr(tool_result, "tools")
                else tool_result
                if isinstance(tool_result, list)
                else []
            )

            for tool in tools:
                self._tools[tool.name] = MCPToolInfo(
                    name=tool.name,
                    description=tool.description or "",
                    title=getattr(tool, "title", None),
                    input_schema=(
                        tool.inputSchema if hasattr(tool, "inputSchema") else {}
                    ),
                    output_schema=(
                        tool.outputSchema if hasattr(tool, "outputSchema") else {}
                    )
                    or {},
                    server_name=self.name,
                    annotations=self._extract_annotations(tool),
                )

            await self._set_status(
                MCPServerStatus.CONNECTED,
                detail=f"{len(self._tools)} tools",
            )
            self.auth_phase = None

        except Exception as e:
            await self._cleanup_failed_connect()
            cmd = self.config.command or self.config.url or "unknown"

            # Check for command-not-found (FileNotFoundError wrapped in RuntimeError)
            root = e.__cause__ or e
            if isinstance(root, FileNotFoundError) or (
                isinstance(e, OSError) and e.errno == 2
            ):
                resolved = shutil.which(str(cmd))
                hint = (
                    f"Command '{cmd}' was not found on your PATH."
                    if resolved is None
                    else f"Command '{cmd}' resolved to '{resolved}' but failed to start."
                )
                msg = (
                    f"MCP server '{self.name}' failed to start: {hint}\n"
                    f"  → Check the 'command' field in [mcp_servers.{self.name}] "
                    f"in your .ite/config.toml"
                )
                self.last_error = msg
                await self._set_status(MCPServerStatus.ERROR, detail=hint)
                logger.error(msg)
                raise RuntimeError(msg) from None

            # All other connection errors — clean message, no traceback
            # Extract the root error message for clarity
            error_str = str(root) if root is not e else str(e)
            stderr_tail = self._read_stdio_log_tail()
            detail = error_str
            if stderr_tail:
                first_line = stderr_tail.splitlines()[0].strip()
                if first_line:
                    detail = f"{error_str}: {first_line}"
            msg = (
                f"MCP server '{self.name}' failed to connect: {error_str}"
            )
            if stderr_tail:
                msg += f"\n  → Server stderr:\n{stderr_tail}"
            else:
                msg += (
                    f"\n  → Check the configuration in [mcp_servers.{self.name}] "
                    f"in your .ite/config.toml"
                )
            self.last_error = msg
            await self._set_status(MCPServerStatus.ERROR, detail=detail)
            logger.error(msg)
            raise RuntimeError(msg) from None
        finally:
            self._status_callback = None

    async def _cleanup_failed_connect(self) -> None:
        if not self._client:
            return

        try:
            await self._client.__aexit__(None, None, None)
        except Exception:
            logger.debug(
                "MCP server '%s' cleanup after failed connect also failed",
                self.name,
                exc_info=True,
            )
        finally:
            self._client = None
            self._tools.clear()

    def _extract_annotations(self, tool: Any) -> dict[str, Any]:
        annotations = getattr(tool, "annotations", None)
        if annotations is None:
            return {}
        if hasattr(annotations, "model_dump"):
            return annotations.model_dump(exclude_none=True)
        if isinstance(annotations, dict):
            return {k: v for k, v in annotations.items() if v is not None}
        return {}

    async def disconnect(self, *, status: MCPServerStatus = MCPServerStatus.DISCONNECTED) -> None:
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None

        self._tools.clear()
        self.status = status
        self.status_detail = None
        self.auth_phase = None

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._client or self.status != MCPServerStatus.CONNECTED:
            raise RuntimeError(f"Not connected to server {self.name}")

        result = await self._client.call_tool(tool_name, arguments)
        output = []
        for item in result.content:
            if hasattr(item, "text"):
                output.append(item.text)
            else:
                output.append(str(item))

        return {"output": "\n".join(output), "is_error": result.is_error}

    async def _oauth_progress(self, phase: str, detail: str | None = None) -> None:
        self.auth_phase = phase
        if phase in {"auth_required", "opening_browser", "waiting_for_callback", "callback_received", "exchanging_token"}:
            await self._set_status(MCPServerStatus.CONNECTING, detail=detail)

    async def _set_status(
        self,
        status: MCPServerStatus,
        *,
        detail: str | None = None,
    ) -> None:
        self.status = status
        self.status_detail = detail
        if self._status_callback is None:
            return
        result = self._status_callback(
            {
                "server": self.name,
                "status": status.value,
                "detail": detail,
                "auth_phase": self.auth_phase,
            }
        )
        if result is not None:
            await result
