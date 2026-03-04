import flet as ft
from typing import Any
import io

from ite.config.config import Config
from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.tools.base import ToolConfirmation
from ite.commands import build_registry, CommandContext
from rich.console import Console


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
        self.streaming_markdown: ft.Markdown | None = None
        self.streaming_container: ft.Container | None = None
        self.streaming_text: str = ""
        self._command_registry = build_registry()

    def run(self, page: ft.Page):
        self.page = page
        page.title = "ITE - Interactive Terminal Environment"
        page.theme_mode = ft.ThemeMode.DARK
        page.padding = 0

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

    def _add_message(self, role: str, content: str, is_error: bool = False):
        """Add a message to the chat."""
        if not self.messages_column or not self.page:
            return

        bg_color = (
            ft.Colors.ERROR_CONTAINER if is_error
            else ft.Colors.SURFACE_CONTAINER_HIGH if role == "user"
            else ft.Colors.SURFACE
        )
        bubble = ft.Container(
            content=ft.Markdown(
                content,
                selectable=True,
                extension_set="gitHubFlavored",
            ),
            bgcolor=bg_color,
            border_radius=10,
            padding=12,
            width=700
        )

        row_alignment = (
            ft.MainAxisAlignment.END if role == "user" else ft.MainAxisAlignment.START
        )
        self.messages_column.controls.append(
            ft.Row([bubble], alignment=row_alignment)
        )
        self.page.update()

    def _stream_assistant_delta(self, content: str):
        """Stream assistant text into a single in-progress bubble."""
        if not self.messages_column or not self.page:
            return

        if self.streaming_markdown is None or self.streaming_container is None:
            self.streaming_text = ""
            self.streaming_markdown = ft.Markdown(
                "",
                selectable=True,
                extension_set="gitHubFlavored",
            )
            self.streaming_container = ft.Container(
                content=self.streaming_markdown,
                bgcolor=ft.Colors.SURFACE,
                border_radius=10,
                padding=12,
                width=700,
            )
            self.messages_column.controls.append(
                ft.Row([self.streaming_container], alignment=ft.MainAxisAlignment.START)
            )

        self.streaming_text += content
        self.streaming_markdown.value = self.streaming_text
        self.page.update()

    def _finalize_streaming_message(self):
        """Mark the current streamed assistant bubble as complete."""
        self.streaming_markdown = None
        self.streaming_container = None
        self.streaming_text = ""

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
        try:
            self._set_loading(True)
            self._add_message("user", message)
            await self._ensure_agent()

            if not self.agent:
                self._add_message("system", "Error: agent not initialized", is_error=True)
                return

            async for event in self.agent.run(message):
                await self._handle_agent_event(event)
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

    async def _run_command(self, command_line: str) -> None:
        """Dispatch slash commands through the same registry as CLI mode."""
        self._set_loading(True)
        self._add_message("user", command_line)
        try:
            await self._ensure_agent()
            if not self.agent:
                self._add_message("system", "Error: agent not initialized", is_error=True)
                return

            parts = command_line.split()
            command = parts[0].lower()
            args = parts[1:]

            if command == "/setup" or (command == "/subagent" and args and args[0] == "create"):
                self._add_message(
                    "system",
                    "This command is interactive and currently supported in TUI only.",
                    is_error=True,
                )
                return

            output = io.StringIO()
            command_console = Console(
                file=output,
                force_terminal=False,
                color_system=None,
                width=110,
            )
            ctx = CommandContext(
                config=self.config,
                agent=self.agent,
                tui=self,
                console=command_console,
            )
            await self._command_registry.dispatch(command, args, ctx)

            rendered = output.getvalue().strip()
            if rendered:
                self._add_message("assistant", f"```text\n{rendered}\n```")
        except SystemExit:
            self._add_message("system", "Exiting ITE GUI.")
            raise
        except Exception as e:
            self._add_message("system", f"Error: {e}", is_error=True)
        finally:
            self._set_loading(False)

    def print_welcome(self, model: str, cwd, commands: list[str] | None = None):
        command_text = ""
        if commands:
            command_text = "\nCommands: " + ", ".join(commands)
        self._add_message(
            "assistant",
            f"ITE ready\nModel: {model}\nWorkspace: {cwd}{command_text}",
        )

    async def _handle_agent_event(self, event: AgentEvent):
        """Handle agent events and publish to UI."""
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

    def _gui_confirmation_callback(self, confirmation: ToolConfirmation) -> bool:
        """Handle tool confirmation requests from the agent."""
        if not self.page:
            return False

        # Send confirmation request to UI
        diff_text = confirmation.diff.to_diff() if confirmation.diff else None

        self._request_confirmation(
            {
                "tool_name": confirmation.tool_name,
                "description": confirmation.description,
                "command": confirmation.command,
                "diff": diff_text,
            }
        )

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

        # Route slash commands through the command registry.
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
        """Cleanup on page close."""
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
