from __future__ import annotations
import flet as ft
from ..tokens import *
from ite.config.config import ApprovalPolicy


class LayoutBuilderMixin:
    def run(self, page: ft.Page):
        self.page = page
        page.title = "ITE - Interactive Terminal Environment"
        page.theme_mode = ft.ThemeMode.DARK
        page.theme = ft.Theme(font_family=FONT_UI)
        page.padding = 0
        page.bgcolor = CANVAS
        page.on_close = self._on_close

        self._build_ui(page)

    def _build_ui(self, page: ft.Page):
        self.sidebar_root = self.build_sidebar()
        self.chat_shell = ft.Row(
            [
                self.sidebar_root,
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
        self.setup_view = self.build_setup_view()
        page.add(
            ft.Stack(
                [
                    self.chat_shell,
                    self.setup_view,
                ],
                expand=True,
            )
        )
        self._refresh_workspace_options()
        self._refresh_sidebar_threads()
        self._apply_sidebar_state(update=False)
        self._apply_app_mode()

    def build_setup_view(self) -> ft.Control:
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
        self.setup_error_text = ft.Text(
            "",
            size=11,
            color=ft.Colors.with_opacity(0.9, ft.Colors.RED_300),
            visible=False,
        )
        self.setup_base_url_field = ft.TextField(
            label="Base URL",
            value=self.config.base_url or "https://openrouter.ai/api/v1",
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            text_size=12,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        )
        self.setup_api_key_field = ft.TextField(
            label="API Key",
            password=True,
            can_reveal_password=True,
            value=self.config.api_key or "",
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            text_size=12,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        )
        self.setup_model_field = ft.TextField(
            label="Model",
            value=self.config.model_name,
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            text_size=12,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        )
        self.approval_selector = ft.Dropdown(
            value=self.config.approval.value,
            options=[
                ft.dropdown.Option(
                    key=p.value,
                    text=_format_approval_label(p.value),
                    content=ft.Column(
                        [
                            ft.Text(_format_approval_label(p.value), size=12, color=TEXT_PRIMARY),
                            ft.Text(
                                approval_descriptions.get(p.value, ""),
                                size=10,
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
            text_size=11,
            dense=True,
            border=ft.InputBorder.OUTLINE,
            border_color=BORDER,
            focused_border_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            on_select=self._on_approval_select,
        )

        card = ft.Container(
            width=520,
            bgcolor=SURFACE_1,
            border=ft.Border.all(1, BORDER_STRONG),
            border_radius=RADIUS_MD,
            padding=ft.Padding.symmetric(horizontal=18, vertical=16),
            content=ft.Column(
                [
                    ft.Text(
                        "Settings" if not self.config.needs_setup else "Setup ITE",
                        size=20,
                        weight=ft.FontWeight.W_700,
                        color=TEXT_PRIMARY,
                    ),
                    ft.Text(
                        (
                            "Connect your provider credentials to start using the GUI."
                            if self.config.needs_setup
                            else "Update provider and approval settings."
                        ),
                        size=12,
                        color=TEXT_SECONDARY,
                    ),
                    ft.Divider(height=10, color=BORDER),
                    self.setup_base_url_field,
                    self.setup_api_key_field,
                    self.setup_model_field,
                    ft.Text("Approval mode", size=11, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                    self.approval_selector,
                    self.setup_error_text,
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                "Cancel",
                                on_click=lambda e: self.page.run_task(self._cancel_setup_view) if self.page else None,
                                style=ft.ButtonStyle(
                                    side={ft.ControlState.DEFAULT: ft.BorderSide(1, BORDER_STRONG)},
                                    color=TEXT_SECONDARY,
                                    shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                                ),
                            ),
                            ft.Container(expand=True),
                            ft.FilledButton(
                                "Continue",
                                on_click=lambda e: self.page.run_task(self._submit_setup_view) if self.page else None,
                                style=ft.ButtonStyle(
                                    bgcolor={ft.ControlState.DEFAULT: ACCENT, ft.ControlState.HOVERED: "#8BB9FF"},
                                    color=ft.Colors.BLACK,
                                    shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                                ),
                            ),
                        ]
                    ),
                ],
                spacing=10,
                tight=True,
            ),
        )
        return ft.Container(
            visible=False,
            expand=True,
            bgcolor=CANVAS,
            alignment=ft.Alignment(0, 0),
            content=card,
        )

    def build_sidebar(self) -> ft.Control:
        self.sidebar_threads_column = ft.Column([], spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        self.workspace_selector = ft.Dropdown(
            value=str(self.config.cwd.resolve()),
            options=[],
            text_size=11,
            dense=True,
            border=ft.InputBorder.OUTLINE,
            border_color=BORDER,
            focused_border_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            on_select=self._on_workspace_select,
        )

        self.sidebar_new_thread_button = ft.TextButton(
            content=ft.Text("+ New thread", size=12, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600),
            on_click=lambda e: self._on_new_thread(),
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: SURFACE_2, ft.ControlState.HOVERED: SURFACE_3},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                side=ft.BorderSide(1, BORDER_STRONG),
                padding=ft.Padding.symmetric(horizontal=10, vertical=7),
            ),
        )
        self.sidebar_new_thread_compact = ft.IconButton(
            icon=ft.Icons.ADD,
            tooltip="New thread",
            on_click=lambda e: self._on_new_thread(),
            icon_color=TEXT_PRIMARY,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: SURFACE_2, ft.ControlState.HOVERED: SURFACE_3},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                side=ft.BorderSide(1, BORDER_STRONG),
            ),
        )
        self.sidebar_toggle_button = ft.IconButton(
            icon=ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT,
            tooltip="Collapse sidebar",
            on_click=lambda e: self._toggle_sidebar(),
            icon_size=16,
            icon_color=TEXT_SECONDARY,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, ft.Colors.WHITE)},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )

        self.sidebar_workspace_block = ft.Column(
            [
                ft.Text("Workspace", size=11, color=TEXT_MUTED, weight=ft.FontWeight.W_500),
                self.workspace_selector,
            ],
            spacing=6,
            tight=True,
        )
        self.sidebar_threads_label = ft.Text(
            "Threads",
            size=11,
            color=TEXT_MUTED,
            weight=ft.FontWeight.W_500,
        )

        self.sidebar_new_thread_container = ft.Container(
            self.sidebar_new_thread_button,
            expand=True,
        )
        self.sidebar_top_row = ft.Row(
            [
                self.sidebar_new_thread_container,
                self.sidebar_new_thread_compact,
                self.sidebar_toggle_button,
            ],
            spacing=6,
        )

        self.sidebar_body = ft.Column(
            [
                ft.Divider(height=12, color=BORDER),
                self.sidebar_workspace_block,
                ft.Divider(height=12, color=BORDER),
                self.sidebar_threads_label,
                self.sidebar_threads_column,
            ],
            spacing=SPACE_SM,
            expand=True,
        )
        self.sidebar_footer = ft.Container(
            content=ft.Column(
                [
                    ft.Divider(height=12, color=BORDER),
                    ft.TextButton(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.SETTINGS_OUTLINED, size=16, color=TEXT_SECONDARY),
                                ft.Text("Settings", size=12, color=TEXT_SECONDARY, weight=ft.FontWeight.W_600),
                            ],
                            spacing=8,
                        ),
                        on_click=lambda e: self.page.run_task(self._open_setup_view) if self.page else None,
                        style=ft.ButtonStyle(
                            bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.06, ft.Colors.WHITE)},
                            shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                            padding=ft.Padding.symmetric(horizontal=8, vertical=7),
                        ),
                    ),
                ],
                spacing=6,
                tight=True,
            )
        )

        sidebar = ft.Container(
            width=THREADS_WIDTH,
            bgcolor=SURFACE_1,
            padding=ft.Padding.symmetric(horizontal=12, vertical=12),
            content=ft.Column(
                [
                    self.sidebar_top_row,
                    self.sidebar_body,
                    self.sidebar_footer,
                ],
                spacing=SPACE_SM,
                expand=True,
            ),
        )
        return sidebar

    def _toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        self._apply_sidebar_state()

    def _apply_sidebar_state(self, update: bool = True):
        if not self.sidebar_root:
            return
        collapsed = self.sidebar_collapsed
        self.sidebar_root.width = THREADS_WIDTH_COLLAPSED if collapsed else THREADS_WIDTH
        self.sidebar_root.padding = (
            ft.Padding.symmetric(horizontal=8, vertical=8)
            if collapsed
            else ft.Padding.symmetric(horizontal=12, vertical=12)
        )

        if self.sidebar_toggle_button:
            self.sidebar_toggle_button.icon = (
                ft.Icons.KEYBOARD_DOUBLE_ARROW_RIGHT
                if collapsed
                else ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT
            )
            self.sidebar_toggle_button.tooltip = (
                "Expand sidebar" if collapsed else "Collapse sidebar"
            )
        if self.sidebar_top_row:
            self.sidebar_top_row.alignment = (
                ft.MainAxisAlignment.CENTER
                if collapsed
                else ft.MainAxisAlignment.START
            )
        if self.sidebar_new_thread_container:
            self.sidebar_new_thread_container.visible = not collapsed
        if self.sidebar_new_thread_button:
            self.sidebar_new_thread_button.visible = not collapsed
        if self.sidebar_new_thread_compact:
            self.sidebar_new_thread_compact.visible = False
        if self.sidebar_body:
            self.sidebar_body.visible = not collapsed
        if self.sidebar_workspace_block:
            self.sidebar_workspace_block.visible = not collapsed
        if self.sidebar_threads_label:
            self.sidebar_threads_label.visible = not collapsed
        if self.sidebar_footer:
            self.sidebar_footer.visible = not collapsed

        self._refresh_sidebar_threads()
        if update and self.page:
            self.page.update()

    def build_header(self) -> ft.Control:
        self.header_session_text = ft.Text(
            self.current_session_title,
            size=15,
            weight=ft.FontWeight.W_700,
            color=TEXT_PRIMARY,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.header_workspace_text = ft.Text(
            f"Workspace: {self.config.cwd}",
            size=11,
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
        self.current_session_title = normalized if normalized else "New thread"
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
            width=230,
            text_size=11,
            dense=True,
            border=ft.InputBorder.OUTLINE,
            border_color=BORDER,
            focused_border_color=ACCENT,
            content_padding=ft.Padding.symmetric(horizontal=11, vertical=8),
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
            text_style=ft.TextStyle(size=14, color=TEXT_PRIMARY),
            hint_style=ft.TextStyle(size=14, color=TEXT_MUTED),
            content_padding=ft.Padding.symmetric(horizontal=14, vertical=11),
        )

        self.send_button = ft.IconButton(
            icon=ft.Icons.ARROW_UPWARD_ROUNDED,
            tooltip="Send",
            on_click=self._on_send,
            icon_color=ft.Colors.BLACK,
            icon_size=18,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ACCENT, ft.ControlState.HOVERED: "#8BB9FF"},
                shape=ft.CircleBorder(),
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
                    self.loading_indicator,
                    self.send_button,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _refresh_action_button(self):
        if not self.send_button:
            return
        if self._is_turn_running:
            self.send_button.icon = ft.Icons.STOP_ROUNDED
            self.send_button.tooltip = "Stop"
            self.send_button.icon_color = ft.Colors.WHITE
            self.send_button.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.85, ft.Colors.RED_400)},
                shape=ft.CircleBorder(),
            )
        else:
            self.send_button.icon = ft.Icons.ARROW_UPWARD_ROUNDED
            self.send_button.tooltip = "Send"
            self.send_button.icon_color = ft.Colors.BLACK
            self.send_button.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ACCENT, ft.ControlState.HOVERED: "#8BB9FF"},
                shape=ft.CircleBorder(),
            )
        if self.page:
            self.send_button.update()

    def _set_loading(self, loading: bool):
        if self.loading_indicator:
            self.loading_indicator.visible = loading
        if self.input_field:
            self.input_field.disabled = self._is_turn_running
        self._refresh_action_button()
        if self.page:
            self.page.update()
