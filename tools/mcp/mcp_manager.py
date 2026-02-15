from tools.mcp.mcp_tool import MCPTool
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
        print(mcp_configs)

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

            for tool_info in client.tools:
                mcp_tool = MCPTool(
                    tool_info=tool_info,
                    client=client,
                    config=self.config,
                    name=f"{client.name}_{tool_info.name}",
                )
                registry.register_mcp_tool(mcp_tool)
                count += 1

        return count
