from __future__ import annotations
from ite.client.response import TokenUsage
from dataclasses import field
from typing import Any
from enum import Enum
from dataclasses import dataclass
from ite.tools.base import ToolResult


class AgentEventType(str, Enum):
    # agent lifecycle
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"

    # text streaming
    TEXT_DELTA = "text_delta"
    TEXT_COMPLETE = "text_complete"

    # tool calls
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_PROGRESS = "tool_call_progress"
    TOOL_CALL_COMPLETE = "tool_call_complete"

    # loop detection
    LOOP_DETECTED = "loop_detected"
    CONTEXT_COMPACTING = "context_compacting"
    CONTEXT_COMPACTED = "context_compacted"
    PLAN_READY = "plan_ready"


@dataclass
class AgentEvent:
    type: AgentEventType
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def agent_start(cls, message: str) -> AgentEvent:
        return cls(
            type=AgentEventType.AGENT_START,
            data={"message": message},
        )

    @classmethod
    def agent_end(
        cls,
        response: str | None = None,
        usage: TokenUsage | None = None,
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.AGENT_END,
            data={
                "response": response,
                "usage": usage.__dict__ if usage else None,
            },
        )

    @classmethod
    def agent_error(
        cls,
        error: str,
        details: dict[str, Any] | None = None,
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.AGENT_ERROR,
            data={"error": error, "details": details or {}},
        )

    @classmethod
    def text_delta(cls, content: str) -> AgentEvent:
        return cls(
            type=AgentEventType.TEXT_DELTA,
            data={"content": content},
        )

    @classmethod
    def text_complete(cls, content: str) -> AgentEvent:
        return cls(
            type=AgentEventType.TEXT_COMPLETE,
            data={"content": content},
        )

    @classmethod
    def tool_call_start(
        cls,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.TOOL_CALL_START,
            data={
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
            },
        )

    @classmethod
    def tool_call_complete(
        cls,
        call_id: str,
        name: str,
        result: ToolResult,
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.TOOL_CALL_COMPLETE,
            data={
                "call_id": call_id,
                "name": name,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "metadata": result.metadata,
                "diff": result.diff.to_diff() if result.diff else None,
                "truncated": result.truncated,
                "exit_code": result.exit_code,
            },
        )

    @classmethod
    def tool_call_progress(
        cls,
        call_id: str,
        name: str,
        *,
        output: str,
        metadata: dict[str, Any] | None = None,
        success: bool = True,
        error: str | None = None,
        exit_code: int | None = None,
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.TOOL_CALL_PROGRESS,
            data={
                "call_id": call_id,
                "name": name,
                "success": success,
                "output": output,
                "error": error,
                "metadata": metadata or {},
                "exit_code": exit_code,
            },
        )

    @classmethod
    def loop_detected(cls, message: str) -> AgentEvent:
        return cls(
            type=AgentEventType.LOOP_DETECTED,
            data={"message": message},
        )

    @classmethod
    def context_compacting(
        cls,
        trigger_reason: str = "threshold",
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.CONTEXT_COMPACTING,
            data={
                "trigger_reason": trigger_reason,
            },
        )

    @classmethod
    def context_compacted(
        cls,
        trigger_tokens: int,
        context_window: int,
        summary_chars: int,
        trigger_reason: str = "threshold",
        auto_resume_required: bool = False,
    ) -> AgentEvent:
        return cls(
            type=AgentEventType.CONTEXT_COMPACTED,
            data={
                "trigger_tokens": trigger_tokens,
                "context_window": context_window,
                "summary_chars": summary_chars,
                "trigger_reason": trigger_reason,
                "auto_resume_required": auto_resume_required,
            },
        )

    @classmethod
    def plan_ready(cls, plan_text: str) -> AgentEvent:
        return cls(
            type=AgentEventType.PLAN_READY,
            data={
                "plan_text": plan_text,
            },
        )
