from __future__ import annotations

import re
from typing import Any

from rich.cells import cell_len
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static


class ThreadSwitcherRow(Static):
    class Selected(Message):
        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    def __init__(
        self,
        renderable: Any = "",
        *,
        session_id: str,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(renderable, id=id, classes=classes)
        self.session_id = session_id

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Selected(self.session_id))


class ThreadSwitcherSidePanel(Widget):
    ALLOW_MAXIMIZE = False
    MAX_LABEL_CELLS = 24

    def __init__(
        self,
        *,
        threads: list[tuple[str, str, str, str]],
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._threads = threads
        self._row_widgets: dict[str, ThreadSwitcherRow] = {}
        self._row_snapshot: tuple[tuple[str, str, str], ...] = ()

    def compose(self) -> ComposeResult:
        with Horizontal(classes="thread-switcher-header"):
            yield Static("Threads", classes="thread-switcher-title")
            yield Button(
                "Close",
                id="thread-switcher-close",
                classes="thread-switcher-close",
            )
        yield Button(
            "New chat",
            id="thread-switcher-new-chat",
            classes="thread-switcher-new-chat",
        )
        yield VerticalScroll(id="thread-switcher-list", classes="thread-switcher-list")

    async def on_mount(self) -> None:
        await self.refresh_threads(self._threads)

    async def refresh_threads(self, threads: list[tuple[str, str, str, str]]) -> None:
        self._threads = threads
        try:
            thread_list = self.query_one("#thread-switcher-list", VerticalScroll)
        except Exception:
            return
        if not thread_list.is_attached:
            return
        rows: list[tuple[str, str, str]] = []
        for session_id, title, state, source in threads:
            classes = "thread-switcher-item"
            if state == "current":
                classes += " current"
            elif state == "running":
                classes += " live"
            elif source == "saved":
                classes += " saved"
            label = self._thread_label(title, state)
            rows.append((session_id, label, classes))
        snapshot = tuple(rows)
        if snapshot == self._row_snapshot:
            return
        previous_ids = [row[0] for row in self._row_snapshot]
        next_ids = [row[0] for row in snapshot]
        if previous_ids != next_ids:
            await thread_list.remove_children()
            self._row_widgets = {}
            for session_id, label, classes in rows:
                widget = ThreadSwitcherRow(
                    label,
                    session_id=session_id,
                    id=f"thread-switcher-row-{session_id}",
                    classes=classes,
                )
                self._row_widgets[session_id] = widget
                await thread_list.mount(widget)
            self._row_snapshot = snapshot
            return
        previous_by_id = {
            session_id: (label, classes)
            for session_id, label, classes in self._row_snapshot
        }
        for session_id, label, classes in rows:
            widget = self._row_widgets.get(session_id)
            if widget is None:
                continue
            previous_label, previous_classes = previous_by_id.get(session_id, ("", ""))
            if label != previous_label:
                widget.update(label)
            if classes != previous_classes:
                widget.remove_class("current")
                widget.remove_class("live")
                widget.remove_class("saved")
                for class_name in classes.split():
                    if class_name != "thread-switcher-item":
                        widget.add_class(class_name)
        self._row_snapshot = snapshot

    @classmethod
    def _ellipsize(cls, text: str, max_cells: int) -> str:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if cell_len(text) <= max_cells:
            return text
        if max_cells <= 3:
            return "." * max_cells
        output = ""
        for char in text:
            if cell_len(output + char + "...") > max_cells:
                break
            output += char
        return output.rstrip() + "..."

    @classmethod
    def _thread_label(cls, title: str, state: str) -> str:
        if state == "running":
            prefix = "●●● "
            return prefix + cls._ellipsize(
                title, cls.MAX_LABEL_CELLS - cell_len(prefix)
            )
        return cls._ellipsize(title, cls.MAX_LABEL_CELLS)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "thread-switcher-close":
            event.stop()
            self.app.run_worker(self.app._hide_thread_switcher_panel(), exclusive=False)
            return
        if event.button.id == "thread-switcher-new-chat":
            event.stop()
            self.app.run_worker(self.app.start_new_thread(), exclusive=False)
