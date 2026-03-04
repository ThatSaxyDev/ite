import flet as ft
import asyncio
from pathlib import Path
from typing import Any

from ite.config.config import Config
from ite.config.loader import load_config, ensure_workspace_layout
from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.tools.base import ToolConfirmation


class GUI:
    def __init__(self, config: Config):
        self.config = config
        self.agent: Agent | None = None
        self.page: ft.Page | None = None
        self.messages_column: ft.Column | None = None
        self.input_field: ft.TextField | None = None
        self.send_button: ft.Button | None = None
        self.loading_indicator: ft.ProgressRing | None = None
        self.confirmation_dialog: ft.AlertDialog | None = None
        self.pending_confirmation: ToolConfirmation | None = None

    def run(self, page: ft.Page):
        self.page = page
        page.title = "ITE - Interactive Terminal Environment"
        page.theme_mode = ft.ThemeMode.DARK
        page.padding = 0

        # Subscribe to pubsub messages for agent updates
        page.pubsub.subscribe(self._on_pubsub_message)

        # Cleanup on close
        page.on_close = self._on_close

        self._build_ui(page)

    def _build_ui(self, page: ft.Page):
        # Header
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        "ITE",
                        size=24,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.CYAN,
                    ),
                    ft.Text(
                        f"Model: {self.config.model_name}",
                        size=14,
                        color=ft.Colors.GREY,
                    ),
                    ft.Text(
                        f"Workspace: {self.config.cwd}",
                        size=14,
                        color=ft.Colors.GREY,
                        expand=True,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=15,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        )

        # Chat messages area
        self.messages_column = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=10,
        )

        messages_container = ft.Container(
            content=self.messages_column,
            expand=True,
            padding=15,
            bgcolor=ft.Colors.SURFACE,
        )

        # Loading indicator
        self.loading_indicator = ft.ProgressRing(
            visible=False,
            width=20,
            height=20,
        )

        # Input area
        self.input_field = ft.TextField(
            hint_text="Type your message...",
            expand=True,
            multiline=False,
            on_submit=self._on_send,
        )

        self.send_button = ft.FilledButton(
            "Send",
            on_click=self._on_send,
            disabled=False,
        )

        input_container = ft.Container(
            content=ft.Row(
                [self.input_field, self.send_button, self.loading_indicator],
                alignment=ft.MainAxisAlignment.END,
                spacing=10,
            ),
            padding=15,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        )

        # Main layout
        page.add(
            ft.Column(
                [header, messages_container, input_container],
                expand=True,
                spacing=0,
            )
        )

    def _on_pubsub_message(self, msg: Any):
        """Handle pubsub messages from the agent."""
        if not isinstance(msg, dict):
            return

        event_type = msg.get("type")
        data = msg.get("data", {})

        if event_type == "add_message":
            self._add_message(
                data.get("role", "assistant"),
                data.get("content", ""),
            )
        elif event_type == "add_tool_call":
            self._add_tool_call(
                data.get("call_id", ""),
                data.get("name", ""),
                data.get("arguments", {}),
                data.get("tool_kind", ""),
            )
        elif event_type == "tool_call_complete":
            self._update_tool_call(
                data.get("call_id", ""),
                data.get("name", ""),
                data.get("success", False),
                data.get("output", ""),
                data.get("error"),
                data.get("diff"),
                data.get("exit_code"),
            )
        elif event_type == "set_loading":
            self._set_loading(data.get("loading", False))
        elif event_type == "request_confirmation":
            self._request_confirmation(data)
        elif event_type == "error":
            self._add_message("system", f"Error: {data.get('error', 'Unknown error')}", is_error=True)

    def _add_message(self, role: str, content: str, is_error: bool = False):
        """Add a message to the chat."""
        if not self.messages_column or not self.page:
            return

        bg_color = (
            ft.Colors.ERROR_CONTAINER if is_error
            else ft.Colors.SURFACE_CONTAINER_HIGH if role == "user"
            else ft.Colors.SURFACE
        )
        alignment = ft.CrossAxisAlignment.END if role == "user" else ft.CrossAxisAlignment.START

        bubble = ft.Container(
            content=ft.Markdown(
                content,
                selectable=True,
                extension_set="gitHubFlavored",
            ),
            bgcolor=bg_color,
            border_radius=10,
            padding=12,
            width=700,
            alignment=alignment,
        )

        self.messages_column.controls.append(bubble)
        self.page.update()

    def _add_tool_call(
        self,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        tool_kind: str,
    ):
        """Add a tool call card to the chat."""
        if not self.messages_column or not self.page:
            return

        # Build args display
        args_text = "\n".join(f"**{k}:** {v}" for k, v in arguments.items())

        card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("⏺", color=ft.Colors.GREY),
                    ft.Text(name, weight=ft.FontWeight.BOLD, color=ft.Colors.PINK_200),
                    ft.Text(f"#{call_id[:8]}", color=ft.Colors.GREY),
                    ft.Text("running...", color=ft.Colors.GREY, expand=True, text_align=ft.TextAlign.RIGHT),
                ]),
                ft.Divider(height=1),
                ft.Markdown(args_text, selectable=True),
            ]),
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=8,
            padding=12,
            width=700,
        )

        # Store reference for updates
        card.call_id = call_id
        self.messages_column.controls.append(card)
        self.page.update()

    def _update_tool_call(
        self,
        call_id: str,
        name: str,
        success: bool,
        output: str,
        error: str | None,
        diff: str | None,
        exit_code: int | None,
    ):
        """Update a tool call card with the result."""
        if not self.messages_column or not self.page:
            return

        # Find the card
        for i, control in enumerate(self.messages_column.controls):
            if hasattr(control, "call_id") and control.call_id == call_id:
                status_icon = "✅" if success else "❌"
                status_color = ft.Colors.GREEN if success else ft.Colors.RED

                # Build output display
                output_display = output[:1000] if len(output) > 1000 else output
                if len(output) > 1000:
                    output_display += "\n... [truncated]"

                if diff:
                    output_display = f"```diff\n{diff}\n```"

                card_content = ft.Column([
                    ft.Row([
                        ft.Text(status_icon, color=status_color),
                        ft.Text(name, weight=ft.FontWeight.BOLD, color=ft.Colors.PINK_200),
                        ft.Text(f"#{call_id[:8]}", color=ft.Colors.GREY),
                        ft.Text(
                            "done" if success else "failed",
                            color=status_color,
                            expand=True,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ]),
                    ft.Divider(height=1),
                    ft.Markdown(output_display, selectable=True) if output_display else ft.Text("No output", color=ft.Colors.GREY),
                ])

                # Replace the card
                new_card = ft.Container(
                    content=card_content,
                    border=ft.border.all(1, ft.Colors.OUTLINE),
                    border_radius=8,
                    padding=12,
                    width=700,
                )
                self.messages_column.controls[i] = new_card
                self.page.update()
                break

    def _set_loading(self, loading: bool):
        """Show or hide loading indicator."""
        if self.loading_indicator:
            self.loading_indicator.visible = loading
        if self.send_button:
            self.send_button.disabled = loading
        if self.input_field:
            self.input_field.disabled = loading
        if self.page:
            self.page.update()

    def _request_confirmation(self, data: dict[str, Any]):
        """Show a confirmation dialog."""
        if not self.page:
            return

        tool_name = data.get("tool_name", "Unknown tool")
        description = data.get("description", "")
        diff = data.get("diff")

        content_parts = [
            ft.Text(f"Tool: {tool_name}", weight=ft.FontWeight.BOLD),
            ft.Text(description),
        ]

        if diff:
            content_parts.append(ft.Markdown(f"```diff\n{diff}\n```"))

        def on_yes(e):
            self.pending_confirmation = True
            if self.confirmation_dialog:
                self.confirmation_dialog.open = False
            self.page.update()
            self._resume_agent(True)

        def on_no(e):
            self.pending_confirmation = False
            if self.confirmation_dialog:
                self.confirmation_dialog.open = False
            self.page.update()
            self._resume_agent(False)

        dialog = ft.AlertDialog(
            title=ft.Text("Approval Required"),
            content=ft.Column(content_parts, tight=True),
            actions=[
                ft.TextButton("Deny", on_click=on_no),
                ft.FilledButton("Approve", on_click=on_yes),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.confirmation_dialog = dialog
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()

    def _resume_agent(self, approved: bool):
        """Resume agent after confirmation."""
        # This would need to be handled via a future/async mechanism
        pass

    async def _run_agent(self, message: str):
        """Run the agent with the given message."""
        self._set_loading(True)
        self._add_message("user", message)

        async with Agent(
            config=self.config,
            confirmation_callback=self._gui_confirmation_callback,
        ) as agent:
            self.agent = agent

            try:
                async for event in agent.run(message):
                    await self._handle_agent_event(event)
            except Exception as e:
                self._add_message("system", f"Error: {str(e)}", is_error=True)

        self._set_loading(False)

    async def _handle_agent_event(self, event: AgentEvent):
        """Handle agent events and publish to UI."""
        if not self.page:
            return

        if event.type == AgentEventType.TEXT_DELTA:
            # For streaming text, we'd need to accumulate - simplified here
            pass

        elif event.type == AgentEventType.TEXT_COMPLETE:
            content = event.data.get("content", "")
            if content:
                self.page.pubsub.send_all({
                    "type": "add_message",
                    "data": {"role": "assistant", "content": content}
                })

        elif event.type == AgentEventType.TOOL_CALL_START:
            self.page.pubsub.send_all({
                "type": "add_tool_call",
                "data": {
                    "call_id": event.data.get("call_id", ""),
                    "name": event.data.get("name", ""),
                    "arguments": event.data.get("arguments", {}),
                    "tool_kind": event.data.get("tool_kind"),
                }
            })

        elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
            self.page.pubsub.send_all({
                "type": "tool_call_complete",
                "data": {
                    "call_id": event.data.get("call_id", ""),
                    "name": event.data.get("name", ""),
                    "success": event.data.get("success", False),
                    "output": event.data.get("output", ""),
                    "error": event.data.get("error"),
                    "diff": event.data.get("diff"),
                    "exit_code": event.data.get("exit_code"),
                }
            })

        elif event.type == AgentEventType.AGENT_ERROR:
            self.page.pubsub.send_all({
                "type": "error",
                "data": {"error": event.data.get("error", "Unknown error")}
            })

    def _gui_confirmation_callback(self, confirmation: ToolConfirmation) -> bool:
        """Handle tool confirmation requests from the agent."""
        if not self.page:
            return False

        # Send confirmation request to UI
        diff_text = confirmation.diff.to_diff() if confirmation.diff else None

        self.page.pubsub.send_all({
            "type": "request_confirmation",
            "data": {
                "tool_name": confirmation.tool_name,
                "description": confirmation.description,
                "command": confirmation.command,
                "diff": diff_text,
            }
        })

        # For now, auto-deny in GUI mode - proper async confirmation would need more work
        return False

    def _on_send(self, e):
        """Handle send button click or enter key."""
        if not self.input_field or not self.page:
            return

        message = self.input_field.value.strip()
        if not message:
            return

        self.input_field.value = ""
        self.input_field.update()

        # Run agent on Flet's event loop.
        try:
            self.page.run_task(self._run_agent, message)
        except Exception as ex:
            self._add_message(
                "system",
                f"Error: failed to start agent task: {ex}",
                is_error=True,
            )

    def _on_close(self, e):
        """Cleanup on page close."""
        if self.page:
            self.page.pubsub.unsubscribe(self._on_pubsub_message)


def create_gui_app(config: Config):
    """Create and return the Flet app."""
    gui = GUI(config)
    return gui.run


def run_gui(config: Config):
    """Run the Flet GUI application."""
    import flet

    def create_page(page: ft.Page):
        gui = GUI(config)
        gui.run(page)

    flet.run(main=create_page, view=ft.AppView.FLET_APP)
