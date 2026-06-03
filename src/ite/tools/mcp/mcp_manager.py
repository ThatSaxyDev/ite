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
from rich.console import Console
from rich import box
import logging

logger = logging.getLogger(__name__)


def _get_console():
    return Console()


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
            self._clients[name].status = MCPServerStatus.READY

        if not self._clients:
            self._initialized = True
            return

        console = _get_console()
        server_count = len(self._clients)
        server_word = "server" if server_count == 1 else "servers"
        names = ", ".join(self._clients.keys())

        startup_clients = [
            client for client in self._clients.values() if client.config.auto_connect
        ]

        if not startup_clients:
            self._initialized = True
            return

        connection_tasks = [self._connect_client(client) for client in startup_clients]

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

        for client, result in zip(startup_clients, results):
            name = client.name
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

    async def _connect_client(self, client: MCPClient, status_callback=None) -> None:
        timeout_sec = (
            client.config.oauth_timeout_sec
            if client.config.auth == "oauth"
            else client.config.startup_timeout_sec
        )
        try:
            await asyncio.wait_for(
                client.connect(status_callback=status_callback),
                timeout=timeout_sec,
            )
        except TimeoutError as exc:
            timeout_message = (
                f"MCP server '{client.name}' timed out after "
                f"{timeout_sec:g}s during startup"
            )
            await client.disconnect(status=MCPServerStatus.ERROR)
            client.status = MCPServerStatus.ERROR
            client.last_error = timeout_message
            client.status_detail = "Timed out during startup."
            raise RuntimeError(
                timeout_message
            ) from exc

    async def connect_server(self, name: str, registry: ToolRegistry, status_callback=None) -> int:
        client = self._clients.get(name)
        if client is None:
            raise KeyError(f"Unknown MCP server: {name}")
        if client.status == MCPServerStatus.CONNECTED:
            return 0

        await self._connect_client(client, status_callback=status_callback)
        return self._register_client_tools(client, registry)

    async def disconnect_server(self, name: str, registry: ToolRegistry) -> int:
        client = self._clients.get(name)
        if client is None:
            raise KeyError(f"Unknown MCP server: {name}")

        removed = registry.unregister_mcp_server(name)
        await client.disconnect(status=MCPServerStatus.READY)
        return removed

    @property
    def configured_server_count(self) -> int:
        return len(self._clients)

    @property
    def connected_server_count(self) -> int:
        return sum(
            1
            for client in self._clients.values()
            if client.status == MCPServerStatus.CONNECTED
        )

    @property
    def failed_server_count(self) -> int:
        return sum(
            1 for client in self._clients.values() if client.status == MCPServerStatus.ERROR
        )

    @property
    def total_tool_count(self) -> int:
        return sum(len(client.tools) for client in self._clients.values())

    @property
    def startup_server_count(self) -> int:
        return sum(1 for client in self._clients.values() if client.config.auto_connect)

    @property
    def all_startup_servers_failed(self) -> bool:
        return self.startup_server_count > 0 and self.connected_server_count == 0

    def register_tools(self, registry: ToolRegistry) -> int:
        count = 0

        for client in self._clients.values():
            if client.status != MCPServerStatus.CONNECTED:
                continue

            count += self._register_client_tools(client, registry)

        return count

    def _register_client_tools(self, client: MCPClient, registry: ToolRegistry) -> int:
        count = 0
        registry.unregister_mcp_server(client.name)
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
            unresolved = getattr(client.config, "unresolved_env_vars", None)
            missing_env = unresolved() if callable(unresolved) else []
            detail = client.status_detail
            if missing_env and client.status == MCPServerStatus.READY:
                detail = "Missing env: " + ", ".join(missing_env)
            server_info = {
                "name": name,
                "status": client.status.value,
                "tools": len(client.tools),
                "transport": client.config.effective_transport,
                "auto_connect": client.config.auto_connect,
                "detail": detail,
                "auth_phase": client.auth_phase,
                "last_error": client.last_error,
                "missing_env": missing_env,
            }
            if client.config.url:
                server_info["url"] = client.config.url
            servers.append(server_info)

        return servers
