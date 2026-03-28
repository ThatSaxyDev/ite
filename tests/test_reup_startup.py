import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ite.config.config import Config
from ite.ui.reup.app import ReupApp


class ReupStartupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def _app(self) -> ReupApp:
        return ReupApp(Config(cwd=self.cwd))

    def test_on_mount_allows_signed_in_user_without_byok_setup(self) -> None:
        async def run_test() -> None:
            app = self._app()
            prompt = SimpleNamespace(focus=lambda: None)
            toggle = SimpleNamespace(display=True)

            with (
                patch.object(app, "refresh_header"),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_refresh_empty_state"),
                patch.object(app, "_resize_composer_for_prompt"),
                patch.object(app, "_apply_aside_panel_state"),
                patch.object(app, "_apply_change_review_panel_state"),
                patch.object(app, "set_interval"),
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch.object(app, "_refresh_change_review_source", AsyncMock()) as refresh_change_review,
                patch.object(app, "_sync_command_palette") as sync_command_palette,
                patch.object(app, "_open_setup_modal", AsyncMock()) as open_setup_modal,
                patch("ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=True)),
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#aside-toggle": toggle,
                        "#changes-toggle": toggle,
                        "#prompt": prompt,
                    }[selector],
                ),
            ):
                await app.on_mount()

            open_setup_modal.assert_not_called()
            ensure_agent.assert_awaited_once()
            refresh_change_review.assert_awaited_once()
            sync_command_palette.assert_called_once_with("")

        asyncio.run(run_test())

    def test_cloud_login_allows_manual_setup_after_sign_in(self) -> None:
        async def run_test() -> None:
            app = self._app()
            prompt = SimpleNamespace(focus=lambda: None)
            conversation = SimpleNamespace(remove_children=AsyncMock())

            with (
                patch.object(app, "_set_signed_out_state"),
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch.object(app, "_open_setup_modal", AsyncMock()) as open_setup_modal,
                patch.object(app, "_reset_session_local_ui_state"),
                patch.object(app, "_refresh_empty_state"),
                patch("ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=None)),
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#conversation": conversation,
                        "#prompt": prompt,
                    }[selector],
                ),
            ):
                await app._run_cloud_login_flow()

            open_setup_modal.assert_not_called()
            ensure_agent.assert_awaited_once()
            conversation.remove_children.assert_awaited_once()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
