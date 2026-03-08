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
        self._active_turn_task: asyncio.Task | None = None
        self._is_turn_running: bool = False
        self.thinking_row: ft.Row | None = None
        self.thinking_text: ft.Text | None = None
        self.thinking_spinner: ft.ProgressRing | None = None
        self._thinking_task: asyncio.Task | None = None

        self._command_registry = build_registry()
        self._auto_scroll_enabled = True
        self._scroll_request_id = 0

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

    async def _run_agent(self, message: str):
        try:
            self._is_turn_running = True
            self._set_loading(True)
            self._add_message("user", message)
            self._show_thinking_indicator()
            await self._ensure_agent()

            if not self.agent:
                self._add_message("system", "Error: agent not initialized", is_error=True)
                return

            async for event in self.agent.run(message):
                await self._handle_agent_event(event)
            await self._auto_save()
        except asyncio.CancelledError:
            self._add_assistant_card(
                "Interrupted",
                ft.Text("Stopped current turn.", color=ft.Colors.with_opacity(0.85, ft.Colors.AMBER_300)),
            )
        except Exception as e:
            self._add_message("system", f"Error: {str(e)}", is_error=True)
        finally:
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

        # A new send should always anchor the viewport at the latest chat content.
        self._auto_scroll_enabled = True
        self._scroll_chat_to_bottom(animate=False, force=True)

        self.input_field.value = ""
        self.input_field.update()

        try:
            if message.startswith("/"):
                self.page.run_task(self._run_command, message)
            else:
                self._active_turn_task = self.page.run_task(self._run_agent, message)
        except Exception as ex:
            self._add_message(
                "system",
                f"Error: failed to start agent task: {ex}",
                is_error=True,
            )

    async def _stop_active_turn(self):
        task = self._active_turn_task
        if not task:
            return
        try:
            if hasattr(task, "done") and hasattr(task, "cancel"):
                if not task.done():
                    task.cancel()
        except Exception as ex:
            self._add_message(
                "system",
                f"Error stopping turn: {ex}",
                is_error=True,
            )

    def _show_thinking_indicator(self):
        if not self.messages_column or not self.page:
            return
        if self.thinking_row:
            try:
                self._remove_chat_control(self.thinking_row)
            except Exception:
                pass
            self._append_chat_control(self.thinking_row)
            self.page.update()
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
        self.page.update()
        self._scroll_chat_to_bottom(animate=False, force=True)
        self._thinking_task = self.page.run_task(self._animate_thinking_text)

    async def _animate_thinking_text(self):
        phases = ["Thinking", "Thinking.", "Thinking..", "Thinking..."]
        i = 0
        try:
            while self._is_turn_running and self.thinking_text and self.page:
                self.thinking_text.value = phases[i % len(phases)]
                self.thinking_text.update()
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
        if self.page:
            self.page.update()

    def _on_close(self, e):
        self._stop_branch_sync_watcher()
        if self.page and self.agent is not None:
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
            if self.page:
                self.page.update()
            return

        if not self._is_valid_base_url(base_url):
            if self.setup_error_text:
                self.setup_error_text.value = "Base URL must be a valid http/https URL."
                self.setup_error_text.visible = True
            if self.page:
                self.page.update()
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
            if self.page:
                self.page.update()
            return

        self.config.api_key = api_key
        self.config.base_url = base_url
        self.config.model.name = model_name
        if self.model_selector_text:
            self.model_selector_text.value = self.config.model_name
            self.model_selector_text.update()
        if self.config.model_name not in self.model_items:
            self.model_items.insert(0, self.config.model_name)

        if self.agent is not None:
            await self._shutdown_agent()

        if self.header_workspace_text:
            self.header_workspace_text.value = f"Workspace: {self.config.cwd}"
            self.header_workspace_text.update()

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
        self.page.update()

    async def _shutdown_agent(self):
        if self.agent is None:
            return
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
            if self.page:
                self.plan_toggle_button.update()

    async def _toggle_plan_mode(self):
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return
        session = self.agent.session
        session.set_plan_mode(not session.plan_mode_enabled)
        if session.plan_mode_enabled:
            session.set_plan_phase("idle")
            self._plan_question_count = 0
        else:
            session.plan_questions_asked = 0
            self._plan_question_count = 0
        self._sync_plan_toggle_ui()
        self._add_assistant_card(
            "Plan Mode",
            ft.Text(
                f"Plan mode {'enabled' if session.plan_mode_enabled else 'disabled'}.",
                color=TEXT_SECONDARY,
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
        status_text = ft.Text("", size=TYPE_SM, color=TEXT_MUTED)

        choices: list[ft.Control] = []
        for idx, option in enumerate(options):
            recommended = idx == recommended_index
            button = ft.OutlinedButton(
                content=ft.Text(
                    f"{idx + 1}. {option}" + ("  (Recommended)" if recommended else ""),
                    size=TYPE_MD,
                    color=TEXT_PRIMARY,
                ),
                on_click=lambda _e, i=idx, o=option: self._resolve_plan_question(
                    i,
                    o,
                    "",
                    status_text=status_text,
                    option_buttons=choices,
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

        free_text_input = ft.TextField(
            hint_text="Other answer",
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            visible=allow_free_text,
        )
        free_submit = ft.TextButton(
            "Submit answer",
            on_click=lambda _e: self._resolve_plan_question(
                None,
                "",
                free_text_input.value.strip() if free_text_input else "",
                status_text=status_text,
                option_buttons=choices,
                free_input=free_text_input,
                free_submit=free_submit,
            ),
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
                    ft.Column(choices, spacing=6, tight=True),
                    free_text_input,
                    free_submit,
                    status_text,
                ],
                spacing=8,
                tight=True,
            ),
        )
        self._append_chat_control(
            self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        )
        self.page.update()
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
        option_buttons: list[ft.Control] | None = None,
        free_input: ft.TextField | None = None,
        free_submit: ft.TextButton | None = None,
    ) -> None:
        if not self._plan_question_future or self._plan_question_future.done():
            return
        result = {
            "selected_index": selected_index,
            "selected_option": selected_option,
            "free_text": free_text,
        }
        answer_preview = selected_option or free_text or "(no answer)"
        if status_text:
            status_text.value = f"Answered: {answer_preview}"
            status_text.color = SUCCESS
        for control in option_buttons or []:
            control.disabled = True
        if free_input:
            free_input.disabled = True
        if free_submit:
            free_submit.disabled = True
        if self.page:
            self.page.update()
        self._show_thinking_indicator()
        loop = self._plan_question_future.get_loop()
        loop.call_soon_threadsafe(self._plan_question_future.set_result, result)

    async def _render_plan_ready_prompt(self):
        if not self.page or not self.messages_column:
            return
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return

        status = ft.Text("", size=TYPE_SM, color=TEXT_MUTED)

        def on_approve(_e):
            if self.page:
                self.page.run_task(self._handle_plan_ready_decision, True, status)

        def on_decline(_e):
            if self.page:
                self.page.run_task(self._handle_plan_ready_decision, False, status)

        actions = ft.Row(
            [
                ft.TextButton("No", on_click=on_decline),
                ft.FilledButton(
                    "Yes, implement plan",
                    on_click=on_approve,
                    style=ft.ButtonStyle(
                        bgcolor={ft.ControlState.DEFAULT: ACCENT},
                        color=ft.Colors.BLACK,
                        shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                    ),
                ),
            ],
            alignment=ft.MainAxisAlignment.END,
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
                        "Implement this plan?",
                        size=TYPE_MD,
                        color=TEXT_PRIMARY,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        "Execution is blocked until you approve.",
                        size=TYPE_SM,
                        color=TEXT_SECONDARY,
                    ),
                    ft.Text(
                        f"Asked {self.agent.session.plan_questions_asked} questions",
                        size=TYPE_SM,
                        color=TEXT_MUTED,
                    ),
                    actions,
                    status,
                ],
                spacing=8,
                tight=True,
            ),
        )
        self._append_chat_control(
            self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        )
        self.page.update()
        self._scroll_chat_to_bottom(force=True)

    async def _handle_plan_ready_decision(self, approved: bool, status_text: ft.Text):
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return

        if approved:
            # Approving exits plan mode and starts execution.
            self.agent.session.set_plan_mode(False)
            self.agent.session.set_plan_phase("idle")
            self.agent.session.plan_questions_asked = 0
            self._plan_question_count = 0
            self._sync_plan_toggle_ui()
            status_text.value = "Approved · Plan mode off"
            status_text.color = SUCCESS
            if self.page:
                self.page.update()
            self._add_assistant_card(
                "Plan Mode",
                ft.Text("Plan mode disabled. Starting implementation.", color=TEXT_SECONDARY),
            )
            self._active_turn_task = self.page.run_task(
                self._run_agent,
                "Implement the approved plan now. Execute the planned changes.",
            )
            return

        # Declining keeps plan mode enabled for iterative refinement.
        self.agent.session.set_plan_mode(True)
        self.agent.session.set_plan_phase("asking_questions")
        self._sync_plan_toggle_ui()
        status_text.value = "Not implemented · Plan mode still on"
        status_text.color = TEXT_MUTED
        self._add_assistant_card(
            "Plan Mode",
            ft.Text("Plan mode remains enabled. Refine the plan with follow-up prompts.", color=TEXT_SECONDARY),
        )
        if self.page:
            self.page.update()


def create_gui_app(config: Config):
    gui = GUIApp(config)
    return gui.run


def run_gui(config: Config):
    import flet

    def create_page(page: ft.Page):
        gui = GUIApp(config)
        gui.run(page)

    flet.run(main=create_page, view=ft.AppView.FLET_APP)
