from tools.subagent import SubagentTool
from tools.subagent import get_default_subagent_definitions
from tools.subagent_loader import discover_subagents
from config.config import Config
from tools.builtin import get_all_builtin_tools
from tools.base import ToolInvocation
from tools.base import ToolResult
from pathlib import Path
from typing import Any
import logging
from tools.base import Tool

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, config: Config):
        self._tools: dict[str, Tool] = {}
        self.config = config

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool: {tool.name}")

        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            return True

        return False

    def get(self, name: str) -> Tool | None:
        if name in self._tools:
            return self._tools[name]

        return None

    def get_tools(self) -> list[Tool]:
        tools: list[Tool] = []

        for tool in self._tools.values():
            tools.append(tool)

        if self.config.allowed_tools:
            allowed_set = set(self.config.allowed_tools)
            tools = [t for t in tools if t.name in allowed_set]

        return tools

    def get_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_openai_schema() for tool in self.get_tools()]

    async def invoke(
        self,
        name: str,
        params: dict[str, Any],
        cwd: Path,
    ) -> ToolResult:
        tool = self.get(name)

        if tool is None:
            return ToolResult.error_result(
                f"Tool not found: {name}",
                metadata={
                    "tool_name": name,
                },
            )

        validation_errors = tool.validate_params(params)

        if validation_errors:
            return ToolResult.error_result(
                f"Invalid parameters: {'; '.join(validation_errors)}",
                metadata={
                    "tool_name": name,
                    "validation_errors": validation_errors,  # TODO: remove later
                },
            )

        invocation = ToolInvocation(
            params=params,
            cwd=cwd,
        )

        try:
            result = await tool.execute(invocation)
        except Exception as e:
            logger.exception(f"Error executing tool {name}")
            result = ToolResult.error_result(
                f"Internal error: {str(e)}",
                metadata={
                    "tool_name",
                    name,
                },
            )

        return result


def create_default_registry(config: Config) -> ToolRegistry:
    registry = ToolRegistry(config)

    for tool_class in get_all_builtin_tools():
        registry.register(tool_class(config))

    for subagent_definition in get_default_subagent_definitions():
        registry.register(SubagentTool(config, subagent_definition))

    # Discover and register user-defined subagents (override defaults by name)
    user_subagents = discover_subagents(config.cwd)
    for definition in user_subagents:
        registry.register(SubagentTool(config, definition))

    return registry