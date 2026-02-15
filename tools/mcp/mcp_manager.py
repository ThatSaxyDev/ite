from tools.mcp.client import MCPServerStatus
from tools.registry import ToolRegistry
import asyncio
from tools.mcp.client import MCPClient
from config.config import Config


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

            self._clients[name] = MCPClient(
                name=name,
                config=server_config,
                cwd=self.config.cwd,
            )

        connection_tasks = [
            await asyncio.wait_for(client.connect())
            for name, client in self._clients.items()
        ]

        await asyncio.gather(*connection_tasks, return_exceptions=True)

        self._initialized = True

    def register_tools(self, registry: ToolRegistry) -> int:
        count = 0

        for client in self._clients.values():
            if client.status != MCPServerStatus.CONNECTED:
                continue

            for tool in client.tools:
                registry.register_mcp_tool(tool)
