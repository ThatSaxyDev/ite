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

    class OpenSettings(Message):
        """Posted when the user opens the settings screen."""

        def __init__(self) -> None:
            super().__init__()

    def __init__(
        self,
        *,
        threads: list[tuple[str, str, str, str]],
        email: str = "",
        image: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._threads = threads
        self._row_widgets: dict[str, ThreadSwitcherRow] = {}
        self._row_snapshot: tuple[tuple[str, str, str], ...] = ()
        self._account_email = email
        self._account_image = image

    def compose(self) -> ComposeResult:
        with Horizontal(classes="thread-switcher-header"):
            yield Button(
                "Settings",
                id="thread-switcher-settings",
                classes="thread-switcher-title",
            )
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
        status = Static("", id="thread-switcher-history-status")
        status.display = False
        yield status
        yield VerticalScroll(id="thread-switcher-list", classes="thread-switcher-list")
        with Horizontal(id="thread-switcher-account-footer", classes="thread-switcher-account"):
            yield Static("", id="thread-switcher-account-icon", classes="thread-switcher-account-icon")
            yield Static("", id="thread-switcher-account-email", classes="thread-switcher-account-email")

    async def on_mount(self) -> None:
        await self.refresh_threads(self._threads)
        self._update_account_footer()

    def refresh_account_info(self, email: str, image: str | None) -> None:
        self._account_email = email
        self._account_image = image
        if self.is_mounted:
            self._update_account_footer()

    def set_history_status(self, text: str) -> None:
        status = self.query_one("#thread-switcher-history-status", Static)
        status.update(text)
        status.display = bool(text)

    def _update_account_footer(self) -> None:
        try:
            footer = self.query_one("#thread-switcher-account-footer", Horizontal)
            icon = self.query_one("#thread-switcher-account-icon", Static)
            email_label = self.query_one("#thread-switcher-account-email", Static)
        except Exception:
            return
        email = (self._account_email or "").strip()
        if not email:
            footer.display = False
            return
        footer.display = True
        initial = email[0].upper()
        icon.update(initial)
        email_label.update(self._ellipsize(email, self.MAX_LABEL_CELLS))

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
            next_id_set = set(next_ids)
            removed = [
                widget for session_id, widget in self._row_widgets.items()
                if session_id not in next_id_set
            ]
            if removed:
                await thread_list.remove_children(removed)
            for session_id in list(self._row_widgets):
                if session_id not in next_id_set:
                    del self._row_widgets[session_id]
            added = []
            for session_id, label, classes in rows:
                if session_id not in self._row_widgets:
                    widget = ThreadSwitcherRow(
                        label,
                        session_id=session_id,
                        id=f"thread-switcher-row-{session_id}",
                        classes=classes,
                    )
                    self._row_widgets[session_id] = widget
                    added.append(widget)
            if added:
                await thread_list.mount(*added)
            current_ids = [sid for sid in previous_ids if sid in next_id_set]
            current_ids.extend(widget.session_id for widget in added)
            for index, session_id in enumerate(next_ids):
                if current_ids[index] != session_id:
                    thread_list.move_child(
                        self._row_widgets[session_id],
                        before=self._row_widgets[current_ids[index]],
                    )
                    current_ids.remove(session_id)
                    current_ids.insert(index, session_id)
        previous_by_id = {
            session_id: (label, classes)
            for session_id, label, classes in self._row_snapshot
        }
        for session_id, label, classes in rows:
            widget = self._row_widgets.get(session_id)
            if widget is None or session_id not in previous_by_id:
                continue
            previous_label, previous_classes = previous_by_id[session_id]
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
        if event.button.id == "thread-switcher-settings":
            event.stop()
            self.post_message(self.OpenSettings())
            return
        if event.button.id == "thread-switcher-new-chat":
            event.stop()
            self.app.run_worker(self.app.start_new_thread(), exclusive=False)
