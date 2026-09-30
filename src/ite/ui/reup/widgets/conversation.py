from __future__ import annotations

from textual.containers import VerticalScroll
from textual.geometry import Offset


class ConversationScroll(VerticalScroll):
    """Follow new messages until the user scrolls away from the bottom."""

    def on_mount(self) -> None:
        self.anchor()

    @property
    def scroll_offset(self) -> Offset:
        # Anchoring can calculate a negative Y offset before content fills the
        # viewport. Keep short conversations at the top instead of shifting
        # their children down to align with the bottom.
        offset = super().scroll_offset
        return Offset(offset.x, max(0, offset.y))
