from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Static

from ite.cloud import get_activity

WEEK_COUNT = 52
DAY_LABELS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
LABELED_WEEKDAYS = (1, 3, 5)
# Each cell occupies 1 column plus a 1-column gap on its trailing edge.
CELL_STRIDE = 2


class SettingsPanel(Widget):
    """In-shell settings view that replaces the chat feed and composer."""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="settings-content", classes="settings-content-shell"):
            yield Static("Settings", classes="settings-title")
            yield Static(
                "iTE activity — how active this account has been over the last year.",
                classes="settings-subtitle",
            )
            with Container(classes="settings-heatmap-panel"):
                yield Static(
                    "Loading iTE activity…",
                    id="settings-activity-status",
                    classes="settings-activity-status",
                )
                yield Vertical(id="settings-heatmap", classes="settings-heatmap")
                yield Static(
                    "",
                    id="settings-activity-summary",
                    classes="settings-activity-summary",
                )
            with Horizontal(classes="settings-actions"):
                yield Button("Back to chat", id="settings-back", variant="default")

    def on_mount(self) -> None:
        self.run_worker(self._load_activity(), exclusive=True)

    @on(Button.Pressed, "#settings-back")
    def on_back_pressed(self, _event: Button.Pressed) -> None:
        self.app.set_settings_active(False)

    async def _load_activity(self) -> None:
        try:
            payload = await asyncio.to_thread(get_activity, self.app.config)
        except Exception:
            payload = None

        status = self.query_one("#settings-activity-status", Static)
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list) or not events:
            status.update("No iTE activity recorded yet.")
            return

        status.display = False
        counts = self._count_events(events)
        await self._render_heatmap(counts)
        self._render_summary(counts)

    @staticmethod
    def _count_events(events: list[dict[str, Any]]) -> dict[date, int]:
        counts: dict[date, int] = defaultdict(int)
        for event in events:
            if not isinstance(event, dict):
                continue
            raw = event.get("createdAt")
            if not isinstance(raw, str):
                continue
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone()
            except ValueError:
                continue
            counts[parsed.date()] += 1
        return dict(counts)

    @staticmethod
    def _week_sundays(today: date) -> list[date]:
        days_since_sunday = (today.weekday() + 1) % 7
        current_sunday = today - timedelta(days=days_since_sunday)
        start = current_sunday - timedelta(weeks=WEEK_COUNT - 1)
        return [start + timedelta(weeks=index) for index in range(WEEK_COUNT)]

    @staticmethod
    def _level(count: int) -> int:
        if count <= 0:
            return 0
        if count == 1:
            return 1
        if count <= 3:
            return 2
        if count <= 6:
            return 3
        return 4

    @staticmethod
    def _month_header(sundays: list[date]) -> str:
        label_width = 4
        buffer = [" "] * (label_width + len(sundays) * CELL_STRIDE)
        previous_month: int | None = None
        for index, sunday in enumerate(sundays):
            if sunday.month == previous_month:
                continue
            offset = label_width + index * CELL_STRIDE
            name = sunday.strftime("%b")
            for char_index, char in enumerate(name):
                position = offset + char_index
                if position < len(buffer):
                    buffer[position] = char
            previous_month = sunday.month
        return "".join(buffer).rstrip()

    async def _render_heatmap(self, counts: dict[date, int]) -> None:
        today = date.today()
        sundays = self._week_sundays(today)
        container = self.query_one("#settings-heatmap", Vertical)
        await container.remove_children()

        await container.mount(
            Static(self._month_header(sundays), classes="heat-month-header")
        )

        grid = Horizontal(classes="heat-grid")
        await container.mount(grid)

        label_col = Vertical(classes="heat-weekday-labels")
        await grid.mount(label_col)
        for weekday in range(7):
            label = DAY_LABELS[weekday] if weekday in LABELED_WEEKDAYS else ""
            await label_col.mount(Static(label, classes="heat-weekday-label"))

        cell_cols = Vertical(classes="heat-cell-columns")
        await grid.mount(cell_cols)
        for weekday in range(7):
            row = Horizontal(classes="heat-row")
            await cell_cols.mount(row)
            cells = [
                Static(
                    "",
                    classes=self._cell_classes(
                        sunday + timedelta(days=weekday), counts, today
                    ),
                )
                for sunday in sundays
            ]
            await row.mount(*cells)

        legend = Horizontal(classes="heat-legend")
        await container.mount(legend)
        await legend.mount(Static("Less", classes="heat-legend-label"))
        for level in range(5):
            await legend.mount(Static("", classes=f"heat-cell heat-l{level}"))
        await legend.mount(Static("More", classes="heat-legend-label"))

    @classmethod
    def _cell_classes(
        cls, cell_date: date, counts: dict[date, int], today: date
    ) -> str:
        if cell_date > today:
            return "heat-cell heat-future"
        return f"heat-cell heat-l{cls._level(counts.get(cell_date, 0))}"

    def _render_summary(self, counts: dict[date, int]) -> None:
        summary = self.query_one("#settings-activity-summary", Static)
        total = sum(counts.values())
        active_days = sum(1 for count in counts.values() if count > 0)
        if total == 0:
            summary.update("No iTE activity recorded yet.")
            return
        busiest = max(counts, key=lambda day: counts[day])
        summary.update(
            f"{total} events · {active_days} active days · busiest {busiest.strftime('%b %-d')}"
        )
