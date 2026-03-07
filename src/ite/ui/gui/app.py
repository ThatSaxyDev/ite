from __future__ import annotations

import asyncio
import flet as ft
from urllib.parse import urlparse

from ite.agent.agent import Agent
from ite.commands import build_registry
from ite.config.config import Config
from ite.config.loader import save_system_config
from ite.tools.base import ToolConfirmation

from .builders.layout import LayoutBuilderMixin
from .builders.messages import MessageBuilderMixin
from .controllers.scroll import ScrollControllerMixin
from .controllers.workspace import WorkspaceControllerMixin
from .controllers.approval import ApprovalControllerMixin
from .controllers.sessions import SessionControllerMixin
from .controllers.commands import CommandControllerMixin
from .controllers.agent_events import AgentEventControllerMixin
from .tokens import BORDER, RADIUS_SM, SURFACE_1, TEXT_MUTED


class GUIApp(
    LayoutBuilderMixin,
    MessageBuilderMixin,
    ScrollControllerMixin,
    WorkspaceControllerMixin,
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
        self.input_field: ft.TextField | None = None
        self.send_button: ft.IconButton | None = None
        self.loading_indicator: ft.ProgressRing | None = None
        self.model_selector: ft.Dropdown | None = None
        self.workspace_selector: ft.Dropdown | None = None
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
        )
        await self.agent.__aenter__()
        if self.agent.session:
            self.active_session_id = self.agent.session.session_id
            self._set_current_session_title(self.agent.session.name)

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
            return

        self.thinking_spinner = ft.ProgressRing(
            width=8,
            height=8,
            stroke_width=1,
            color=TEXT_MUTED,
        )
        self.thinking_text = ft.Text("Thinking", size=11, color=TEXT_MUTED)
        bubble = ft.Container(
            content=ft.Row(
                [self.thinking_spinner, self.thinking_text],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE_1,
            border=ft.Border.all(1, BORDER),
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            width=160,
        )
        self.thinking_row = ft.Row([bubble], alignment=ft.MainAxisAlignment.START)
        self.messages_column.controls.append(self.thinking_row)
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
            if self.thinking_row in self.messages_column.controls:
                self.messages_column.controls.remove(self.thinking_row)
        except Exception:
            pass
        self.thinking_row = None
        self.thinking_text = None
        self.thinking_spinner = None
        if self.page:
            self.page.update()

    def _on_close(self, e):
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
        if self.model_selector:
            self.model_selector.value = self.config.model_name
            self.model_selector.update()

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


def create_gui_app(config: Config):
    gui = GUIApp(config)
    return gui.run


def run_gui(config: Config):
    import flet

    def create_page(page: ft.Page):
        gui = GUIApp(config)
        gui.run(page)

    flet.run(main=create_page, view=ft.AppView.FLET_APP)
