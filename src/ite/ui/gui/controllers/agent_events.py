from __future__ import annotations
from ite.agent.events import AgentEventType, AgentEvent
import flet as ft
from ite.ui.tool_narrative import progress_label
from ..tokens import *


class AgentEventControllerMixin:
    def _progress_indicator_label(
        self,
        *,
        tool_name: str | None = None,
        arguments: dict | None = None,
        metadata: dict | None = None,
        phase: str = "reasoning",
        plan_only_phase: bool = False,
    ) -> str:
        return progress_label(
            tool_name=tool_name,
            arguments=arguments,
            metadata=metadata,
            phase=phase,
            plan_mode=plan_only_phase,
        )

    def _resolve_todo_scope_for_event(
        self,
        *,
        arguments: dict | None = None,
        metadata: dict | None = None,
    ) -> str:
        if isinstance(metadata, dict) and isinstance(metadata.get("scope"), str):
            return str(metadata.get("scope")).strip().lower()
        if isinstance(arguments, dict) and isinstance(arguments.get("scope"), str):
            return str(arguments.get("scope")).strip().lower()
        if (
            self.agent
            and self.agent.session
            and self.agent.session.plan_mode_enabled
            and self.agent.session.plan_phase != "executing"
        ):
            return "planning"
        return "execution"

    def _should_hide_todo_scope(self, scope: str) -> bool:
        if scope != "planning":
            return False
        if not self.agent or not self.agent.session:
            return True
        return not bool(self.agent.session.show_planning_todos)

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
        suppressed_tools = {"memory", "plan_question"}

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
                self._show_thinking_indicator(
                    self._progress_indicator_label(plan_only_phase=plan_only_phase)
                )

        elif event.type == AgentEventType.TOOL_CALL_START:
            tool_name = event.data.get("name")
            if tool_name == "todos":
                # Todos render in Workboard; keep chat stream clean.
                if self._is_turn_running:
                    self._show_thinking_indicator(
                        self._progress_indicator_label(
                            tool_name=tool_name,
                            arguments=event.data.get("arguments", {}),
                            plan_only_phase=plan_only_phase,
                        )
                    )
                return
            if tool_name in suppressed_tools:
                return
            if plan_only_phase and tool_name not in {"todos", "web_search", "web_fetch"}:
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
            if tool_name == "todos":
                scope = self._resolve_todo_scope_for_event(metadata=event.data.get("metadata"))
                metadata = event.data.get("metadata") if isinstance(event.data.get("metadata"), dict) else {}
                action = str(metadata.get("action", "")).strip().lower()
                scope_name = str(metadata.get("scope", "")).strip().lower()
                total = int(metadata.get("total", 0) or 0)
                changed_ids = metadata.get("changed_ids", [])
                changed_count = len(changed_ids) if isinstance(changed_ids, list) else 0
                success = bool(event.data.get("success", False))
                if hasattr(self, "_refresh_workboard_from_session"):
                    self._refresh_workboard_from_session()
                if (
                    success
                    and action == "add"
                    and scope_name == "execution"
                    and total > 0
                    and changed_count == total
                    and hasattr(self, "_open_workboard_if_available")
                ):
                    self._open_workboard_if_available()
                if not self._should_hide_todo_scope(scope):
                    self._add_todo_compact_notice(
                        metadata,
                        success,
                    )
                if self._is_turn_running:
                    self._show_thinking_indicator(
                        self._progress_indicator_label(
                            tool_name=tool_name,
                            metadata=event.data.get("metadata"),
                            phase="post_tool",
                            plan_only_phase=plan_only_phase,
                        )
                    )
                return
            if tool_name in suppressed_tools:
                if self._is_turn_running:
                    self._show_thinking_indicator(
                        self._progress_indicator_label(
                            tool_name=tool_name,
                            metadata=event.data.get("metadata"),
                            phase="post_tool",
                            plan_only_phase=plan_only_phase,
                        )
                    )
                return
            if (
                plan_only_phase
                and tool_name not in {"todos", "web_search", "web_fetch"}
                and event.data.get("success", False)
            ):
                if self._is_turn_running:
                    self._show_thinking_indicator(
                        self._progress_indicator_label(
                            tool_name=tool_name,
                            metadata=event.data.get("metadata"),
                            phase="post_tool",
                            plan_only_phase=plan_only_phase,
                        )
                    )
                return
            self._update_tool_call(
                event.data.get("call_id", ""),
                tool_name or "",
                event.data.get("success", False),
                event.data.get("output", ""),
                event.data.get("error"),
                event.data.get("metadata"),
                event.data.get("diff"),
                event.data.get("exit_code"),
            )
            # Tool finished but the turn may continue with more reasoning/calls.
            if self._is_turn_running:
                self._show_thinking_indicator(
                    self._progress_indicator_label(
                        tool_name=tool_name,
                        metadata=event.data.get("metadata"),
                        phase="post_tool",
                        plan_only_phase=plan_only_phase,
                    )
                )

        elif event.type == AgentEventType.AGENT_ERROR:
            self._hide_thinking_indicator()
            error_text = str(event.data.get("error", "Unknown error"))
            if "Maximum turns" in error_text:
                self._show_recovery_actions_card(
                    "This run hit the turn limit before finishing."
                )
            else:
                self._add_message(
                    "system",
                    f"Error: {error_text}",
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
                if hasattr(self, "_refresh_workboard_from_session"):
                    self._refresh_workboard_from_session()
                if hasattr(self, "_open_workboard_if_available"):
                    self._open_workboard_if_available()
            await self._render_plan_ready_prompt()
