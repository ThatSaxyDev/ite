from __future__ import annotations
import asyncio
import base64
from pathlib import Path
import flet as ft
from ..tokens import *
from ite.config.config import ApprovalPolicy


class LayoutBuilderMixin:
    def _load_empty_state_image_base64(self) -> str | None:
        try:
            image_path = Path(__file__).resolve().parents[2] / "assets" / "ite_image.png"
            if not image_path.exists():
                return None
            return base64.b64encode(image_path.read_bytes()).decode("ascii")
        except Exception:
            return None

    def run(self, page: ft.Page):
        self.page = page
        page.title = "iTE"
        page.theme_mode = ft.ThemeMode.DARK
        page.theme = ft.Theme(font_family=FONT_UI)
        page.padding = 0
        page.bgcolor = CANVAS
        page.window.width = 1500
        page.window.height = 980
        page.window.min_width = 1180
        page.window.min_height = 760
        page.run_task(self._center_window)
        page.on_close = self._on_close
        page.on_keyboard_event = self._on_keyboard_event

        self._build_ui(page)

    async def _center_window(self):
        if not self.page:
            return
        await asyncio.sleep(0)
        await self.page.window.center()

    def _build_ui(self, page: ft.Page):
        self.sidebar_root = self.build_sidebar()
        self.chat_workboard_row = ft.Row(
            [
                self._build_chat_panel(),
                ft.VerticalDivider(width=1, color=BORDER),
                self._build_workboard_panel(),
            ],
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.chat_shell = ft.Row(
            [
                self.sidebar_root,
                ft.VerticalDivider(width=1, color=BORDER),
                ft.Container(
                    content=ft.Column(
                        [
                            self.build_header(),
                            self.chat_workboard_row,
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
        page.run_task(self._refresh_branch_options_async)
        self._start_branch_sync_watcher()
        self._apply_sidebar_state(update=False)
        self._apply_workboard_state(update=False)
        self._apply_app_mode()
        if hasattr(self, "_refresh_workboard_from_session"):
            self._refresh_workboard_from_session()
        if hasattr(self, "_refresh_empty_state_copy"):
            self._refresh_empty_state_copy()
        if hasattr(self, "_refresh_empty_state_visibility"):
            self._refresh_empty_state_visibility()

    def build_setup_view(self) -> ft.Control:
        from ite.config.config import DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_MODEL_NAME

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
            size=TYPE_SM,
            color=ft.Colors.with_opacity(0.9, ft.Colors.RED_300),
            visible=False,
        )
        self.setup_base_url_field = ft.TextField(
            label="Base URL",
            value=self.config.base_url or DEFAULT_BASE_URL,
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            text_size=TYPE_MD,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        )
        self.setup_api_key_field = ft.TextField(
            label="API Key",
            password=True,
            can_reveal_password=True,
            value=self.config.api_key or DEFAULT_API_KEY,
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            text_size=TYPE_MD,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        )
        self.setup_model_field = ft.TextField(
            label="Model",
            value=self.config.model_name or DEFAULT_MODEL_NAME,
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            text_size=TYPE_MD,
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
                            ft.Text(_format_approval_label(p.value), size=TYPE_MD, color=TEXT_PRIMARY),
                            ft.Text(
                                approval_descriptions.get(p.value, ""),
                                size=TYPE_XS,
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
            text_size=TYPE_SM,
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
                        size=TYPE_H1,
                        weight=WEIGHT_BOLD,
                        color=TEXT_PRIMARY,
                    ),
                    ft.Text(
                        (
                            "Connect your provider credentials to start using the GUI."
                            if self.config.needs_setup
                            else "Update provider and approval settings."
                        ),
                        size=TYPE_MD,
                        color=TEXT_SECONDARY,
                    ),
                    ft.Divider(height=10, color=BORDER),
                    self.setup_base_url_field,
                    self.setup_api_key_field,
                    self.setup_model_field,
                    ft.Text("Approval mode", size=TYPE_SM, color=TEXT_MUTED, weight=WEIGHT_SEMIBOLD),
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
                spacing=SPACE_SM,
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
        self.sidebar_threads_column = ft.Column([], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        self.workspace_selector = ft.Dropdown(
            value=str(self.config.cwd.resolve()),
            options=[],
            text_size=TYPE_SM,
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
            content=ft.Text("+ New thread", size=TYPE_MD, color=TEXT_PRIMARY, weight=WEIGHT_SEMIBOLD),
            on_click=lambda e: self._on_new_thread(),
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: SURFACE_2, ft.ControlState.HOVERED: SURFACE_3},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                side=ft.BorderSide(1, BORDER_STRONG),
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
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
                ft.Text("Workspace", size=TYPE_SM, color=TEXT_MUTED, weight=WEIGHT_MEDIUM),
                self.workspace_selector,
            ],
            spacing=SPACE_XS,
            tight=True,
        )
        self.sidebar_threads_label = ft.Text(
            "Threads",
            size=TYPE_SM,
            color=TEXT_MUTED,
            weight=WEIGHT_MEDIUM,
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
            spacing=SPACE_XS,
            expand=True,
        )
        self.sidebar_footer = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.TextButton(
                                content=ft.Row(
                                    [
                                        ft.Icon(ft.Icons.SETTINGS_OUTLINED, size=16, color=TEXT_SECONDARY),
                                        ft.Text("Settings", size=TYPE_MD, color=TEXT_SECONDARY, weight=WEIGHT_SEMIBOLD),
                                    ],
                                    spacing=6,
                                ),
                                on_click=lambda e: self.page.run_task(self._open_setup_view) if self.page else None,
                                style=ft.ButtonStyle(
                                    bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.06, ft.Colors.WHITE), ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT},
                                    shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=7),
                                ),
                            ),
                        ],
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
        self.gui_state.toggle_sidebar()
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

        self._render_sidebar_threads()
        if update:
            if self.sidebar_root:
                self._safe_control_update(self.sidebar_root)
            if self.sidebar_toggle_button:
                self._safe_control_update(self.sidebar_toggle_button)

    def build_header(self) -> ft.Control:
        self.header_session_text = ft.Text(
            self.current_session_title,
            size=TYPE_TITLE,
            weight=WEIGHT_BOLD,
            color=TEXT_PRIMARY,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.workboard_header_toggle_button = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
            tooltip="Hide workboard",
            on_click=lambda e: self._toggle_workboard(),
            icon_size=16,
            icon_color=TEXT_SECONDARY,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, ft.Colors.WHITE)},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )
        self.header_workspace_text = ft.Text(
            f"Workspace: {self.config.cwd}",
            size=TYPE_SM,
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
                    self.workboard_header_toggle_button,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _set_current_session_title(self, title: str | None):
        self.gui_state.set_current_session_title(title)

    def _build_chat_panel(self) -> ft.Control:
        self.messages_column = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            auto_scroll=False,
            on_scroll=self._on_chat_scroll,
            spacing=CHAT_ITEM_GAP,
            expand=True,
        )
        self._ensure_chat_bottom_spacer()
        self.empty_state_title_text = ft.Text(
            "Ready when you are",
            size=32,
            weight=WEIGHT_SEMIBOLD,
            color=TEXT_PRIMARY,
        )
        self.empty_state_workspace_text = ft.Text(
            "",
            size=24,
            color=TEXT_MUTED,
        )
        empty_state_workspace_button = ft.TextButton(
            content=ft.Row(
                [
                    self.empty_state_workspace_text,
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=16, color=TEXT_MUTED),
                ],
                spacing=4,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            on_click=self._open_empty_state_workspace_dialog,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                bgcolor={
                    ft.ControlState.HOVERED: ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
                    ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                },
            ),
        )
        image_base64 = self._load_empty_state_image_base64()
        if image_base64:
            empty_image = ft.Image(
                src=f"data:image/png;base64,{image_base64}",
                width=400,              
                fit="cover",
            )
        else:
            empty_image = ft.Image(src="ite_image.png", width=400, fit="cover")
        shimmer_cls = getattr(ft, "Shimmer", None)
        if shimmer_cls:
            empty_image_control: ft.Control = shimmer_cls(
                content=empty_image,
                base_color=ft.Colors.with_opacity(0.2, ft.Colors.WHITE),
                highlight_color=ft.Colors.with_opacity(0.4, ft.Colors.WHITE),
                period=2200,
            )
            # Quick fallback (non-shimmer): empty_image_control = empty_image
        else:
            empty_image_control = empty_image
        self.empty_state_container = ft.Container(
            alignment=ft.Alignment(0, 0),
            expand=True,
            visible=True,
            content=ft.Column(
                [
                    empty_image_control,
                    self.empty_state_title_text,
                    empty_state_workspace_button,
                ],
                spacing=5,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                tight=True,
            ),
        )

        return ft.Container(
            expand=True,
            bgcolor=CANVAS,
            padding=ft.Padding.only(left=20, right=20, top=16),
            content=ft.Row(
                [
                    ft.Container(
                        width=CONTENT_LANE_WIDTH,
                        content=ft.Stack(
                            [
                                self.empty_state_container,
                                self.messages_column,
                            ],
                            expand=True,
                        ),
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                expand=True,
            ),
        )

    def _build_workboard_panel(self) -> ft.Control:
        self.workboard_toggle_button = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
            tooltip="Collapse workboard",
            on_click=lambda e: self._toggle_workboard(),
            icon_size=16,
            icon_color=TEXT_SECONDARY,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, ft.Colors.WHITE)},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )
        self.workboard_todos_column = ft.Column(
            [],
            spacing=10,
            tight=True,
        )
        self.workboard_todos_section = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Progress", size=TYPE_SM, color=TEXT_MUTED, weight=WEIGHT_SEMIBOLD),
                    self.workboard_todos_column,
                ],
                spacing=8,
                tight=True,
            ),
            visible=False,
        )
        self.workboard_plan_markdown = ft.Markdown(
            "",
            selectable=True,
            extension_set="gitHubFlavored",
        )
        self.workboard_plan_section = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.DESCRIPTION_ROUNDED, size=16, color=ACCENT),
                            ft.Text("Implementation plan", size=TYPE_TITLE, color=TEXT_PRIMARY, weight=WEIGHT_BOLD),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.workboard_plan_markdown,
                ],
                spacing=8,
                tight=True,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=12),
            border=ft.Border.all(1, BORDER),
            border_radius=RADIUS_MD,
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            visible=False,
        )
        self.workboard_plan_wrapper = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Plan", size=TYPE_SM, color=TEXT_MUTED, weight=WEIGHT_SEMIBOLD),
                    self.workboard_plan_section,
                ],
                spacing=8,
                tight=True,
            ),
            visible=False,
        )

        workboard_header = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.DASHBOARD_CUSTOMIZE_ROUNDED, size=16, color=ACCENT),
                            ft.Text("Workboard", size=TYPE_TITLE, color=TEXT_PRIMARY, weight=WEIGHT_BOLD),
                            ft.Container(expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=1, color=HAIRLINE),
                ],
                spacing=8,
                tight=True,
            ),
            bgcolor=SURFACE_1,
            padding=ft.Padding.only(bottom=4),
        )

        self.workboard_body = ft.Column(
            [
                self.workboard_todos_section,
                self.workboard_plan_wrapper,
                ft.Container(height=35),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self.workboard_container = ft.Container(
            width=self.workboard_width,
            expand=True,
            bgcolor=SURFACE_1,
            border=ft.Border.only(left=ft.BorderSide(1, BORDER)),
            padding=ft.Padding.only(left=10, right=10, top=12, bottom=0),
            content=ft.Column(
                [
                    workboard_header,
                    self.workboard_body,
                ],
                spacing=0,
                tight=True,
                expand=True,
            ),
        )
        return self.workboard_container

    def build_composer(self) -> ft.Control:
        model_choices = [
            "minimax-m2.7:cloud",
            "kimi-k2.5:cloud",
            "glm-5:cloud",
            "glm-5.1:cloud",
        ]
        if self.config.model_name not in model_choices:
            model_choices.insert(0, self.config.model_name)

        self.model_items = model_choices
        self.model_selector_text = ft.Text(
            self.config.model_name,
            size=TYPE_BODY,
            color=TEXT_PRIMARY,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.model_selector = ft.TextButton(
            content=ft.Row(
                [   
                    ft.Container(width=2),
                    self.model_selector_text,
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=14, color=TEXT_MUTED),
                    ft.Container(width=2),
                ],
                spacing=3,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            on_click=self._open_model_picker_dialog,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=2, vertical=2),
                shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.06, ft.Colors.WHITE), ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT},
            ),
        )
        self.branch_selector_text = ft.Text(
            "branch",
            size=TYPE_BODY,
            color=TEXT_SECONDARY,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.branch_selector = ft.TextButton(
            content=ft.Row(
                [
                    ft.Container(width=2),
                    self.branch_selector_text,
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=14, color=TEXT_MUTED),
                    ft.Container(width=2),
                ],
                spacing=3,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            on_click=self._open_branch_picker_dialog,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=2, vertical=2),
                shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.06, ft.Colors.WHITE), ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT},
            ),
        )
        self.branch_create_button = ft.IconButton(
            icon=ft.Icons.ADD,
            tooltip="Create branch",
            width=28,
            height=28,
            icon_size=14,
            icon_color=TEXT_SECONDARY,
            on_click=self._open_create_branch_dialog,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, ft.Colors.WHITE)},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
            ),
        )
        self.branch_controls_row = ft.Row(
            [                   
                ft.Container(
                    content=ft.Icon(ft.Icons.ACCOUNT_TREE, size=18, color=TEXT_MUTED),
                    # padding=ft.Padding.only(top=6),
                ),
                ft.Container(
                    content=self.branch_create_button,
                    # padding=ft.Padding.only(top=6),
                ),
                self.branch_selector,    
                                             
            ],
            spacing=3,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            visible=False,
        )
        self.plan_toggle_button = ft.TextButton(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.TUNE_OUTLINED, size=13, color=TEXT_MUTED),
                    ft.Text("Plan", size=TYPE_BODY, color=TEXT_SECONDARY, weight=WEIGHT_MEDIUM),
                ],
                spacing=6,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=lambda _e: self.page.run_task(self._toggle_plan_mode) if self.page else None,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                bgcolor={
                    ft.ControlState.HOVERED: ft.Colors.with_opacity(0.07, ft.Colors.WHITE),
                    ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                },
            ),
        )

        self.input_field = ft.TextField(
            hint_text="Message the agent...",
            expand=True,
            multiline=True,
            shift_enter=True,
            min_lines=1,
            max_lines=8,
            on_submit=self._on_send,
            filled=False,
            border=ft.InputBorder.NONE,
            border_color=ft.Colors.TRANSPARENT,
            focused_border_color=ft.Colors.TRANSPARENT,
            bgcolor=ft.Colors.TRANSPARENT,
            cursor_color=ACCENT,
            text_style=ft.TextStyle(size=13, color=TEXT_PRIMARY),
            hint_style=ft.TextStyle(size=TYPE_BODY, color=TEXT_MUTED),
            text_size=TYPE_BODY,
            content_padding=ft.Padding.symmetric(horizontal=0, vertical=0),
            on_focus=self._on_composer_focus,
            on_blur=self._on_composer_blur,
        )

        self.send_button = ft.IconButton(
            icon=ft.Icons.ARROW_UPWARD_ROUNDED,
            width=38,
            height=38,
            tooltip="Send",
            on_click=self._on_send,
            icon_color=ft.Colors.BLACK,
            icon_size=18,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: TEXT_PRIMARY, ft.ControlState.HOVERED: "#FFFFFF"},
                shape=ft.CircleBorder(),
            ),
        )
        self.attach_button = ft.IconButton(
            icon=ft.Icons.ATTACH_FILE_ROUNDED,
            width=24,
            height=24,
            tooltip="Attach files",
            on_click=self._open_attach_picker,
            icon_color=TEXT_SECONDARY,
            icon_size=14,
            style=ft.ButtonStyle(
                padding=0,
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, ft.Colors.WHITE)},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
            ),
        )
        self.attachments_row = ft.Row(
            [],
            wrap=True,
            spacing=8,
            run_spacing=6,
            visible=False,
        )
        composer_lane = ft.Container(
            width=CONTENT_LANE_WIDTH,
            border=ft.Border.all(1, BORDER),
            border_radius=RADIUS_LG,
            bgcolor=SURFACE_ELEVATED,
            padding=ft.Padding.only(left=14, right=14, bottom=7),
            content=ft.Column(
                [
                    ft.Container(
                        content=self.attachments_row,
                        padding=ft.Padding.only(top=8),
                    ),
                    ft.Container(
                        content=self.input_field,
                        expand=True,
                    ),
                    ft.Row(
                        [
                            self.attach_button,
                            self.model_selector,
                            self.plan_toggle_button,
                            ft.Container(expand=True),
                            self.branch_controls_row,
                            self.send_button,
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=0,
            ),
        )
        return ft.Container(
            bgcolor=CANVAS,
            # border=ft.Border.only(top=ft.BorderSide(1, HAIRLINE)),
            padding=ft.Padding.only(left=20, bottom=10, right=20),
            content=ft.Row([composer_lane], alignment=ft.MainAxisAlignment.CENTER),
        )

    def _refresh_action_button(self):
        if not self.send_button:
            return
        if self._is_turn_running:
            self.send_button.icon = ft.Icons.STOP_ROUNDED
            self.send_button.tooltip = "Stop"
            self.send_button.icon_color = ft.Colors.BLACK
            self.send_button.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.WHITE},
                shape=ft.CircleBorder(),
            )
        else:
            self.send_button.icon = ft.Icons.ARROW_UPWARD_ROUNDED
            self.send_button.tooltip = "Send"
            self.send_button.icon_color = ft.Colors.BLACK
            self.send_button.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: TEXT_PRIMARY, ft.ControlState.HOVERED: "#FFFFFF"},
                shape=ft.CircleBorder(),
            )
        if self.page:
            self._safe_control_update(self.send_button)

    def _set_loading(self, loading: bool):
        self._apply_loading_controls()
