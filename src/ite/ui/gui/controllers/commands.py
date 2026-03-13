from __future__ import annotations
import io
from datetime import datetime
import flet as ft
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

            if command == "/subagent" and args and args[0] == "create":
                self._add_message(
                    "system",
                    "This command is interactive and currently supported in TUI only.",
                    is_error=True,
                )
                return

            if await self._run_native_gui_command(command, args):
                return

            output = io.StringIO()
            ctx = build_command_context(
                config=self.config,
                agent=self.agent,
                tui=self,
                output_stream=output,
            )
            await self._command_registry.dispatch(command, args, ctx)
            if command == "/branch" and self.page:
                self.page.run_task(self._refresh_branch_options_async)
            if hasattr(self, "_refresh_workboard_from_session"):
                self._refresh_workboard_from_session()

            rendered = output.getvalue().strip()
            if rendered:
                cleaned = self._sanitize_cli_output(rendered)
                if cleaned and self.messages_column and self.page:
                    self._append_chat_control(
                        self.build_system_log_message(f"command {command}", cleaned)
                    )
                    self._safe_page_update()
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
                            ft.Text(cmd.name + aliases, size=TYPE_MD, weight=WEIGHT_SEMIBOLD, color=TEXT_PRIMARY, width=240),
                            ft.Text(cmd.description, size=TYPE_MD, color=TEXT_SECONDARY, expand=True),
                        ]
                    )
                )
            self._add_assistant_card("Available Commands", ft.Column(rows, tight=True, spacing=CHAT_BLOCK_GAP))
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

        if command == "/branch":
            self._add_assistant_card(
                "Command Disabled in GUI",
                ft.Text(
                    "Use the Branch selector in the composer controls to switch or create branches.",
                    color=TEXT_SECONDARY,
                ),
            )
            return True

        if command == "/plan":
            await self._ensure_agent()
            if not self.agent or not self.agent.session:
                self._add_message("system", "Error: agent not initialized", is_error=True)
                return True
            session = self.agent.session
            if args:
                mode = args[0].lower()
                if mode not in {"on", "off"}:
                    self._add_assistant_card(
                        "Plan Mode",
                        ft.Text("Use /plan, /plan on, or /plan off.", color=TEXT_SECONDARY),
                    )
                    return True
                session.set_plan_mode(mode == "on")
                if session.plan_mode_enabled:
                    session.set_plan_phase("idle")
                    self._plan_question_count = 0
                    if hasattr(self, "_show_plan_resume_options_if_available"):
                        await self._show_plan_resume_options_if_available()
                else:
                    session.plan_questions_asked = 0
                    self._plan_question_count = 0
                    if hasattr(self, "_plan_ready_prompt_open"):
                        self._plan_ready_prompt_open = False
                self._sync_plan_toggle_ui()
            self._add_assistant_card(
                "Plan Mode",
                ft.Column(
                    [
                        ft.Text(
                            f"Status: {'on' if session.plan_mode_enabled else 'off'}",
                            size=TYPE_MD,
                            color=TEXT_PRIMARY,
                        ),
                        ft.Text(
                            f"Phase: {session.plan_phase}",
                            size=TYPE_MD,
                            color=TEXT_SECONDARY,
                        ),
                        ft.Text(
                            f"Questions asked: {session.plan_questions_asked}",
                            size=TYPE_MD,
                            color=TEXT_SECONDARY,
                        ),
                        ft.Text(
                            f"Question target: {getattr(session, 'plan_target_questions', 3)}",
                            size=TYPE_MD,
                            color=TEXT_SECONDARY,
                        ),
                        ft.Text(
                            f"Pending plan: {'yes' if session.has_pending_plan() else 'no'}",
                            size=TYPE_MD,
                            color=TEXT_SECONDARY,
                        ),
                    ],
                    spacing=4,
                    tight=True,
                ),
            )
            return True

        if command == "/config":
            rows = ft.Column(
                [
                    ft.Row([ft.Text("Model", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=120, color=TEXT_SECONDARY), ft.Text(self.config.model_name, size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Workspace", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=120, color=TEXT_SECONDARY), ft.Text(str(self.config.cwd), size=TYPE_MD, expand=True, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Approval", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=120, color=TEXT_SECONDARY), ft.Text(self.config.approval.value, size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Max Turns", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=120, color=TEXT_SECONDARY), ft.Text(str(self.config.max_turns), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Hooks", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=120, color=TEXT_SECONDARY), ft.Text(str(self.config.hooks_enabled), size=TYPE_MD, color=TEXT_PRIMARY)]),
                ],
                spacing=CHAT_BLOCK_GAP,
                tight=True,
            )
            self._add_assistant_card("Configuration", rows)
            return True

            if command == "/model":
                if args:
                    old_model = self.config.model_name
                    self.config.model_name = args[0]
                    if self.model_selector_text:
                        self.model_selector_text.value = self.config.model_name
                        self._safe_control_update(self.model_selector_text)
                    self._add_assistant_card("Model Updated", ft.Text(f"{old_model} -> {self.config.model_name}", color=TEXT_PRIMARY))
                else:
                    self._add_assistant_card("Current Model", ft.Text(self.config.model_name, color=TEXT_PRIMARY))
                return True

        if command == "/setup":
            await self._open_setup_view()
            return True

        if command == "/clear":
            if self.agent and self.agent.session:
                self.agent.session.context_manager.clear()
                self.agent.session.loop_detector.clear()
                self.agent.session.name = None
            self.gui_state.session_loaded(
                session_id=None,
                title=None,
                workspace=self.config.cwd,
                visible_transcript_messages=[],
                transcript_truncated=False,
                pending_transcript_load=False,
            )
            if self.messages_column and self.page:
                self._clear_chat_controls()
                self._safe_page_update()
            self._refresh_sidebar_threads()
            self._set_current_session_title(None)
            self._add_assistant_card("Conversation", ft.Text("Cleared session context.", color=TEXT_PRIMARY))
            return True

        if command == "/ite":
            self.print_welcome(
                model=self.config.model_name,
                cwd=self.config.cwd,
                commands=["/help", "/sessions", "/config", "/model", "/plan", "/todos", "/branch", "/approval", "/tools", "/stats", "/mcp"],
            )
            return True

        if command == "/approval":
            await self._open_setup_view()
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
                    ft.Row([ft.Text("Session ID", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(stats["session_id"], size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Turn Count", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["turn_count"]), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Message Count", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["message_count"]), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Context Window", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["context_window"]), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Context Usage", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(f'{stats["context_used_pct"]}% used ({stats["context_left_pct"]}% left)', size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Latest Tokens", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["latest_tokens"]), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Cached Tokens", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["latest_cached_tokens"]), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Token Usage", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["token_usage"]), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Compactions", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["compaction_count"]), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Last Compacted", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(last_compacted_display, size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Pruned Tools", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["pruned_tool_msgs"]), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Plan Mode", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text("on" if stats.get("plan_mode_enabled") else "off", size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Plan Phase", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats.get("plan_phase", "idle")), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Plan Questions", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats.get("plan_questions_asked", 0)), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Plan Target", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats.get("plan_target_questions", 3)), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("Tools Enabled", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["tools_enabled"]), size=TYPE_MD, color=TEXT_PRIMARY)]),
                    ft.Row([ft.Text("MCP Servers", size=TYPE_SM, weight=WEIGHT_SEMIBOLD, width=140, color=TEXT_SECONDARY), ft.Text(str(stats["mcp_servers"]), size=TYPE_MD, color=TEXT_PRIMARY)]),
                ],
                spacing=CHAT_BLOCK_GAP,
                tight=True,
            )
            self._add_assistant_card("Session Stats", rows)
            return True

        if command == "/tools" and self.agent and self.agent.session:
            tools = self.agent.session.tool_registry.get_tools()
            chips = ft.Wrap(
                controls=[
                    ft.Container(
                        ft.Text(t.name, size=TYPE_MD, color=TEXT_PRIMARY),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                        bgcolor=SURFACE_2,
                        border_radius=RADIUS_SM,
                        border=ft.Border.all(1, BORDER),
                    )
                    for t in tools
                ],
                spacing=SPACE_XS,
                run_spacing=SPACE_XS,
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
                            ft.Text(server["name"], size=TYPE_MD, width=220, weight=WEIGHT_SEMIBOLD, color=TEXT_PRIMARY),
                            ft.Text(server["status"], size=TYPE_MD, color=color, width=120),
                            ft.Text(f"{server['tools']} tools", size=TYPE_MD, color=TEXT_SECONDARY),
                        ]
                    )
                )
            self._add_assistant_card("MCP Servers", ft.Column(rows, spacing=CHAT_BLOCK_GAP, tight=True))
            return True

        return False

    def _open_model_picker_dialog(self, e=None):
        if not self.page:
            return
        options = list(self.model_items or [])
        if self.config.model_name not in options:
            options.insert(0, self.config.model_name)

        items: list[ft.Control] = []
        for model in options:
            is_current = model == self.config.model_name
            items.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=8, vertical=8),
                    border_radius=RADIUS_SM,
                    bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE) if is_current else ft.Colors.TRANSPARENT,
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.MODEL_TRAINING_OUTLINED, size=13, color=TEXT_MUTED),
                            ft.Text(model, size=TYPE_BODY, color=TEXT_PRIMARY, expand=True, no_wrap=True),
                            ft.Container(
                                visible=is_current,
                                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                border_radius=999,
                                bgcolor=ft.Colors.with_opacity(0.12, ACCENT),
                                content=ft.Text("current", size=TYPE_XS, color=ACCENT, weight=WEIGHT_SEMIBOLD),
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    on_click=lambda _, m=model: self._on_model_pick(m),
                )
            )

        self.model_picker_dialog = ft.AlertDialog(
            modal=True,
            bgcolor=SURFACE_1,
            title=ft.Text("Select model", color=TEXT_PRIMARY, size=TYPE_H1, weight=WEIGHT_SEMIBOLD),
            content=ft.Container(
                width=420,
                height=360,
                content=ft.Column(
                    [ft.Column(items, spacing=4, scroll=ft.ScrollMode.AUTO, expand=True)],
                    spacing=0,
                    expand=True,
                ),
            ),
            actions=[
                ft.TextButton("Close", on_click=lambda _: self.page.pop_dialog() if self.page else None, style=ft.ButtonStyle(color=ft.Colors.WHITE)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            actions_padding=ft.Padding.only(right=16, bottom=12),
            content_padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        )
        self.page.show_dialog(self.model_picker_dialog)

    def _on_model_pick(self, selected: str):
        if not self.page:
            return
        self.page.pop_dialog()
        if selected == self.config.model_name:
            return
        old_model = self.config.model_name
        self.config.model_name = selected
        if self.model_selector_text:
            self.model_selector_text.value = self.config.model_name
            self._safe_control_update(self.model_selector_text)
        self._add_assistant_card(
            "Model Updated",
            ft.Text(f"{old_model} -> {self.config.model_name}", color=TEXT_SECONDARY),
        )
