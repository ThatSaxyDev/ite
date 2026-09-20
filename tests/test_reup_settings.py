from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Static

from ite.cloud.auth import CloudAuthStatus, CloudEntitlementsResult, CloudSessionState
from ite.config.config import Config
from ite.ui.reup.settings import SettingsPanel


class SettingsPanelApp(App[None]):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self._cloud_signed_out = False
        self._cloud_user_email: str | None = None
        self._cloud_user_name: str | None = None
        self._account_plan_is_pro: bool | None = None
        self.open_island_toggles: list[bool] = []

    async def _set_open_island_enabled(self, enabled: bool) -> None:
        self.open_island_toggles.append(enabled)
        self.config.integrations.open_island.enabled = enabled

    def compose(self) -> ComposeResult:
        yield SettingsPanel(id="settings-panel")


class SettingsPanelTests(IsolatedAsyncioTestCase):
    @staticmethod
    def _text(widget: Static) -> str:
        content = getattr(widget, "content", "")
        if content:
            return str(content)
        return str(getattr(widget, "renderable", ""))

    async def test_metadata_failure_is_not_rendered_as_a_free_account(self) -> None:
        with TemporaryDirectory() as directory:
            config = Config(cwd=Path(directory))
            result = CloudEntitlementsResult(
                entitlements={},
                auth=CloudAuthStatus(
                    state=CloudSessionState.VALID,
                    session=object(),  # type: ignore[arg-type]
                ),
                metadata_available=False,
            )
            with (
                patch(
                    "ite.ui.reup.settings.get_cloud_entitlements_result",
                    return_value=result,
                ),
                patch("ite.ui.reup.settings.get_usage_summary", return_value=None),
                patch("ite.ui.reup.settings.get_activity", return_value=None),
                patch.object(SettingsPanel, "on_show", lambda _self: None),
            ):
                app = SettingsPanelApp(config)
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await pilot.pause()

                    panel = app.query_one(SettingsPanel)
                    plan = panel.query_one(".settings-plan-name", Static)
                    account = panel.query_one(".settings-account-name", Static)
                    locked_copy = panel.query_one(
                        "#settings-activity-locked-copy", Static
                    )

                    self.assertEqual(self._text(plan), "Plan unavailable")
                    self.assertEqual(
                        self._text(account), "Account details unavailable"
                    )
                    self.assertIn(
                        "couldn't verify your plan",
                        self._text(locked_copy).lower(),
                    )

    async def test_open_island_control_toggles_the_local_preference(self) -> None:
        with TemporaryDirectory() as directory:
            config = Config(cwd=Path(directory))
            with (
                patch("ite.ui.reup.settings.get_usage_summary", return_value=None),
                patch("ite.ui.reup.settings.get_activity", return_value=None),
                patch.object(SettingsPanel, "on_show", lambda _self: None),
            ):
                app = SettingsPanelApp(config)
                async with app.run_test() as pilot:
                    await pilot.pause()
                    panel = app.query_one(SettingsPanel)
                    await panel._on_open_island_action_pressed(None)  # type: ignore[arg-type]
                    await pilot.pause()

                    action = panel.query_one("#settings-open-island-action")
                    self.assertEqual(app.open_island_toggles, [True])
                    self.assertTrue(config.integrations.open_island.enabled)
                    self.assertEqual(str(getattr(action, "label", "")), "Turn off")
