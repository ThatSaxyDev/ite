import flet as ft
from typing import Any
import io
import re
from datetime import datetime

from ite.config.config import Config
from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.tools.base import ToolConfirmation
from ite.commands import build_registry, CommandContext
from rich.console import Console
from ite.agent.session_manager import SessionManager

UI_BG = "#181818"


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
        page.bgcolor = UI_BG

        # Cleanup on close
        page.on_close = self._on_close

        self._build_ui(page)

    def _build_ui(self, page: ft.Page):
        # Header
        brand = ft.Row(
            [
                ft.Container(
                    content=ft.Text("ITE", size=18, weight=ft.FontWeight.W_700, color=ft.Colors.CYAN_200),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                    border_radius=999,
                    bgcolor=UI_BG,
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.25, ft.Colors.CYAN_200)),
                ),
                ft.Text(
                    f"Model: {self.config.model_name}",
                    size=14,
                    color=ft.Colors.GREY_300,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        header = ft.Container(
            content=ft.Row(
                [
                    brand,
                    ft.Text(
                        f"Workspace: {self.config.cwd}",
                        size=14,
                        color=ft.Colors.GREY_300,
                        expand=True,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding.symmetric(horizontal=22, vertical=14),
            border=ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.with_opacity(0.15, ft.Colors.WHITE))),
            bgcolor=UI_BG,
        )

        # Chat messages area
        self.messages_column = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=16,
            auto_scroll=True,
        )

        messages_container = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=self.messages_column,
                        width=980,
                        expand=False,
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                expand=True,
            ),
            expand=True,
            padding=ft.Padding.symmetric(horizontal=20, vertical=18),
            bgcolor=UI_BG,
        )

        # Loading indicator
        self.loading_indicator = ft.ProgressRing(
            visible=False,
            width=18,
            height=18,
            color=ft.Colors.CYAN_200,
        )

        # Input area
        self.input_field = ft.TextField(
            hint_text="Type your message...",
            expand=True,
            multiline=False,
            on_submit=self._on_send,
            border_radius=14,
            border_color=ft.Colors.with_opacity(0.3, ft.Colors.WHITE),
            focused_border_color=ft.Colors.CYAN_200,
            bgcolor=UI_BG,
            cursor_color=ft.Colors.CYAN_200,
            text_style=ft.TextStyle(size=18, color=ft.Colors.GREY_50),
            hint_style=ft.TextStyle(size=18, color=ft.Colors.GREY_500),
            content_padding=ft.Padding.symmetric(horizontal=18, vertical=18),
        )

        self.send_button = ft.FilledButton(
            "Send",
            on_click=self._on_send,
            disabled=False,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.CYAN_200,
                color=ft.Colors.BLUE_GREY_900,
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=ft.Padding.symmetric(horizontal=22, vertical=18),
                text_style=ft.TextStyle(size=16, weight=ft.FontWeight.W_700),
            ),
        )

        input_container = ft.Container(
            content=ft.Row(
                [
                    ft.Container(content=self.input_field, expand=True),
                    self.loading_indicator,
                    self.send_button,
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=12,
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=16),
            border=ft.Border.only(top=ft.BorderSide(1, ft.Colors.with_opacity(0.16, ft.Colors.WHITE))),
            bgcolor=UI_BG,
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
            UI_BG
        )
        bubble_width = 700 if role != "user" else 620
        border_color = (
            ft.Colors.with_opacity(0.35, ft.Colors.RED_200)
            if is_error
            else ft.Colors.with_opacity(0.2, ft.Colors.CYAN_100) if role == "assistant"
            else ft.Colors.with_opacity(0.25, ft.Colors.WHITE)
        )
        bubble = ft.Container(
            content=ft.Markdown(
                content,
                selectable=True,
                extension_set="gitHubFlavored",
            ),
            bgcolor=bg_color,
            border_radius=14,
            padding=14,
            width=bubble_width,
            border=ft.Border.all(1, border_color),
        )

        row_alignment = (
            ft.MainAxisAlignment.END if role == "user" else ft.MainAxisAlignment.START
        )
        self.messages_column.controls.append(
            ft.Row([bubble], alignment=row_alignment)
        )
        self.page.update()
        self._scroll_chat_to_bottom()

    def _add_assistant_card(self, title: str, content: ft.Control):
        if not self.messages_column or not self.page:
            return

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Text(title, weight=ft.FontWeight.BOLD, size=15, color=ft.Colors.CYAN_100),
                    ft.Divider(height=1),
                    content,
                ],
                tight=True,
                spacing=8,
            ),
            bgcolor=UI_BG,
            border_radius=14,
            padding=14,
            width=760,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.25, ft.Colors.CYAN_100)),
        )
        self.messages_column.controls.append(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        self.page.update()
        self._scroll_chat_to_bottom()

    def _sanitize_cli_output(self, text: str) -> str:
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", text)
        cleaned = re.sub(r"[│┌┐└┘├┤┬┴┼─]+", "", cleaned)
        cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines())
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

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
                bgcolor=UI_BG,
                border_radius=14,
                padding=14,
                width=700,
                border=ft.Border.all(1, ft.Colors.with_opacity(0.2, ft.Colors.CYAN_100)),
            )
            self.messages_column.controls.append(
                ft.Row([self.streaming_container], alignment=ft.MainAxisAlignment.START)
            )

        self.streaming_text += content
        self.streaming_markdown.value = self.streaming_text
        self.page.update()
        self._scroll_chat_to_bottom(animate=False)

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
                    ft.Text("●", color=ft.Colors.AMBER_300),
                    ft.Text(name, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_100),
                    ft.Text(f"#{call_id[:8]}", color=ft.Colors.GREY_400),
                    ft.Text("running...", color=ft.Colors.GREY_300, expand=True, text_align=ft.TextAlign.RIGHT),
                ]),
                ft.Divider(height=1),
                ft.Markdown(args_text, selectable=True),
            ]),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.AMBER_300)),
            border_radius=14,
            padding=14,
            width=700,
            bgcolor=UI_BG,
        )

        # Store reference for updates
        card.call_id = call_id
        self.messages_column.controls.append(card)
        self.page.update()
        self._scroll_chat_to_bottom()

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
                status_icon = "●"
                status_color = ft.Colors.GREEN_300 if success else ft.Colors.RED_300

                # Build output display
                output_display = output[:1000] if len(output) > 1000 else output
                if len(output) > 1000:
                    output_display += "\n... [truncated]"

                if diff:
                    output_display = f"```diff\n{diff}\n```"

                card_content = ft.Column([
                    ft.Row([
                        ft.Text(status_icon, color=status_color),
                        ft.Text(name, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_100),
                        ft.Text(f"#{call_id[:8]}", color=ft.Colors.GREY_400),
                        ft.Text(
                            "done" if success else "failed",
                            color=status_color,
                            expand=True,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ]),
                    ft.Divider(height=1),
                    ft.Markdown(output_display, selectable=True) if output_display else ft.Text("No output", color=ft.Colors.GREY_300),
                ])

                # Replace the card
                new_card = ft.Container(
                    content=card_content,
                    border=ft.Border.all(
                        1,
                        ft.Colors.with_opacity(0.35, ft.Colors.GREEN_300 if success else ft.Colors.RED_300),
                    ),
                    border_radius=14,
                    padding=14,
                    width=700,
                    bgcolor=UI_BG,
                )
                self.messages_column.controls[i] = new_card
                self.page.update()
                self._scroll_chat_to_bottom(animate=False)
                break

    def _scroll_chat_to_bottom(self, animate: bool = True):
        """Keep the latest chat content in view."""
        if not self.messages_column or not self.page:
            return
        try:
            self.page.run_task(self._scroll_chat_to_bottom_async, animate)
        except Exception:
            pass

    async def _scroll_chat_to_bottom_async(self, animate: bool = True):
        if not self.messages_column:
            return
        try:
            await self.messages_column.scroll_to(
                offset=-1,
                duration=180 if animate else 0,
            )
        except Exception:
            pass

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

            if await self._run_native_gui_command(command, args):
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
                cleaned = self._sanitize_cli_output(rendered)
                if cleaned:
                    self._add_assistant_card(
                        f"Command Result · {command}",
                        ft.Markdown(cleaned, selectable=True, extension_set="gitHubFlavored"),
                    )
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

    async def _run_native_gui_command(self, command: str, args: list[str]) -> bool:
        if command == "/help":
            rows = []
            for cmd in self._command_registry.all_commands():
                aliases = f" ({', '.join(cmd.aliases)})" if cmd.aliases else ""
                rows.append(
                    ft.Row(
                        [
                            ft.Text(cmd.name + aliases, weight=ft.FontWeight.W_600, color=ft.Colors.CYAN_100, width=240),
                            ft.Text(cmd.description, color=ft.Colors.GREY_300, expand=True),
                        ]
                    )
                )
            self._add_assistant_card("Available Commands", ft.Column(rows, tight=True, spacing=6))
            return True

        if command == "/sessions":
            sessions = [s for s in SessionManager().list_sessions() if s.get("turn_count", 0) > 0]
            if not sessions:
                self._add_assistant_card("Sessions", ft.Text("No saved sessions found.", color=ft.Colors.GREY_300))
                return True

            headers = ft.Row(
                [
                    ft.Text("Session", width=300, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_300),
                    ft.Text("Name", width=220, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_300),
                    ft.Text("Updated", width=140, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_300),
                    ft.Text("Turns", weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_300),
                ]
            )
            rows: list[ft.Control] = [headers, ft.Divider(height=1)]
            for session in sessions[:20]:
                updated = datetime.fromisoformat(session["updated_at"]).strftime("%b %d · %I:%M %p")
                rows.append(
                    ft.Row(
                        [
                            ft.Text(session["session_id"], width=300),
                            ft.Text(session.get("name") or "-", width=220),
                            ft.Text(updated, width=140),
                            ft.Text(str(session["turn_count"])),
                        ]
                    )
                )
            self._add_assistant_card("Saved Sessions", ft.Column(rows, spacing=4, tight=True))
            return True

        if command == "/config":
            rows = ft.Column(
                [
                    ft.Row([ft.Text("Model", weight=ft.FontWeight.BOLD, width=120), ft.Text(self.config.model_name)]),
                    ft.Row([ft.Text("Workspace", weight=ft.FontWeight.BOLD, width=120), ft.Text(str(self.config.cwd), expand=True)]),
                    ft.Row([ft.Text("Approval", weight=ft.FontWeight.BOLD, width=120), ft.Text(self.config.approval.value)]),
                    ft.Row([ft.Text("Max Turns", weight=ft.FontWeight.BOLD, width=120), ft.Text(str(self.config.max_turns))]),
                    ft.Row([ft.Text("Hooks", weight=ft.FontWeight.BOLD, width=120), ft.Text(str(self.config.hooks_enabled))]),
                ],
                spacing=6,
                tight=True,
            )
            self._add_assistant_card("Configuration", rows)
            return True

        if command == "/model":
            if args:
                old_model = self.config.model_name
                self.config.model_name = args[0]
                self._add_assistant_card("Model Updated", ft.Text(f"{old_model} -> {self.config.model_name}"))
            else:
                self._add_assistant_card("Current Model", ft.Text(self.config.model_name))
            return True

        if command == "/clear":
            if self.agent and self.agent.session:
                self.agent.session.context_manager.clear()
                self.agent.session.loop_detector.clear()
            self._add_assistant_card("Conversation", ft.Text("Cleared session context."))
            return True

        if command == "/ite":
            self.print_welcome(
                model=self.config.model_name,
                cwd=self.config.cwd,
                commands=["/help", "/sessions", "/config", "/model", "/approval", "/tools", "/stats", "/mcp"],
            )
            return True

        if command == "/approval":
            if args and args[0].lower() != "help":
                from ite.config.config import ApprovalPolicy
                try:
                    self.config.approval = ApprovalPolicy(args[0].lower())
                    self._add_assistant_card(
                        "Approval Mode",
                        ft.Column(
                            [
                                ft.Text(f"Set to {self.config.approval.value}"),
                                ft.Text("Use /approval <mode> to change", color=ft.Colors.GREY_300),
                                ft.Text("Use /approval help to see all modes", color=ft.Colors.GREY_300),
                            ],
                            spacing=6,
                            tight=True,
                        ),
                    )
                except ValueError:
                    self._add_message("system", "Invalid approval mode.", is_error=True)
            else:
                self._add_assistant_card(
                    "Approval Mode",
                    ft.Column(
                        [
                            ft.Text(f"Active: {self.config.approval.value}"),
                            ft.Text("Use /approval <mode> to change", color=ft.Colors.GREY_300),
                            ft.Text("Use /approval help to see all modes", color=ft.Colors.GREY_300),
                        ],
                        spacing=6,
                        tight=True,
                    ),
                )
            return True

        if command == "/stats" and self.agent and self.agent.session:
            stats = self.agent.session.get_stats()
            rows = ft.Column(
                [
                    ft.Row([ft.Text("Session ID", weight=ft.FontWeight.BOLD, width=140), ft.Text(stats["session_id"])]),
                    ft.Row([ft.Text("Turn Count", weight=ft.FontWeight.BOLD, width=140), ft.Text(str(stats["turn_count"]))]),
                    ft.Row([ft.Text("Message Count", weight=ft.FontWeight.BOLD, width=140), ft.Text(str(stats["message_count"]))]),
                    ft.Row([ft.Text("Token Usage", weight=ft.FontWeight.BOLD, width=140), ft.Text(str(stats["token_usage"]))]),
                    ft.Row([ft.Text("Tools Enabled", weight=ft.FontWeight.BOLD, width=140), ft.Text(str(stats["tools_enabled"]))]),
                    ft.Row([ft.Text("MCP Servers", weight=ft.FontWeight.BOLD, width=140), ft.Text(str(stats["mcp_servers"]))]),
                ],
                spacing=6,
                tight=True,
            )
            self._add_assistant_card("Session Stats", rows)
            return True

        if command == "/tools" and self.agent and self.agent.session:
            tools = self.agent.session.tool_registry.get_tools()
            chips = ft.Wrap(
                controls=[ft.Container(ft.Text(t.name), padding=8, bgcolor=UI_BG, border_radius=8, border=ft.Border.all(1, ft.Colors.with_opacity(0.2, ft.Colors.WHITE))) for t in tools],
                spacing=8,
                run_spacing=8,
            )
            self._add_assistant_card(f"Tools ({len(tools)})", chips)
            return True

        if command == "/mcp" and self.agent and self.agent.session:
            servers = self.agent.session.mcp_manager.get_all_servers()
            if not servers:
                self._add_assistant_card("MCP Servers", ft.Text("No MCP servers configured.", color=ft.Colors.GREY_300))
                return True
            rows = []
            for server in servers:
                color = ft.Colors.GREEN if server["status"] == "connected" else ft.Colors.RED
                rows.append(
                    ft.Row(
                        [
                            ft.Text(server["name"], width=220, weight=ft.FontWeight.BOLD),
                            ft.Text(server["status"], color=color, width=120),
                            ft.Text(f"{server['tools']} tools"),
                        ]
                    )
                )
            self._add_assistant_card("MCP Servers", ft.Column(rows, spacing=6, tight=True))
            return True

        return False

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
