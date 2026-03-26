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
import re
from ite.tools.base import Tool
from ite.safety.approval import classify_command_safety

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

    def normalize_params(
        self,
        *,
        tool_name: str,
        params: dict[str, Any],
        plan_mode_enabled: bool = False,
        plan_phase: str = "idle",
    ) -> dict[str, Any]:
        return self._normalize_params_for_phase(
            tool_name=tool_name,
            params=params,
            plan_mode_enabled=plan_mode_enabled,
            plan_phase=plan_phase,
        )

    async def invoke(
        self,
        name: str,
        params: dict[str, Any],
        cwd: Path,
        hook_system: HookSystem,
        approval_manager: ApprovalManager | None = None,
        *,
        tool_call_id: str | None = None,
        session_id: str | None = None,
        plan_mode_enabled: bool = False,
        plan_phase: str = "idle",
        todo_execution_handoff_active: bool = False,
        set_plan_phase: Callable[[str], None] | None = None,
        plan_question_callback: (
            Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None
        ) = None,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> ToolResult:
        started_at = time.perf_counter()
        params = self._normalize_params_for_phase(
            tool_name=name,
            params=params,
            plan_mode_enabled=plan_mode_enabled,
            plan_phase=plan_phase,
        )
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
            todo_execution_handoff_active=todo_execution_handoff_active,
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
            call_id=tool_call_id,
            session_id=session_id,
            progress_callback=progress_callback,
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
                approval_reason = None
                if context.command:
                    safety = classify_command_safety(context.command).value
                    if decision == ApprovalDecision.REJECTED:
                        approval_reason = (
                            f"Shell command blocked by safety policy ({safety})."
                        )
                    elif decision == ApprovalDecision.NEEDS_CONFIRMATION:
                        approval_reason = (
                            f"Shell command requires approval before execution ({safety})."
                        )

                if decision == ApprovalDecision.REJECTED:
                    result = ToolResult.error_result(
                        approval_reason or "Operation rejected by safety policy",
                        metadata={
                            "tool_name": name,
                            "tool_metadata": metadata.to_dict(),
                            "approval_decision": decision.value,
                            "approval_reason": approval_reason,
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
                            "Approval declined. Operation was not executed.",
                            metadata={
                                "tool_name": name,
                                "tool_metadata": metadata.to_dict(),
                                "approval_decision": decision.value,
                                "approval_reason": approval_reason,
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

    def _normalize_params_for_phase(
        self,
        *,
        tool_name: str,
        params: dict[str, Any],
        plan_mode_enabled: bool,
        plan_phase: str,
    ) -> dict[str, Any]:
        normalized = self._normalize_common_tool_params(tool_name=tool_name, params=params)
        if tool_name != "todos":
            return normalized

        raw_scope = normalized.get("scope")
        if isinstance(raw_scope, str) and raw_scope.strip():
            normalized["scope"] = raw_scope.strip().lower()
            return normalized

        in_planning = plan_mode_enabled and plan_phase != "executing"
        normalized["scope"] = "planning" if in_planning else "execution"
        return normalized

    def _normalize_common_tool_params(
        self,
        *,
        tool_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(params)
        raw_text = ""
        raw_value = normalized.get("raw_arguments", normalized.get("raw"))
        if isinstance(raw_value, str):
            raw_text = raw_value

        def adopt(target: str, *aliases: str) -> None:
            existing = normalized.get(target)
            if existing not in (None, ""):
                return
            for alias in aliases:
                value = normalized.get(alias)
                if value in (None, ""):
                    continue
                normalized[target] = value
                return

        def adopt_from_raw(target: str, *aliases: str) -> None:
            existing = normalized.get(target)
            if existing not in (None, ""):
                return
            if not raw_text.strip():
                return
            for alias in aliases:
                pattern = rf'"{re.escape(alias)}"\s*:\s*"((?:[^"\\]|\\.)*)"'
                match = re.search(pattern, raw_text)
                if not match:
                    continue
                normalized[target] = bytes(match.group(1), "utf-8").decode("unicode_escape")
                return

        if tool_name == "grep":
            adopt("pattern", "query", "search", "regex", "match")
            adopt("path", "file", "target", "directory", "dir")
            return normalized

        if tool_name == "read_file":
            adopt("path", "file", "file_path", "filepath", "target")
            return normalized

        if tool_name == "write_file":
            adopt("path", "file", "file_path", "filepath", "target")
            adopt("content", "text", "body", "new_string", "new_text")
            return normalized

        if tool_name == "shell":
            adopt("command", "cmd", "script")
            command = normalized.get("command")
            if isinstance(command, str) and command.strip():
                sanitized = self._sanitize_shell_command(command)
                if sanitized != command:
                    normalized["command"] = sanitized
                    metadata = normalized.get("_normalization_notes")
                    notes = list(metadata) if isinstance(metadata, list) else []
                    notes.append("Removed /dev/null redirection for sandbox compatibility.")
                    normalized["_normalization_notes"] = notes
            return normalized

        if tool_name == "edit":
            adopt("path", "file", "file_path", "filepath", "target")
            adopt(
                "old_string",
                "old",
                "old_text",
                "oldText",
                "search",
                "find",
                "target_text",
            )
            adopt(
                "new_string",
                "new",
                "new_text",
                "newText",
                "replacement",
                "replace_with",
            )
            if "all" in normalized and "replace_all" not in normalized:
                normalized["replace_all"] = bool(normalized.get("all"))
            return normalized

        if tool_name == "apply_patch":
            adopt("patch", "content", "patch_text", "text")
            if "preview" in normalized and "dry_run" not in normalized:
                normalized["dry_run"] = bool(normalized.get("preview"))
            return normalized

        if tool_name == "spawn_subagent":
            adopt(
                "subagent",
                "specialist",
                "agent",
                "worker",
                "subagent_name",
                "specialist_name",
                "name",
                "topic",
                "area",
            )
            adopt_from_raw(
                "subagent",
                "subagent",
                "specialist",
                "agent",
                "worker",
                "subagent_name",
                "specialist_name",
                "name",
                "topic",
                "area",
            )
            adopt(
                "goal",
                "task",
                "prompt",
                "objective",
                "request",
                "instruction",
                "work",
                "description",
            )
            adopt_from_raw(
                "goal",
                "goal",
                "task",
                "prompt",
                "objective",
                "request",
                "instruction",
                "work",
                "description",
            )
            return normalized

        if tool_name == "spawn_subagents":
            requests = normalized.get("requests")
            if not isinstance(requests, list):
                candidates = normalized.get("items")
                if not isinstance(candidates, list):
                    candidates = normalized.get("subagents")
                if isinstance(candidates, list):
                    requests = []
                    for item in candidates:
                        if not isinstance(item, dict):
                            continue
                        request = dict(item)
                        subagent = (
                            request.get("subagent")
                            or request.get("specialist")
                            or request.get("agent")
                            or request.get("worker")
                            or request.get("name")
                            or request.get("topic")
                            or request.get("area")
                        )
                        goal = (
                            request.get("goal")
                            or request.get("task")
                            or request.get("prompt")
                            or request.get("objective")
                            or request.get("request")
                            or request.get("instruction")
                            or request.get("description")
                            or request.get("work")
                        )
                        normalized_request: dict[str, Any] = {}
                        if subagent not in (None, ""):
                            normalized_request["subagent"] = subagent
                        if goal not in (None, ""):
                            normalized_request["goal"] = goal
                        requests.append(normalized_request)
                    normalized["requests"] = requests
            return normalized

        if tool_name == "wait_subagent":
            adopt("run_ids", "runs", "ids", "run_id")
            adopt_from_raw("run_ids", "runs", "ids", "run_id")
            if isinstance(normalized.get("run_ids"), str):
                normalized["run_ids"] = [normalized["run_ids"]]
            adopt("timeout_seconds", "timeout", "wait_seconds")
            adopt("return_when", "mode", "wait_for")
            adopt_from_raw("return_when", "mode", "wait_for", "return_when")
            return normalized

        if tool_name == "cancel_subagent":
            adopt("run_ids", "runs", "ids", "run_id")
            adopt_from_raw("run_ids", "runs", "ids", "run_id")
            if isinstance(normalized.get("run_ids"), str):
                normalized["run_ids"] = [normalized["run_ids"]]
            return normalized

        if tool_name == "list_subagents":
            adopt("status", "statuses", "state")
            adopt_from_raw("status", "statuses", "state", "status")
            return normalized

        return normalized

    @staticmethod
    def _sanitize_shell_command(command: str) -> str:
        cleaned = str(command)
        cleaned = re.sub(r"\s*(?:1?>|2>)\s*/dev/null\b", "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned

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

    refresh_subagent_tools(
        registry,
        config,
        log_errors=False,
        include_user_subagents=False,
    )

    return registry


def refresh_subagent_tools(
    registry: ToolRegistry,
    config: Config,
    *,
    log_errors: bool = True,
    include_user_subagents: bool = True,
) -> None:
    existing = [
        name
        for name, tool in list(registry._tools.items())
        if isinstance(tool, SubagentTool)
    ]
    for name in existing:
        registry.unregister(name)

    available_tools = {
        tool.name: tool
        for tool in registry.get_tools()
        if not tool.name.startswith("subagent_")
    }

    for subagent_definition in get_default_subagent_definitions():
        try:
            effective_allowed_tools = _validate_subagent_definition(
                subagent_definition, available_tools
            )
        except ValueError as e:
            if log_errors:
                logger.warning(
                    "Skipping default subagent '%s': %s",
                    subagent_definition.name,
                    e,
                )
            continue
        allows_mutation = any(
            available_tools[name].get_metadata({}).mutating
            for name in effective_allowed_tools
        )
        registry.register(
            SubagentTool(
                config,
                subagent_definition,
                allowed_tools=effective_allowed_tools,
                allows_mutation=allows_mutation,
            )
        )

    if include_user_subagents:
        # Discover and register user-defined subagents (override defaults by name)
        user_subagents = discover_subagents(config.cwd)
        for definition in user_subagents:
            try:
                effective_allowed_tools = _validate_subagent_definition(
                    definition, available_tools
                )
            except ValueError as e:
                if log_errors:
                    logger.warning("Skipping subagent '%s': %s", definition.name, e)
                continue
            allows_mutation = any(
                available_tools[name].get_metadata({}).mutating
                for name in effective_allowed_tools
            )
            registry.register(
                SubagentTool(
                    config,
                    definition,
                    allowed_tools=effective_allowed_tools,
                    allows_mutation=allows_mutation,
                )
            )


def _validate_subagent_definition(
    definition: SubagentDefinition,
    available_tools: dict[str, Tool],
) -> list[str]:
    available_tool_names = set(available_tools.keys())

    if not definition.allowed_tools:
        return sorted(
            name
            for name, tool in available_tools.items()
            if tool.get_metadata({}).supports_subagent_use
        )

    invalid = sorted(t for t in definition.allowed_tools if t not in available_tool_names)
    if invalid:
        raise ValueError(
            "invalid allowed_tools entries: "
            + ", ".join(invalid)
            + ". Valid options: "
            + ", ".join(sorted(available_tool_names))
        )

    unsupported = sorted(
        t
        for t in definition.allowed_tools
        if not available_tools[t].get_metadata({}).supports_subagent_use
    )
    if unsupported:
        raise ValueError(
            "subagent-ineligible tools in allowed_tools: "
            + ", ".join(unsupported)
        )

    return list(definition.allowed_tools)
