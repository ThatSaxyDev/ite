from __future__ import annotations

import asyncio
from datetime import date, timedelta

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, HorizontalScroll, Vertical
from textual.widget import Widget
from textual.widgets import Button, Static

from ite.cloud import get_activity

WEEK_COUNT = 52
DAY_LABELS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
LABELED_WEEKDAYS = (1, 3, 5)
# Each cell occupies 2 columns plus a 1-column gap on its trailing edge.
CELL_STRIDE = 3


class SettingsPanel(Widget):
    """In-shell settings view that replaces the chat feed and composer."""

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-content", classes="settings-content-shell"):
            with Horizontal(classes="settings-header"):
                yield Button("Back to chat", id="settings-back", variant="default")
                yield Static("Settings", classes="settings-title")
            with Container(classes="settings-heatmap-panel"):
                yield Static(
                    "Loading iTE activity…",
                    id="settings-activity-status",
                    classes="settings-activity-status",
                )
                with HorizontalScroll(classes="heatmap-scroller"):
                    yield Vertical(id="settings-heatmap", classes="settings-heatmap")
                yield Horizontal(classes="heat-legend")

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
        daily_tokens = payload.get("dailyTokens") if isinstance(payload, dict) else None
        tokens = self._parse_daily_tokens(daily_tokens)
        if not tokens:
            status.update("No iTE activity recorded yet.")
            return

        status.display = False
        await self._render_heatmap(tokens)

    @staticmethod
    def _parse_daily_tokens(
        daily_tokens: dict[str, int] | None,
    ) -> dict[date, int]:
        tokens: dict[date, int] = {}
        if not isinstance(daily_tokens, dict):
            return tokens
        for raw, value in daily_tokens.items():
            if not isinstance(raw, str):
                continue
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                continue
            try:
                amount = int(value)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                tokens[day] = amount
        return tokens

    @staticmethod
    def _start_sunday(today: date) -> date:
        # Anchor the window to the month 11 months back so the header
        # begins on a clean month boundary (Oct last year when viewing in Sep).
        month_start = date(today.year, today.month, 1)
        total = month_start.year * 12 + (month_start.month - 1) - 11
        year, month_index = divmod(total, 12)
        start_month = date(year, month_index + 1, 1)
        days_to_sunday = (6 - start_month.weekday()) % 7
        return start_month + timedelta(days=days_to_sunday)

    @staticmethod
    def _week_sundays(today: date) -> list[date]:
        days_since_sunday = (today.weekday() + 1) % 7
        current_sunday = today - timedelta(days=days_since_sunday)
        start = SettingsPanel._start_sunday(today)
        weeks = (current_sunday - start).days // 7 + 1
        return [start + timedelta(weeks=index) for index in range(weeks)]

    @staticmethod
    def _level(tokens: int) -> int:
        if tokens <= 0:
            return 0
        if tokens < 100_000:
            return 1
        if tokens < 1_000_000:
            return 2
        if tokens < 10_000_000:
            return 3
        return 4

    @staticmethod
    def _month_header(sundays: list[date]) -> str:
        label_width = 4
        buffer = [" "] * (label_width + (len(sundays) + 1) * CELL_STRIDE)
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

    async def _render_heatmap(self, tokens: dict[date, int]) -> None:
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
                        sunday + timedelta(days=weekday), tokens, today
                    ),
                )
                for sunday in sundays
            ]
            await row.mount(*cells)

        legend = self.query_one(".heat-legend", Horizontal)
        await legend.remove_children()
        await legend.mount(Static("Less", classes="heat-legend-label"))
        for level in range(5):
            await legend.mount(Static("", classes=f"heat-cell heat-l{level}"))
        await legend.mount(Static("More", classes="heat-legend-label"))

    @classmethod
    def _cell_classes(
        cls, cell_date: date, tokens: dict[date, int], today: date
    ) -> str:
        if cell_date > today:
            return "heat-cell heat-future"
        return f"heat-cell heat-l{cls._level(tokens.get(cell_date, 0))}"

