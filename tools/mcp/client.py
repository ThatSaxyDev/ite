from typing import Any
from dataclasses import field
from dataclasses import dataclass
import os
import shutil
from fastmcp.client.transports import StdioTransport, SSETransport
from enum import Enum
from pathlib import Path
from config.config import MCPServerConfig
from fastmcp import Client
import logging

logger = logging.getLogger(__name__)


class MCPServerStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class MCPToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


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
        self._client: Client | None = None

        self._tools: dict[str, MCPToolInfo] = dict()

    @property
    def tools(self) -> list[MCPToolInfo]:
        return list(self._tools.values())

    def _create_transport(self) -> StdioTransport | SSETransport:
        if self.config.command:
            env = os.environ.copy()
            env.update(self.config.env)
            cwd = self.config.cwd if self.config.cwd is not None else self.cwd
            return StdioTransport(
                command=self.config.command,
                args=list(self.config.args),
                env=env,
                cwd=str(cwd),
                log_file=Path(os.devnull),
            )

        else:
            return SSETransport(
                url=self.config.url,
            )

    async def connect(self) -> None:
        if self.status == MCPServerStatus.CONNECTED:
            return

        self.status = MCPServerStatus.CONNECTING

        try:
            self._client = Client(transport=self._create_transport())

            await self._client.__aenter__()

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
                    input_schema=(
                        tool.inputSchema if hasattr(tool, "inputSchema") else {}
                    ),
                    server_name=self.name,
                )

            self.status = MCPServerStatus.CONNECTED

        except Exception as e:
            self.status = MCPServerStatus.ERROR
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
                logger.error(msg)
                raise RuntimeError(msg) from None

            # All other connection errors — clean message, no traceback
            # Extract the root error message for clarity
            error_str = str(root) if root is not e else str(e)
            msg = (
                f"MCP server '{self.name}' failed to connect: {error_str}\n"
                f"  → Check the configuration in [mcp_servers.{self.name}] "
                f"in your .ite/config.toml"
            )
            logger.error(msg)
            raise RuntimeError(msg) from None

    async def disconnect(self) -> None:
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None

        self._tools.clear()
        self.status = MCPServerStatus.DISCONNECTED

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
