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

        if not self.branch_controls_row or not self.branch_selector:
            return

        if not in_repo:
            self.current_branch_name = None
            self.branch_selector.options = []
            self.branch_selector.value = None
            self.branch_controls_row.visible = False
            self.page.update()
            return

        branches = await asyncio.to_thread(list_local_branches, cwd)
        current = await asyncio.to_thread(current_branch, cwd)
        if self._branch_workspace_key != cwd_key:
            return

        self.current_branch_name = current
        self.branch_selector.options = [
            ft.dropdown.Option(
                key=b.name,
                text=b.name,
            )
            for b in branches
        ]
        self.branch_selector.value = current if any(b.name == current for b in branches) else None
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

    def _on_branch_select(self, e: ft.Event[ft.Dropdown]):
        if not self.page or not self.branch_selector:
            return
        selected = self.branch_selector.value
        if not selected or selected == self.current_branch_name or self.branch_loading:
            return
        self.page.run_task(self._checkout_branch_from_gui, selected)

    async def _checkout_branch_from_gui(self, branch: str):
        self._set_branch_loading(True)
        previous = self.current_branch_name
        try:
            cwd = Path(self.config.cwd).resolve()
            result = await asyncio.to_thread(checkout_branch, cwd, branch)
            if result.ok:
                self._add_assistant_card("Branch", ft.Text(result.message, color=TEXT_SECONDARY))
            else:
                self._add_message("system", f"Branch switch failed: {result.message}", is_error=True)
                if self.branch_selector:
                    self.branch_selector.value = previous
            await self._refresh_branch_options_async()
        finally:
            self._set_branch_loading(False)

    def _open_create_branch_dialog(self, e=None):
        if not self.page:
            return
        self.branch_name_input = ft.TextField(
            label="New branch name",
            autofocus=True,
            hint_text="feature/my-branch",
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=ACCENT,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            text_size=TYPE_MD,
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
            content=self.branch_name_input,
            actions=[
                ft.TextButton("Cancel", on_click=on_cancel),
                ft.FilledButton("Create", on_click=on_create),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
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
