from __future__ import annotations

import asyncio
import unittest

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from ite.ui.reup._streaming import StreamingMixin
from ite.ui.reup.assistant_typing import AssistantTypingBuffer
from ite.ui.reup.markdown_widget import CopyableMarkdown


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


class AssistantTypingTests(unittest.IsolatedAsyncioTestCase):
    async def test_network_bursts_pause_and_resume_without_losing_text(self):
        shown = []

        async def render(fragment):
            shown.append(fragment)

        buffer = AssistantTypingBuffer(render, interval=0.001)
        buffer.append("Hello")
        assert not shown
        await until(lambda: "".join(shown) == "Hello")
        assert not buffer._task.done()
        await asyncio.sleep(0.01)
        assert "".join(shown) == "Hello"
        buffer.append(" world 👋\n")
        await buffer.finish()
        assert "".join(shown) == "Hello world 👋\n"
        assert all(len(fragment) == 1 for fragment in shown)
        assert buffer._task.done()

    async def test_cancel_stops_queued_output_and_long_replies_catch_up(self):
        shown = []

        async def render(fragment):
            shown.append(fragment)

        buffer = AssistantTypingBuffer(render, interval=0.001)
        buffer.append("x" * 10000)
        await until(lambda: bool(shown))
        assert len(shown[0]) > 1
        await buffer.cancel()
        count = len(shown)
        await asyncio.sleep(0.01)
        assert len(shown) == count
        assert buffer.revealed < len(buffer.received)
        assert buffer._task.done()
        other = AssistantTypingBuffer(render, interval=0.001)
        shown.clear()
        other.append("text\n" * 1000)
        await other.finish()
        assert "".join(shown) == "text\n" * 1000


class TypingTestApp(StreamingMixin, App):
    def __init__(self):
        super().__init__()
        self._streaming_widget = None
        self._streaming_buffer = ""
        self._message_count = 0

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="conversation")

    def _refresh_empty_state(self):
        pass

    async def _pin_activity_indicator_to_end(self):
        pass


class MountedTypingTests(unittest.IsolatedAsyncioTestCase):
    async def test_interrupt_flushes_received_text_and_next_segment_is_independent(
        self,
    ):
        app = TypingTestApp()
        async with app.run_test() as pilot:
            received = "Interrupted response " * 100
            await app.stream_assistant_delta(received)
            first = app._streaming_widget.query_one(CopyableMarkdown)
            clock = first._typing
            await app.finalize_streaming_message(animate=False)
            assert first.source == received
            assert clock._task.done()
            await app.stream_assistant_delta("Next segment.")
            await app.finalize_streaming_message()
            await pilot.pause()
            assert first.source == received
            assert len(app.query(".assistant")) == 2

    async def test_removing_widget_during_completion_does_not_cancel_the_turn(self):
        app = TypingTestApp()
        async with app.run_test() as pilot:
            await app.stream_assistant_delta("An outgoing thread's reply " * 20)
            container = app._streaming_widget
            widget = container.query_one(CopyableMarkdown)
            clock = widget._typing
            complete = asyncio.create_task(app.finalize_streaming_message())
            await until(lambda: clock._finished)
            await container.remove()
            await complete
            await pilot.pause()
            assert clock._task.done()
            assert not complete.cancelled()

    async def test_mounted_chat_burst_is_revealed_over_time_and_final_markdown_is_exact(
        self,
    ):
        app = TypingTestApp()
        async with app.run_test() as pilot:
            text = (
                "A smooth reply with **emphasis** and `identifiers`.\n"
                "\n```python\nvalue = 1\nprint(value)\n```\n"
            )
            await app.stream_assistant_delta(text)
            widget = app._streaming_widget.query_one(CopyableMarkdown)
            await until(lambda: bool(widget.source))
            assert len(widget.source) < len(text)
            await until(lambda: widget.source == text)
            assert widget._typing is not None
            assert not widget._typing._task.done()
            await app.stream_assistant_delta("\nSecond burst after a pause.")
            await app.finalize_streaming_message(text + "\nSecond burst after a pause.")
            await pilot.pause()
            assert widget.source == text + "\nSecond burst after a pause."
            assert widget._typing is None
            assert app._streaming_widget is None
            assert len(app.query(".assistant")) == 1

    async def test_final_correction_discards_old_queue_and_unmount_stops_display_clock(
        self,
    ):
        app = TypingTestApp()
        async with app.run_test() as pilot:
            await app.stream_assistant_delta("Old answer " * 100)
            widget = app._streaming_widget.query_one(CopyableMarkdown)
            clock = widget._typing
            await app.finalize_streaming_message("Corrected answer.")
            await pilot.pause()
            assert widget.source == "Corrected answer."
            assert clock._task.done()
            await app.stream_assistant_delta("Another answer " * 100)
            widget = app._streaming_widget.query_one(CopyableMarkdown)
            clock = widget._typing
            await widget.remove()
            await pilot.pause()
            assert clock._task.done()
