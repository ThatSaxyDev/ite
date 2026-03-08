from ite.hooks.hook_system import HookSystem
from ite.safety.approval import ApprovalDecision
from ite.safety.approval import ApprovalContext
from ite.safety.approval import ApprovalManager
from ite.tools.policy import ToolSelectionPolicy
from ite.tools.subagent import SubagentTool
from ite.tools.subagent import SubagentDefinition
from ite.tools.subagent import get_default_subagent_definitions
from ite.tools.subagent_loader import discover_subagents
from ite.config.config import Config
from ite.tools.builtin import get_all_builtin_tools
from ite.tools.base import ToolInvocation
from ite.tools.base import ToolResult
from pathlib import Path
from typing import Any, Awaitable, Callable
import logging
import time
import json
from ite.tools.base import Tool

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, config: Config):
        self._tools: dict[str, Tool] = {}
        self._mcp_tools: dict[str, Tool] = {}
        self._policy = ToolSelectionPolicy()
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

    def get_tool_contracts(self) -> dict[str, dict[str, Any]]:
        contracts: dict[str, dict[str, Any]] = {}
        for tool in self.get_tools():
            contracts[tool.name] = tool.get_metadata({}).to_dict()
        return contracts

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
        started_at = time.perf_counter()
        tool = self.get(name)

        if tool is None:
            available = sorted(t.name for t in self.get_tools())
            result = ToolResult.error_result(
                f"Tool not found: {name}. Available tools: {', '.join(available)}",
                metadata={
                    "tool_name": name,
                    "available_tools": available,
                },
            )
            await hook_system.trigger_after_tool(
                tool_name=name,
                tool_params=params,
                tool_result=result,
            )
            self._emit_telemetry(
                tool_name=name,
                params=params,
                blocked_reason="tool_not_found",
                result=result,
                started_at=started_at,
            )
            return result

        metadata = tool.get_metadata(params)
        policy_decision = self._policy.evaluate(
            tool_name=name,
            params=params,
            metadata=metadata,
            plan_mode_enabled=plan_mode_enabled,
            plan_phase=plan_phase,
        )
        if not policy_decision.allowed:
            result = ToolResult.error_result(
                policy_decision.reason or "Tool blocked by selection policy",
                metadata={
                    "tool_name": name,
                    "redirect_to": policy_decision.redirect_to,
                    "tool_metadata": metadata.to_dict(),
                    "policy_blocked": True,
                },
            )
            await hook_system.trigger_after_tool(
                tool_name=name,
                tool_params=params,
                tool_result=result,
            )
            self._emit_telemetry(
                tool_name=name,
                params=params,
                blocked_reason=policy_decision.reason or "policy_blocked",
                result=result,
                started_at=started_at,
                tool_metadata=metadata,
            )
            return result

        validation_errors = tool.validate_params(params)

        if validation_errors:
            result = ToolResult.error_result(
                f"Invalid parameters: {'; '.join(validation_errors)}",
                metadata={
                    "tool_name": name,
                    "validation_errors": validation_errors,
                    "tool_metadata": metadata.to_dict(),
                },
            )
            await hook_system.trigger_after_tool(
                tool_name=name,
                tool_params=params,
                tool_result=result,
            )
            self._emit_telemetry(
                tool_name=name,
                params=params,
                blocked_reason="invalid_parameters",
                result=result,
                started_at=started_at,
                tool_metadata=metadata,
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
                        metadata={
                            "tool_name": name,
                            "tool_metadata": metadata.to_dict(),
                            "approval_decision": decision.value,
                        },
                    )
                    await hook_system.trigger_after_tool(
                        tool_name=name,
                        tool_params=params,
                        tool_result=result,
                    )
                    self._emit_telemetry(
                        tool_name=name,
                        params=params,
                        blocked_reason="approval_rejected",
                        result=result,
                        started_at=started_at,
                        tool_metadata=metadata,
                    )
                    return result

                elif decision == ApprovalDecision.NEEDS_CONFIRMATION:
                    approved = await approval_manager.request_confirmation(confirmation)

                    if not approved:
                        result = ToolResult.error_result(
                            "User rejected the operation",
                            metadata={
                                "tool_name": name,
                                "tool_metadata": metadata.to_dict(),
                                "approval_decision": decision.value,
                            },
                        )

                        await hook_system.trigger_after_tool(
                            tool_name=name,
                            tool_params=params,
                            tool_result=result,
                        )
                        self._emit_telemetry(
                            tool_name=name,
                            params=params,
                            blocked_reason="user_rejected_confirmation",
                            result=result,
                            started_at=started_at,
                            tool_metadata=metadata,
                        )
                        return result

        try:
            result = await tool.execute(invocation)
        except Exception as e:
            logger.exception(f"Error executing tool {name}")
            result = ToolResult.error_result(
                f"Internal error: {str(e)}",
                metadata={
                    "tool_name": name,
                    "tool_metadata": metadata.to_dict(),
                },
            )

        result.metadata = result.metadata or {}
        result.metadata.setdefault("tool_name", name)
        result.metadata.setdefault("tool_metadata", metadata.to_dict())

        await hook_system.trigger_after_tool(
            tool_name=name,
            tool_params=params,
            tool_result=result,
        )
        self._emit_telemetry(
            tool_name=name,
            params=params,
            blocked_reason=None,
            result=result,
            started_at=started_at,
            tool_metadata=metadata,
        )
        return result

    def _emit_telemetry(
        self,
        *,
        tool_name: str,
        params: dict[str, Any],
        blocked_reason: str | None,
        result: ToolResult,
        started_at: float,
        tool_metadata: Any | None = None,
    ) -> None:
        payload = {
            "event": "tool_invocation",
            "tool_name": tool_name,
            "success": result.success,
            "blocked_reason": blocked_reason,
            "duration_ms": int((time.perf_counter() - started_at) * 1000),
            "risk_level": (
                tool_metadata.risk_level.value if tool_metadata is not None else None
            ),
            "mutating": tool_metadata.mutating if tool_metadata is not None else None,
            "params_keys": sorted(params.keys()),
            "error": result.error,
        }
        logger.info(json.dumps(payload))


def create_default_registry(config: Config) -> ToolRegistry:
    registry = ToolRegistry(config)

    for tool_class in get_all_builtin_tools():
        registry.register(tool_class(config))

    available_tool_names = set(registry._tools.keys())

    for subagent_definition in get_default_subagent_definitions():
        _validate_subagent_definition(subagent_definition, available_tool_names)
        registry.register(SubagentTool(config, subagent_definition))

    # Discover and register user-defined subagents (override defaults by name)
    user_subagents = discover_subagents(config.cwd)
    for definition in user_subagents:
        try:
            _validate_subagent_definition(definition, available_tool_names)
        except ValueError as e:
            logger.warning("Skipping subagent '%s': %s", definition.name, e)
            continue
        registry.register(SubagentTool(config, definition))

    return registry


def _validate_subagent_definition(
    definition: SubagentDefinition,
    available_tool_names: set[str],
) -> None:
    if not definition.allowed_tools:
        return

    invalid = sorted(t for t in definition.allowed_tools if t not in available_tool_names)
    if invalid:
        raise ValueError(
            "invalid allowed_tools entries: "
            + ", ".join(invalid)
            + ". Valid options: "
            + ", ".join(sorted(available_tool_names))
        )
