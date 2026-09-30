from __future__ import annotations

from math import exp
from time import monotonic

from textual import constants, events
from textual.containers import VerticalScroll
from textual.geometry import Offset
from textual.screen import Screen


class ConversationScroll(VerticalScroll):
    """Follow new messages until the user scrolls away from the bottom."""

    _following: bool = True
    _follow_initialized: bool = False
    _following_update: bool = False
    _follow_active: bool = False

    def on_mount(self) -> None:
        self._last_follow_frame = monotonic()
        self._follow_timer = self.set_interval(
            1 / min(60, constants.MAX_FPS), self._advance_follow, pause=True
        )
        self.screen.screen_layout_refresh_signal.subscribe(self, self._follow_content)
        self.call_after_refresh(self._follow_content, self.screen)

    def _follow_content(self, screen: Screen) -> None:
        """Follow layout growth without restarting an animation for every chunk."""
        if not self._following:
            return
        if not self._follow_initialized or self.app.animation_level == "none":
            self._follow_initialized = True
            self._set_follow_position(self.max_scroll_y)
        elif self.scroll_y < self.max_scroll_y:
            # The target is read on each tick so bursts of new text extend the
            # same motion rather than queuing or restarting scroll animations.
            if not self._follow_active:
                self._last_follow_frame = monotonic()
            self._follow_active = True
            self._follow_timer.resume()

    def _set_follow_position(self, position: float) -> None:
        self._following_update = True
        try:
            # Wheel/key input should start at the visible position, even while
            # automatic following is still catching up with a burst of output.
            self.scroll_target_y = position
            self.scroll_y = position
        finally:
            self._following_update = False

    def _advance_follow(self) -> None:
        if not self._following:
            self._follow_active = False
            self._follow_timer.pause()
            return
        now = monotonic()
        elapsed = now - self._last_follow_frame
        self._last_follow_frame = now
        distance = self.max_scroll_y - self.scroll_y
        if distance <= 0.25 or self.app.animation_level == "none":
            self._set_follow_position(self.max_scroll_y)
            self._follow_active = False
            self._follow_timer.pause()
        else:
            self._set_follow_position(
                self.scroll_y + distance * (1 - exp(-elapsed / 0.045))
            )

    def release_anchor(self) -> None:
        super().release_anchor()
        self._following = False

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if not self._following_update:
            if new_value >= self.max_scroll_y:
                self._following = True
            elif new_value < old_value:
                self._following = False

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if event.ctrl or event.shift:
            super()._on_mouse_scroll_up(event)
        elif self.allow_vertical_scroll and self._scroll_up_for_pointer(
            animate=True, duration=0.075, easing="out_cubic"
        ):
            event.stop()

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if event.ctrl or event.shift:
            super()._on_mouse_scroll_down(event)
        elif self.allow_vertical_scroll and self._scroll_down_for_pointer(
            animate=True, duration=0.075, easing="out_cubic"
        ):
            event.stop()

    @property
    def scroll_offset(self) -> Offset:
        # Keep short conversations at the top, including after content removal.
        offset = super().scroll_offset
        return Offset(offset.x, max(0, offset.y))
