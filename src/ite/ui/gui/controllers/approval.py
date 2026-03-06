from __future__ import annotations
import asyncio
from typing import Any
import flet as ft
from ite.config.config import ApprovalPolicy
from ite.config.loader import save_global_approval_mode
from ite.tools.base import ToolConfirmation
from ..tokens import *


class ApprovalControllerMixin:
    def _set_approval_mode(self, mode: str):
        normalized = mode.strip().lower()
        policy = ApprovalPolicy(normalized)
        self.config.approval = policy
        save_global_approval_mode(policy)
        if self.agent and self.agent.session:
            self.agent.session.approval_manager.approval_policy = policy
        if self.approval_selector:
            self.approval_selector.value = policy.value
            self.approval_selector.update()

    def _on_approval_select(self, e: ft.Event[ft.Dropdown]):
        if not self.approval_selector:
            return
        value = self.approval_selector.value
        if not value:
            return
        try:
            self._set_approval_mode(value)
            self._add_assistant_card(
                "Approval Mode",
                ft.Text(
                    f"Global approval mode set to {value}",
                    color=TEXT_SECONDARY,
                ),
            )
        except Exception as ex:
            self._add_message(
                "system",
                f"Failed to set approval mode: {ex}",
                is_error=True,
            )

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
