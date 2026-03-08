from __future__ import annotations
from ite.agent.events import AgentEventType, AgentEvent
import flet as ft
from ..tokens import *


class AgentEventControllerMixin:
    async def _handle_agent_event(self, event: AgentEvent):
        if not self.page:
            return

        plan_enabled = bool(
            self.agent and self.agent.session and self.agent.session.plan_mode_enabled
        )
        plan_only_phase = bool(
            plan_enabled
            and self.agent
            and self.agent.session
            and self.agent.session.plan_phase != "executing"
        )
        suppressed_tools = {"memory", "plan_question", "todos", "web_search", "web_fetch"}

        if event.type == AgentEventType.TEXT_DELTA:
            content = event.data.get("content", "")
            if content:
                self._hide_thinking_indicator()
                self._stream_assistant_delta(content)

        elif event.type == AgentEventType.TEXT_COMPLETE:
            content = event.data.get("content", "")
            self._hide_thinking_indicator()
            if self.streaming_markdown is not None:
                self._finalize_streaming_message()
            elif content and not (plan_only_phase and content.strip()):
                self._add_message("assistant", content)
            # In plan-only phases, final plan rendering is handled exclusively
            # by PLAN_READY to avoid duplicate plan cards.
            # If the turn is still running after this text block, show activity again.
            if self._is_turn_running:
                self._show_thinking_indicator()

        elif event.type == AgentEventType.TOOL_CALL_START:
            tool_name = event.data.get("name")
            if tool_name in suppressed_tools:
                return
            if plan_only_phase:
                return
            self._hide_thinking_indicator()
            self._add_tool_call(
                event.data.get("call_id", ""),
                tool_name or "",
                event.data.get("arguments", {}),
                event.data.get("tool_kind"),
            )

        elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
            tool_name = event.data.get("name")
            if tool_name in suppressed_tools:
                if self._is_turn_running:
                    self._show_thinking_indicator()
                return
            if plan_only_phase and event.data.get("success", False):
                if self._is_turn_running:
                    self._show_thinking_indicator()
                return
            self._update_tool_call(
                event.data.get("call_id", ""),
                tool_name or "",
                event.data.get("success", False),
                event.data.get("output", ""),
                event.data.get("error"),
                event.data.get("diff"),
                event.data.get("exit_code"),
            )
            # Tool finished but the turn may continue with more reasoning/calls.
            if self._is_turn_running:
                self._show_thinking_indicator()

        elif event.type == AgentEventType.AGENT_ERROR:
            self._hide_thinking_indicator()
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
        elif event.type == AgentEventType.PLAN_READY:
            plan_text = event.data.get("plan_text", "")
            if isinstance(plan_text, str) and plan_text.strip():
                self._add_plan_card(plan_text)
            await self._render_plan_ready_prompt()
