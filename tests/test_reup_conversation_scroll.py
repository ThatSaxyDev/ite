from __future__ import annotations

import asyncio
import unittest

from textual import events
from textual.app import App, ComposeResult
from textual.widgets import Static

from ite.ui.reup._streaming import StreamingMixin
from ite.ui.reup.app import ReupApp
from ite.ui.reup.widgets.conversation import ConversationScroll


class ConversationTestApp(StreamingMixin, App):
    CSS = """
    ConversationScroll { height: 1fr; }
    ConversationScroll > * { height: auto; }
    """

    _pin_activity_indicator_to_end = ReupApp._pin_activity_indicator_to_end

    def __init__(self, activity: bool) -> None:
        super().__init__()
        self._hydrating_from_snapshot = False
        self._streaming_buffer = ""
        self._streaming_widget = None
        self._message_count = 0
        self._activity_widget = Static("Working…") if activity else None

    def compose(self) -> ComposeResult:
        with ConversationScroll(id="conversation"):
            yield Static("\n".join(f"Earlier message {i}" for i in range(60)))
            if self._activity_widget is not None:
                yield self._activity_widget

    def _refresh_empty_state(self) -> None:
        pass


class ConversationScrollTests(unittest.TestCase):
    def test_streaming_respects_manual_scroll_and_resumes_at_bottom(self) -> None:
        async def check(activity: bool, mouse: bool) -> None:
            app = ConversationTestApp(activity)
            async with app.run_test(size=(80, 20)) as pilot:
                feed = app.query_one(ConversationScroll)
                await pilot.pause()
                self.assertGreater(feed.max_scroll_y, 0)
                self.assertEqual(feed.scroll_y, feed.max_scroll_y)

                await app.stream_assistant_delta("First paragraph.\n\n")
                await pilot.pause()
                self.assertEqual(feed.scroll_y, feed.max_scroll_y)

                if mouse:
                    feed.post_message(events.MouseScrollUp(
                        feed, 1, 1, 0, -1, 0, False, False, False
                    ))
                else:
                    feed.focus()
                    await pilot.press("pageup")
                await pilot.pause()
                position = feed.scroll_y
                self.assertLess(position, feed.max_scroll_y)

                for i in range(3):
                    await app.stream_assistant_delta(f"More content {i}.\n\n" * 5)
                    await pilot.pause()
                    self.assertEqual(feed.scroll_y, position)
                    if activity:
                        self.assertIs(feed.children[-1], app._activity_widget)
                await app.finalize_streaming_message()
                await pilot.pause()
                self.assertEqual(feed.scroll_y, position)

                # Ordinary scrolling back to the bottom restores following.
                feed.scroll_to(y=feed.max_scroll_y, animate=False)
                await pilot.pause()
                await app.stream_assistant_delta("Another response.\n\n" * 10)
                await pilot.pause()
                self.assertEqual(feed.scroll_y, feed.max_scroll_y)

                # Loading a conversation intentionally resets to its latest message.
                feed.scroll_home(animate=False)
                await pilot.pause()
                feed.scroll_end(animate=False)
                await pilot.pause()
                await app.stream_assistant_delta("After loading.\n\n" * 10)
                await pilot.pause()
                self.assertEqual(feed.scroll_y, feed.max_scroll_y)

        for activity in (False, True):
            for mouse in (False, True):
                with self.subTest(activity=activity, mouse=mouse):
                    asyncio.run(check(activity, mouse))
