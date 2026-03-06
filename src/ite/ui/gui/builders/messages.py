from __future__ import annotations
import re
import flet as ft
from typing import Any
from ..tokens import *


class MessageBuilderMixin:
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

