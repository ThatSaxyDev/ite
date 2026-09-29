from __future__ import annotations

import asyncio
import sys
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

from ite import __version__
from ite.cloud import (
    get_activity,
    get_cloud_entitlements_result,
    get_usage_summary,
)
from ite.skills.manager import SkillManager
from ite.skills.trust import SkillTrustManager
from ite.tools.registry import create_default_registry, refresh_subagent_tools

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
        multiline: bool = False,
    ) -> None:
        classes = "settings-info-row"
        if field is not None:
            classes += " settings-info-clickable"
        if multiline:
            classes += " settings-info-multiline"
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


class UsageLimitCard(Container):
    """The usage-limits card. Clicking anywhere on it opens the usage modal."""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        opener = getattr(self.app, "_open_usage_modal_from_meta", None)
        if callable(opener):
            self.app.run_worker(opener(), exclusive=False)


class FooterLink(Static):
    """A compact text link used by the application footer."""

    def __init__(self, label: str, url: str) -> None:
        super().__init__(label, classes="app-footer-link")
        self.url = url


class AppFooter(Vertical):
    """Compact author, product, and social links shared across app surfaces."""

    PORTFOLIO_URL = "https://kiishi.space"
    GITHUB_URL = "https://github.com/ThatSaxyDev/ite"
    LINKEDIN_URL = "https://www.linkedin.com/in/david-dedeke-382915281"
    ITE_X_URL = "https://x.com/itetheagent"

    @on(events.Click, ".app-footer-link")
    def _on_footer_link_clicked(self, event: events.Click) -> None:
        url = getattr(event.control, "url", None)
        if not isinstance(url, str):
            return
        opened = webbrowser.open(url)
        if opened:
            self.app.post_notice("iTE", "Opened link in your browser.")
        else:
            self.app.post_notice("iTE", f"Open {url} in your browser.")

    def compose(self) -> ComposeResult:
        year = date.today().year
        with Horizontal(classes="app-footer-credit"):
            yield Static("Built by ", classes="app-footer-text")
            yield FooterLink("Kiishi David", self.PORTFOLIO_URL)
            yield Static(f" · © {year} · v{__version__}", classes="app-footer-text")
        with Horizontal(classes="app-footer-links"):
            yield FooterLink("GitHub", self.GITHUB_URL)
            yield Static(" · ", classes="app-footer-text")
            yield FooterLink("LinkedIn", self.LINKEDIN_URL)
            yield Static(" · ", classes="app-footer-text")
            yield FooterLink("iTE on X", self.ITE_X_URL)


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
                    self._account_action = Button(
                        "Sign in", id="settings-sign-in", variant="primary"
                    )
                    yield self._account_action

            # Usage limits
            yield Static(
                "Usage limits",
                id="settings-usage-title",
                classes="settings-section-title",
            )
            with UsageLimitCard(
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
                with Horizontal(classes="settings-usage-head settings-usage-head-secondary"):
                    with Vertical(classes="settings-usage-text"):
                        yield Static(
                            "7-day usage limit",
                            classes="settings-usage-label",
                        )
                        self._seven_day_usage_reset = Static(
                            "Resets soon", classes="settings-usage-reset"
                        )
                        yield self._seven_day_usage_reset
                    self._seven_day_usage_pct = Static(
                        "…", classes="settings-seven-day-usage-pct"
                    )
                    yield self._seven_day_usage_pct
                self._seven_day_usage_bar = Static(
                    "", classes="settings-usage-bar"
                )
                yield self._seven_day_usage_bar

            # Your plan
            yield Static(
                "Your plan",
                id="settings-plan-title",
                classes="settings-section-title",
            )
            with Container(classes="settings-plan-card", id="settings-plan-card"):
                with Horizontal(classes="settings-plan-row"):
                    with Vertical(classes="settings-plan-text"):
                        self._plan_name = Static("—", classes="settings-plan-name")
                        yield self._plan_name
                    self._plan_action = Button(
                        "Upgrade", id="settings-plan-action", variant="default"
                    )
                    yield self._plan_action

            # Usage stats
            with Horizontal(
                classes="settings-stats-row", id="settings-stats-row"
            ):
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

            # Activity locked behind Pro (hidden for Pro users)
            with Container(
                id="settings-activity-locked", classes="settings-activity-locked"
            ):
                yield Static(
                    "Unlock streaks and activity tracker by subscribing for the Pro plan.",
                    id="settings-activity-locked-copy",
                    classes="settings-activity-locked-copy",
                )

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
                self._info_tools = SettingsInfoRow("tools", "…", multiline=True)
                self._info_agents = SettingsInfoRow("agents", "…", multiline=True)
                self._info_skills = SettingsInfoRow("skills", "…", multiline=True)
                yield self._info_model
                yield self._info_provider
                yield self._info_cwd
                yield self._info_approval
                yield self._info_tools
                yield self._info_agents
                yield self._info_skills

            # Token activity
            yield Static(
                "Token activity",
                id="settings-activity-title",
                classes="settings-section-title",
            )
            with Container(
                classes="settings-heatmap-panel", id="settings-activity-panel"
            ):
                yield Static(
                    "Loading iTE activity…",
                    id="settings-activity-status",
                    classes="settings-activity-status",
                )
                with HorizontalScroll(classes="heatmap-scroller"):
                    yield Vertical(id="settings-heatmap", classes="settings-heatmap")
                yield Horizontal(classes="heat-legend")

            # Open Island is device-local and therefore available regardless
            # of the user's Cloud sign-in state.
            yield Static(
                "Open Island",
                id="settings-open-island-title",
                classes="settings-section-title",
            )
            with Container(
                classes="settings-open-island-card",
                id="settings-open-island-card",
            ):
                with Horizontal(classes="settings-open-island-row"):
                    self._open_island_status = Static(
                        "",
                        classes="settings-open-island-copy",
                    )
                    yield self._open_island_status
                    self._open_island_action = Button(
                        "Turn on",
                        id="settings-open-island-action",
                        variant="default",
                    )
                    yield self._open_island_action

            # Sign out
            yield Static(
                "Sign out",
                id="settings-signout-title",
                classes="settings-section-title",
            )
            with Container(
                classes="settings-signout-card", id="settings-signout-card"
            ):
                with Horizontal(classes="settings-signout-row"):
                    yield Static(
                        "Sign out of iTE Cloud. Your sessions stay on this device.",
                        classes="settings-signout-copy",
                    )
                    yield Button(
                        "Sign out", id="settings-signout", variant="default"
                    )

            # Footer
            yield AppFooter(classes="settings-footer")

    def on_mount(self) -> None:
        self._account_action.display = False
        self._populate_context()
        self.refresh_open_island_state()
        self.refresh_cloud_data()

    def on_show(self) -> None:
        # The agent/session may not have been ready at mount time, and model
        # or approval can change while the panel is hidden. Refresh on open.
        self._populate_context()
        self.refresh_open_island_state()
        self.refresh_cloud_data()

    def refresh_cloud_data(self) -> None:
        """Refresh settings data without allowing one request to cancel another."""
        self.run_worker(
            self._load_account(), group="settings-account", exclusive=True
        )
        self.run_worker(
            self._load_activity(), group="settings-activity", exclusive=True
        )

    def on_resize(self, _event: events.Resize) -> None:
        """Re-render the usage bar so it always fills the card width."""
        remaining = getattr(self, "_usage_remaining", None)
        if remaining is None:
            return
        bar = getattr(self, "_usage_bar", None)
        if bar is None:
            return
        bar.update(self._build_usage_bar(remaining, bar))
        seven_day_remaining = getattr(self, "_seven_day_usage_remaining", None)
        seven_day_bar = getattr(self, "_seven_day_usage_bar", None)
        if seven_day_remaining is not None and seven_day_bar is not None:
            seven_day_bar.update(
                self._build_usage_bar(seven_day_remaining, seven_day_bar)
            )

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

    @on(Button.Pressed, "#settings-sign-in")
    def _on_sign_in_pressed(self, _event: Button.Pressed) -> None:
        self.app.set_settings_active(False)
        flow = getattr(self.app, "_run_cloud_login_flow", None)
        if callable(flow):
            self.app.run_worker(flow(), exclusive=False)

    @on(Button.Pressed, "#settings-open-island-action")
    async def _on_open_island_action_pressed(self, _event: Button.Pressed) -> None:
        toggle = getattr(self.app, "_set_open_island_enabled", None)
        if not callable(toggle):
            return
        enabled = bool(self.app.config.integrations.open_island.enabled)
        self._open_island_action.disabled = True
        try:
            await toggle(not enabled)
        finally:
            self._open_island_action.disabled = False
            self.refresh_open_island_state()

    @on(Button.Pressed, "#settings-signout")
    def _on_signout_pressed(self, _event: Button.Pressed) -> None:
        flow = getattr(self.app, "_run_cloud_logout_flow", None)
        if callable(flow):
            self.app.run_worker(flow(), exclusive=False)

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

        # Tools / agents / skills — always populated, with a live-session
        # preference and a config-only fallback when no session exists yet.
        tool_names, agent_names, skill_names = self._collect_capabilities()
        self._info_tools.update_value(self._format_capability_list(tool_names))
        self._info_agents.update_value(self._format_capability_list(agent_names))
        self._info_skills.update_value(self._format_capability_list(skill_names))

    def refresh_open_island_state(self) -> None:
        """Render the local Open Island preference and its single action."""
        enabled = bool(self.app.config.integrations.open_island.enabled)
        if enabled:
            if sys.platform == "darwin":
                self._open_island_status.update(
                    "Notifications are on. iTE activity and approval requests can appear in Open Island."
                )
            else:
                self._open_island_status.update(
                    "Notifications are on. Open Island notifications are available on macOS only."
                )
            self._open_island_action.label = "Turn off"
        else:
            self._open_island_status.update(
                "Notifications are off. Turn them on to mirror iTE activity in Open Island."
            )
            self._open_island_action.label = "Turn on"

    def _collect_capabilities(self) -> tuple[list[str], list[str], list[str]]:
        """Return (tools, agents, skills) names, preferring the live session."""
        agent = getattr(self.app, "agent", None)
        session = getattr(agent, "session", None)
        if session is not None:
            try:
                tools = session.tool_registry.get_tools()
            except Exception:
                tools = []
            else:
                return (
                    [t.name for t in tools],
                    [
                        t.name.removeprefix("subagent_")
                        for t in tools
                        if t.name.startswith("subagent_")
                    ],
                    [s["name"] for s in session.list_available_skills()],
                )

        config = self.app.config
        try:
            registry = create_default_registry(config)
            refresh_subagent_tools(registry, config, log_errors=False)
            tools = registry.get_tools()
        except Exception:
            tools = []
        try:
            skill_manager = SkillManager(
                config.cwd, trust_manager=SkillTrustManager()
            )
            skill_manager.discover()
            skills = [s["name"] for s in skill_manager.summaries()]
        except Exception:
            skills = []
        return (
            [t.name for t in tools],
            [
                t.name.removeprefix("subagent_")
                for t in tools
                if t.name.startswith("subagent_")
            ],
            skills,
        )

    @staticmethod
    def _format_capability_list(names: list[str]) -> str:
        if not names:
            return "—"
        shown = names[:20]
        suffix = f" +{len(names) - len(shown)} more" if len(names) > len(shown) else ""
        return ", ".join(shown) + suffix

    async def _load_account(self) -> None:
        """Load cloud account profile, plan state, and usage limits."""
        app = self.app
        signed_out = bool(getattr(app, "_cloud_signed_out", True))
        cached_user: dict[str, object] | None = None
        email = getattr(app, "_cloud_user_email", None)
        name = getattr(app, "_cloud_user_name", None)
        if email or name:
            cached_user = {"name": name or "", "email": email or ""}
        cached_pro = getattr(app, "_account_plan_is_pro", None)
        cached_summary = getattr(app, "_usage_summary_cache", None)

        if signed_out:
            self._apply_signed_out_profile()
            self._apply_usage_summary(None)
            return

        # Render the last verified state first. A later request can refresh it,
        # but a temporary network failure must not erase it.
        if cached_user is not None:
            self._apply_account_profile(cached_user)
        if isinstance(cached_pro, bool):
            self._apply_plan_state(cached_pro)
        if isinstance(cached_summary, dict):
            self._apply_usage_summary(cached_summary)

        try:
            entitlements_result = await asyncio.to_thread(
                get_cloud_entitlements_result, app.config
            )
        except Exception:
            entitlements_result = None

        auth_valid = bool(
            entitlements_result
            and getattr(getattr(entitlements_result, "auth", None), "is_valid", False)
        )
        metadata_available = bool(
            entitlements_result
            and getattr(entitlements_result, "metadata_available", True)
        )
        if auth_valid and metadata_available:
            candidate = getattr(entitlements_result, "user", None)
            if isinstance(candidate, dict) and (
                candidate.get("email") or candidate.get("name")
            ):
                self._cache_cloud_user(candidate)
                self._apply_account_profile(candidate)
            elif cached_user is None:
                self._apply_account_profile(
                    {"name": "Account profile unavailable", "email": ""}
                )

            entitlements = getattr(entitlements_result, "entitlements", None) or {}
            pro = bool(
                entitlements.get("proAccess")
                or entitlements.get("remoteCompanion")
                or entitlements.get("bundledInference")
            )
            self._cache_plan_state(pro)
            self._apply_plan_state(pro)
        else:
            if cached_user is None:
                self._apply_unavailable_profile()
            if not isinstance(cached_pro, bool):
                self._apply_plan_state(None)

        summary = cached_summary if isinstance(cached_summary, dict) else None
        try:
            refreshed_summary = await asyncio.to_thread(get_usage_summary, app.config)
        except Exception:
            refreshed_summary = None
        if isinstance(refreshed_summary, dict):
            summary = refreshed_summary
            self._cache_usage_summary(summary)
        self._apply_usage_summary(summary)

    def _cache_cloud_user(self, user: dict[str, object]) -> None:
        cache_user = getattr(self.app, "_set_cloud_user_profile", None)
        if callable(cache_user):
            cache_user(user)
            return
        self.app._cloud_user_email = str(user.get("email") or "") or None
        self.app._cloud_user_name = str(user.get("name") or "") or None

    def _cache_plan_state(self, pro: bool) -> None:
        cache_plan = getattr(self.app, "_set_account_plan_badge_state", None)
        if callable(cache_plan):
            cache_plan(pro)
            return
        self.app._account_plan_is_pro = pro

    def _cache_usage_summary(self, summary: dict[str, object]) -> None:
        cache_summary = getattr(self.app, "_set_usage_summary_cache", None)
        if callable(cache_summary):
            cache_summary(summary)
            return
        self.app._usage_summary_cache = summary

    def _apply_account_profile(self, user: dict[str, object]) -> None:
        name = str(user.get("name") or "").strip()
        email = str(user.get("email") or "").strip()
        if not name:
            name = email.split("@")[0] if email else "Signed in"
        initial = name[:1].upper() or "?"
        self._account_avatar.update(initial)
        self._account_name.update(name)
        self._account_handle.update(email or "@cloud")
        self._account_action.display = False
        self._set_signed_in_sections_visible(True)

    def _apply_signed_out_profile(self) -> None:
        self._account_avatar.update("?")
        self._account_name.update("Not signed in")
        self._account_handle.update("Sign in to enable iTE Cloud")
        self._account_action.display = True
        self._set_signed_in_sections_visible(False)

    def _apply_unavailable_profile(self) -> None:
        """Show an honest state while cloud metadata is unavailable."""
        self._account_avatar.update("?")
        self._account_name.update("Account details unavailable")
        self._account_handle.update("Could not verify iTE Cloud account")
        self._account_action.display = False
        self._set_signed_in_sections_visible(True)

    def _set_signed_in_sections_visible(self, visible: bool) -> None:
        self.query_one("#settings-usage-title").display = visible
        self.query_one("#settings-usage-card").display = visible
        self.query_one("#settings-plan-title").display = visible
        self.query_one("#settings-plan-card").display = visible
        self.query_one("#settings-signout-title").display = visible
        self.query_one("#settings-signout-card").display = visible
        if not visible:
            self.query_one("#settings-stats-row").display = False
            self.query_one("#settings-activity-title").display = False
            self.query_one("#settings-activity-panel").display = False
            self.query_one("#settings-activity-locked").display = False

    def _apply_plan_state(self, pro: bool | None) -> None:
        if pro is True:
            self._plan_name.update("Pro plan")
            self._plan_action.display = False
        elif pro is False:
            self._plan_name.update("Free plan")
            self._plan_action.display = True
        else:
            self._plan_name.update("Plan unavailable")
            self._plan_action.display = False
        self._apply_activity_access(pro)

    def _apply_activity_access(self, pro: bool | None) -> None:
        """Show streaks/activity for Pro users, an upsell card otherwise."""
        is_pro = pro is True
        self.query_one("#settings-stats-row").display = is_pro
        self.query_one("#settings-activity-title").display = is_pro
        self.query_one("#settings-activity-panel").display = is_pro
        self.query_one("#settings-activity-locked").display = not is_pro
        copy = self.query_one("#settings-activity-locked-copy", Static)
        if pro is None:
            copy.update(
                "We couldn't verify your plan. Check your iTE Cloud connection and reopen Settings."
            )
        else:
            copy.update(
                "Unlock streaks and activity tracker by subscribing for the Pro plan."
            )

    def _apply_usage_summary(self, summary: dict[str, object] | None) -> None:
        if not isinstance(summary, dict):
            self._usage_remaining = None
            self._seven_day_usage_remaining = None
            self._usage_pct.update("—")
            self._usage_bar.update("")
            self._usage_reset.update("Resets soon")
            self._seven_day_usage_pct.update("—")
            self._seven_day_usage_bar.update("")
            self._seven_day_usage_reset.update("Resets soon")
            return
        quotas = summary.get("quotas") or {}
        if not isinstance(quotas, dict):
            quotas = {}
        five_hour_remaining = self._apply_usage_window(
            quotas.get("fiveHour"),
            percent_widget=self._usage_pct,
            bar_widget=self._usage_bar,
            reset_widget=self._usage_reset,
        )
        self._usage_remaining = five_hour_remaining
        self._seven_day_usage_remaining = self._apply_usage_window(
            quotas.get("sevenDay"),
            percent_widget=self._seven_day_usage_pct,
            bar_widget=self._seven_day_usage_bar,
            reset_widget=self._seven_day_usage_reset,
        )

    def _apply_usage_window(
        self,
        quota: object,
        *,
        percent_widget: Static,
        bar_widget: Static,
        reset_widget: Static,
    ) -> int:
        if not isinstance(quota, dict):
            quota = {}
        used = float(quota.get("usedUsdCents") or 0)
        cap = max(1.0, float(quota.get("capUsdCents") or 1))
        remaining = max(0, min(100, int(((cap - used) / cap) * 100)))
        percent_widget.update(f"{remaining}% left")
        bar_widget.update(self._build_usage_bar(remaining, bar_widget))
        reset_raw = str(
            quota.get("fullWindowClearAt") or quota.get("nextResetAt") or ""
        )
        reset_widget.update(self._format_reset(reset_raw))
        return remaining

    def _build_usage_bar(self, remaining_percent: int, bar: Static) -> Text:
        """Render the usage bar the same way the usage summary modal does."""
        from ite.ui.reup.app import ReupApp

        app = self.app
        styles = {}
        if isinstance(app, ReupApp):
            styles = app._render_styles()
        filled_color = styles.get("success", "#8AD4A1")
        empty_color = styles.get("disabled", "#3a3a3f")
        bar_width = self._usage_bar_width(bar)
        used_percent = max(0, min(100, 100 - remaining_percent))
        filled = max(0, min(bar_width, round((used_percent / 100) * bar_width)))
        empty = max(0, bar_width - filled)
        line = Text()
        if filled:
            line.append("█" * filled, style=f"bold {filled_color}")
        if empty:
            line.append("█" * empty, style=empty_color)
        return line

    def _usage_bar_width(self, bar: Static) -> int:
        try:
            w = bar.size.width
            if w > 0:
                return w
        except Exception:
            pass
        return 92

    @staticmethod
    def _format_reset(value: str) -> str:
        if value:
            try:
                dt = datetime.fromisoformat(value).astimezone()
                hour = dt.hour % 12 or 12
                minute = dt.strftime("%M")
                period = "am" if dt.hour < 12 else "pm"
                return (
                    f"Resets {dt.strftime('%a, %b')} {dt.day} "
                    f"at {hour}:{minute}{period}"
                )
            except ValueError:
                pass
        return "Resets soon"

    async def _load_activity(self) -> None:
        cached_payload = getattr(self.app, "_activity_cache", None)
        try:
            refreshed_payload = await asyncio.to_thread(get_activity, self.app.config)
        except Exception:
            refreshed_payload = None
        payload = (
            refreshed_payload
            if isinstance(refreshed_payload, dict)
            else cached_payload
        )
        if isinstance(refreshed_payload, dict):
            self.app._activity_cache = refreshed_payload

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
