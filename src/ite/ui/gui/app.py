from __future__ import annotations

import flet as ft

from ite.agent.agent import Agent
from ite.commands import build_registry
from ite.config.config import Config
from ite.tools.base import ToolConfirmation

from .builders.layout import LayoutBuilderMixin
from .builders.messages import MessageBuilderMixin
from .controllers.scroll import ScrollControllerMixin
from .controllers.workspace import WorkspaceControllerMixin
from .controllers.approval import ApprovalControllerMixin
from .controllers.sessions import SessionControllerMixin
from .controllers.commands import CommandControllerMixin
from .controllers.agent_events import AgentEventControllerMixin


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
        self.send_button: ft.Button | None = None
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
        self.sidebar_status_card: ft.Container | None = None
        self.sidebar_collapsed: bool = False
        self.active_session_id: str | None = None

        self.confirmation_dialog: ft.AlertDialog | None = None
        self.pending_confirmation: ToolConfirmation | None = None

        self.streaming_markdown: ft.Markdown | None = None
        self.streaming_container: ft.Container | None = None
        self.streaming_text: str = ""
        self._tool_call_row_indices: dict[str, int] = {}

        self._command_registry = build_registry()
        self._auto_scroll_enabled = True
        self._scroll_request_id = 0

    async def _run_agent(self, message: str):
        try:
            self._set_loading(True)
            self._add_message("user", message)
            await self._ensure_agent()

            if not self.agent:
                self._add_message("system", "Error: agent not initialized", is_error=True)
                return

            async for event in self.agent.run(message):
                await self._handle_agent_event(event)
            await self._auto_save()
        except Exception as e:
            self._add_message("system", f"Error: {str(e)}", is_error=True)
        finally:
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
                self.page.run_task(self._run_agent, message)
        except Exception as ex:
            self._add_message(
                "system",
                f"Error: failed to start agent task: {ex}",
                is_error=True,
            )

    def _on_close(self, e):
        if self.page and self.agent is not None:
            self.page.run_task(self._shutdown_agent)

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
