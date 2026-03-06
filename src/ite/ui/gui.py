import io
import json
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import flet as ft

from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.agent.session import Session
from ite.agent.session_manager import SessionManager, SessionSnapshot
from ite.commands import CommandContext, build_registry
from ite.config.config import Config
from ite.tools.base import ToolConfirmation
from rich.console import Console

# Design tokens
CANVAS = "#181818"
SURFACE_1 = "#202020"
SURFACE_2 = "#222222"
BORDER = ft.Colors.with_opacity(0.07, ft.Colors.WHITE)
TEXT_PRIMARY = ft.Colors.with_opacity(0.90, ft.Colors.WHITE)
TEXT_SECONDARY = ft.Colors.with_opacity(0.62, ft.Colors.WHITE)
TEXT_MUTED = ft.Colors.with_opacity(0.40, ft.Colors.WHITE)
ACCENT = "#6EA7FF"

RADIUS_SM = 6
RADIUS_MD = 8
SPACE_XS = 6
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 20

THREADS_WIDTH = 284
CHAT_WIDTH = 940

SHADOW_SUBTLE = [
    ft.BoxShadow(
        spread_radius=0,
        blur_radius=12,
        color=ft.Colors.with_opacity(0.18, ft.Colors.BLACK),
        offset=ft.Offset(0, 4),
    )
]

MONO_STYLE = ft.TextStyle(
    font_family="monospace",
    size=13,
    color=TEXT_SECONDARY,
)


class GUI:
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
        self.header_session_text: ft.Text | None = None
        self.header_workspace_text: ft.Text | None = None
        self.current_session_title: str = "New Session"
        self.sidebar_threads_column: ft.Column | None = None

        self.confirmation_dialog: ft.AlertDialog | None = None
        self.pending_confirmation: ToolConfirmation | None = None

        self.streaming_markdown: ft.Markdown | None = None
        self.streaming_container: ft.Container | None = None
        self.streaming_text: str = ""
        self._tool_call_row_indices: dict[str, int] = {}

        self._command_registry = build_registry()
        self._auto_scroll_enabled = True
        self._scroll_request_id = 0

    def _truncate_content(
        self,
        content: str,
        *,
        max_chars: int = 700,
        max_lines: int = 8,
    ) -> tuple[str, bool]:
        lines = content.splitlines()
        clipped_lines = lines[:max_lines]
        clipped = "\n".join(clipped_lines)
        if len(clipped) > max_chars:
            clipped = clipped[:max_chars]
        is_truncated = len(lines) > max_lines or len(content) > max_chars
        return clipped, is_truncated

    def _build_expandable_block(
        self,
        content: str,
        *,
        as_markdown: bool = False,
        max_chars: int = 700,
        max_lines: int = 8,
    ) -> ft.Control:
        preview, is_truncated = self._truncate_content(
            content,
            max_chars=max_chars,
            max_lines=max_lines,
        )

        if as_markdown:
            body: ft.Control = ft.Markdown(
                preview if is_truncated else content,
                selectable=True,
                extension_set="gitHubFlavored",
            )
        else:
            body = ft.Text(
                preview if is_truncated else content,
                style=MONO_STYLE,
                selectable=True,
            )

        if not is_truncated:
            return body

        expanded = {"value": False}
        state_label = ft.Text("", size=11, color=TEXT_MUTED)
        toggle = ft.IconButton(
            icon=ft.Icons.KEYBOARD_ARROW_DOWN,
            icon_size=18,
            tooltip="Expand",
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.07, ft.Colors.WHITE)},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )

        def on_toggle(e):
            expanded["value"] = not expanded["value"]
            new_text = content if expanded["value"] else preview
            if isinstance(body, ft.Markdown):
                body.value = new_text
            else:
                body.value = new_text
            toggle.icon = (
                ft.Icons.KEYBOARD_ARROW_UP
                if expanded["value"]
                else ft.Icons.KEYBOARD_ARROW_DOWN
            )
            toggle.tooltip = "Collapse" if expanded["value"] else "Expand"
            state_label.value = "" if expanded["value"] else ""
            if self.page:
                self.page.update()
                self._scroll_chat_to_bottom(animate=False)

        toggle.on_click = on_toggle

        return ft.Column(
            [
                ft.Row(
                    [state_label, ft.Container(expand=True), toggle],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                body,
            ],
            tight=True,
            spacing=4,
        )

    def run(self, page: ft.Page):
        self.page = page
        page.title = "ITE - Interactive Terminal Environment"
        page.theme_mode = ft.ThemeMode.DARK
        page.padding = 0
        page.bgcolor = CANVAS
        page.on_close = self._on_close

        self._build_ui(page)

    def _build_ui(self, page: ft.Page):
        shell = ft.Row(
            [
                self.build_sidebar(),
                ft.VerticalDivider(width=1, color=BORDER),
                ft.Container(
                    content=ft.Column(
                        [
                            self.build_header(),
                            self._build_chat_panel(),
                            self.build_composer(),
                        ],
                        expand=True,
                        spacing=0,
                    ),
                    expand=True,
                    bgcolor=CANVAS,
                ),
            ],
            expand=True,
            spacing=0,
        )
        page.add(shell)
        self._refresh_workspace_options()
        self._refresh_sidebar_threads()

    def build_sidebar(self) -> ft.Control:
        self.sidebar_threads_column = ft.Column([], spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        self.workspace_selector = ft.Dropdown(
            value=str(self.config.cwd.resolve()),
            options=[],
            text_size=12,
            dense=True,
            border=ft.InputBorder.OUTLINE,
            border_color=BORDER,
            focused_border_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            on_select=self._on_workspace_select,
        )

        status_card = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Status", size=12, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY),
                    ft.Row([
                        ft.Text("Approval", size=11, color=TEXT_MUTED),
                        ft.Text(self.config.approval.value, size=11, color=TEXT_SECONDARY),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    # ft.Row([
                    #     ft.Text("Hooks", size=11, color=TEXT_MUTED),
                    #     ft.Text(str(self.config.hooks_enabled), size=11, color=TEXT_SECONDARY),
                    # ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ],
                spacing=SPACE_XS,
            ),
            padding=ft.Padding.symmetric(horizontal=10, vertical=10),
            bgcolor=SURFACE_1,
            border=ft.Border.all(1, BORDER),
            border_radius=RADIUS_SM,
        )

        return ft.Container(
            width=THREADS_WIDTH,
            bgcolor=SURFACE_1,
            padding=ft.Padding.symmetric(horizontal=12, vertical=12),
            content=ft.Column(
                [
                    ft.TextButton(
                        content=ft.Text("+ New thread", size=13, color=TEXT_PRIMARY),
                        on_click=lambda e: self._on_new_thread(),
                        style=ft.ButtonStyle(
                            bgcolor={ft.ControlState.DEFAULT: SURFACE_2},
                            shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                            side=ft.BorderSide(1, BORDER),
                            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        ),
                    ),
                    ft.Divider(height=12, color=BORDER),
                    ft.Text("Workspace", size=12, color=TEXT_MUTED, weight=ft.FontWeight.W_500),
                    self.workspace_selector,
                    ft.Divider(height=12, color=BORDER),
                    ft.Text("Threads", size=12, color=TEXT_MUTED, weight=ft.FontWeight.W_500),
                    self.sidebar_threads_column,
                    ft.Divider(height=12, color=BORDER),
                    status_card,
                ],
                spacing=SPACE_SM,
                expand=True,
            ),
        )

    def _refresh_sidebar_threads(self):
        if not self.sidebar_threads_column:
            return

        sessions = [
            s
            for s in SessionManager().list_sessions(
                workspace_path=self.config.cwd,
                include_legacy_unscoped=False,
            )
            if s.get("turn_count", 0) > 0
        ][:20]
        controls: list[ft.Control] = []
        if not sessions:
            controls.append(ft.Text("No saved threads", size=12, color=TEXT_MUTED))
        else:
            for session in sessions:
                updated = datetime.fromisoformat(session["updated_at"]).strftime("%b %d")
                controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(
                                            (session.get("name") or session["session_id"])[:30],
                                            size=13,
                                            color=TEXT_PRIMARY,
                                            no_wrap=True,
                                        ),
                                        ft.Text(
                                            f"{session['turn_count']} turns",
                                            size=11,
                                            color=TEXT_MUTED,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Text(updated, size=11, color=TEXT_MUTED),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        ),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        border=ft.Border.all(1, BORDER),
                        border_radius=RADIUS_SM,
                        bgcolor=SURFACE_1,
                        on_click=lambda e, sid=session["session_id"]: self._on_sidebar_session_click(sid),
                    )
                )

        self.sidebar_threads_column.controls = controls
        if self.page:
            self.page.update()

    def _refresh_workspace_options(self):
        if not self.workspace_selector:
            return
        manager = SessionManager()
        current_workspace = str(self.config.cwd.resolve())
        known = [p for p in manager.list_workspaces() if p]
        if current_workspace not in known:
            known.insert(0, current_workspace)
        self.workspace_selector.options = [ft.dropdown.Option(p) for p in known]
        self.workspace_selector.value = current_workspace
        if self.page:
            self.page.update()

    def _on_workspace_select(self, e: ft.Event[ft.Dropdown]):
        if not self.workspace_selector or not self.page:
            return
        selected = self.workspace_selector.value
        if not selected:
            return
        self.page.run_task(self._switch_workspace, selected)

    async def _switch_workspace(self, workspace: str):
        target = Path(workspace).expanduser().resolve()
        if not target.exists() or not target.is_dir():
            self._add_message("system", f"Workspace not found: {target}", is_error=True)
            self._refresh_workspace_options()
            return
        if target == self.config.cwd.resolve():
            return
        self._set_loading(True)
        try:
            self.config.cwd = target
            if self.header_workspace_text:
                self.header_workspace_text.value = f"Workspace: {self.config.cwd}"
            if self.agent is not None:
                await self._shutdown_agent()
            if self.messages_column:
                self.messages_column.controls.clear()
            self._set_current_session_title(None)
            self._tool_call_row_indices.clear()
            self._refresh_workspace_options()
            self._refresh_sidebar_threads()
            self._add_assistant_card(
                "Workspace",
                ft.Text(f"Switched to {self.config.cwd}", color=TEXT_SECONDARY),
            )
        finally:
            self._set_loading(False)

    def build_header(self) -> ft.Control:
        self.header_session_text = ft.Text(
            self.current_session_title,
            size=16,
            weight=ft.FontWeight.W_700,
            color=TEXT_PRIMARY,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.header_workspace_text = ft.Text(
            f"Workspace: {self.config.cwd}",
            size=12,
            color=TEXT_MUTED,
            expand=True,
            text_align=ft.TextAlign.RIGHT,
            no_wrap=True,
        )
        return ft.Container(
            bgcolor=CANVAS,
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
            content=ft.Row(
                [
                    self.header_session_text,
                    self.header_workspace_text,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _set_current_session_title(self, title: str | None):
        normalized = (title or "").strip()
        self.current_session_title = normalized if normalized else "New Session"
        if self.header_session_text:
            self.header_session_text.value = self.current_session_title
            self.header_session_text.update()

    def _build_chat_panel(self) -> ft.Control:
        self.messages_column = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            auto_scroll=False,
            on_scroll=self._on_chat_scroll,
            spacing=SPACE_LG,
            expand=True,
        )

        return ft.Container(
            expand=True,
            bgcolor=CANVAS,
            padding=ft.Padding.symmetric(horizontal=18, vertical=14),
            content=ft.Row(
                [
                    ft.Container(
                        width=CHAT_WIDTH,
                        expand=False,
                        content=self.messages_column,
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                expand=True,
            ),
        )

    def build_composer(self) -> ft.Control:
        model_choices = [
            "gpt-4o-mini",
            "gpt-5",
            "gpt-5-mini",
            "claude-3.7-sonnet",
            "minimax-m2.5:cloud",
        ]
        if self.config.model_name not in model_choices:
            model_choices.insert(0, self.config.model_name)

        self.model_selector = ft.Dropdown(
            value=self.config.model_name,
            options=[ft.dropdown.Option(m) for m in model_choices],
            width=220,
            text_size=12,
            dense=True,
            border=ft.InputBorder.OUTLINE,
            border_color=BORDER,
            focused_border_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            bgcolor=SURFACE_1,
            color=TEXT_PRIMARY,
            on_select=self._on_model_select,
        )

        self.loading_indicator = ft.ProgressRing(
            visible=False,
            width=14,
            height=14,
            color=ACCENT,
        )

        self.input_field = ft.TextField(
            hint_text="Message the agent...",
            expand=True,
            multiline=False,
            on_submit=self._on_send,
            border_radius=RADIUS_MD,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_1,
            cursor_color=ACCENT,
            text_style=ft.TextStyle(size=15, color=TEXT_PRIMARY),
            hint_style=ft.TextStyle(size=15, color=TEXT_MUTED),
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=12),
        )

        self.send_button = ft.FilledButton(
            "Send",
            on_click=self._on_send,
            disabled=False,
            style=ft.ButtonStyle(
                bgcolor=ACCENT,
                color=ft.Colors.BLACK,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_700),
            ),
        )

        clear_button = ft.TextButton(
            "Clear",
            on_click=lambda e: self.page.run_task(self._run_command, "/clear") if self.page else None,
            style=ft.ButtonStyle(
                color=TEXT_SECONDARY,
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.07, ft.Colors.WHITE)},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            ),
        )

        return ft.Container(
            bgcolor=CANVAS,
            border=ft.Border.only(top=ft.BorderSide(1, BORDER)),
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            content=ft.Row(
                [
                    self.model_selector,
                    ft.Container(content=self.input_field, expand=True),
                    clear_button,
                    self.loading_indicator,
                    self.send_button,
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def build_chat_message(self, role: str, content: str, is_error: bool = False) -> ft.Control:
        bg = SURFACE_1 if role == "assistant" else SURFACE_2
        border_color = BORDER
        if is_error:
            border_color = ft.Colors.with_opacity(0.28, ft.Colors.RED_300)

        bubble = ft.Container(
            content=ft.Markdown(content, selectable=True, extension_set="gitHubFlavored"),
            bgcolor=bg,
            border_radius=RADIUS_MD,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border=ft.Border.all(1, border_color),
            shadow=SHADOW_SUBTLE,
            width=760 if role != "user" else 640,
        )

        align = ft.MainAxisAlignment.END if role == "user" else ft.MainAxisAlignment.START
        return ft.Row([bubble], alignment=align)

    def build_system_log_message(self, title: str, content: str, level: str = "info") -> ft.Control:
        color = TEXT_SECONDARY
        border = BORDER
        if level == "error":
            color = ft.Colors.with_opacity(0.85, ft.Colors.RED_200)
            border = ft.Colors.with_opacity(0.25, ft.Colors.RED_300)

        card = ft.Container(
            bgcolor=SURFACE_1,
            border_radius=RADIUS_SM,
            border=ft.Border.all(1, border),
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            width=760,
            content=ft.Column(
                [
                    ft.Text(title, size=11, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                    ft.Text(content, style=MONO_STYLE, selectable=True, color=color),
                ],
                tight=True,
                spacing=5,
            ),
        )
        return ft.Row([card], alignment=ft.MainAxisAlignment.START)

    def _add_message(
        self,
        role: str,
        content: str,
        is_error: bool = False,
        force_scroll: bool = True,
    ):
        if not self.messages_column or not self.page:
            return
        self.messages_column.controls.append(self.build_chat_message(role, content, is_error=is_error))
        self.page.update()
        self._scroll_chat_to_bottom(force=force_scroll)

    def _add_assistant_card(self, title: str, content: ft.Control):
        if not self.messages_column or not self.page:
            return

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Text(title, size=12, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                    ft.Divider(height=1, color=BORDER),
                    content,
                ],
                spacing=6,
                tight=True,
            ),
            bgcolor=SURFACE_1,
            border=ft.Border.all(1, BORDER),
            border_radius=RADIUS_MD,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            width=760,
        )
        self.messages_column.controls.append(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        self.page.update()
        self._scroll_chat_to_bottom(force=True)

    def _sanitize_cli_output(self, text: str) -> str:
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", text)
        cleaned = re.sub(r"[│┌┐└┘├┤┬┴┼─]+", "", cleaned)
        cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines())
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _stream_assistant_delta(self, content: str):
        if not self.messages_column or not self.page:
            return

        if self.streaming_markdown is None or self.streaming_container is None:
            self.streaming_text = ""
            self.streaming_markdown = ft.Markdown("", selectable=True, extension_set="gitHubFlavored")
            self.streaming_container = ft.Container(
                content=self.streaming_markdown,
                bgcolor=SURFACE_1,
                border_radius=RADIUS_MD,
                border=ft.Border.all(1, BORDER),
                padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                width=760,
                shadow=SHADOW_SUBTLE,
            )
            self.messages_column.controls.append(
                ft.Row([self.streaming_container], alignment=ft.MainAxisAlignment.START)
            )

        self.streaming_text += content
        self.streaming_markdown.value = self.streaming_text
        self.page.update()
        self._scroll_chat_to_bottom(animate=True, force=True)

    def _finalize_streaming_message(self):
        self.streaming_markdown = None
        self.streaming_container = None
        self.streaming_text = ""

    def _add_tool_call(
        self,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        tool_kind: str | None,
    ):
        if not self.messages_column or not self.page:
            return

        args_text = "\n".join(f"{k}={v}" for k, v in arguments.items()) or "(no args)"
        card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("tool", size=11, color=TEXT_MUTED),
                            ft.Text(name, size=12, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY),
                            ft.Text(f"#{call_id[:8]}", size=11, color=TEXT_MUTED),
                            ft.Text("running", size=11, color=ACCENT, expand=True, text_align=ft.TextAlign.RIGHT),
                        ]
                    ),
                    ft.Divider(height=1, color=BORDER),
                    self._build_expandable_block(
                        args_text,
                        as_markdown=False,
                        max_chars=500,
                        max_lines=5,
                    ),
                ],
                spacing=6,
                tight=True,
            ),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.22, ACCENT)),
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            width=760,
            bgcolor=SURFACE_1,
        )
        row = ft.Row([card], alignment=ft.MainAxisAlignment.START)
        self.messages_column.controls.append(row)
        self._tool_call_row_indices[call_id] = len(self.messages_column.controls) - 1
        self.page.update()
        self._scroll_chat_to_bottom(force=True)

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
        if not self.messages_column or not self.page:
            return

        index = self._tool_call_row_indices.get(call_id)
        if index is None or index >= len(self.messages_column.controls):
            return

        state_text = "done" if success else "failed"
        state_color = ft.Colors.with_opacity(0.90, ft.Colors.GREEN_300 if success else ft.Colors.RED_300)
        payload = output or error or "No output"

        if diff:
            body: ft.Control = self._build_expandable_block(
                f"```diff\n{diff}\n```",
                as_markdown=True,
                max_chars=900,
                max_lines=8,
            )
        else:
            body = self._build_expandable_block(
                payload,
                as_markdown=False,
                max_chars=700,
                max_lines=7,
            )

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("tool", size=11, color=TEXT_MUTED),
                            ft.Text(name, size=12, weight=ft.FontWeight.W_600, color=TEXT_PRIMARY),
                            ft.Text(f"#{call_id[:8]}", size=11, color=TEXT_MUTED),
                            ft.Text(state_text, size=11, color=state_color, expand=True, text_align=ft.TextAlign.RIGHT),
                        ]
                    ),
                    ft.Divider(height=1, color=BORDER),
                    body,
                ],
                spacing=6,
                tight=True,
            ),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.22, ft.Colors.GREEN_300 if success else ft.Colors.RED_300)),
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            width=760,
            bgcolor=SURFACE_1,
        )
        self.messages_column.controls[index] = ft.Row([card], alignment=ft.MainAxisAlignment.START)
        self.page.update()
        self._scroll_chat_to_bottom(animate=False, force=True)

    def _on_chat_scroll(self, e: ft.OnScrollEvent):
        # Only auto-scroll while user is near the bottom.
        distance_to_bottom = max(e.max_scroll_extent - e.pixels, 0)
        self._auto_scroll_enabled = distance_to_bottom <= 96

    def _scroll_chat_to_bottom(self, animate: bool = True, force: bool = False):
        if not self.messages_column or not self.page:
            return
        if not force and not self._auto_scroll_enabled:
            return
        try:
            self._scroll_request_id += 1
            request_id = self._scroll_request_id
            self.page.run_task(self._scroll_chat_to_bottom_async, animate, force, request_id)
        except Exception:
            pass

    async def _scroll_chat_to_bottom_async(
        self,
        animate: bool = True,
        force: bool = False,
        request_id: int = 0,
    ):
        if not self.messages_column:
            return
        try:
            if force:
                self._auto_scroll_enabled = True
            duration = 120 if animate else 0
            # Multi-pass snap: handles layout lag when new controls are added.
            for delay in (0.0, 0.03, 0.08):
                if request_id != self._scroll_request_id:
                    return
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    await self.messages_column.scroll_to(
                        offset=-1,
                        duration=duration,
                        curve=ft.AnimationCurve.EASE_OUT_CUBIC,
                    )
                except TypeError:
                    await self.messages_column.scroll_to(offset=-1, duration=duration)
        except Exception:
            pass

    def _set_loading(self, loading: bool):
        if self.loading_indicator:
            self.loading_indicator.visible = loading
        if self.send_button:
            self.send_button.disabled = loading
        if self.input_field:
            self.input_field.disabled = loading
        if self.page:
            self.page.update()

    def _request_confirmation(
        self,
        data: dict[str, Any],
        confirmation_future: asyncio.Future[bool],
    ):
        if not self.page or not self.messages_column:
            return

        tool_name = data.get("tool_name", "Unknown tool")
        description = data.get("description", "")
        command = data.get("command")
        diff = data.get("diff")

        parts: list[ft.Control] = [
            ft.Text("Approval required", size=11, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
            ft.Text(f"Tool: {tool_name}", weight=ft.FontWeight.W_600, color=TEXT_PRIMARY),
            ft.Text(description, color=TEXT_SECONDARY),
        ]

        if command:
            parts.append(
                ft.Container(
                    content=self._build_expandable_block(
                        command,
                        as_markdown=False,
                        max_chars=450,
                        max_lines=4,
                    ),
                    bgcolor=SURFACE_2,
                    border=ft.Border.all(1, BORDER),
                    border_radius=RADIUS_SM,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                )
            )

        if diff:
            parts.append(
                self._build_expandable_block(
                    f"```diff\n{diff}\n```",
                    as_markdown=True,
                    max_chars=850,
                    max_lines=8,
                )
            )

        status_text = ft.Text(
            "Pending approval",
            size=11,
            color=ft.Colors.with_opacity(0.9, ft.Colors.AMBER_300),
            weight=ft.FontWeight.W_600,
        )
        buttons_row: ft.Row | None = None
        approval_card: ft.Container | None = None

        def on_yes(e):
            self.pending_confirmation = True
            approve_btn.disabled = True
            deny_btn.disabled = True
            if buttons_row:
                buttons_row.visible = False
            status_text.value = "Approved"
            status_text.color = ft.Colors.with_opacity(0.9, ft.Colors.GREEN_300)
            if approval_card:
                approval_card.border = ft.Border.all(
                    1, ft.Colors.with_opacity(0.35, ft.Colors.GREEN_300)
                )
            self.page.update()
            if not confirmation_future.done():
                confirmation_future.set_result(True)

        def on_no(e):
            self.pending_confirmation = False
            approve_btn.disabled = True
            deny_btn.disabled = True
            if buttons_row:
                buttons_row.visible = False
            status_text.value = "Denied"
            status_text.color = ft.Colors.with_opacity(0.9, ft.Colors.RED_300)
            if approval_card:
                approval_card.border = ft.Border.all(
                    1, ft.Colors.with_opacity(0.35, ft.Colors.RED_300)
                )
            self.page.update()
            if not confirmation_future.done():
                confirmation_future.set_result(False)

        deny_btn = ft.TextButton(
            "Deny",
            on_click=on_no,
            style=ft.ButtonStyle(
                color=TEXT_SECONDARY,
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, ft.Colors.WHITE)},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )

        approve_btn = ft.FilledButton(
            "Approve",
            on_click=on_yes,
            style=ft.ButtonStyle(
                bgcolor=ACCENT,
                color=ft.Colors.BLACK,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )

        buttons_row = ft.Row(
            [ft.Container(expand=True), deny_btn, approve_btn],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        parts.append(status_text)
        parts.append(buttons_row)

        approval_card = ft.Container(
            content=ft.Column(parts, tight=True, spacing=8),
            bgcolor=SURFACE_1,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.25, ft.Colors.AMBER_300)),
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            width=760,
            shadow=SHADOW_SUBTLE,
        )
        self.messages_column.controls.append(
            ft.Row([approval_card], alignment=ft.MainAxisAlignment.START)
        )
        self.page.update()
        self._scroll_chat_to_bottom(force=True)

    def _resume_agent(self, approved: bool):
        # TODO: async confirmation resume path
        pass

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
                return "New Session"

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
        return fallback.strip() or "New Session"

    async def _ensure_agent(self) -> None:
        if self.agent is not None:
            return

        self.agent = Agent(
            config=self.config,
            confirmation_callback=self._gui_confirmation_callback,
        )
        await self.agent.__aenter__()
        if self.agent.session:
            self._set_current_session_title(self.agent.session.name)

    async def _run_command(self, command_line: str) -> None:
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
            show_all = "--all" in args
            sessions = [
                s
                for s in SessionManager().list_sessions(
                    workspace_path=None if show_all else self.config.cwd,
                    include_legacy_unscoped=show_all,
                )
                if s.get("turn_count", 0) > 0
            ]
            if not sessions:
                self._add_assistant_card("Sessions", ft.Text("No saved sessions found.", color=TEXT_SECONDARY))
                return True

            headers = ft.Row(
                [
                    ft.Text("Session", width=300, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY),
                    ft.Text("Name", width=220, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY),
                    ft.Text("Updated", width=120, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY),
                    ft.Text("Turns", weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY),
                ]
            )
            rows: list[ft.Control] = [headers, ft.Divider(height=1, color=BORDER)]
            for session in sessions[:20]:
                updated = datetime.fromisoformat(session["updated_at"]).strftime("%b %d")
                rows.append(
                    ft.Row(
                        [
                            ft.Text(session["session_id"], width=300, color=TEXT_PRIMARY),
                            ft.Text(session.get("name") or "-", width=220, color=TEXT_PRIMARY),
                            ft.Text(updated, width=120, color=TEXT_SECONDARY),
                            ft.Text(str(session["turn_count"]), color=TEXT_SECONDARY),
                        ]
                    )
                )
            self._add_assistant_card("Saved Sessions", ft.Column(rows, spacing=4, tight=True))
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
            if args and args[0].lower() != "help":
                from ite.config.config import ApprovalPolicy

                try:
                    self.config.approval = ApprovalPolicy(args[0].lower())
                    self._add_assistant_card(
                        "Approval Mode",
                        ft.Column(
                            [
                                ft.Text(f"Set to {self.config.approval.value}", color=TEXT_PRIMARY),
                                ft.Text("Use /approval <mode> to change", color=TEXT_SECONDARY),
                                ft.Text("Use /approval help to see all modes", color=TEXT_SECONDARY),
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
                            ft.Text(f"Active: {self.config.approval.value}", color=TEXT_PRIMARY),
                            ft.Text("Use /approval <mode> to change", color=TEXT_SECONDARY),
                            ft.Text("Use /approval help to see all modes", color=TEXT_SECONDARY),
                        ],
                        spacing=6,
                        tight=True,
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

    async def _handle_agent_event(self, event: AgentEvent):
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

        elif event.type == AgentEventType.CONTEXT_COMPACTED:
            trigger_tokens = int(event.data.get("trigger_tokens", 0))
            context_window = int(event.data.get("context_window", 0))
            used_pct = (trigger_tokens / context_window * 100) if context_window else 0
            self._add_assistant_card(
                "Context",
                ft.Text(
                    f"Context compacted at {trigger_tokens}/{context_window} tokens ({used_pct:.1f}% used).",
                    color=TEXT_SECONDARY,
                ),
            )

    async def _gui_confirmation_callback(self, confirmation: ToolConfirmation) -> bool:
        if not self.page:
            return False

        diff_text = confirmation.diff.to_diff() if confirmation.diff else None
        confirmation_future = asyncio.get_running_loop().create_future()
        self._request_confirmation(
            {
                "tool_name": confirmation.tool_name,
                "description": confirmation.description,
                "command": confirmation.command,
                "diff": diff_text,
            },
            confirmation_future,
        )
        try:
            return await asyncio.wait_for(confirmation_future, timeout=300)
        except asyncio.TimeoutError:
            self._add_message(
                "system",
                "Approval request timed out after 5 minutes; operation denied.",
                is_error=True,
            )
            return False

    def _on_model_select(self, e: ft.Event[ft.Dropdown]):
        if not self.model_selector:
            return
        selected = self.model_selector.value
        if not selected:
            return
        self.config.model_name = selected

    def _on_new_thread(self):
        if self.page:
            self.page.run_task(self._run_command, "/clear")

    def _on_sidebar_session_click(self, session_id: str):
        if self.page:
            self.page.run_task(self._open_session_from_sidebar, session_id)

    async def _open_session_from_sidebar(self, session_id: str):
        self._set_loading(True)
        try:
            snapshot = SessionManager().load_session(session_id)
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

            await self._ensure_agent()
            if not self.agent:
                self._add_message("system", "Error: agent not initialized", is_error=True)
                return

            await self._resume_agent_session(snapshot)
            self._set_current_session_title(snapshot.name)
            self._hydrate_chat_from_snapshot(snapshot.messages)
            self._add_assistant_card(
                "Session Loaded",
                ft.Text(
                    f"{snapshot.name or snapshot.session_id} · {snapshot.turn_count} turns",
                    color=TEXT_SECONDARY,
                ),
            )
            # First-load layout can lag one frame; force a second pass.
            await self._scroll_chat_to_bottom_async(animate=False, force=True)
            await asyncio.sleep(0.06)
            await self._scroll_chat_to_bottom_async(animate=False, force=True)
        except Exception as e:
            self._add_message("system", f"Error loading session: {e}", is_error=True)
        finally:
            self._set_loading(False)

    async def _resume_agent_session(self, snapshot):
        if not self.agent or not self.agent.session:
            return

        resumed = Session(config=self.config)
        resumed.session_id = snapshot.session_id
        resumed.name = snapshot.name
        resumed.created_at = snapshot.created_at
        resumed.updated_at = snapshot.updated_at
        resumed.turn_count = snapshot.turn_count

        await self.agent.session.client.close()
        await self.agent.session.mcp_manager.shutdown()
        await resumed.initialize()

        resumed.context_manager.set_messages(snapshot.messages)
        resumed.context_manager.total_usage = snapshot.total_usage
        resumed.approval_manager.confirmation_callback = self._gui_confirmation_callback
        self.agent.session = resumed

    def _hydrate_chat_from_snapshot(self, messages: list[dict[str, Any]]):
        if not self.messages_column or not self.page:
            return

        self.messages_column.controls.clear()
        self._tool_call_row_indices.clear()
        self.streaming_markdown = None
        self.streaming_container = None
        self.streaming_text = ""

        tool_call_names: dict[str, str] = {}

        for message in messages:
            role = message.get("role")
            content = message.get("content", "")

            if role == "system":
                # Internal system prompt; omit from UI transcript.
                continue

            if role == "user":
                self.messages_column.controls.append(self.build_chat_message("user", content))
                continue

            if role == "assistant":
                if content:
                    self.messages_column.controls.append(
                        self.build_chat_message("assistant", content)
                    )

                for tool_call in message.get("tool_calls") or []:
                    call_id = tool_call.get("id", "")
                    function = tool_call.get("function", {}) or {}
                    tool_name = function.get("name", "tool")
                    raw_args = function.get("arguments", "") or ""
                    try:
                        parsed_args = json.loads(raw_args) if raw_args else {}
                    except Exception:
                        parsed_args = {"raw": raw_args}

                    tool_call_names[call_id] = tool_name
                    self._add_tool_call(call_id, tool_name, parsed_args, None)
                continue

            if role == "tool":
                call_id = message.get("tool_call_id", "")
                tool_name = tool_call_names.get(call_id, "tool")
                output = content if isinstance(content, str) else str(content)
                success = not output.lstrip().startswith("Error:")
                self._update_tool_call(
                    call_id=call_id,
                    name=tool_name,
                    success=success,
                    output=output,
                    error=None if success else output,
                    diff=None,
                    exit_code=None,
                )
                continue

        self.page.update()
        self._scroll_chat_to_bottom(animate=True, force=True)

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
    gui = GUI(config)
    return gui.run


def run_gui(config: Config):
    import flet

    def create_page(page: ft.Page):
        gui = GUI(config)
        gui.run(page)

    flet.run(main=create_page, view=ft.AppView.FLET_APP)
