from __future__ import annotations
import re
import flet as ft
from typing import Any
from ..tokens import *


class MessageBuilderMixin:
    def _wrap_in_lane(self, content: ft.Control) -> ft.Control:
        return ft.Row(
            [
                ft.Container(
                    width=CONTENT_LANE_WIDTH,
                    content=content,
                )
            ],
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def _build_status_chip(self, text: str, color: str, border: str, bg: str) -> ft.Container:
        return ft.Container(
            content=ft.Text(text, size=TYPE_XS, color=color, weight=WEIGHT_SEMIBOLD),
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            border=ft.Border.all(1, border),
            border_radius=RADIUS_LG,
            bgcolor=bg,
        )

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
        state_label = ft.Text("", size=TYPE_SM, color=TEXT_MUTED)
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
            spacing=SPACE_XS,
        )

    def build_chat_message(self, role: str, content: str, is_error: bool = False) -> ft.Control:
        if role == "assistant" and not is_error:
            bubble = ft.Container(
                content=ft.Markdown(content, selectable=True, extension_set="gitHubFlavored"),
                border_radius=RADIUS_SM,
                padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                width=ASSISTANT_MESSAGE_WIDTH - 20,
            )
        else:
            bg = SURFACE_2 if role == "user" else SURFACE_1
            border_color = BORDER if not is_error else ft.Colors.with_opacity(0.28, ft.Colors.RED_300)
            bubble = ft.Container(
                content=ft.Markdown(content, selectable=True, extension_set="gitHubFlavored"),
                bgcolor=bg,
                border_radius=RADIUS_MD,
                padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                border=ft.Border.all(1, border_color),
                shadow=SHADOW_SUBTLE if is_error else None,
                width=USER_MESSAGE_WIDTH if role == "user" else ASSISTANT_MESSAGE_WIDTH,
            )

        align = ft.MainAxisAlignment.END if role == "user" else ft.MainAxisAlignment.START
        return self._wrap_in_lane(ft.Row([bubble], alignment=align))

    def build_system_log_message(self, title: str, content: str, level: str = "info") -> ft.Control:
        color = TEXT_SECONDARY
        border = BORDER
        if level == "error":
            color = ft.Colors.with_opacity(0.85, ft.Colors.RED_200)
            border = ft.Colors.with_opacity(0.25, ft.Colors.RED_300)

        card = ft.Container(
            bgcolor=SURFACE_ELEVATED,
            border_radius=RADIUS_SM,
            border=ft.Border.all(1, border if level == "error" else HAIRLINE),
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            width=SPECIAL_CARD_WIDTH,
            content=ft.Column(
                [
                    ft.Text(title, size=10, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                    ft.Text(content, style=MONO_STYLE, selectable=True, color=color),
                ],
                tight=True,
                spacing=CHAT_BLOCK_GAP,
            ),
        )
        return self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))

    def _add_message(
        self,
        role: str,
        content: str,
        is_error: bool = False,
        force_scroll: bool = True,
    ):
        if not self.messages_column or not self.page:
            return
        self._append_chat_control(self.build_chat_message(role, content, is_error=is_error))
        self.page.update()
        self._scroll_chat_to_bottom(force=force_scroll)

    def _add_assistant_card(self, title: str, content: ft.Control):
        if not self.messages_column or not self.page:
            return

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Text(title, size=TYPE_SM, color=TEXT_MUTED, weight=WEIGHT_SEMIBOLD),
                    ft.Divider(height=1, color=HAIRLINE),
                    content,
                ],
                spacing=CHAT_BLOCK_GAP,
                tight=True,
            ),
            bgcolor=SURFACE_ELEVATED,
            border=ft.Border.all(1, HAIRLINE),
            border_radius=RADIUS_MD,
            padding=ft.Padding.symmetric(horizontal=CARD_PAD_X + 2, vertical=CARD_PAD_Y + 1),
            width=SPECIAL_CARD_WIDTH,
        )
        self._append_chat_control(
            self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        )
        self.page.update()
        self._scroll_chat_to_bottom(force=True)

    def _add_plan_card(self, plan_text: str):
        if not self.messages_column or not self.page:
            return
        # Plans are primary artifacts; render full content without preview clipping.
        plan_body = ft.Markdown(
            plan_text,
            selectable=True,
            extension_set="gitHubFlavored",
        )
        self._add_assistant_card("Plan", plan_body)

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
                border_radius=RADIUS_SM,
                padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                width=ASSISTANT_MESSAGE_WIDTH - 20,
            )
            self._append_chat_control(
                self._wrap_in_lane(
                    ft.Row([self.streaming_container], alignment=ft.MainAxisAlignment.START)
                )
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
                            ft.Text("tool", size=TYPE_XS, color=TEXT_MUTED),
                            ft.Text(name, size=TYPE_MD, weight=WEIGHT_BOLD, color=TEXT_PRIMARY),
                            ft.Text(f"#{call_id[:8]}", size=TYPE_XS, color=TEXT_MUTED),
                            ft.Container(expand=True),
                            self._build_status_chip(
                                "running",
                                ACCENT,
                                ACCENT_SOFT,
                                ft.Colors.with_opacity(0.1, ACCENT),
                            ),
                        ]
                    ),
                    ft.Divider(height=1, color=HAIRLINE),
                    self._build_expandable_block(
                        args_text,
                        as_markdown=False,
                        max_chars=500,
                        max_lines=5,
                    ),
                ],
                spacing=CHAT_BLOCK_GAP,
                tight=True,
            ),
            border=ft.Border.all(1, ACCENT_SOFT),
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=CARD_PAD_X, vertical=CARD_PAD_Y),
            width=SPECIAL_CARD_WIDTH,
            bgcolor=SURFACE_ELEVATED,
        )
        row = self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        row_index = self._append_chat_control(row)
        if row_index is not None:
            self._tool_call_row_indices[call_id] = row_index
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
        state_color = SUCCESS if success else DANGER
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
                            ft.Text("tool", size=TYPE_XS, color=TEXT_MUTED),
                            ft.Text(name, size=TYPE_MD, weight=WEIGHT_BOLD, color=TEXT_PRIMARY),
                            ft.Text(f"#{call_id[:8]}", size=TYPE_XS, color=TEXT_MUTED),
                            ft.Container(expand=True),
                            self._build_status_chip(
                                state_text,
                                state_color,
                                SUCCESS_SOFT if success else DANGER_SOFT,
                                ft.Colors.with_opacity(
                                    0.1, ft.Colors.GREEN_300 if success else ft.Colors.RED_300
                                ),
                            ),
                        ]
                    ),
                    ft.Divider(height=1, color=HAIRLINE),
                    body,
                ],
                spacing=CHAT_BLOCK_GAP,
                tight=True,
            ),
            border=ft.Border.all(1, SUCCESS_SOFT if success else DANGER_SOFT),
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=CARD_PAD_X, vertical=CARD_PAD_Y),
            width=SPECIAL_CARD_WIDTH,
            bgcolor=SURFACE_ELEVATED,
        )
        self.messages_column.controls[index] = self._wrap_in_lane(
            ft.Row([card], alignment=ft.MainAxisAlignment.START)
        )
        self.page.update()
        self._scroll_chat_to_bottom(animate=False, force=True)
