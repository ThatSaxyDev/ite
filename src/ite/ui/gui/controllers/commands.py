from __future__ import annotations
import io
from datetime import datetime
import flet as ft
from rich.console import Console
from ite.commands import build_registry
from ite.commands import CommandContext
from ite.config.config import ApprovalPolicy
from ..adapters.registry import build_command_context
from ..tokens import *


class CommandControllerMixin:
    async def _run_command(self, command_line: str) -> None:
        self._set_loading(True)
        self._add_message("user", command_line)
        try:
            parts = command_line.split()
            command = parts[0].lower()
            args = parts[1:]

            if command in {"/exit", "/quit"}:
                await self._close_gui_window()
                return

            await self._ensure_agent()
            if not self.agent:
                self._add_message("system", "Error: agent not initialized", is_error=True)
                return

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
                if cleaned and self.messages_column and self.page:
                    self.messages_column.controls.append(
                        self.build_system_log_message(f"command {command}", cleaned)
                    )
                    self.page.update()
                    self._scroll_chat_to_bottom(force=True)
        except SystemExit:
            self._add_message("system", "Exiting ITE GUI.")
            raise
        except Exception as e:
            self._add_message("system", f"Error: {e}", is_error=True)
        finally:
            self._set_loading(False)

    async def _close_gui_window(self):
        if self.agent is not None:
            await self._shutdown_agent()
        if not self.page:
            return
        try:
            self.page.window.close()
        except Exception:
            try:
                self.page.window.destroy()
            except Exception:
                pass

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
                            ft.Text(cmd.name + aliases, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY, width=240),
                            ft.Text(cmd.description, color=TEXT_SECONDARY, expand=True),
                        ]
                    )
                )
            self._add_assistant_card("Available Commands", ft.Column(rows, tight=True, spacing=6))
            return True

        if command == "/sessions":
            self._add_assistant_card(
                "Command Disabled in GUI",
                ft.Text(
                    "Use the Threads list in the left sidebar to browse and open sessions.",
                    color=TEXT_SECONDARY,
                ),
            )
            return True

        if command == "/config":
            rows = ft.Column(
                [
                    ft.Row([ft.Text("Model", weight=ft.FontWeight.BOLD, width=120, color=TEXT_SECONDARY), ft.Text(self.config.model_name, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Workspace", weight=ft.FontWeight.BOLD, width=120, color=TEXT_SECONDARY), ft.Text(str(self.config.cwd), expand=True, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Approval", weight=ft.FontWeight.BOLD, width=120, color=TEXT_SECONDARY), ft.Text(self.config.approval.value, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Max Turns", weight=ft.FontWeight.BOLD, width=120, color=TEXT_SECONDARY), ft.Text(str(self.config.max_turns), color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Hooks", weight=ft.FontWeight.BOLD, width=120, color=TEXT_SECONDARY), ft.Text(str(self.config.hooks_enabled), color=TEXT_PRIMARY)]),
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
                if self.model_selector:
                    self.model_selector.value = self.config.model_name
                    self.model_selector.update()
                self._add_assistant_card("Model Updated", ft.Text(f"{old_model} -> {self.config.model_name}", color=TEXT_PRIMARY))
            else:
                self._add_assistant_card("Current Model", ft.Text(self.config.model_name, color=TEXT_PRIMARY))
            return True

        if command == "/clear":
            if self.agent and self.agent.session:
                self.agent.session.context_manager.clear()
                self.agent.session.loop_detector.clear()
                self.agent.session.name = None
            if self.messages_column and self.page:
                self.messages_column.controls.clear()
                self.page.update()
            self._set_current_session_title(None)
            self._add_assistant_card("Conversation", ft.Text("Cleared session context.", color=TEXT_PRIMARY))
            return True

        if command == "/ite":
            self.print_welcome(
                model=self.config.model_name,
                cwd=self.config.cwd,
                commands=["/help", "/sessions", "/config", "/model", "/approval", "/tools", "/stats", "/mcp"],
            )
            return True

        if command == "/approval":
            self._add_assistant_card(
                "Command Disabled in GUI",
                ft.Text(
                    "Use the Approval dropdown in the sidebar Status card.",
                    color=TEXT_SECONDARY,
                ),
            )
            return True

        if command == "/stats" and self.agent and self.agent.session:
            stats = self.agent.session.get_stats()
            last_compacted = stats.get("last_compacted_at")
            last_compacted_display = (
                datetime.fromisoformat(last_compacted).strftime("%b %d · %I:%M %p")
                if last_compacted
                else "never"
            )
            rows = ft.Column(
                [
                    ft.Row([ft.Text("Session ID", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(stats["session_id"], color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Turn Count", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["turn_count"]), color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Message Count", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["message_count"]), color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Context Window", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["context_window"]), color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Context Usage", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(f'{stats["context_used_pct"]}% used ({stats["context_left_pct"]}% left)', color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Latest Tokens", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["latest_tokens"]), color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Cached Tokens", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["latest_cached_tokens"]), color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Token Usage", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["token_usage"]), color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Compactions", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["compaction_count"]), color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Last Compacted", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(last_compacted_display, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Pruned Tools", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["pruned_tool_msgs"]), color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Tools Enabled", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["tools_enabled"]), color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("MCP Servers", weight=ft.FontWeight.BOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["mcp_servers"]), color=TEXT_PRIMARY)]),
                ],
                spacing=6,
                tight=True,
            )
            self._add_assistant_card("Session Stats", rows)
            return True

        if command == "/tools" and self.agent and self.agent.session:
            tools = self.agent.session.tool_registry.get_tools()
            chips = ft.Wrap(
                controls=[
                    ft.Container(
                        ft.Text(t.name, size=12, color=TEXT_PRIMARY),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                        bgcolor=SURFACE_2,
                        border_radius=RADIUS_SM,
                        border=ft.Border.all(1, BORDER),
                    )
                    for t in tools
                ],
                spacing=8,
                run_spacing=8,
            )
            self._add_assistant_card(f"Tools ({len(tools)})", chips)
            return True

        if command == "/mcp" and self.agent and self.agent.session:
            servers = self.agent.session.mcp_manager.get_all_servers()
            if not servers:
                self._add_assistant_card("MCP Servers", ft.Text("No MCP servers configured.", color=TEXT_SECONDARY))
                return True
            rows = []
            for server in servers:
                color = ft.Colors.with_opacity(0.9, ft.Colors.GREEN_300 if server["status"] == "connected" else ft.Colors.RED_300)
                rows.append(
                    ft.Row(
                        [
                            ft.Text(server["name"], width=220, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                            ft.Text(server["status"], color=color, width=120),
                            ft.Text(f"{server['tools']} tools", color=TEXT_SECONDARY),
                        ]
                    )
                )
            self._add_assistant_card("MCP Servers", ft.Column(rows, spacing=6, tight=True))
            return True

        return False

    def _on_model_select(self, e: ft.Event[ft.Dropdown]):
        if not self.model_selector:
            return
        selected = self.model_selector.value
        if not selected:
            return
        self.config.model_name = selected

