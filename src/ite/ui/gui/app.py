from __future__ import annotations

import asyncio
import flet as ft
from urllib.parse import urlparse
from typing import Any

from ite.agent.agent import Agent
from ite.commands import build_registry
from ite.config.config import Config
from ite.config.loader import save_system_config
from ite.tools.base import ToolConfirmation

from .builders.layout import LayoutBuilderMixin
from .builders.messages import MessageBuilderMixin
from .controllers.scroll import ScrollControllerMixin
from .controllers.workspace import WorkspaceControllerMixin
from .controllers.branch import BranchControllerMixin
from .controllers.approval import ApprovalControllerMixin
from .controllers.sessions import SessionControllerMixin
from .controllers.commands import CommandControllerMixin
from .controllers.agent_events import AgentEventControllerMixin
from .tokens import *


class GUIApp(
    LayoutBuilderMixin,
    MessageBuilderMixin,
    ScrollControllerMixin,
    WorkspaceControllerMixin,
    BranchControllerMixin,
    ApprovalControllerMixin,
    SessionControllerMixin,
    CommandControllerMixin,
    AgentEventControllerMixin,
):
    def __init__(self, config: Config):
        self.config = config
        self.agent: Agent | None = None
        self.page: ft.Page | None = None

        self.messages_column: ft.Column | None = None
        self.chat_bottom_spacer: ft.Container | None = None
        self.input_field: ft.TextField | None = None
        self.send_button: ft.IconButton | None = None
        self.loading_indicator: ft.ProgressRing | None = None
        self.model_selector: ft.Control | None = None
        self.model_selector_text: ft.Text | None = None
        self.model_items: list[str] = []
        self.model_picker_dialog: ft.AlertDialog | None = None
        self.workspace_selector: ft.Dropdown | None = None
        self.branch_selector: ft.Control | None = None
        self.branch_selector_text: ft.Text | None = None
        self.branch_controls_row: ft.Row | None = None
        self.branch_create_button: ft.IconButton | None = None
        self.branch_dialog: ft.AlertDialog | None = None
        self.branch_name_input: ft.TextField | None = None
        self.branch_picker_dialog: ft.AlertDialog | None = None
        self.branch_picker_search: ft.TextField | None = None
        self.branch_picker_list: ft.Column | None = None
        self.branch_items: list = []
        self.current_branch_name: str | None = None
        self.branch_loading: bool = False
        self.plan_toggle_button: ft.TextButton | None = None
        self.plan_mode_badge: ft.Text | None = None
        self._plan_question_future: asyncio.Future | None = None
        self._plan_confirm_future: asyncio.Future | None = None
        self._plan_question_count: int = 0
        self._branch_workspace_key: str | None = None
        self._branch_sync_task: asyncio.Task | None = None
        self._branch_sync_running: bool = False
        self.approval_selector: ft.Dropdown | None = None
        self.header_session_text: ft.Text | None = None
        self.header_workspace_text: ft.Text | None = None
        self.current_session_title: str = "New thread"
        self.sidebar_threads_column: ft.Column | None = None
        self.sidebar_root: ft.Container | None = None
        self.sidebar_top_row: ft.Row | None = None
        self.sidebar_new_thread_container: ft.Container | None = None
        self.sidebar_body: ft.Column | None = None
        self.sidebar_toggle_button: ft.IconButton | None = None
        self.sidebar_new_thread_button: ft.TextButton | None = None
        self.sidebar_new_thread_compact: ft.IconButton | None = None
        self.sidebar_workspace_block: ft.Column | None = None
        self.sidebar_threads_label: ft.Text | None = None
        self.sidebar_footer: ft.Container | None = None
        self.sidebar_collapsed: bool = False
        self.active_session_id: str | None = None
        self.loading_session_id: str | None = None
        self.sidebar_sessions_cache: list[dict] = []
        self.sidebar_sessions_by_id: dict[str, dict] = {}
        self.app_mode: str = "setup" if self.config.needs_setup else "chat"
        self.chat_shell: ft.Row | None = None
        self.setup_view: ft.Container | None = None
        self.setup_error_text: ft.Text | None = None
        self.setup_base_url_field: ft.TextField | None = None
        self.setup_api_key_field: ft.TextField | None = None
        self.setup_model_field: ft.TextField | None = None

        self.confirmation_dialog: ft.AlertDialog | None = None
        self.pending_confirmation: ToolConfirmation | None = None

        self.streaming_markdown: ft.Markdown | None = None
        self.streaming_container: ft.Container | None = None
        self.streaming_text: str = ""
        self._tool_call_row_indices: dict[str, int] = {}
        self._tool_args_by_call_id: dict[str, dict[str, Any]] = {}
        self._active_turn_task: asyncio.Task | None = None
        self._is_turn_running: bool = False
        self._active_turn_id: int = 0
        self._is_closing: bool = False
        self._plan_ready_prompt_open: bool = False
        self.thinking_row: ft.Row | None = None
        self.thinking_text: ft.Text | None = None
        self.thinking_spinner: ft.ProgressRing | None = None
        self._thinking_task: asyncio.Task | None = None

        self._command_registry = build_registry()
        self._auto_scroll_enabled = True
        self._scroll_request_id = 0
        self._defer_ui_updates: bool = False

    def _is_page_alive(self) -> bool:
        if self._is_closing or not self.page:
            return False
        try:
            _ = self.page.session
            return True
        except Exception:
            return False

    def _safe_page_update(self, *controls: ft.Control) -> bool:
        if self._defer_ui_updates:
            return True
        if not self._is_page_alive() or not self.page:
            return False
        try:
            if controls:
                self.page.update(*controls)
            else:
                self.page.update()
            return True
        except RuntimeError as ex:
            if "destroyed session" in str(ex).lower():
                self._is_closing = True
            return False
        except Exception:
            return False

    def _safe_control_update(self, control: ft.Control | None) -> bool:
        if control is None or not self._is_page_alive():
            return False
        try:
            control.update()
            return True
        except RuntimeError as ex:
            if "destroyed session" in str(ex).lower():
                self._is_closing = True
            return False
        except Exception:
            return False

    def _ensure_chat_bottom_spacer(self):
        if not self.messages_column:
            return
        if self.chat_bottom_spacer is None:
            self.chat_bottom_spacer = ft.Container(height=16)
        controls = self.messages_column.controls
        if self.chat_bottom_spacer in controls:
            controls.remove(self.chat_bottom_spacer)
        controls.append(self.chat_bottom_spacer)

    def _append_chat_control(self, control: ft.Control) -> int | None:
        if not self.messages_column:
            return None
        self._ensure_chat_bottom_spacer()
        controls = self.messages_column.controls
        if controls and controls[-1] is self.chat_bottom_spacer:
            controls.insert(len(controls) - 1, control)
            return len(controls) - 2
        controls.append(control)
        self._ensure_chat_bottom_spacer()
        return len(self.messages_column.controls) - 2

    def _clear_chat_controls(self):
        if not self.messages_column:
            return
        self.messages_column.controls.clear()
        self._ensure_chat_bottom_spacer()

    def _remove_chat_control(self, control: ft.Control):
        if not self.messages_column:
            return
        if control in self.messages_column.controls:
            self.messages_column.controls.remove(control)
        self._ensure_chat_bottom_spacer()

    async def _run_agent(self, message: str, turn_id: int):
        try:
            if turn_id != self._active_turn_id:
                return
            self._is_turn_running = True
            self._set_loading(True)
            self._add_message("user", message)
            self._show_thinking_indicator()
            await self._ensure_agent()

            if not self.agent:
                self._add_message("system", "Error: agent not initialized", is_error=True)
                return

            async for event in self.agent.run(message):
                if turn_id != self._active_turn_id:
                    return
                await self._handle_agent_event(event)
                if turn_id != self._active_turn_id:
                    return
            await self._auto_save()
        except asyncio.CancelledError:
            if turn_id == self._active_turn_id:
                self._add_assistant_card(
                    "Interrupted",
                    ft.Text("Stopped current turn.", color=ft.Colors.with_opacity(0.85, ft.Colors.AMBER_300)),
                )
        except Exception as e:
            if turn_id == self._active_turn_id:
                self._add_message("system", f"Error: {str(e)}", is_error=True)
        finally:
            if turn_id == self._active_turn_id:
                self._is_turn_running = False
                self._active_turn_task = None
                self._hide_thinking_indicator()
                self._set_loading(False)

    async def _ensure_agent(self) -> None:
        if self.agent is not None:
            return

        self.agent = Agent(
            config=self.config,
            confirmation_callback=self._gui_confirmation_callback,
            plan_question_callback=self._gui_plan_question_callback,
        )
        await self.agent.__aenter__()
        if self.agent.session:
            self.active_session_id = self.agent.session.session_id
            self._set_current_session_title(self.agent.session.name)
            self._sync_plan_toggle_ui()

    def _on_send(self, e):
        if self._is_turn_running:
            if self.page:
                self.page.run_task(self._stop_active_turn)
            return

        if not self.input_field or not self.page:
            return

        message = self.input_field.value.strip()
        if not message:
            return

        normalized = self._normalize_plan_execution_request(message)
        if normalized is None:
            return
        message = normalized

        if self.loading_session_id is not None:
            self._add_assistant_card(
                "Threads",
                ft.Text("Thread is still loading. Send once loading completes.", color=TEXT_MUTED),
            )
            return

        self._dispatch_message(message)

    def _dispatch_message(self, message: str):
        if not self.page:
            return

        # A new send should always anchor the viewport at the latest chat content.
        self._auto_scroll_enabled = True
        self._scroll_chat_to_bottom(animate=False, force=True)

        self.input_field.value = ""
        self._safe_control_update(self.input_field)

        try:
            if message.startswith("/"):
                self.page.run_task(self._run_command, message)
            else:
                self._active_turn_id += 1
                turn_id = self._active_turn_id
                self._active_turn_task = self.page.run_task(self._run_agent, message, turn_id)
        except Exception as ex:
            self._add_message(
                "system",
                f"Error: failed to start agent task: {ex}",
                is_error=True,
            )

    def _normalize_plan_execution_request(self, message: str) -> str | None:
        raw = message.strip()
        lowered = raw.lower()
        if lowered not in {
            "implement plan",
            "implement the plan",
            "go ahead and implement",
            "execute plan",
            "approve plan",
            "yes, implement plan",
        }:
            return raw

        if not self.agent or not self.agent.session:
            return raw

        session = self.agent.session
        if (
            session.plan_mode_enabled
            and session.plan_phase == "awaiting_implementation_confirmation"
        ):
            self._plan_ready_prompt_open = False
            session.clear_pending_plan()
            session.set_plan_mode(False)
            session.set_plan_phase("idle")
            self._sync_plan_toggle_ui()
            return Agent.PLAN_EXECUTE_PROMPT

        self._add_assistant_card(
            "Plan Mode",
            ft.Text(
                "No pending plan is waiting for approval. Ask for a plan first, then approve implementation.",
                color=TEXT_SECONDARY,
            ),
        )
        return None

    async def _stop_active_turn(self):
        await self._cancel_active_turn_and_wait()

    async def _cancel_active_turn_and_wait(self, timeout_seconds: float = 2.0):
        task = self._active_turn_task
        if not task:
            if self._is_turn_running:
                self._active_turn_id += 1
                self._is_turn_running = False
                self._hide_thinking_indicator()
                self._set_loading(False)
            return
        timed_out = False
        try:
            if hasattr(task, "done") and hasattr(task, "cancel") and not task.done():
                task.cancel()
            if hasattr(task, "done") and not task.done():
                await asyncio.wait_for(task, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            self._add_message(
                "system",
                f"Error stopping turn: {ex}",
                is_error=True,
            )
        finally:
            # If cancellation stalls, invalidate this turn so stale events cannot mutate UI.
            if timed_out:
                self._active_turn_id += 1
                self._is_turn_running = False
                self._hide_thinking_indicator()
                self._set_loading(False)
            self._active_turn_task = None

    def _reset_turn_ui_state(self):
        self._active_turn_task = None
        self._is_turn_running = False
        self._hide_thinking_indicator()
        self._set_loading(False)

    def _show_thinking_indicator(self):
        if not self.messages_column or not self._is_page_alive():
            return
        if self.thinking_row:
            try:
                self._remove_chat_control(self.thinking_row)
            except Exception:
                pass
            self._append_chat_control(self.thinking_row)
            self._safe_page_update()
            self._scroll_chat_to_bottom(animate=False, force=True)
            return

        self.thinking_spinner = ft.ProgressRing(
            width=8,
            height=8,
            stroke_width=1,
            color=TEXT_MUTED,
        )
        self.thinking_text = ft.Text("Thinking", size=TYPE_SM, color=TEXT_MUTED)
        bubble = ft.Container(
            content=ft.Row(
                [self.thinking_spinner, self.thinking_text],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE_ELEVATED,
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            width=160,
        )
        self.thinking_row = ft.Row([bubble], alignment=ft.MainAxisAlignment.START)
        self.thinking_row = self._wrap_in_lane(self.thinking_row)
        self._append_chat_control(self.thinking_row)
        self._safe_page_update()
        self._scroll_chat_to_bottom(animate=False, force=True)
        if self.page:
            self._thinking_task = self.page.run_task(self._animate_thinking_text)

    async def _animate_thinking_text(self):
        phases = ["Thinking", "Thinking.", "Thinking..", "Thinking..."]
        i = 0
        try:
            while self._is_turn_running and self.thinking_text and self._is_page_alive():
                self.thinking_text.value = phases[i % len(phases)]
                if not self._safe_control_update(self.thinking_text):
                    return
                i += 1
                await asyncio.sleep(0.36)
        except asyncio.CancelledError:
            return

    def _hide_thinking_indicator(self):
        if self._thinking_task and hasattr(self._thinking_task, "done"):
            if not self._thinking_task.done():
                self._thinking_task.cancel()
        self._thinking_task = None

        if not self.messages_column or not self.thinking_row:
            self.thinking_row = None
            self.thinking_text = None
            self.thinking_spinner = None
            return

        try:
            self._remove_chat_control(self.thinking_row)
        except Exception:
            pass
        self.thinking_row = None
        self.thinking_text = None
        self.thinking_spinner = None
        self._safe_page_update()

    def _on_close(self, e):
        self._is_closing = True
        self._stop_branch_sync_watcher()
        if self._thinking_task and hasattr(self._thinking_task, "cancel"):
            self._thinking_task.cancel()
        if self.page:
            self.page.run_task(self._shutdown_agent)

    def _is_valid_base_url(self, base_url: str) -> bool:
        parsed = urlparse(base_url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    async def _open_setup_view(self):
        if self.setup_base_url_field:
            self.setup_base_url_field.value = self.config.base_url or "https://openrouter.ai/api/v1"
        if self.setup_api_key_field:
            self.setup_api_key_field.value = self.config.api_key or ""
        if self.setup_model_field:
            self.setup_model_field.value = self.config.model_name
        if self.approval_selector:
            self.approval_selector.value = self.config.approval.value
        if self.setup_error_text:
            self.setup_error_text.value = ""
            self.setup_error_text.visible = False
        self.app_mode = "setup"
        self._apply_app_mode()

    async def _cancel_setup_view(self):
        if self.config.needs_setup:
            await self._close_gui_window()
            return
        self.app_mode = "chat"
        self._apply_app_mode()

    async def _submit_setup_view(self):
        if not self.setup_base_url_field or not self.setup_api_key_field or not self.setup_model_field:
            return
        base_url = self.setup_base_url_field.value.strip() or "https://openrouter.ai/api/v1"
        api_key = self.setup_api_key_field.value.strip()
        model_name = self.setup_model_field.value.strip() or self.config.model.name

        if not api_key:
            if self.setup_error_text:
                self.setup_error_text.value = "API key is required."
                self.setup_error_text.visible = True
            self._safe_page_update()
            return

        if not self._is_valid_base_url(base_url):
            if self.setup_error_text:
                self.setup_error_text.value = "Base URL must be a valid http/https URL."
                self.setup_error_text.visible = True
            self._safe_page_update()
            return

        try:
            save_system_config(
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
            )
        except Exception as exc:
            if self.setup_error_text:
                self.setup_error_text.value = f"Failed to save setup: {exc}"
                self.setup_error_text.visible = True
            self._safe_page_update()
            return

        self.config.api_key = api_key
        self.config.base_url = base_url
        self.config.model.name = model_name
        if self.model_selector_text:
            self.model_selector_text.value = self.config.model_name
            self._safe_control_update(self.model_selector_text)
        if self.config.model_name not in self.model_items:
            self.model_items.insert(0, self.config.model_name)

        if self.agent is not None:
            await self._shutdown_agent()

        if self.header_workspace_text:
            self.header_workspace_text.value = f"Workspace: {self.config.cwd}"
            self._safe_control_update(self.header_workspace_text)

        self.app_mode = "chat"
        self._apply_app_mode()
        self._add_assistant_card(
            "Setup Complete",
            ft.Text("Credentials saved and applied.", color=ft.Colors.with_opacity(0.8, ft.Colors.GREEN_300)),
        )

    def _apply_app_mode(self):
        if not self.page:
            return
        if self.chat_shell:
            self.chat_shell.visible = self.app_mode == "chat"
        if self.setup_view:
            self.setup_view.visible = self.app_mode == "setup"
        self._safe_page_update()

    async def _shutdown_agent(self):
        if self.agent is None:
            return
        await self._cancel_active_turn_and_wait()
        try:
            await self.agent.__aexit__(None, None, None)
        finally:
            self.agent = None

    def _sync_plan_toggle_ui(self):
        enabled = bool(
            self.agent and self.agent.session and self.agent.session.plan_mode_enabled
        )
        if self.plan_toggle_button:
            label = "✓ Plan" if enabled else "Plan"
            self.plan_toggle_button.content = ft.Row(
                [
                    ft.Icon(
                        ft.Icons.TUNE if enabled else ft.Icons.TUNE_OUTLINED,
                        size=13,
                        color="#8FC3FF" if enabled else TEXT_MUTED,
                    ),
                    ft.Text(
                        label,
                        size=TYPE_BODY,
                        color="#8FC3FF" if enabled else TEXT_SECONDARY,
                        weight=ft.FontWeight.W_600 if enabled else ft.FontWeight.W_500,
                    ),
                ],
                spacing=6,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            self._safe_control_update(self.plan_toggle_button)

    async def _toggle_plan_mode(self):
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return
        session = self.agent.session
        session.set_plan_mode(not session.plan_mode_enabled)
        if session.plan_mode_enabled:
            session.set_plan_phase("idle")
            self._plan_question_count = 0
            await self._show_plan_resume_options_if_available()
        else:
            session.plan_questions_asked = 0
            self._plan_question_count = 0
        if not session.plan_mode_enabled:
            self._plan_ready_prompt_open = False
        self._sync_plan_toggle_ui()
        self._add_assistant_card(
            "Plan Mode",
            ft.Text(
                f"Plan mode {'enabled' if session.plan_mode_enabled else 'disabled'}.",
                color=TEXT_SECONDARY,
            ),
        )

    async def _show_plan_resume_options_if_available(self) -> None:
        if not self.page:
            return
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return
        session = self.agent.session
        if not session.has_pending_plan():
            return

        status = ft.Text("", size=TYPE_BODY, color=TEXT_MUTED)
        refine_button = ft.OutlinedButton("Refine old plan")
        accept_button = ft.FilledButton("Accept and implement")
        new_button = ft.TextButton("Generate new plan")
        actions = [refine_button, accept_button, new_button]

        async def handle(choice: str):
            for button in actions:
                button.disabled = True
            if choice == "accept":
                session.set_plan_mode(True)
                session.set_plan_phase("awaiting_implementation_confirmation")
                self._sync_plan_toggle_ui()
                status.value = "Reusing saved plan. Confirm implementation below."
                status.color = SUCCESS
                if self.page:
                    self._safe_page_update()
                await self._render_plan_ready_prompt()
                return
            if choice == "refine":
                session.set_plan_mode(True)
                session.set_plan_phase("asking_questions")
                self._sync_plan_toggle_ui()
                status.value = "Old plan loaded. Send follow-up guidance to refine it."
                status.color = TEXT_MUTED
                if self.page:
                    self._safe_page_update()
                return

            session.clear_pending_plan()
            session.set_plan_mode(True)
            session.set_plan_phase("idle")
            self._sync_plan_toggle_ui()
            status.value = "Saved plan discarded. Next prompt will generate a new plan."
            status.color = TEXT_MUTED
            self._safe_page_update()

        refine_button.on_click = lambda _e: self.page.run_task(handle, "refine") if self.page else None
        accept_button.on_click = lambda _e: self.page.run_task(handle, "accept") if self.page else None
        new_button.on_click = lambda _e: self.page.run_task(handle, "new") if self.page else None

        preview_lines = (session.pending_plan_text or "").strip().splitlines()
        preview_text = "\n".join(preview_lines[:6]).strip() or "Saved plan available."
        if len(preview_lines) > 6:
            preview_text += "\n..."

        self._add_assistant_card(
            "Saved Plan Found",
            ft.Column(
                [
                    ft.Text(
                        "A previously generated plan is available. Choose what to do next.",
                        color=TEXT_SECONDARY,
                    ),
                    ft.Container(
                        content=ft.Text(
                            preview_text,
                            style=ft.TextStyle(font_family="JetBrains Mono", size=TYPE_SM, color=TEXT_PRIMARY),
                            selectable=True,
                        ),
                        border=ft.Border.all(1, HAIRLINE),
                        border_radius=RADIUS_SM,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        bgcolor=SURFACE_2,
                    ),
                    ft.Row(actions, alignment=ft.MainAxisAlignment.END),
                    status,
                ],
                spacing=8,
                tight=True,
            ),
        )

    async def _gui_plan_question_callback(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.page or not self.messages_column:
            return {"selected_option": "", "free_text": "", "selected_index": None}
        self._hide_thinking_indicator()

        question = str(payload.get("question", "")).strip()
        options = [str(o) for o in payload.get("options", []) if str(o).strip()]
        recommended_index = payload.get("recommended_index")
        allow_free_text = bool(payload.get("allow_free_text", True))

        loop = asyncio.get_running_loop()
        self._plan_question_future = loop.create_future()
        self._plan_question_count += 1
        status_icon = ft.Icon(
            ft.Icons.CHECK_CIRCLE_ROUNDED,
            size=12,
            color=SUCCESS,
            visible=False,
        )
        status_text = ft.Text(
            "Answered",
            size=TYPE_MD,
            color=SUCCESS,
            weight=ft.FontWeight.W_600,
            visible=False,
        )
        status_row = ft.Row([status_icon, status_text], spacing=6, visible=False)

        choices: list[ft.OutlinedButton] = []
        option_labels: list[str] = []
        for idx, option in enumerate(options):
            recommended = idx == recommended_index
            label = f"{idx + 1}. {option}" + ("  (Recommended)" if recommended else "")
            option_labels.append(label)
            button = ft.OutlinedButton(
                content=ft.Text(
                    label,
                    size=TYPE_MD,
                    color=TEXT_PRIMARY,
                ),
                on_click=lambda _e, i=idx, o=option: self._resolve_plan_question(
                    i,
                    o,
                    "",
                    status_text=status_text,
                    status_icon=status_icon,
                    status_row=status_row,
                    option_buttons=choices,
                    option_labels=option_labels,
                    options_column=options_column,
                    custom_option_container=custom_option_container,
                    custom_option_index=len(options),
                    custom_option_text="",
                    custom_selected=False,
                    free_input=free_text_input,
                    free_submit=free_submit,
                ),
                style=ft.ButtonStyle(
                    side=ft.BorderSide(1, BORDER_STRONG),
                    color=TEXT_PRIMARY,
                    bgcolor={
                        ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                    },
                    shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                ),
            )
            choices.append(button)
        options_column = ft.Column(choices, spacing=6, tight=True)
        custom_option_container = ft.Container(visible=False)

        def _submit_custom_answer(_e=None):
            custom_value = free_text_input.value.strip() if free_text_input else ""
            if not custom_value:
                return
            self._resolve_plan_question(
                None,
                "",
                custom_value,
                status_text=status_text,
                status_icon=status_icon,
                status_row=status_row,
                option_buttons=choices,
                option_labels=option_labels,
                options_column=options_column,
                custom_option_container=custom_option_container,
                custom_option_index=len(options) + 1,
                custom_option_text=custom_value,
                custom_selected=True,
                free_input=free_text_input,
                free_submit=free_submit,
            )

        free_text_input = ft.TextField(
            hint_text="Other answer",
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=BORDER,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            width=SPECIAL_CARD_WIDTH - 40,
            multiline=True,
            shift_enter=True,
            min_lines=1,
            max_lines=3,
            text_size=TYPE_MD,
            on_submit=_submit_custom_answer,
            visible=allow_free_text,
        )
        free_submit = ft.TextButton(
            "Submit",
            on_click=_submit_custom_answer,
            visible=allow_free_text,
        )

        card = ft.Container(
            width=SPECIAL_CARD_WIDTH,
            border=ft.Border.all(1, ACCENT_SOFT),
            border_radius=RADIUS_MD,
            bgcolor=SURFACE_ELEVATED,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            content=ft.Column(
                [
                    ft.Text(
                        f"Asking questions · {self._plan_question_count}",
                        size=TYPE_SM,
                        color=TEXT_MUTED,
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(question, size=TYPE_MD, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600),
                    options_column,
                    custom_option_container,
                    free_text_input,
                    free_submit,
                    status_row,
                ],
                spacing=8,
                tight=True,
            ),
        )
        self._append_chat_control(
            self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        )
        self._safe_page_update()
        self._scroll_chat_to_bottom(force=True)

        result = await self._plan_question_future
        self._plan_question_future = None
        return result

    def _resolve_plan_question(
        self,
        selected_index: int | None,
        selected_option: str,
        free_text: str,
        *,
        status_text: ft.Text | None = None,
        status_icon: ft.Icon | None = None,
        status_row: ft.Row | None = None,
        option_buttons: list[ft.OutlinedButton] | None = None,
        option_labels: list[str] | None = None,
        options_column: ft.Column | None = None,
        custom_option_container: ft.Container | None = None,
        custom_option_index: int = 0,
        custom_option_text: str = "",
        custom_selected: bool = False,
        free_input: ft.TextField | None = None,
        free_submit: ft.TextButton | None = None,
    ) -> None:
        if not self._plan_question_future or self._plan_question_future.done():
            return
        free_text_clean = free_text.strip()
        result = {
            "selected_index": selected_index,
            "selected_option": selected_option,
            "free_text": free_text_clean,
        }

        for idx, control in enumerate(option_buttons or []):
            label = (
                option_labels[idx]
                if option_labels and idx < len(option_labels)
                else f"{idx + 1}. Option"
            )
            is_selected = selected_index is not None and idx == selected_index
            control.disabled = True
            control.content = ft.Text(
                f"✓ {label}" if is_selected else label,
                size=TYPE_MD,
                color=TEXT_PRIMARY if is_selected else TEXT_MUTED,
                weight=ft.FontWeight.W_600 if is_selected else ft.FontWeight.W_500,
            )
            control.style = ft.ButtonStyle(
                side=ft.BorderSide(1, ft.Colors.with_opacity(0.45, ft.Colors.WHITE) if is_selected else BORDER_STRONG),
                bgcolor={
                    ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.08, ft.Colors.WHITE) if is_selected else ft.Colors.TRANSPARENT,
                },
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            )

        if custom_option_container is not None:
            custom_option_container.visible = custom_selected and bool(free_text_clean)
            if custom_selected and free_text_clean:
                custom_option_container.content = ft.OutlinedButton(
                    disabled=True,
                    content=ft.Text(
                        f"✓ {custom_option_index}. {custom_option_text}",
                        size=TYPE_MD,
                        color=TEXT_PRIMARY,
                        weight=ft.FontWeight.W_600,
                    ),
                    style=ft.ButtonStyle(
                        side=ft.BorderSide(1, ft.Colors.with_opacity(0.45, ft.Colors.WHITE)),
                        bgcolor={ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.08, ft.Colors.WHITE)},
                        shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                    ),
                )

        if free_input:
            free_input.disabled = True
            free_input.visible = False
        if free_submit:
            free_submit.disabled = True
            free_submit.visible = False
        if status_text:
            status_text.value = "Answered by user" if custom_selected else "Answered"
            status_text.visible = True
        if status_icon:
            status_icon.visible = True
        if status_row:
            status_row.visible = True
        self._safe_page_update()
        self._show_thinking_indicator()
        loop = self._plan_question_future.get_loop()
        loop.call_soon_threadsafe(self._plan_question_future.set_result, result)

    async def _render_plan_ready_prompt(self):
        if not self.page or not self.messages_column:
            return
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return
        if self._plan_ready_prompt_open:
            return
        self._plan_ready_prompt_open = True

        status = ft.Text("", size=TYPE_SM, color=TEXT_MUTED)
        no_button = ft.TextButton("No")
        yes_button = ft.FilledButton(
            "Yes, implement plan",
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ACCENT},
                color=ft.Colors.BLACK,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )

        def on_approve(_e):
            if self.page:
                self.page.run_task(
                    self._handle_plan_ready_decision,
                    True,
                    status,
                    [no_button, yes_button],
                    actions_wrap,
                )

        def on_decline(_e):
            if self.page:
                self.page.run_task(
                    self._handle_plan_ready_decision,
                    False,
                    status,
                    [no_button, yes_button],
                    actions_wrap,
                )

        no_button.on_click = on_decline
        yes_button.on_click = on_approve

        actions = ft.Row(
            [
                no_button,
                yes_button,
            ],
            alignment=ft.MainAxisAlignment.END,
        )
        actions_wrap = ft.Container(content=actions)

        card = ft.Container(
            width=SPECIAL_CARD_WIDTH,
            border=ft.Border.all(1, ACCENT_SOFT),
            border_radius=RADIUS_MD,
            bgcolor=SURFACE_ELEVATED,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            content=ft.Column(
                [
                    ft.Text(
                        "Implement this plan?",
                        size=TYPE_TITLE,
                        color=TEXT_PRIMARY,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        "Execution is blocked until you approve.",
                        size=TYPE_BODY,
                        color=TEXT_SECONDARY,
                    ),
                    ft.Text(
                        f"Asked {self.agent.session.plan_questions_asked} questions",
                        size=TYPE_BODY,
                        color=TEXT_MUTED,
                    ),
                    actions_wrap,
                    status,
                ],
                spacing=8,
                tight=True,
            ),
        )
        self._append_chat_control(
            self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        )
        self._safe_page_update()
        self._scroll_chat_to_bottom(force=True)

    async def _handle_plan_ready_decision(
        self,
        approved: bool,
        status_text: ft.Text,
        action_buttons: list[ft.Control] | None = None,
        actions_container: ft.Container | None = None,
    ):
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return
        for control in action_buttons or []:
            control.disabled = True
        if actions_container is not None:
            actions_container.visible = False

        if approved:
            # Approving exits plan mode and starts execution.
            self.agent.session.set_plan_mode(False)
            self.agent.session.set_plan_phase("idle")
            self.agent.session.clear_pending_plan()
            self.agent.session.plan_questions_asked = 0
            self._plan_question_count = 0
            self._plan_ready_prompt_open = False
            self._sync_plan_toggle_ui()
            status_text.value = "Approved. Plan mode off. Starting implementation."
            status_text.color = SUCCESS
            self._safe_page_update()
            self._add_assistant_card(
                "Plan Mode",
                ft.Column(
                    [
                        ft.Text(
                            "Implementation started.",
                            size=TYPE_TITLE,
                            color=TEXT_PRIMARY,
                            weight=ft.FontWeight.W_600,
                        ),
                        ft.Text(
                            "Plan mode has been turned off for this run.",
                            size=TYPE_BODY,
                            color=TEXT_SECONDARY,
                        ),
                    ],
                    spacing=4,
                    tight=True,
                ),
            )
            self._active_turn_id += 1
            turn_id = self._active_turn_id
            self._active_turn_task = self.page.run_task(
                self._run_agent,
                Agent.PLAN_EXECUTE_PROMPT,
                turn_id,
            )
            return

        # Declining keeps plan mode enabled and the plan in pending-approval state.
        self.agent.session.set_plan_mode(True)
        self.agent.session.set_plan_phase("awaiting_implementation_confirmation")
        self._plan_ready_prompt_open = False
        self._sync_plan_toggle_ui()
        status_text.value = "Not implemented. Plan remains pending."
        status_text.color = TEXT_MUTED
        self._add_assistant_card(
            "Plan Mode",
            ft.Column(
                [
                    ft.Text(
                        "Plan mode remains enabled.",
                        size=TYPE_TITLE,
                        color=TEXT_PRIMARY,
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(
                        "Next: send follow-up guidance to refine this plan.",
                        size=TYPE_BODY,
                        color=TEXT_SECONDARY,
                    ),
                    ft.Text(
                        "Or type 'implement plan' later to execute this exact plan.",
                        size=TYPE_MD,
                        color=TEXT_MUTED,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
        )
        self._safe_page_update()


def create_gui_app(config: Config):
    gui = GUIApp(config)
    return gui.run


def run_gui(config: Config):
    import flet

    def create_page(page: ft.Page):
        gui = GUIApp(config)
        gui.run(page)

    flet.run(main=create_page, view=ft.AppView.FLET_APP)
