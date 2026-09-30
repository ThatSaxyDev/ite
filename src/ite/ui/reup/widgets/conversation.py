from __future__ import annotations

from textual.containers import VerticalScroll


class ConversationScroll(VerticalScroll):
    """Follow new messages until the user scrolls away from the bottom."""

    def on_mount(self) -> None:
        self.anchor()
