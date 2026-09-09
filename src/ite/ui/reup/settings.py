from __future__ import annotations

import asyncio
import webbrowser
from datetime import date, datetime, timedelta

from textual import events, on
from textual.app import ComposeResult
from textual.containers import (
    Container,
    Horizontal,
    HorizontalScroll,
    Vertical,
    VerticalScroll,
)
from textual.message import Message
from rich.text import Text
from textual.widget import Widget
from textual.widgets import Button, Static

from ite.cloud import (
    get_activity,
    get_cloud_entitlements_result,
    get_usage_summary,
)

WEEK_COUNT = 52
DAY_LABELS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
LABELED_WEEKDAYS = (1, 3, 5)
# Each cell occupies 2 columns plus a 1-column gap on its trailing edge.
CELL_STRIDE = 3

# Info-row fields that open a picker — maps field name to an app method.
_ACTION_FIELDS = {
    "model": "_open_model_picker_from_meta",
    "provider": "_open_setup_modal",
    "approval": "_open_approval_picker_from_meta",
}


class HeatCell(Static):
    """A single heatmap day cell that opens a day-detail modal when clicked."""

    class Clicked(Message):
        """Posted when a heatmap cell is clicked."""

        def __init__(self, cell: HeatCell) -> None:
            super().__init__()
            self.cell = cell

    def __init__(self, cell_date: date, classes: str) -> None:
        super().__init__("", classes=classes)
        self.cell_date = cell_date

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Clicked(self))


class SettingsInfoRow(Horizontal):
    """A single key/value line in the session context block.

    When ``field`` names an action on the app, the whole row becomes
    clickable and posts a ``Pressed`` message.
    """

    class Pressed(Message):
        """Posted when a clickable info row is clicked."""

        def __init__(self, method: str) -> None:
            super().__init__()
            self.method = method

    def __init__(
        self,
        label: str,
        value: str,
        *,
        field: str | None = None,
    ) -> None:
        classes = "settings-info-row"
        if field is not None:
            classes += " settings-info-clickable"
        super().__init__(classes=classes)
        self._label = label
        self._field = field
        self._value_widget = Static(value, classes="settings-info-value")

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="settings-info-label")
        yield self._value_widget

    def update_value(self, value: str) -> None:
        self._value_widget.update(value)

    def on_click(self, event: events.Click) -> None:
        if self._field is None:
            return
        event.stop()
        self.post_message(self.Pressed(self._field))


class SettingsPanel(Widget):
    """In-shell settings view that replaces the chat feed and composer."""

    def compose(self) -> ComposeResult:
        with VerticalScroll(
            id="settings-content", classes="settings-content-shell"
        ):
            with Horizontal(classes="settings-header"):
                yield Button("Back to chat", id="settings-back", variant="default")
                yield Static("Settings", classes="settings-title")
                yield Static("", classes="settings-header-spacer")

            # Account profile
            with Container(classes="settings-account"):
                with Horizontal(classes="settings-account-row"):
                    self._account_avatar = Static("", classes="settings-avatar")
                    yield self._account_avatar
                    with Vertical(classes="settings-account-meta"):
                        self._account_name = Static("", classes="settings-account-name")
                        yield self._account_name
                        self._account_handle = Static(
                            "", classes="settings-account-handle"
                        )
                        yield self._account_handle

            # Usage limits
            yield Static("Usage limits", classes="settings-section-title")
            with Container(
                classes="settings-usage-card", id="settings-usage-card"
            ):
                with Horizontal(classes="settings-usage-head"):
                    with Vertical(classes="settings-usage-text"):
                        yield Static(
                            "5-hour usage limit",
                            classes="settings-usage-label",
                        )
                        self._usage_reset = Static(
                            "Resets soon", classes="settings-usage-reset"
                        )
                        yield self._usage_reset
                    self._usage_pct = Static("…", classes="settings-usage-pct")
                    yield self._usage_pct
                self._usage_bar = Static("", classes="settings-usage-bar")
                yield self._usage_bar

            # Your plan
            yield Static("Your plan", classes="settings-section-title")
            with Container(classes="settings-plan-card"):
                with Horizontal(classes="settings-plan-row"):
                    with Vertical(classes="settings-plan-text"):
                        self._plan_name = Static("—", classes="settings-plan-name")
                        yield self._plan_name
                        self._plan_tier = Static("—", classes="settings-plan-tier")
                        yield self._plan_tier
                    yield Button(
                        "Upgrade", id="settings-plan-action", variant="default"
                    )

            # Usage stats
            with Horizontal(classes="settings-stats-row"):
                self._stat_lifetime = Vertical(
                    classes="settings-stat-card settings-stat-lifetime"
                )
                self._stat_busiest = Vertical(
                    classes="settings-stat-card settings-stat-busiest"
                )
                self._stat_active = Vertical(
                    classes="settings-stat-card settings-stat-active"
                )
                self._stat_current = Vertical(
                    classes="settings-stat-card settings-stat-current"
                )
                self._stat_longest = Vertical(
                    classes="settings-stat-card settings-stat-longest"
                )
                for stat in (
                    self._stat_lifetime,
                    self._stat_busiest,
                    self._stat_active,
                    self._stat_current,
                    self._stat_longest,
                ):
                    yield stat

            # Session / user configuration (kept)
            with Vertical(classes="settings-info"):
                self._info_model = SettingsInfoRow("model", "…", field="model")
                self._info_provider = SettingsInfoRow(
                    "provider", "…", field="provider"
                )
                self._info_cwd = SettingsInfoRow("cwd", "…")
                self._info_approval = SettingsInfoRow(
                    "approval", "…", field="approval"
                )
                self._info_tools = SettingsInfoRow("tools", "…")
                self._info_agents = SettingsInfoRow("agents", "…")
                self._info_skills = SettingsInfoRow("skills", "…")
                yield self._info_model
                yield self._info_provider
                yield self._info_cwd
                yield self._info_approval
                yield self._info_tools
                yield self._info_agents
                yield self._info_skills

            # Token activity
            yield Static("Token activity", classes="settings-section-title")
            with Container(classes="settings-heatmap-panel"):
                yield Static(
                    "Loading iTE activity…",
                    id="settings-activity-status",
                    classes="settings-activity-status",
                )
                with HorizontalScroll(classes="heatmap-scroller"):
                    yield Vertical(id="settings-heatmap", classes="settings-heatmap")
                yield Horizontal(classes="heat-legend")

            # Sign out
            yield Static("Sign out", classes="settings-section-title")
            with Container(classes="settings-signout-card"):
                with Horizontal(classes="settings-signout-row"):
                    yield Static(
                        "Sign out of iTE Cloud. Your sessions stay on this device.",
                        classes="settings-signout-copy",
                    )
                    yield Button(
                        "Sign out", id="settings-signout", variant="default"
                    )

    def on_mount(self) -> None:
        self._populate_context()
        self.run_worker(self._load_activity(), exclusive=True)
        self.run_worker(self._load_account(), exclusive=False)

    def on_show(self) -> None:
        # The agent/session may not have been ready at mount time, and model
        # or approval can change while the panel is hidden. Refresh on open.
        self._populate_context()
        self.run_worker(self._load_account(), exclusive=False)

    @on(Button.Pressed, "#settings-back")
    def on_back_pressed(self, _event: Button.Pressed) -> None:
        self.app.set_settings_active(False)

    @on(Button.Pressed, "#settings-plan-action")
    def _on_plan_action_pressed(self, _event: Button.Pressed) -> None:
        opened = webbrowser.open("https://ite.kiishi.space/pricing")
        if opened:
            self.app.post_notice("Pricing", "Opened iTE Pro pricing in your browser.")
        else:
            self.app.post_notice(
                "Pricing",
                "Open https://ite.kiishi.space/pricing to start iTE Pro.",
            )

    @on(Button.Pressed, "#settings-signout")
    def _on_signout_pressed(self, _event: Button.Pressed) -> None:
        flow = getattr(self.app, "_run_cloud_logout_flow", None)
        if callable(flow):
            self.app.run_worker(flow(), exclusive=False)

    @on(events.Click, "#settings-usage-card")
    def _on_usage_card_clicked(self, event: events.Click) -> None:
        event.stop()
        opener = getattr(self.app, "_open_usage_modal_from_meta", None)
        if callable(opener):
            self.app.run_worker(opener(), exclusive=False)

    @on(SettingsInfoRow.Pressed)
    def _on_info_row_pressed(self, message: SettingsInfoRow.Pressed) -> None:
        method_name = _ACTION_FIELDS.get(message.method)
        if not method_name:
            return
        method = getattr(self.app, method_name, None)
        if callable(method):
            self.app.run_worker(method(), exclusive=False)

    def _populate_context(self) -> None:
        config = self.app.config

        # Model
        self._info_model.update_value(config.model_name)

        # Provider — best-effort friendly name from base_url.
        source_kind = (
            str(getattr(config.model, "source_kind", "") or "").strip().lower()
        )
        if source_kind == "bundled":
            provider = "iTE"
        else:
            provider = "local"
            base_url = str(config.base_url or "").strip().lower()
            if "openrouter.ai" in base_url:
                provider = "OpenRouter"
            elif "localhost:11434" in base_url or "127.0.0.1:11434" in base_url:
                provider = "Ollama"
            elif base_url:
                provider = base_url
        self._info_provider.update_value(provider)

        # CWD
        self._info_cwd.update_value(str(config.cwd))

        # Approval
        self._info_approval.update_value(config.approval.value)

        # Tools / agents / skills — best-effort from the live session.
        agent = getattr(self.app, "agent", None)
        if agent is not None and agent.session is not None:
            session = agent.session

            tools = session.tool_registry.get_tools()
            self._info_tools.update_value(
                ", ".join(t.name for t in tools[:3])
                + (f" +{len(tools) - 3} more" if len(tools) > 3 else "")
            )

            agent_names = [
                t.name.removeprefix("subagent_")
                for t in tools
                if t.name.startswith("subagent_")
            ]
            self._info_agents.update_value(
                ", ".join(agent_names[:3])
                + (f" +{len(agent_names) - 3} more" if len(agent_names) > 3 else "")
            )

            skills = session.list_available_skills()
            self._info_skills.update_value(
                ", ".join(s["name"] for s in skills[:3])
                + (f" +{len(skills) - 3} more" if len(skills) > 3 else "")
            )

    async def _load_account(self) -> None:
        """Load cloud account profile, plan state, and usage limits."""
        entitlements_result = None
        try:
            entitlements_result = await asyncio.to_thread(
                get_cloud_entitlements_result, self.app.config
            )
        except Exception:
            entitlements_result = None

        user = getattr(entitlements_result, "user", None) or {}
        entitlements = getattr(entitlements_result, "entitlements", None) or {}
        pro = bool(
            entitlements.get("proAccess")
            or entitlements.get("remoteCompanion")
            or entitlements.get("bundledInference")
        )
        if isinstance(user, dict):
            self._apply_account_profile(user)
        else:
            self._apply_local_profile()
        self._apply_plan_state(pro)

        summary = None
        try:
            summary = await asyncio.to_thread(get_usage_summary, self.app.config)
        except Exception:
            summary = None
        self._apply_usage_summary(summary)

    def _apply_account_profile(self, user: dict[str, object]) -> None:
        name = str(
            user.get("name")
            or user.get("username")
            or ""
        ).strip()
        email = str(user.get("email") or "").strip()
        if not name:
            name = email.split("@")[0] if email else "Local user"
        initial = name[:1].upper() or "?"
        self._account_avatar.update(initial)
        self._account_name.update(name)
        self._account_handle.update(email or "@local")

    def _apply_local_profile(self) -> None:
        self._account_avatar.update(
            self.app.config.model_name[:1].upper() or "?"
        )
        self._account_name.update(self.app.config.model_name or "iTE")
        self._account_handle.update("@local")

    def _apply_plan_state(self, pro: bool) -> None:
        if pro:
            self._plan_name.update("Pro plan")
            self._plan_tier.update("Pro")
        else:
            self._plan_name.update("Free plan")
            self._plan_tier.update("Free")

    def _apply_usage_summary(self, summary: dict[str, object] | None) -> None:
        if not isinstance(summary, dict):
            self._usage_pct.update("—")
            self._usage_bar.update("")
            self._usage_reset.update("Resets soon")
            return
        quotas = summary.get("quotas") or {}
        if not isinstance(quotas, dict):
            quotas = {}
        five_hour = quotas.get("fiveHour") or {}
        if not isinstance(five_hour, dict):
            five_hour = {}
        used = float(five_hour.get("usedUsdCents") or 0)
        cap = max(1.0, float(five_hour.get("capUsdCents") or 1))
        remaining = max(0, min(100, int(((cap - used) / cap) * 100)))
        self._usage_pct.update(f"{remaining}% left")
        self._usage_bar.update(self._build_usage_bar(remaining))
        reset_raw = str(
            five_hour.get("fullWindowClearAt") or five_hour.get("nextResetAt") or ""
        )
        self._usage_reset.update(self._format_reset(reset_raw))

    def _build_usage_bar(self, remaining_percent: int) -> Text:
        """Render the usage bar the same way the usage summary modal does."""
        from ite.ui.reup.app import ReupApp

        app = self.app
        styles = {}
        if isinstance(app, ReupApp):
            styles = app._render_styles()
        filled_color = styles.get("success", "#8AD4A1")
        empty_color = styles.get("disabled", "#3a3a3f")
        bar_width = self._usage_bar_width()
        used_percent = max(0, min(100, 100 - remaining_percent))
        filled = max(0, min(bar_width, round((used_percent / 100) * bar_width)))
        empty = max(0, bar_width - filled)
        line = Text()
        if filled:
            line.append("█" * filled, style=f"bold {filled_color}")
        if empty:
            line.append("█" * empty, style=empty_color)
        return line

    def _usage_bar_width(self) -> int:
        try:
            w = self._usage_bar.size.width
            if w > 0:
                return w
        except Exception:
            pass
        return 92

    @staticmethod
    def _format_reset(value: str) -> str:
        if value:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
                return f"Resets {dt.strftime('%a, %b %-d')}"
            except ValueError:
                pass
        return "Resets soon"

    async def _load_activity(self) -> None:
        try:
            payload = await asyncio.to_thread(get_activity, self.app.config)
        except Exception:
            payload = None

        status = self.query_one("#settings-activity-status", Static)
        daily_tokens = payload.get("dailyTokens") if isinstance(payload, dict) else None
        tokens = self._parse_daily_tokens(daily_tokens)
        self._apply_stats(tokens)
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

    def _apply_stats(self, tokens: dict[date, int]) -> None:
        today = date.today()
        active = {
            day: value
            for day, value in tokens.items()
            if day <= today and value > 0
        }

        lifetime = sum(active.values())
        self._stat_lifetime.remove_children()
        self._stat_lifetime.mount(
            Static(self._format_compact(lifetime), classes="settings-stat-value"),
            Static("Lifetime tokens", classes="settings-stat-label"),
        )

        busiest_day = max(active, key=active.get, default=None)
        busiest = active[busiest_day] if busiest_day else 0
        busiest_label = (
            busiest_day.strftime("%b %-d") if busiest_day else "—"
        )
        self._stat_busiest.remove_children()
        self._stat_busiest.mount(
            Static(busiest_label, classes="settings-stat-value"),
            Static("Busiest day", classes="settings-stat-label"),
        )

        self._stat_active.remove_children()
        self._stat_active.mount(
            Static(str(len(active)), classes="settings-stat-value"),
            Static("Active days", classes="settings-stat-label"),
        )

        current, longest = self._compute_streaks(active)
        self._stat_current.remove_children()
        self._stat_current.mount(
            Static(f"{current}d", classes="settings-stat-value"),
            Static("Current streak", classes="settings-stat-label"),
        )

        self._stat_longest.remove_children()
        self._stat_longest.mount(
            Static(f"{longest}d", classes="settings-stat-value"),
            Static("Longest streak", classes="settings-stat-label"),
        )

    @staticmethod
    def _compute_streaks(active: dict[date, int]) -> tuple[int, int]:
        if not active:
            return 0, 0
        days = sorted(active)
        longest = 1
        current = 0
        run = 1
        for index in range(1, len(days)):
            if (days[index] - days[index - 1]).days == 1:
                run += 1
            else:
                run = 1
            longest = max(longest, run)

        # Current streak: consecutive days ending today or yesterday.
        today = date.today()
        if today in active:
            cursor = today
        elif today - timedelta(days=1) in active:
            cursor = today - timedelta(days=1)
        else:
            cursor = None
        if cursor is not None:
            while cursor in active:
                current += 1
                cursor -= timedelta(days=1)
        return current, longest

    @staticmethod
    def _format_compact(value: int) -> str:
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.1f}B"
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return str(value)

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
        if tokens < 25_000_000:
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
        self._tokens = tokens
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
            cells: list[HeatCell] = []
            for sunday in sundays:
                cell_date = sunday + timedelta(days=weekday)
                cells.append(
                    HeatCell(
                        cell_date,
                        classes=self._cell_classes(cell_date, tokens, today),
                    )
                )
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

    @on(HeatCell.Clicked)
    def _on_heat_cell_clicked(self, message: HeatCell.Clicked) -> None:
        from ite.ui.reup.modals import DayActivityModal

        cell_date = message.cell.cell_date
        if cell_date > date.today():
            return
        tokens = getattr(self, "_tokens", {})
        self.app.push_screen(DayActivityModal(cell_date, tokens))
