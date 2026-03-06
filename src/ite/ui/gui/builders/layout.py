from __future__ import annotations
import flet as ft
from pathlib import Path
from ite.agent.session_manager import SessionManager
from ..tokens import *
from ite.config.config import ApprovalPolicy


class LayoutBuilderMixin:
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
        def _format_approval_label(value: str) -> str:
            return value.replace("_", " ").title()

        approval_descriptions = {
            "on_request": "Ask before each mutating action",
            "on_failure": "Auto-run; only ask after failure",
            "auto": "Auto-approve safe operations",
            "auto_edit": "Auto-edit in workspace; ask otherwise",
            "never": "Reject unsafe operations automatically",
            "yolo": "Approve everything with no guardrails",
        }
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
        self.approval_selector = ft.Dropdown(
            value=self.config.approval.value,
            options=[
                ft.dropdown.Option(
                    key=p.value,
                    text=_format_approval_label(p.value),
                    content=ft.Column(
                        [
                            ft.Text(_format_approval_label(p.value), size=13, color=TEXT_PRIMARY),
                            ft.Text(
                                approval_descriptions.get(p.value, ""),
                                size=11,
                                color=TEXT_MUTED,
                                no_wrap=True,
                            ),
                        ],
                        tight=True,
                        spacing=1,
                    ),
                )
                for p in ApprovalPolicy
            ],
            width=160,
            text_size=11,
            dense=True,
            border=ft.InputBorder.OUTLINE,
            border_color=BORDER,
            focused_border_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=6),
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            on_select=self._on_approval_select,
        )

        status_card = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Status", size=12, weight=ft.FontWeight.W_600, color=TEXT_SECONDARY),
                    ft.Row([
                        ft.Text("Approval", size=11, color=TEXT_MUTED),
                        self.approval_selector,
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

    def _set_loading(self, loading: bool):
        if self.loading_indicator:
            self.loading_indicator.visible = loading
        if self.send_button:
            self.send_button.disabled = loading
        if self.input_field:
            self.input_field.disabled = loading
        if self.page:
            self.page.update()

