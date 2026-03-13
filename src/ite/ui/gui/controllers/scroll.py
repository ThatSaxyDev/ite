from __future__ import annotations
import asyncio
import flet as ft


class ScrollControllerMixin:
    def _on_chat_scroll(self, e: ft.OnScrollEvent):
        # Only auto-scroll while user is near the bottom.
        distance_to_bottom = max(e.max_scroll_extent - e.pixels, 0)
        self._auto_scroll_enabled = distance_to_bottom <= 96

    def _scroll_chat_to_bottom(self, animate: bool = True, force: bool = False):
        if not self.messages_column or not self.page:
            return
        if not force and not self._auto_scroll_enabled:
            return
        try:
            self._scroll_request_id += 1
            request_id = self._scroll_request_id
            self.page.run_task(self._scroll_chat_to_bottom_async, animate, force, request_id)
        except Exception:
            pass

    async def _scroll_chat_to_bottom_async(
        self,
        animate: bool = True,
        force: bool = False,
        request_id: int = 0,
    ):
        if not self.messages_column:
            return
        try:
            if force:
                self._auto_scroll_enabled = True
            duration = 120 if animate else 0
            # Multi-pass snap: repeated end-offset scroll is more stable here than anchor or giant offsets.
            for delay in (0.0, 0.03, 0.08, 0.16):
                if request_id and request_id != self._scroll_request_id:
                    return
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    await self.messages_column.scroll_to(
                        offset=-1,
                        duration=duration,
                        curve=ft.AnimationCurve.EASE_OUT_CUBIC,
                    )
                except TypeError:
                    await self.messages_column.scroll_to(offset=-1, duration=duration)
        except Exception:
            pass
