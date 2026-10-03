from __future__ import annotations

from copy import deepcopy
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


_IDENTIFIER_SUFFIX_RE = re.compile(
    r"(?:^|[_-])(?:id|key|slug|uuid|identifier|handle)$|(?:Id|Key|Slug|Uuid|Identifier|Handle)$"
)
_ENTITY_SUFFIX_RE = re.compile(
    r"(?:^|[_-])(?:id|key|slug|uuid|identifier|handle|name)$|(?:Id|Key|Slug|Uuid|Identifier|Handle|Name)$"
)
_DETAIL_TOOL_PREFIX_RE = re.compile(r"^(get|read|fetch|retrieve|describe|open|load)", re.IGNORECASE)
_DISCOVERY_TOOL_PREFIX_RE = re.compile(r"^(list|search|find|lookup|select|resolve|query|browse)", re.IGNORECASE)


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
        return deepcopy(self._tool_info.input_schema or {"type": "object", "properties": {}})

    @property
    def available(self) -> bool:
        from ite.tools.mcp.client import MCPServerStatus
        return (self._client.status == MCPServerStatus.CONNECTED and self._client.config.enabled
                and (self._client.config.enabled_tools is None or self._tool_info.name in self._client.config.enabled_tools))

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
        preflight = self._preflight_missing_context(invocation.params)
        if preflight is not None:
            return preflight
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

            metadata = self._success_metadata()
            if result.get("structured_content") is not None:
                metadata["structured_content"] = result["structured_content"]
            metadata["mcp_content"] = result.get("content", [])
            return ToolResult.success_result(output, metadata=metadata, truncated=result.get("truncated", False))
        except Exception as e:
            raw = f"MCP tool failed: {e}"
            return ToolResult.error_result(
                raw,
                metadata=self._error_metadata(raw),
            )

    def _success_metadata(self) -> dict[str, Any]:
        server_name = self._tool_info.server_name or self.name.split("__", 1)[0]
        return {
            "mcp_server": server_name,
            "mcp_tool": self._tool_info.name,
        }

    def _error_metadata(self, raw_error: str) -> dict[str, Any]:
        server_name = self._tool_info.server_name or self.name.split("__", 1)[0]
        summary, detail, recoverable = self._classify_error(raw_error, server_name)
        metadata: dict[str, Any] = self._success_metadata()
        metadata["ui_summary"] = summary
        metadata["ui_detail"] = detail
        missing_context = self._extract_missing_context_fields(raw_error)
        if missing_context:
            metadata["missing_context"] = missing_context
            metadata["recovery_hint"] = detail
        if recoverable:
            metadata["recoverable"] = True
        return metadata

    def _classify_error(self, raw_error: str, server_name: str) -> tuple[str, str, bool]:
        text = str(raw_error or "").strip()
        compact = " ".join(text.split())
        expected_operation = self._extract_expected_operation(text)
        server_label = self._server_label(server_name)

        if (
            "Input validation error" in text
            or "Invalid arguments for tool" in text
            or "invalid_union" in text
            or "invalid_literal" in text
        ):
            summary = f"That {server_label} call used the wrong input."
            detail = "Retry with corrected arguments."
            if expected_operation:
                detail = f"Use the `{expected_operation}` action instead."
            return (summary, detail, True)

        if "Could not connect to Chrome" in text:
            return (
                "Chrome isn't ready yet.",
                "Open Chrome and allow the debugging session, then try again.",
                True,
            )

        if "Failed to fetch API: 404" in text or re.search(r"\b404\b", compact):
            return (
                f"That {server_label} item wasn't found.",
                "Check the item or identifier, then retry.",
                True,
            )

        if "Failed to fetch API: 401" in text or "Failed to fetch API: 403" in text:
            return (
                f"{server_label} blocked this request.",
                f"Check access or reconnect {server_label}.",
                False,
            )

        missing_context = self._extract_missing_context_fields(text)
        if missing_context or self._looks_like_context_error(text):
            fields = missing_context or ["context"]
            return (
                "Required context is missing.",
                self._missing_context_detail(fields),
                True,
            )

        if "Connection closed" in text:
            return (
                f"{server_label} stopped responding.",
                "Retrying or reconnecting usually fixes this.",
                True,
            )

        first_line = compact.split(". ", 1)[0].strip() if compact else "The MCP request failed."
        return (f"The {server_label} request failed.", first_line, False)

    @staticmethod
    def _server_label(server_name: str) -> str:
        words = [part for part in re.split(r"[-_]+", str(server_name or "").strip()) if part]
        if not words:
            return "MCP"
        return " ".join(word.capitalize() for word in words)

    @staticmethod
    def _extract_expected_operation(text: str) -> str | None:
        match = re.search(r'expected\s+\\?"([^"\\]+)\\?"', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _preflight_missing_context(self, params: dict[str, Any]) -> ToolResult | None:
        schema = self.schema
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        missing_required = [
            name
            for name in required
            if not self._has_value(params.get(name))
            and self._looks_like_context_param(name, properties.get(name, {}), required=True)
        ]
        if missing_required:
            return self._missing_context_result(missing_required)

        if self._is_discovery_tool():
            return None

        return None

    def _missing_context_result(self, fields: list[str]) -> ToolResult:
        detail = self._missing_context_detail(fields)
        missing = ", ".join(fields)
        return ToolResult.error_result(
            f"Missing required context: {missing}. {detail}",
            metadata={
                **self._success_metadata(),
                "recoverable": True,
                "missing_context": fields,
                "ui_summary": "Required context is missing.",
                "ui_detail": detail,
                "recovery_hint": detail,
            },
        )

    def _missing_context_detail(self, fields: list[str]) -> str:
        if not fields:
            return "Use a list, search, or select tool first, then retry."
        suggestions = self._discovery_suggestions(fields)
        field_list = ", ".join(f"`{field}`" for field in fields)
        if suggestions:
            return f"Resolve {field_list} first. Try {suggestions}, then retry."
        return f"Resolve {field_list} first with a list, search, or select tool, then retry."

    def _discovery_suggestions(self, fields: list[str]) -> str:
        configured = self._configured_discovery_suggestions(fields)
        if configured:
            return configured
        candidates: list[str] = []
        tool_names = [info.name for info in self._client.tools]
        for field in fields:
            entity = self._entity_hint_for_field(field)
            for tool_name in tool_names:
                if not _DISCOVERY_TOOL_PREFIX_RE.match(tool_name):
                    continue
                lowered = tool_name.lower()
                if entity and entity not in lowered:
                    continue
                if tool_name not in candidates:
                    candidates.append(tool_name)
                if len(candidates) >= 2:
                    break
            if len(candidates) >= 2:
                break
        if not candidates:
            return ""
        if len(candidates) == 1:
            return f"`{candidates[0]}` first"
        return f"`{candidates[0]}` or `{candidates[1]}` first"

    def _configured_discovery_suggestions(self, fields: list[str]) -> str:
        config_map = getattr(self._client.config, "context_resolution", {}) or {}
        candidates: list[str] = []
        for field in fields:
            keys = [field, field.lower()]
            entity = self._entity_hint_for_field(field)
            if entity:
                keys.extend([entity, entity.lower()])
            for key in keys:
                mapped = config_map.get(key)
                if not mapped:
                    continue
                for tool_name in mapped:
                    if tool_name not in candidates:
                        candidates.append(tool_name)
                    if len(candidates) >= 2:
                        break
                if len(candidates) >= 2:
                    break
            if len(candidates) >= 2:
                break
        if not candidates:
            return ""
        if len(candidates) == 1:
            return f"`{candidates[0]}` first"
        return f"`{candidates[0]}` or `{candidates[1]}` first"

    def _is_detail_tool(self) -> bool:
        return bool(_DETAIL_TOOL_PREFIX_RE.match(self._tool_info.name or self.name))

    def _is_discovery_tool(self) -> bool:
        return bool(_DISCOVERY_TOOL_PREFIX_RE.match(self._tool_info.name or self.name))

    @staticmethod
    def _has_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, dict, set)):
            return bool(value)
        return True

    @classmethod
    def _looks_like_context_param(cls, name: str, prop: dict[str, Any], *, required: bool) -> bool:
        if not name:
            return False
        if _IDENTIFIER_SUFFIX_RE.search(name):
            return True
        description = str(prop.get("description", "") or "")
        title = str(prop.get("title", "") or "")
        combined = " ".join(part for part in [description, title] if part).lower()
        if "patient context" in combined or "launchpad" in combined:
            return True
        if required and ("identifier" in combined or "select" in combined):
            return True
        return False

    @classmethod
    def _entity_hint_for_field(cls, field: str) -> str:
        value = _ENTITY_SUFFIX_RE.sub("", str(field or "")).strip("_- ")
        if not value:
            return ""
        spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        return spaced.replace("_", " ").replace("-", " ").split()[0].lower()

    @classmethod
    def _looks_like_context_error(cls, text: str) -> bool:
        lowered = str(text or "").lower()
        return (
            "no patient context found" in lowered
            or "no context found" in lowered
            or "missing context" in lowered
            or "provide a patientid" in lowered
            or "invoke from" in lowered and "launchpad" in lowered
            or ("missing required field" in lowered and "id" in lowered)
        )

    @classmethod
    def _extract_missing_context_fields(cls, text: str) -> list[str]:
        lowered = str(text or "")
        names: list[str] = []
        for match in re.finditer(
            r"(?:provide|missing required field:?|missing parameter:?|missing)\s+(?:(?:a|an|the)\s+)?[`'\"]?([A-Za-z_][A-Za-z0-9_-]*(?:Id|Key|Slug|Uuid|Identifier|Handle|id|key|slug|uuid|identifier|handle))[`'\"]?",
            lowered,
            re.IGNORECASE,
        ):
            field = match.group(1).strip()
            if field not in names:
                names.append(field)
        return names
