from __future__ import annotations
from ite.agent.events import AgentEventType, AgentEvent
import flet as ft
from ..tokens import *


class AgentEventControllerMixin:
    async def _handle_agent_event(self, event: AgentEvent):
        if not self.page:
            return

        if event.type == AgentEventType.TEXT_DELTA:
            content = event.data.get("content", "")
            if content:
                self._stream_assistant_delta(content)

        elif event.type == AgentEventType.TEXT_COMPLETE:
            content = event.data.get("content", "")
            if self.streaming_markdown is not None:
                self._finalize_streaming_message()
            elif content:
                self._add_message("assistant", content)

        elif event.type == AgentEventType.TOOL_CALL_START:
            self._add_tool_call(
                event.data.get("call_id", ""),
                event.data.get("name", ""),
                event.data.get("arguments", {}),
                event.data.get("tool_kind"),
            )

        elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
            self._update_tool_call(
                event.data.get("call_id", ""),
                event.data.get("name", ""),
                event.data.get("success", False),
                event.data.get("output", ""),
                event.data.get("error"),
                event.data.get("diff"),
                event.data.get("exit_code"),
            )

        elif event.type == AgentEventType.AGENT_ERROR:
            self._add_message(
                "system",
                f"Error: {event.data.get('error', 'Unknown error')}",
                is_error=True,
            )

        elif event.type == AgentEventType.CONTEXT_COMPACTED:
            trigger_tokens = int(event.data.get("trigger_tokens", 0))
            context_window = int(event.data.get("context_window", 0))
            used_pct = (trigger_tokens / context_window * 100) if context_window else 0
            self._add_assistant_card(
                "Context",
                ft.Text(
                    f"Context compacted at {trigger_tokens}/{context_window} tokens ({used_pct:.1f}% used).",
                    color=TEXT_SECONDARY,
                ),
            )

