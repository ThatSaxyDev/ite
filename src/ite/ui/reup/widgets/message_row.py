from __future__ import annotations

from typing import Any

from textual import events
from textual.containers import Container
from textual.widgets import Static

from .image_preview import render_image_halfblock


class UserMessageRow(Container):
    BUBBLE_MAX_WIDTH = 92
    BUBBLE_MIN_WIDTH = 12
    BUBBLE_HORIZONTAL_GUTTER = 10

    def __init__(
        self,
        bubble: Static,
        *,
        desired_width: int,
        raw_text: str = "",
        images: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        children: list[Static] = []
        for path in images or []:
            preview = self._image_preview(path)
            if preview is not None:
                children.append(preview)
        children.append(bubble)
        super().__init__(*children, **kwargs)
        self._bubble = bubble
        self._desired_width = desired_width
        self._raw_text = raw_text
        if raw_text:
            self.tooltip = "Click to copy"

    @staticmethod
    def _image_preview(path: str) -> Static | None:
        text = render_image_halfblock(path)
        if text is None:
            return None
        return Static(text, classes="chat-image-preview")

    def on_click(self) -> None:
        if not self._raw_text:
            return
        self.app.copy_to_clipboard(self._raw_text)
        self.app.notify("Copied to clipboard", timeout=2)

    def on_mount(self) -> None:
        self.refresh_bubble_width()

    def on_resize(self, _event: events.Resize) -> None:
        self.refresh_bubble_width()

    @classmethod
    def clamped_bubble_width(cls, desired_width: int, row_width: int | None) -> int:
        base_width = max(
            cls.BUBBLE_MIN_WIDTH,
            min(cls.BUBBLE_MAX_WIDTH, max(1, int(desired_width or 0))),
        )
        if not row_width or row_width <= 0:
            return base_width
        available_width = max(1, int(row_width) - cls.BUBBLE_HORIZONTAL_GUTTER)
        return min(base_width, available_width)

    def refresh_bubble_width(self, row_width: int | None = None) -> None:
        if row_width is None:
            row_width = int(getattr(self.size, "width", 0) or 0)
        if not row_width and self.parent is not None:
            row_width = int(getattr(self.parent.size, "width", 0) or 0)
        self._bubble.styles.width = self.clamped_bubble_width(
            self._desired_width,
            row_width,
        )
