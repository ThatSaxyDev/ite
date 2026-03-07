from __future__ import annotations

import asyncio
from pathlib import Path
import flet as ft
from ite.git.branches import (
    BranchInfo,
    checkout_branch,
    create_and_checkout,
    current_branch,
    is_git_repo,
    list_local_branches,
)
from ..tokens import *


class BranchControllerMixin:
    async def _refresh_branch_options_async(self):
        if not self.page:
            return
        cwd = Path(self.config.cwd).resolve()
        cwd_key = str(cwd)
        self._branch_workspace_key = cwd_key
        in_repo = await asyncio.to_thread(is_git_repo, cwd)
        if self._branch_workspace_key != cwd_key:
            return

        if not self.branch_controls_row or not self.branch_selector_text:
            return

        if not in_repo:
            self.current_branch_name = None
            self.branch_items = []
            self.branch_selector_text.value = "branch"
            self.branch_controls_row.visible = False
            self.page.update()
            return

        branches = await asyncio.to_thread(list_local_branches, cwd)
        current = await asyncio.to_thread(current_branch, cwd)
        if self._branch_workspace_key != cwd_key:
            return

        self.current_branch_name = current
        self.branch_items = branches
        self.branch_selector_text.value = current
        self.branch_controls_row.visible = True
        self.page.update()

    def _set_branch_loading(self, loading: bool):
        self.branch_loading = loading
        if self.branch_selector:
            self.branch_selector.disabled = loading
        if self.branch_create_button:
            self.branch_create_button.disabled = loading
        if self.page:
            self.page.update()

    def _open_branch_picker_dialog(self, e=None):
        if not self.page or self.branch_loading:
            return
        self.branch_picker_search = ft.TextField(
            hint_text="Search branches...",
            autofocus=True,
            prefix_icon=ft.Icons.SEARCH,
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            text_size=TYPE_BODY,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=10),
            on_change=self._on_branch_picker_search_change,
        )
        self.branch_picker_list = ft.Column(
            [],
            spacing=3,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._render_branch_picker_items("")
        self.branch_picker_dialog = ft.AlertDialog(
            modal=True,
            bgcolor=SURFACE_1,
            title=ft.Text("Switch branch", color=TEXT_PRIMARY, size=TYPE_TITLE, weight=WEIGHT_SEMIBOLD),
            content=ft.Container(
                width=420,
                height=360,
                content=ft.Column(
                    [
                        ft.Container(
                            content=self.branch_picker_search,
                            padding=ft.Padding.only(top=2),
                        ),
                        ft.Text(
                            "Type to filter local branches",
                            size=TYPE_XS,
                            color=TEXT_MUTED,
                        ),
                        ft.Divider(height=6, color=HAIRLINE),
                        self.branch_picker_list,
                    ],
                    spacing=8,
                    expand=True,
                ),
            ),
            actions=[
                ft.TextButton("Close", on_click=lambda _: self.page.pop_dialog() if self.page else None),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            actions_padding=ft.Padding.only(right=16, bottom=12),
            content_padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        )
        self.page.show_dialog(self.branch_picker_dialog)

    def _on_branch_picker_search_change(self, e: ft.Event[ft.TextField]):
        text = ""
        if self.branch_picker_search and self.branch_picker_search.value:
            text = self.branch_picker_search.value
        self._render_branch_picker_items(text)

    def _render_branch_picker_items(self, query: str):
        if not self.branch_picker_list:
            return
        q = query.strip().lower()
        controls: list[ft.Control] = []
        for item in self.branch_items:
            if q and q not in item.name.lower():
                continue
            is_current = item.name == self.current_branch_name
            row = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.ACCOUNT_TREE_OUTLINED,
                            size=13,
                            color=TEXT_MUTED,
                        ),
                        ft.Text(item.name, size=TYPE_BODY, color=TEXT_PRIMARY, no_wrap=True, expand=True),
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
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                border_radius=RADIUS_SM,
                bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE)
                if is_current
                else ft.Colors.TRANSPARENT,
                on_click=lambda _, name=item.name: self._on_branch_picker_choose(name),
            )
            controls.append(row)
        if not controls:
            controls.append(
                ft.Container(
                    padding=ft.Padding.only(top=6, left=4),
                    content=ft.Text("No branches found", size=TYPE_SM, color=TEXT_MUTED),
                )
            )
        self.branch_picker_list.controls = controls
        if self.page:
            self.page.update()

    def _on_branch_picker_choose(self, branch: str):
        if not self.page or self.branch_loading:
            return
        self.page.pop_dialog()
        if branch == self.current_branch_name:
            return
        self.page.run_task(self._checkout_branch_from_gui, branch)

    async def _checkout_branch_from_gui(self, branch: str):
        self._set_branch_loading(True)
        try:
            cwd = Path(self.config.cwd).resolve()
            result = await asyncio.to_thread(checkout_branch, cwd, branch)
            if result.ok:
                self._add_assistant_card("Branch", ft.Text(result.message, color=TEXT_SECONDARY))
            else:
                self._add_message("system", f"Branch switch failed: {result.message}", is_error=True)
            await self._refresh_branch_options_async()
        finally:
            self._set_branch_loading(False)

    def _open_create_branch_dialog(self, e=None):
        if not self.page:
            return
        self.branch_name_input = ft.TextField(
            autofocus=True,
            hint_text="feature/my-branch",
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            text_size=TYPE_MD,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=10),
        )

        def on_cancel(_):
            if self.page:
                self.page.pop_dialog()

        def on_create(_):
            if self.page:
                self.page.pop_dialog()
                self.page.run_task(self._create_branch_from_gui)

        self.branch_dialog = ft.AlertDialog(
            modal=True,
            bgcolor=SURFACE_1,
            title=ft.Text("Create branch", color=TEXT_PRIMARY, size=TYPE_TITLE, weight=WEIGHT_SEMIBOLD),
            content=ft.Container(
                width=420,
                content=ft.Column(
                    [
                        ft.Text("Enter a new local branch name.", size=TYPE_SM, color=TEXT_MUTED),
                        ft.Container(
                            bgcolor=SURFACE_2,
                            border=ft.Border.all(1, BORDER),
                            border_radius=RADIUS_SM,
                            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                            content=ft.Row(
                                [
                                    ft.Text(
                                        "git checkout -b",
                                        size=TYPE_SM,
                                        color=TEXT_MUTED,
                                        no_wrap=True,
                                    ),
                                    ft.Container(width=1, height=18, bgcolor=HAIRLINE),
                                    ft.Container(self.branch_name_input, expand=True),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ),
                    ],
                    spacing=8,
                    tight=True,
                ),
            ),
            actions=[
                ft.TextButton("Cancel", on_click=on_cancel),
                ft.FilledButton("Create", on_click=on_create),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            actions_padding=ft.Padding.only(right=16, bottom=12),
            content_padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        )
        self.page.show_dialog(self.branch_dialog)

    async def _create_branch_from_gui(self):
        if not self.branch_name_input:
            return
        branch = self.branch_name_input.value.strip()
        if not branch:
            self._add_message("system", "Branch name is required.", is_error=True)
            return

        self._set_branch_loading(True)
        try:
            cwd = Path(self.config.cwd).resolve()
            result = await asyncio.to_thread(create_and_checkout, cwd, branch)
            if result.ok:
                self._add_assistant_card("Branch", ft.Text(result.message, color=TEXT_SECONDARY))
            else:
                self._add_message("system", f"Create branch failed: {result.message}", is_error=True)
            await self._refresh_branch_options_async()
        finally:
            self._set_branch_loading(False)
