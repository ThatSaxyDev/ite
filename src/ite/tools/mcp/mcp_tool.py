from typing import Any
import re
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
                return ToolResult.error_result(
                    output,
                    metadata=self._error_metadata(str(output or "")),
                )

            return ToolResult.success_result(output)
        except Exception as e:
            raw = f"MCP tool failed: {e}"
            return ToolResult.error_result(
                raw,
                metadata=self._error_metadata(raw),
            )

    def _error_metadata(self, raw_error: str) -> dict[str, Any]:
        summary, detail, recoverable = self._classify_error(raw_error)
        metadata: dict[str, Any] = {
            "mcp_server": self._tool_info.server_name or self.name.split("__", 1)[0],
            "mcp_tool": self._tool_info.name,
            "ui_summary": summary,
            "ui_detail": detail,
        }
        if recoverable:
            metadata["recoverable"] = True
        return metadata

    def _classify_error(self, raw_error: str) -> tuple[str, str, bool]:
        text = str(raw_error or "").strip()
        compact = " ".join(text.split())
        expected_operation = self._extract_expected_operation(text)

        if (
            "Input validation error" in text
            or "Invalid arguments for tool" in text
            or "invalid_union" in text
            or "invalid_literal" in text
        ):
            summary = "That Netlify call used the wrong input."
            detail = "Trying again with corrected arguments."
            if expected_operation:
                detail = f"Trying the `{expected_operation}` action instead."
            return (summary, detail, True)

        if "Failed to fetch API: 404" in text or re.search(r"\b404\b", compact):
            return (
                "That Netlify item wasn't found.",
                "Trying a different site or deploy.",
                True,
            )

        if "Failed to fetch API: 401" in text or "Failed to fetch API: 403" in text:
            return (
                "Netlify blocked this request.",
                "Check workspace access or reconnect Netlify.",
                False,
            )

        if "Connection closed" in text:
            return (
                "Netlify stopped responding.",
                "Retrying or reconnecting usually fixes this.",
                True,
            )

        first_line = compact.split(". ", 1)[0].strip() if compact else "The MCP request failed."
        return ("The Netlify request failed.", first_line, False)

    @staticmethod
    def _extract_expected_operation(text: str) -> str | None:
        match = re.search(r'expected\s+\\?"([^"\\]+)\\?"', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
