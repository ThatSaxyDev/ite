from typing import Any
from ite.tools.mcp.mcp_tool import MCPTool
from ite.tools.mcp.client import MCPServerStatus
from ite.tools.registry import ToolRegistry
import asyncio
from ite.tools.mcp.client import MCPClient
from ite.config.config import Config
from rich.text import Text
from rich.table import Table
from rich.panel import Panel
from rich import box
import logging

logger = logging.getLogger(__name__)


def _get_console():
    """Lazily import the shared console to avoid circular imports."""
    from ite.ui.tui import get_console

    return get_console()


class MCPManager:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._clients: dict[str, MCPClient] = {}
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        mcp_configs = self.config.mcp_servers

        if not mcp_configs:
            return

        for name, server_config in mcp_configs.items():
            if not server_config.enabled:
                continue

            logger.info(
                "Initializing MCP server '%s' (command=%s url=%s cwd=%s)",
                name,
                server_config.command,
                server_config.url,
                server_config.cwd or self.config.cwd,
            )
            self._clients[name] = MCPClient(
                name=name,
                config=server_config,
                cwd=self.config.cwd,
            )

        if not self._clients:
            self._initialized = True
            return

        console = _get_console()
        server_count = len(self._clients)
        server_word = "server" if server_count == 1 else "servers"
        names = ", ".join(self._clients.keys())

        connection_tasks = [
            asyncio.wait_for(
                client.connect(), timeout=client.config.startup_timeout_sec
            )
            for name, client in self._clients.items()
        ]

        with console.status(
            f"[muted] Connecting to {server_count} MCP {server_word} ({names})...[/muted]",
            spinner="dots",
            spinner_style="cyan",
        ):
            results = await asyncio.gather(*connection_tasks, return_exceptions=True)

        # Build a styled panel with per-server results
        connected = 0
        mcp_table = Table.grid(padding=(0, 2))
        mcp_table.add_column(min_width=2)  # status icon
        mcp_table.add_column(min_width=12)  # server name
        mcp_table.add_column()  # details

        for (name, client), result in zip(self._clients.items(), results):
            if isinstance(result, Exception):
                mcp_table.add_row(
                    Text("●", style="bright_red"),
                    Text(name, style="bold"),
                    Text("unavailable", style="muted"),
                )
            else:
                connected += 1
                tool_count = len(client.tools)
                tool_word = "tool" if tool_count == 1 else "tools"
                mcp_table.add_row(
                    Text("●", style="green"),
                    Text(name, style="bold"),
                    Text(f"{tool_count} {tool_word}", style="muted"),
                )

        title = Text.assemble(
            ("🔌 ", ""),
            ("MCP Servers ", "bold bright_white"),
            (f"{connected}/{server_count} connected", "muted"),
        )

        console.print(
            Panel(
                mcp_table,
                title=title,
                title_align="left",
                border_style="cyan" if connected == server_count else "yellow",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

        self._initialized = True

    def register_tools(self, registry: ToolRegistry) -> int:
        count = 0

        for client in self._clients.values():
            if client.status != MCPServerStatus.CONNECTED:
                continue

            for tool_info in client.tools:
                mcp_tool = MCPTool(
                    tool_info=tool_info,
                    client=client,
                    config=self.config,
                    name=f"{client.name}__{tool_info.name}",
                )
                registry.register_mcp_tool(mcp_tool)
                count += 1

        return count

    async def shutdown(self) -> None:
        disconnection_tasks = [client.disconnect() for client in self._clients.values()]

        await asyncio.gather(*disconnection_tasks, return_exceptions=True)

        self._clients.clear()
        self._initialized = False

    def get_all_servers(self) -> list[dict[str, Any]]:
        servers = []
        for name, client in self._clients.items():
            server_info = {
                "name": name,
                "status": client.status.value,
                "tools": len(client.tools),
            }
            servers.append(server_info)

        return servers
