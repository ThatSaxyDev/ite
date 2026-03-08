from ite.hooks.hook_system import HookSystem
from ite.safety.approval import ApprovalDecision
from ite.safety.approval import ApprovalContext
from ite.safety.approval import ApprovalManager
from ite.tools.subagent import SubagentTool
from ite.tools.subagent import get_default_subagent_definitions
from ite.tools.subagent_loader import discover_subagents
from ite.config.config import Config
from ite.tools.builtin import get_all_builtin_tools
from ite.tools.base import ToolInvocation
from ite.tools.base import ToolResult
from pathlib import Path
from typing import Any, Awaitable, Callable
import logging
from ite.tools.base import Tool
from ite.safety.approval import is_safe_command

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, config: Config):
        self._tools: dict[str, Tool] = {}
        self._mcp_tools: dict[str, Tool] = {}
        self.config = config

    @property
    def connected_mcp_servers(self) -> list[Tool]:
        return self._mcp_tools.values()

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool: {tool.name}")

        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def register_mcp_tool(
        self,
        tool: Tool,
    ) -> None:

        self._mcp_tools[tool.name] = tool
        logger.debug(f"Registered MCP tool: {tool.name}")

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            return True

        return False

    def get(self, name: str) -> Tool | None:
        if name in self._tools:
            return self._tools[name]
        elif name in self._mcp_tools:
            return self._mcp_tools[name]

        return None

    def get_tools(self) -> list[Tool]:
        tools: list[Tool] = []

        for tool in self._tools.values():
            tools.append(tool)

        for tool in self._mcp_tools.values():
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
        hook_system: HookSystem,
        approval_manager: ApprovalManager | None = None,
        *,
        plan_mode_enabled: bool = False,
        plan_phase: str = "idle",
        set_plan_phase: Callable[[str], None] | None = None,
        plan_question_callback: (
            Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None
        ) = None,
    ) -> ToolResult:
        tool = self.get(name)

        if tool is None:
            result = ToolResult.error_result(
                f"Tool not found: {name}",
                metadata={
                    "tool_name": name,
                },
            )
            await hook_system.trigger_after_tool(
                tool_name=name,
                tool_params=params,
                tool_result=result,
            )
            return result

        if plan_mode_enabled and plan_phase != "executing":
            if name == "plan_question":
                pass
            elif tool.is_mutating(params):
                if name in {"todos", "memory"}:
                    pass
                elif name == "shell":
                    command = str(params.get("command", "")).strip()
                    if not command or not is_safe_command(command):
                        return ToolResult.error_result(
                            "Plan mode blocks mutating tools before implementation approval. "
                            "Use non-mutating exploration first."
                        )
                else:
                    return ToolResult.error_result(
                        "Plan mode blocks mutating tools before implementation approval. "
                        "Get plan approval first."
                    )

        validation_errors = tool.validate_params(params)

        if validation_errors:
            result = ToolResult.error_result(
                f"Invalid parameters: {'; '.join(validation_errors)}",
                metadata={
                    "tool_name": name,
                    "validation_errors": validation_errors,  # TODO: remove later
                },
            )
            await hook_system.trigger_after_tool(
                tool_name=name,
                tool_params=params,
                tool_result=result,
            )
            return result

        await hook_system.trigger_before_tool(
            tool_name=name,
            tool_params=params,
        )

        invocation = ToolInvocation(
            params=params,
            cwd=cwd,
        )

        if name == "plan_question":
            question_tool = self.get("plan_question")
            if question_tool is not None and hasattr(question_tool, "question_callback"):
                setattr(question_tool, "question_callback", plan_question_callback)
            if set_plan_phase:
                set_plan_phase("asking_questions")

        if approval_manager:
            confirmation = await tool.get_confirmation(invocation)

            if confirmation:
                context = ApprovalContext(
                    tool_name=name,
                    params=params,
                    is_mutating=tool.is_mutating(params),
                    affected_paths=confirmation.affected_paths,
                    command=confirmation.command,
                    is_dangerous=confirmation.is_dangerous,
                )

                decision = await approval_manager.check_approval(context)

                if decision == ApprovalDecision.REJECTED:
                    result = ToolResult.error_result(
                        "Operation rejected by by safety policy",
                    )
                    await hook_system.trigger_after_tool(
                        tool_name=name,
                        tool_params=params,
                        tool_result=result,
                    )
                    return result

                elif decision == ApprovalDecision.NEEDS_CONFIRMATION:
                    approved = await approval_manager.request_confirmation(confirmation)

                    if not approved:
                        result = ToolResult.error_result("User rejected the operation")

                        await hook_system.trigger_after_tool(
                            tool_name=name,
                            tool_params=params,
                            tool_result=result,
                        )
                        return result

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

        await hook_system.trigger_after_tool(
            tool_name=name,
            tool_params=params,
            tool_result=result,
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
