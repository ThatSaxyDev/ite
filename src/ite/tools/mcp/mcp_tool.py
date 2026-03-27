from typing import Any
from ite.config.config import Config
from ite.tools.base import (
    Tool,
    ToolInvocation,
    ToolKind,
    ToolMetadata,
    ToolResult,
    ToolRiskLevel,
)
from ite.tools.mcp.client import MCPClient, MCPToolInfo


class MCPTool(Tool):
    def __init__(
        self,
        config: Config,
        client: MCPClient,
        tool_info: MCPToolInfo,
        name: str,
    ) -> None:
        super().__init__(config)
        self._tool_info = tool_info
        self._client = client
        self.name = name
        self.description = self._tool_info.description or self._tool_info.title or name

    @property
    def schema(self) -> dict[str, Any]:
        input_schema = self._tool_info.input_schema or {}
        return {
            "type": "object",
            "properties": input_schema.get("properties", {}),
            "required": input_schema.get("required", []),
            "additionalProperties": input_schema.get("additionalProperties", True),
        }

    def is_mutating(self, params: dict[str, Any]) -> bool:
        annotations = self._tool_info.annotations
        if annotations.get("destructiveHint") is True:
            return True
        if annotations.get("readOnlyHint") is True:
            return False
        return True

    kind = ToolKind.MCP

    def get_metadata(self, params: dict[str, Any]) -> ToolMetadata:
        annotations = self._tool_info.annotations
        mutating = self.is_mutating(params)

        if annotations.get("destructiveHint") is True:
            risk_level = ToolRiskLevel.HIGH
        elif annotations.get("readOnlyHint") is True:
            risk_level = ToolRiskLevel.LOW
        else:
            risk_level = ToolRiskLevel.MEDIUM

        return ToolMetadata(
            mutating=mutating,
            risk_level=risk_level,
            allowed_in_plan_mode=not mutating,
            supports_subagent_use=True,
            output_schema=self._tool_info.output_schema or {"type": "string"},
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        try:
            result = await self._client.call_tool(
                self._tool_info.name,
                invocation.params,
            )
            output = result.get("output", "")
            is_error = result.get("is_error", False)

            if is_error:
                return ToolResult.error_result(output)

            return ToolResult.success_result(output)
        except Exception as e:
            return ToolResult.error_result(f"MCP tool failed: {e}")
