from __future__ import annotations
import asyncio
import json
from typing import Any
from pathlib import Path
import flet as ft
from ite.agent.session import Session
from ite.agent.session_manager import SessionManager, SessionSnapshot
from ..tokens import *


class SessionControllerMixin:
    GUI_SESSION_RENDER_LIMIT = 80

    def _cancel_session_hydration_task(self):
        task = getattr(self, "_session_hydration_task", None)
        if task and hasattr(task, "done") and hasattr(task, "cancel") and not task.done():
            task.cancel()
        self._session_hydration_task = None
        self._hydrating_session_id = None

    async def _start_new_thread(self):
        """Start a fresh agent session instead of clearing the current one."""
        self._set_loading(True)
        try:
            self._cancel_session_hydration_task()
            await self._cancel_active_turn_and_wait()
            await self._ensure_agent()
            if not self.agent or not self.agent.session:
                return

            # Persist current thread before switching if it has real turns.
            if self.agent.session.turn_count > 0:
                await self._auto_save()

            previous = self.agent.session
            fresh = Session(config=self.config)

            # Close resources bound to the old live session before replacing it.
            await previous.client.close()
            await previous.mcp_manager.shutdown()
            await fresh.initialize()
            fresh.approval_manager.confirmation_callback = self._gui_confirmation_callback
            self.agent.session = fresh
            if hasattr(self, "_sync_plan_toggle_ui"):
                self._sync_plan_toggle_ui()
            if hasattr(self, "_refresh_workboard_from_session"):
                self._refresh_workboard_from_session()

            self.active_session_id = None
            self._set_current_session_title(None)

            if self.messages_column and self.page:
                self._clear_chat_controls()
                self._safe_page_update()

            self._tool_call_row_indices.clear()
            self.streaming_markdown = None
            self.streaming_container = None
            self.streaming_text = ""
            if hasattr(self, "_clear_pending_attachments"):
                self._clear_pending_attachments()
            self._refresh_sidebar_threads()
            self._add_assistant_card(
                "New Thread",
                ft.Text("Started a fresh session.", color=TEXT_SECONDARY),
            )
        except Exception as e:
            self._add_message("system", f"Error starting new thread: {e}", is_error=True)
        finally:
            self._set_loading(False)

    async def _auto_save(self):
        if not self.agent or not self.agent.session:
            return
        if self.agent.session.turn_count == 0:
            return

        session = self.agent.session
        try:
            if session.name is None:
                session.name = await self._generate_session_name(session)

            snapshot = SessionSnapshot(
                session_id=session.session_id,
                name=session.name,
                workspace_path=str(self.config.cwd.resolve()),
                created_at=session.created_at,
                updated_at=session.updated_at,
                turn_count=session.turn_count,
                messages=session.context_manager.get_messages(),
                total_usage=session.context_manager.total_usage,
                plan_mode_enabled=session.plan_mode_enabled,
                plan_phase=session.plan_phase,
                plan_questions_asked=session.plan_questions_asked,
                plan_target_questions=session.plan_target_questions,
                pending_plan_text=session.pending_plan_text,
                active_plan_text=session.active_plan_text,
                todos_state=session.export_todos_state(),
                show_planning_todos=session.show_planning_todos,
            )
            SessionManager().save_session(snapshot)
            self._set_current_session_title(session.name)
            self._refresh_workspace_options()
            self._refresh_sidebar_threads()
        except Exception:
            # Keep GUI responsive; autosave failure should not break chat flow.
            return

    async def _generate_session_name(self, session: Session) -> str:
        first_user = ""
        try:
            messages = session.context_manager.get_messages()
            first_assistant = ""
            for msg in messages:
                if msg.get("role") == "user" and not first_user:
                    first_user = msg.get("content", "")[:200]
                elif msg.get("role") == "assistant" and first_user and not first_assistant:
                    first_assistant = msg.get("content", "")[:200]
                    break

            if not first_user:
                return "New thread"

            naming_messages = [
                {
                    "role": "user",
                    "content": (
                        "Generate a concise 3-6 word title for this conversation. "
                        "Reply with ONLY the title text, nothing else. No quotes, no punctuation at the end.\n\n"
                        f"User: {first_user}\n"
                        + (f"Assistant: {first_assistant}" if first_assistant else "")
                    ),
                }
            ]

            title = ""
            async for event in session.client.chat_completion(
                naming_messages, tools=None, stream=True
            ):
                if event.text_delta and event.text_delta.content:
                    title += event.text_delta.content

            title = title.strip()[:60]
            if title:
                return title
        except Exception:
            pass

        fallback = first_user.split(".")[0].split("?")[0].split("!")[0][:60]
        return fallback.strip() or "New thread"

    async def _open_session_from_sidebar(self, session_id: str):
        self._set_loading(True)
        try:
            self._cancel_session_hydration_task()
            await self._cancel_active_turn_and_wait()
            snapshot = await asyncio.to_thread(SessionManager().load_session, session_id)
            if snapshot is None:
                self._add_message("system", f"Session not found: {session_id}", is_error=True)
                return

            if snapshot.workspace_path:
                snapshot_workspace = Path(snapshot.workspace_path).resolve()
                if snapshot_workspace != self.config.cwd.resolve():
                    self.config.cwd = snapshot_workspace
                    if self.header_workspace_text:
                        self.header_workspace_text.value = f"Workspace: {self.config.cwd}"
                    if self.agent is not None:
                        await self._shutdown_agent()
                    self._refresh_workspace_options()
                    self._refresh_sidebar_threads()
                    if self.page:
                        self.page.run_task(self._refresh_branch_options_async)

            await self._ensure_agent()
            if not self.agent:
                self._add_message("system", "Error: agent not initialized", is_error=True)
                return

            await self._resume_agent_session(snapshot)
            self.active_session_id = snapshot.session_id
            if hasattr(self, "_clear_pending_attachments"):
                self._clear_pending_attachments()
            self._refresh_sidebar_threads()
            self._set_current_session_title(snapshot.name)
            self._clear_chat_controls()
            render_limit = self.GUI_SESSION_RENDER_LIMIT
            hidden_count = max(0, len(snapshot.messages) - render_limit)
            rendered_messages = (
                snapshot.messages[-render_limit:]
                if hidden_count > 0
                else snapshot.messages
            )
            await self._hydrate_chat_from_snapshot(
                rendered_messages,
                expected_session_id=snapshot.session_id,
            )
            self.loading_session_id = None
            self._reset_turn_ui_state()
            self._refresh_sidebar_threads()
            self._set_loading(False)
            if hidden_count > 0:
                self._add_assistant_card(
                    "Transcript",
                    ft.Column(
                        [
                            ft.Text(
                                f"Showing the latest {render_limit} messages for speed. "
                                f"{hidden_count} older messages are available in the saved session.",
                                color=TEXT_SECONDARY,
                            ),
                            ft.Row(
                                [
                                    ft.OutlinedButton(
                                        "Load full transcript",
                                        on_click=lambda _e, sid=snapshot.session_id: (
                                            self.page.run_task(
                                                self._load_full_transcript_for_active_session,
                                                sid,
                                            )
                                            if self.page
                                            else None
                                        ),
                                    )
                                ],
                                alignment=ft.MainAxisAlignment.START,
                            ),
                        ],
                        tight=True,
                        spacing=12,
                    ),
                )
            self._add_assistant_card(
                "Session Loaded",
                ft.Text(
                    f"{snapshot.name or snapshot.session_id} · {snapshot.turn_count} turns",
                    color=TEXT_SECONDARY,
                ),
            )
            await self._scroll_chat_to_bottom_async(animate=False, force=True)
            await asyncio.sleep(0.06)
            await self._scroll_chat_to_bottom_async(animate=False, force=True)
        except Exception as e:
            self._add_message("system", f"Error loading session: {e}", is_error=True)
        finally:
            if self.loading_session_id == session_id:
                self.loading_session_id = None
                self._reset_turn_ui_state()
                self._refresh_sidebar_threads()
                self._set_loading(False)

    async def _resume_agent_session(self, snapshot):
        if not self.agent:
            return

        resumed = self.agent.session
        if resumed is None:
            resumed = Session(config=self.config)
            await resumed.initialize()
            self.agent.session = resumed

        resumed.session_id = snapshot.session_id
        resumed.name = snapshot.name
        resumed.created_at = snapshot.created_at
        resumed.updated_at = snapshot.updated_at
        resumed.turn_count = snapshot.turn_count
        resumed.pending_plan_text = snapshot.pending_plan_text
        resumed.active_plan_text = snapshot.active_plan_text
        resumed.show_planning_todos = snapshot.show_planning_todos

        if resumed.context_manager is None:
            await resumed.initialize()

        resumed.set_plan_mode(snapshot.plan_mode_enabled)
        resumed.plan_questions_asked = snapshot.plan_questions_asked
        resumed.plan_target_questions = snapshot.plan_target_questions
        resumed.set_plan_phase(snapshot.plan_phase)
        resumed.context_manager.set_messages(snapshot.messages)
        resumed.context_manager.total_usage = snapshot.total_usage
        resumed.restore_todos_state(snapshot.todos_state)
        resumed.approval_manager.confirmation_callback = self._gui_confirmation_callback
        if hasattr(self, "_sync_plan_toggle_ui"):
            self._sync_plan_toggle_ui()
        if hasattr(self, "_refresh_workboard_from_session"):
            self._refresh_workboard_from_session()

    async def _load_full_transcript_for_active_session(self, expected_session_id: str):
        if (
            not self.agent
            or not self.agent.session
            or self.active_session_id != expected_session_id
        ):
            return
        try:
            messages = self.agent.session.context_manager.get_messages()
            await self._hydrate_chat_from_snapshot(
                messages,
                expected_session_id=expected_session_id,
            )
            if self.active_session_id != expected_session_id:
                return
            self._add_assistant_card(
                "Transcript",
                ft.Text(
                    "Loaded full saved transcript.",
                    color=TEXT_SECONDARY,
                ),
            )
            await self._scroll_chat_to_bottom_async(animate=False, force=True)
        except asyncio.CancelledError:
            return

    async def _hydrate_chat_from_snapshot(
        self,
        messages: list[dict[str, Any]],
        *,
        expected_session_id: str | None = None,
    ):
        if not self.messages_column or not self.page:
            return

        self._clear_chat_controls()
        self._tool_call_row_indices.clear()
        if hasattr(self, "_tool_args_by_call_id"):
            self._tool_args_by_call_id.clear()
        self.streaming_markdown = None
        self.streaming_container = None
        self.streaming_text = ""

        tool_call_names: dict[str, str] = {}

        def _tool_kind_for_name(tool_name: str) -> str | None:
            if not self.agent or not self.agent.session:
                return None
            tool = self.agent.session.tool_registry.get(tool_name)
            if not tool:
                return None
            return tool.kind.value

        processed = 0
        batch_size = 32

        self._defer_ui_updates = True
        try:
            for message in messages:
                if expected_session_id and self.active_session_id != expected_session_id:
                    return
                processed += 1
                role = message.get("role")
                content = message.get("content", "")

                if role == "system":
                    # Internal system prompt; omit from UI transcript.
                    continue

                if role == "user":
                    self._append_chat_control(self.build_chat_message("user", content))
                    continue

                if role == "assistant":
                    if content:
                        self._append_chat_control(
                            self.build_chat_message("assistant", content)
                        )
                    for tool_call in message.get("tool_calls") or []:
                        call_id = str(tool_call.get("id", "") or "")
                        function = tool_call.get("function", {}) or {}
                        tool_name = str(function.get("name", "tool") or "tool")
                        raw_args = function.get("arguments", "") or ""
                        try:
                            parsed_args = json.loads(raw_args) if raw_args else {}
                        except Exception:
                            parsed_args = {"raw": raw_args}

                        tool_call_names[call_id] = tool_name
                        self._add_tool_call(
                            call_id,
                            tool_name,
                            parsed_args if isinstance(parsed_args, dict) else {},
                            _tool_kind_for_name(tool_name),
                        )
                    continue

                if role == "tool":
                    call_id = str(message.get("tool_call_id", "") or "")
                    tool_name = tool_call_names.get(call_id, "tool")
                    output = content if isinstance(content, str) else str(content)
                    success = not output.lstrip().startswith("Error:")
                    self._update_tool_call(
                        call_id,
                        tool_name,
                        success,
                        output,
                        None if success else output,
                        None,
                        None,
                        None,
                    )
                    continue

                if processed % batch_size == 0:
                    self._defer_ui_updates = False
                    self._safe_page_update()
                    await asyncio.sleep(0)
                    self._defer_ui_updates = True
        finally:
            self._defer_ui_updates = False

        self._safe_page_update()
        await self._scroll_chat_to_bottom_async(animate=False, force=True)
