import asyncio
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ite.cloud.auth import CloudAuthError
from ite.cloud.auth import CloudAuthStatus
from ite.cloud.auth import CloudEntitlementsResult
from ite.cloud.auth import CloudSessionState
from ite.cloud.auth import has_valid_cloud_auth
from ite.client.response import TokenUsage
from ite.agent.session_manager import SessionSnapshot
from ite.config.config import Config
from ite.update_check import RuntimeUpdateNotice
from textual.widgets import Select

from ite.ui.reup.app import ONBOARDING_OTHER_VALUE, ReupApp
from ite.ui.reup.composer_views import build_empty_state_ascii


class ReupStartupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def _app(self) -> ReupApp:
        return ReupApp(Config(cwd=self.cwd))

    def test_empty_state_ascii_uses_straight_embossed_logo(self) -> None:
        logo = build_empty_state_ascii().plain
        lines = logo.splitlines()

        self.assertEqual(len(lines), 6)
        self.assertEqual({len(line) for line in lines}, {24})
        self.assertEqual(lines[0], "  ██╗ ████████╗ ███████╗")
        self.assertEqual(lines[1], "  ╚═╝ ╚══██╔══╝ ██╔════╝")
        self.assertNotIn("╚═██╔═╝", logo)

    def test_app_init_defers_command_registry_build(self) -> None:
        with patch("ite.ui.reup.app.build_registry") as build_registry:
            ReupApp(Config(cwd=self.cwd))

        build_registry.assert_not_called()

    def test_required_update_state_populates_command_box(self) -> None:
        app = self._app()
        copy = SimpleNamespace(
            value="", update=lambda value: setattr(copy, "value", value)
        )
        meta = SimpleNamespace(
            value="", update=lambda value: setattr(meta, "value", value)
        )
        command_box = SimpleNamespace(
            command="", set_command=lambda value: setattr(command_box, "command", value)
        )
        notice = SimpleNamespace(
            latest_version="0.0.46",
            minimum_supported_version="0.0.45",
            current_version="0.0.45",
            message="A newer iTE runtime is required before you can continue. Run below, then reopen iTE.",
            upgrade_command="pipx upgrade ite-agent",
            release_url="https://example.test/releases/0.0.46",
        )
        app._required_update_notice = notice

        with patch.object(
            app,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#update-required-copy": copy,
                "#update-required-meta": meta,
            }.get(selector, command_box),
        ):
            app._refresh_required_update_state()

        self.assertEqual(
            copy.value,
            "A newer iTE runtime is required before you can continue. Exit iTE, run the command below, then reopen it.",
        )
        self.assertEqual(command_box.command, "pipx upgrade ite-agent")
        self.assertIn("Latest 0.0.46", meta.value)
        self.assertIn("Your version 0.0.45", meta.value)
        self.assertNotIn("Required", meta.value)
        self.assertIn("https://example.test/releases/0.0.46", meta.value)

    def test_required_update_state_appends_missing_instruction(self) -> None:
        app = self._app()
        copy = SimpleNamespace(
            value="", update=lambda value: setattr(copy, "value", value)
        )
        meta = SimpleNamespace(value="", update=lambda _value: None)
        command_box = SimpleNamespace(command="", set_command=lambda _value: None)
        app._required_update_notice = SimpleNamespace(
            latest_version="0.0.46",
            minimum_supported_version="0.0.46",
            current_version="0.0.45",
            message="A critical runtime update is required.",
            upgrade_command="pipx upgrade ite-agent",
            release_url=None,
        )

        with patch.object(
            app,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#update-required-copy": copy,
                "#update-required-meta": meta,
            }.get(selector, command_box),
        ):
            app._refresh_required_update_state()

        self.assertEqual(
            copy.value,
            "A critical runtime update is required. Exit iTE, run the command below, then reopen it.",
        )

    def test_required_update_exit_uses_clean_exit_flow(self) -> None:
        app = self._app()

        with patch.object(app, "run_worker") as run_worker:
            app.on_update_required_exit_pressed(SimpleNamespace())

        self.assertEqual(run_worker.call_count, 1)
        work = run_worker.call_args.args[0]
        self.assertIn("_exit_app", getattr(work, "__qualname__", ""))
        work.close()

    def test_recommended_update_notice_copy_is_launch_prompt(self) -> None:
        app = self._app()
        notice = SimpleNamespace(
            latest_version="0.0.46",
            title="Update available",
            message="",
            upgrade_command="pipx upgrade ite-agent",
            release_url=None,
        )

        title, message = app._runtime_update_notice_copy(notice)

        self.assertEqual(title, "Update available")
        self.assertIn("Version 0.0.46 is available", message)
        self.assertIn("Exit iTE, run: pipx upgrade ite-agent, then reopen it", message)

    def test_info_update_notice_copy_uses_inline_command(self) -> None:
        app = self._app()
        notice = SimpleNamespace(
            latest_version="0.0.46",
            title="Update available",
            message="",
            upgrade_command="pipx upgrade ite-agent",
            release_url=None,
        )

        title, message = app._runtime_update_notice_copy(notice)

        self.assertEqual(title, "Update available")
        self.assertIn("Version 0.0.46 is available", message)
        self.assertIn("Exit iTE, run: pipx upgrade ite-agent, then reopen it", message)

    def test_info_update_notice_appends_inline_instruction_to_custom_message(
        self,
    ) -> None:
        app = self._app()
        notice = SimpleNamespace(
            latest_version="0.0.46",
            title="Update available",
            message="A small update is available.",
            upgrade_command="pipx upgrade ite-agent",
            release_url=None,
        )

        _title, message = app._runtime_update_notice_copy(notice)

        self.assertEqual(
            message,
            "A small update is available. Exit iTE, run: pipx upgrade ite-agent, then reopen it.",
        )

    def test_recommended_update_feed_card_has_copyable_command_block(self) -> None:
        app = self._app()
        notice = SimpleNamespace(
            latest_version="0.0.46",
            title="Update available",
            message="",
            upgrade_command="pipx upgrade ite-agent",
            release_url=None,
        )

        title, body = app._runtime_update_notice_feed_card(notice)

        self.assertEqual(title, "Update available")
        self.assertIn("Version 0.0.46 is available", body)
        self.assertIn("Exit iTE, run the command below, then reopen it", body)
        self.assertIn("```bash\npipx upgrade ite-agent\n```", body)

    def test_recommended_update_notice_posts_to_chat_feed(self) -> None:
        async def run_test() -> None:
            app = self._app()
            notice = RuntimeUpdateNotice(
                latest_version="0.0.46",
                required=False,
                title="Update available",
                message="",
                upgrade_command="pipx upgrade ite-agent",
                release_url=None,
                update_required=False,
            )

            with (
                patch("ite.ui.reup.app.check_runtime_update", return_value=notice),
                patch("ite.ui.reup.app.should_show_update_notice", return_value=True),
                patch("ite.ui.reup.app.get_notification_type", return_value="feed"),
                patch.object(app, "add_assistant_card", AsyncMock()) as add_card,
                patch.object(app, "post_notice") as post_notice,
                patch("ite.ui.reup.app.mark_update_notice_seen") as mark_seen,
            ):
                await app._refresh_runtime_update_notice()

            add_card.assert_awaited_once()
            post_notice.assert_not_called()
            mark_seen.assert_called_once_with(notice)

        asyncio.run(run_test())

    def test_info_update_notice_posts_to_toast(self) -> None:
        async def run_test() -> None:
            app = self._app()
            notice = RuntimeUpdateNotice(
                latest_version="0.0.46",
                required=False,
                title="Update available",
                message="",
                upgrade_command="pipx upgrade ite-agent",
                release_url=None,
                update_required=False,
            )

            with (
                patch("ite.ui.reup.app.check_runtime_update", return_value=notice),
                patch("ite.ui.reup.app.should_show_update_notice", return_value=True),
                patch("ite.ui.reup.app.get_notification_type", return_value="toast"),
                patch.object(app, "add_assistant_card", AsyncMock()) as add_card,
                patch.object(app, "post_notice") as post_notice,
                patch("ite.ui.reup.app.mark_update_notice_seen") as mark_seen,
            ):
                await app._refresh_runtime_update_notice()

            add_card.assert_not_awaited()
            post_notice.assert_called_once()
            mark_seen.assert_called_once_with(notice)

        asyncio.run(run_test())

    def test_on_mount_allows_signed_in_user_without_byok_setup(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = True
            app.config.onboarding_completed = True
            prompt = SimpleNamespace(focus=lambda: None)
            toggle = SimpleNamespace(display=True)

            def _consume(coro, **_kwargs):
                qualname = getattr(coro, "__qualname__", "")
                try:
                    coro.close()
                except Exception:
                    pass
                return qualname

            with (
                patch("ite.ui.reup.app.load_theme", return_value=None),
                patch.object(app, "refresh_header"),
                patch.object(app, "_set_loading_state") as set_loading_state,
                patch.object(app, "_refresh_empty_state"),
                patch.object(app, "_resize_composer_for_prompt"),
                patch.object(app, "_apply_aside_panel_state"),
                patch.object(app, "_apply_change_review_panel_state"),
                patch.object(app, "set_interval"),
                patch.object(app, "set_timer"),
                patch.object(app, "_set_signed_out_state") as set_signed_out_state,
                patch.object(app, "run_worker", side_effect=_consume) as run_worker,
                patch.object(app, "_open_setup_modal", AsyncMock()) as open_setup_modal,
                patch(
                    "ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=True)
                ),
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
            set_signed_out_state.assert_not_called()
            self.assertNotIn(
                "starting up",
                [
                    str(call.args[0])
                    for call in set_loading_state.call_args_list
                    if call.args
                ],
            )
            self.assertTrue(
                any(
                    "_bootstrap_after_mount"
                    in getattr(call.args[0], "__qualname__", "")
                    for call in run_worker.call_args_list
                )
            )
            self.assertTrue(
                any(
                    "_initialize_command_palette"
                    in getattr(call.args[0], "__qualname__", "")
                    for call in run_worker.call_args_list
                )
            )

        asyncio.run(run_test())

    def test_on_mount_uses_detected_light_theme_when_still_on_default_dark(
        self,
    ) -> None:
        async def run_test() -> None:
            with patch(
                "ite.ui.reup.app.detect_host_textual_theme",
                return_value="textual-light",
            ):
                app = self._app()
            app.config.onboarding_completed = True
            prompt = SimpleNamespace(focus=lambda: None)
            toggle = SimpleNamespace(display=True)

            def _consume(coro, **_kwargs):
                try:
                    coro.close()
                except Exception:
                    pass
                return None

            with (
                patch("ite.ui.reup.app.load_theme", return_value=None),
                patch.object(app, "refresh_header"),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_refresh_empty_state"),
                patch.object(app, "_resize_composer_for_prompt"),
                patch.object(app, "_apply_aside_panel_state"),
                patch.object(app, "_apply_change_review_panel_state"),
                patch.object(app, "set_interval"),
                patch.object(app, "_set_signed_out_state"),
                patch.object(app, "run_worker", side_effect=_consume),
                patch.object(app, "ensure_agent", AsyncMock()),
                patch.object(app, "_refresh_change_review_source", AsyncMock()),
                patch.object(app, "_sync_command_palette"),
                patch(
                    "ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=True)
                ),
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

            self.assertEqual(app.theme, "textual-light")

        asyncio.run(run_test())

    def test_cloud_login_allows_manual_setup_after_sign_in(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.onboarding_completed = True
            prompt = SimpleNamespace(focus=lambda: None)
            conversation = SimpleNamespace(remove_children=AsyncMock())

            with (
                patch.object(app, "_set_signed_out_state"),
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch.object(app, "_open_setup_modal", AsyncMock()) as open_setup_modal,
                patch.object(app, "_reset_session_local_ui_state"),
                patch.object(app, "_refresh_empty_state"),
                patch(
                    "ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=None)
                ),
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

    def test_skip_sign_in_before_onboarding_disables_cloud_and_shows_onboarding(
        self,
    ) -> None:
        async def run_test() -> None:
            async def _to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            app = self._app()
            app.config.cloud_auth_enabled = True
            app.config.onboarding_completed = False
            name_input = SimpleNamespace(focus=unittest.mock.Mock())

            with (
                patch.object(app, "_set_signed_out_state") as set_signed_out_state,
                patch.object(app, "_set_onboarding_state") as set_onboarding_state,
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch("ite.ui.reup.app.save_cloud_settings") as save_cloud_settings,
                patch(
                    "ite.ui.reup.app.asyncio.to_thread", side_effect=_to_thread
                ),
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#onboarding-name": name_input,
                    }[selector],
                ),
            ):
                await app._continue_without_cloud_sign_in()

            save_cloud_settings.assert_called_once_with(enabled=False)
            self.assertFalse(app.config.cloud_auth_enabled)
            self.assertFalse(app._account_plan_is_pro)
            self.assertFalse(app._account_plan_unavailable)
            self.assertEqual(
                [call.args[0] for call in set_signed_out_state.call_args_list],
                [True, False],
            )
            set_onboarding_state.assert_called_once_with(True)
            name_input.focus.assert_called_once()
            ensure_agent.assert_not_awaited()

        asyncio.run(run_test())

    def test_skip_sign_in_after_onboarding_starts_runtime_with_saved_credentials(
        self,
    ) -> None:
        async def run_test() -> None:
            async def _to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            app = self._app()
            app.config.cloud_auth_enabled = True
            app.config.onboarding_completed = True
            app.config.api_key = "test-key"
            app.config.base_url = "https://api.example.test/v1"
            app.config.model.name = "test-model"
            prompt = SimpleNamespace(focus=unittest.mock.Mock())

            with (
                patch.object(app, "_set_signed_out_state") as set_signed_out_state,
                patch.object(app, "_set_onboarding_state") as set_onboarding_state,
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch.object(app, "_refresh_empty_state") as refresh_empty_state,
                patch.object(app, "_open_setup_modal", AsyncMock()) as open_setup_modal,
                patch("ite.ui.reup.app.save_cloud_settings") as save_cloud_settings,
                patch(
                    "ite.ui.reup.app.asyncio.to_thread", side_effect=_to_thread
                ),
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#prompt": prompt,
                    }[selector],
                ),
            ):
                await app._continue_without_cloud_sign_in()

            save_cloud_settings.assert_called_once_with(enabled=False)
            self.assertFalse(app.config.cloud_auth_enabled)
            self.assertFalse(app._account_plan_is_pro)
            self.assertFalse(app._account_plan_unavailable)
            self.assertEqual(
                [call.args[0] for call in set_signed_out_state.call_args_list],
                [True, False],
            )
            set_onboarding_state.assert_not_called()
            open_setup_modal.assert_not_awaited()
            ensure_agent.assert_awaited_once()
            refresh_empty_state.assert_called_once()
            prompt.focus.assert_called_once()

        asyncio.run(run_test())

    def test_latest_workspace_session_snapshot_picks_newest_non_empty_session(self) -> None:
        app = self._app()
        app.config.resume_last_session = True
        snapshot = SessionSnapshot(
            session_id="latest",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            turn_count=3,
            messages=[{"role": "user", "content": "continue"}],
            total_usage=TokenUsage(),
            workspace_path=str(self.cwd.resolve()),
        )
        fake_manager = SimpleNamespace(
            list_sessions=unittest.mock.Mock(
                return_value=[
                    {
                        "session_id": "empty",
                        "turn_count": 0,
                        "updated_at": "2026-05-29T08:00:00",
                    },
                    {
                        "session_id": "latest",
                        "turn_count": 3,
                        "updated_at": "2026-05-29T09:00:00",
                    },
                ]
            ),
            load_session=unittest.mock.Mock(return_value=snapshot),
        )

        with patch("ite.ui.reup.app.SessionManager", return_value=fake_manager):
            selected = app._latest_workspace_session_snapshot()

        self.assertIs(selected, snapshot)
        fake_manager.list_sessions.assert_called_once_with(
            workspace_path=app.config.cwd,
            include_legacy_unscoped=False,
        )
        fake_manager.load_session.assert_called_once_with("latest")

    def test_latest_workspace_session_snapshot_falls_back_when_disabled_or_missing(self) -> None:
        app = self._app()

        with patch("ite.ui.reup.app.SessionManager") as session_manager:
            self.assertIsNone(app._latest_workspace_session_snapshot())

        session_manager.assert_not_called()

        app.config.resume_last_session = True
        fake_manager = SimpleNamespace(
            list_sessions=unittest.mock.Mock(return_value=[]),
            load_session=unittest.mock.Mock(),
        )
        with patch("ite.ui.reup.app.SessionManager", return_value=fake_manager):
            self.assertIsNone(app._latest_workspace_session_snapshot())

        fake_manager.load_session.assert_not_called()

    def test_bootstrap_resumes_last_workspace_session_when_enabled(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = False
            app.config.onboarding_completed = True
            app.config.resume_last_session = True
            prompt = SimpleNamespace(focus=lambda: None)

            with (
                patch.object(
                    app,
                    "_resume_last_workspace_session_on_startup",
                    AsyncMock(return_value=True),
                ) as resume_last,
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch.object(app, "_set_startup_phase"),
                patch.object(app, "_set_startup_state"),
                patch.object(app, "_schedule_usage_meta_refresh"),
                patch.object(app, "_refresh_change_review_source", AsyncMock()),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_sync_command_palette"),
                patch.object(app, "_schedule_runtime_update_check"),
                patch.object(app, "query_one", return_value=prompt),
            ):
                await app._bootstrap_after_mount()

            resume_last.assert_awaited_once()
            ensure_agent.assert_not_awaited()

        asyncio.run(run_test())

    def test_bootstrap_uses_empty_chat_when_no_resume_session_exists(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = False
            app.config.onboarding_completed = True
            app.config.resume_last_session = True
            prompt = SimpleNamespace(focus=lambda: None)

            with (
                patch.object(
                    app,
                    "_resume_last_workspace_session_on_startup",
                    AsyncMock(return_value=False),
                ) as resume_last,
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch.object(app, "_set_startup_phase"),
                patch.object(app, "_set_startup_state"),
                patch.object(app, "_schedule_usage_meta_refresh"),
                patch.object(app, "_refresh_change_review_source", AsyncMock()),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_sync_command_palette"),
                patch.object(app, "_schedule_runtime_update_check"),
                patch.object(app, "query_one", return_value=prompt),
            ):
                await app._bootstrap_after_mount()

            resume_last.assert_awaited_once()
            ensure_agent.assert_awaited_once()

        asyncio.run(run_test())

    def test_remote_command_requires_bundled_access_before_starting_bridge(
        self,
    ) -> None:
        async def run_test() -> None:
            app = self._app()
            status = CloudAuthStatus(
                state=CloudSessionState.NO_ENTITLEMENT,
                message="Remote companion requires bundled access for this iTE account.",
            )

            with (
                patch.object(
                    app,
                    "_remote_companion_access_status",
                    AsyncMock(return_value=status),
                ),
                patch.object(app, "post_system") as post_system,
                patch.object(
                    app, "_ensure_remote_server", AsyncMock()
                ) as ensure_remote_server,
            ):
                await app._run_remote_command_native(["on"])

            ensure_remote_server.assert_not_awaited()
            post_system.assert_called_once()
            self.assertIn("bundled access", post_system.call_args.args[1])

        asyncio.run(run_test())

    def test_remote_command_reports_credential_store_error_before_starting_bridge(
        self,
    ) -> None:
        async def run_test() -> None:
            app = self._app()
            status = CloudAuthStatus(
                state=CloudSessionState.CREDENTIAL_ERROR,
                message="Could not read iTE Cloud credentials from the OS credential store.",
            )

            with (
                patch.object(
                    app,
                    "_remote_companion_access_status",
                    AsyncMock(return_value=status),
                ),
                patch.object(app, "post_system") as post_system,
                patch.object(
                    app, "_ensure_remote_server", AsyncMock()
                ) as ensure_remote_server,
            ):
                await app._run_remote_command_native(["on"])

            ensure_remote_server.assert_not_awaited()
            post_system.assert_called_once()
            self.assertIn("OS credential store", post_system.call_args.args[1])
            self.assertIn("/cloud login", post_system.call_args.args[1])

        asyncio.run(run_test())

    def test_credential_store_error_does_not_force_signed_out_startup(self) -> None:
        app = self._app()
        app._cloud_signed_out = True
        app._cloud_bootstrap_busy = True
        status = CloudAuthStatus(
            state=CloudSessionState.CREDENTIAL_ERROR,
            message="Could not read iTE Cloud credentials from the OS credential store.",
        )

        with (
            patch.object(app, "_apply_shell_surface") as apply_shell_surface,
            patch.object(app, "post_system") as post_system,
            patch("ite.ui.reup.app.clear_cloud_auth") as clear_auth,
        ):
            result = app._apply_cloud_auth_status(
                status,
                context="iTE Cloud",
                interactive=True,
            )

        self.assertFalse(result)
        self.assertFalse(app._cloud_signed_out)
        self.assertFalse(app._cloud_bootstrap_busy)
        clear_auth.assert_not_called()
        apply_shell_surface.assert_called_once()
        post_system.assert_called_once()
        self.assertIn("OS credential store", post_system.call_args.args[1])

    def test_no_bundled_entitlement_marks_bundled_access_denied(self) -> None:
        app = self._app()
        status = CloudAuthStatus(
            state=CloudSessionState.NO_ENTITLEMENT,
            message="Bundled models require iTE Pro for this account.",
        )

        with patch.object(app, "post_system") as post_system, patch.object(
            app, "post_notice"
        ) as post_notice:
            result = app._apply_cloud_auth_status(
                status,
                context="Bundled models",
                interactive=True,
            )

        self.assertFalse(result)
        self.assertTrue(app._bundled_access_denied)
        post_system.assert_not_called()
        post_notice.assert_called_once()
        self.assertIn("iTE Pro", post_notice.call_args.args[0])

    def test_bundled_entitlement_notice_is_throttled(self) -> None:
        app = self._app()

        with patch.object(app, "post_notice") as post_notice, patch(
            "ite.ui.reup.app.time.monotonic", side_effect=[100.0, 200.0, 3801.0]
        ):
            app._maybe_post_bundled_access_notice()
            app._maybe_post_bundled_access_notice()
            app._maybe_post_bundled_access_notice()

        self.assertEqual(post_notice.call_count, 2)

    def test_bundled_model_refresh_clears_stale_cache_without_entitlement(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app._bundled_models_cache = [{"model_name": "moonshotai/kimi-k2.5"}]
            app._usage_summary_cache = {"ok": True}
            app._usage_remaining_percent = 75
            status = CloudAuthStatus(
                state=CloudSessionState.NO_ENTITLEMENT,
                message="Bundled models require iTE Pro for this account.",
            )
            result = SimpleNamespace(models=[], auth=status, message=status.message)

            with (
                patch("ite.ui.reup.app.get_bundled_models_result", return_value=result),
                patch.object(app, "refresh_header") as refresh_header,
            ):
                await app._refresh_bundled_models_cache()

            self.assertEqual(app._bundled_models_cache, [])
            self.assertIsNone(app._usage_summary_cache)
            self.assertIsNone(app._usage_remaining_percent)
            self.assertTrue(app._bundled_access_denied)
            refresh_header.assert_called_once()

        asyncio.run(run_test())

    def test_plan_badge_uses_theme_aware_plan_color(self) -> None:
        app = self._app()
        app._account_plan_is_pro = None

        loading_badge = app._plan_badge_renderable()
        self.assertIn("▰▱▱", loading_badge.plain)
        self.assertIn(
            f"on {app._render_styles()['surface']}",
            str(loading_badge.style),
        )

        app._account_plan_unavailable = True
        unavailable_badge = app._plan_badge_renderable()
        self.assertIn("Offline", unavailable_badge.plain)
        self.assertIn(
            f"on {app._render_styles()['surface']}",
            str(unavailable_badge.style),
        )
        app._account_plan_unavailable = False

        app._account_plan_is_pro = False

        free_badge = app._plan_badge_renderable()
        free = free_badge.plain
        self.assertIn("Free", free)
        self.assertIn(
            f"on {app._render_styles()['warning']}",
            str(free_badge.style),
        )

        app._account_plan_is_pro = True
        pro_badge = app._plan_badge_renderable()
        pro = pro_badge.plain
        self.assertIn("Pro", pro)
        self.assertIn(
            f"on {app._render_styles()['success']}",
            str(pro_badge.style),
        )

    def test_free_plan_badge_opens_pricing(self) -> None:
        app = self._app()
        app._account_plan_is_pro = False
        event = SimpleNamespace(stop=lambda: setattr(event, "stopped", True))

        with (
            patch("ite.ui.reup.app.webbrowser.open", return_value=True) as open_url,
            patch.object(app, "post_notice") as post_notice,
        ):
            app.on_plan_badge_click(event)  # type: ignore[arg-type]

        open_url.assert_called_once_with("https://ite.kiishi.space/pricing")
        post_notice.assert_called_once()
        self.assertTrue(event.stopped)

    def test_loading_plan_badge_does_not_open_pricing(self) -> None:
        app = self._app()
        app._account_plan_is_pro = None
        event = SimpleNamespace(stop=lambda: setattr(event, "stopped", True))

        with (
            patch("ite.ui.reup.app.webbrowser.open", return_value=True) as open_url,
            patch.object(app, "post_notice") as post_notice,
        ):
            app.on_plan_badge_click(event)  # type: ignore[arg-type]

        open_url.assert_not_called()
        post_notice.assert_not_called()
        self.assertTrue(event.stopped)

    def test_unavailable_plan_badge_posts_try_again_notice(self) -> None:
        app = self._app()
        app._account_plan_is_pro = None
        app._account_plan_unavailable = True
        event = SimpleNamespace(stop=lambda: setattr(event, "stopped", True))

        with (
            patch("ite.ui.reup.app.webbrowser.open", return_value=True) as open_url,
            patch.object(app, "post_notice") as post_notice,
        ):
            app.on_plan_badge_click(event)  # type: ignore[arg-type]

        open_url.assert_not_called()
        post_notice.assert_called_once()
        self.assertIn("Try again later", post_notice.call_args.args[1])
        self.assertTrue(event.stopped)

    def test_account_plan_badge_refreshes_from_entitlements(self) -> None:
        async def run_test() -> None:
            app = self._app()
            result = CloudEntitlementsResult(
                entitlements={"proAccess": True},
                auth=CloudAuthStatus(
                    state=CloudSessionState.VALID,
                    session=object(),  # type: ignore[arg-type]
                ),
            )

            with (
                patch(
                    "ite.ui.reup.app.get_cloud_entitlements_result",
                    return_value=result,
                ),
                patch.object(app, "refresh_header") as refresh_header,
            ):
                await app._refresh_account_plan_badge()

            self.assertTrue(app._account_plan_is_pro)
            refresh_header.assert_called_once()

        asyncio.run(run_test())

    def test_account_plan_badge_resolves_free_when_cloud_auth_disabled(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = False
            app._account_plan_is_pro = None
            app._account_plan_unavailable = True

            with (
                patch(
                    "ite.ui.reup.app.get_cloud_entitlements_result"
                ) as get_entitlements,
                patch.object(app, "refresh_header") as refresh_header,
            ):
                await app._refresh_account_plan_badge()

            get_entitlements.assert_not_called()
            self.assertFalse(app._account_plan_is_pro)
            self.assertFalse(app._account_plan_unavailable)
            refresh_header.assert_called_once()

        asyncio.run(run_test())

    def test_account_plan_badge_concludes_when_entitlements_fail(self) -> None:
        async def run_test() -> None:
            app = self._app()

            with (
                patch(
                    "ite.ui.reup.app.get_cloud_entitlements_result",
                    side_effect=RuntimeError("cloud down"),
                ),
                patch.object(app, "refresh_header") as refresh_header,
            ):
                await app._refresh_account_plan_badge()

            self.assertIsNone(app._account_plan_is_pro)
            self.assertTrue(app._account_plan_unavailable)
            refresh_header.assert_called_once()

        asyncio.run(run_test())

    def test_account_plan_badge_concludes_on_network_error(self) -> None:
        async def run_test() -> None:
            app = self._app()
            result = CloudEntitlementsResult(
                entitlements={},
                auth=CloudAuthStatus(
                    state=CloudSessionState.NETWORK_ERROR,
                    session=None,
                    message="cloud down",
                ),
            )

            with (
                patch(
                    "ite.ui.reup.app.get_cloud_entitlements_result",
                    return_value=result,
                ),
                patch.object(app, "refresh_header") as refresh_header,
            ):
                await app._refresh_account_plan_badge()

            self.assertIsNone(app._account_plan_is_pro)
            self.assertTrue(app._account_plan_unavailable)
            refresh_header.assert_called_once()

        asyncio.run(run_test())

    def test_signed_out_network_watcher_announces_recovery(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = True
            app._cloud_signed_out = True
            app._cloud_network_watch_enabled = True
            app._cloud_network_was_unreachable = True

            with (
                patch(
                    "ite.ui.reup.app.is_cloud_api_reachable",
                    return_value=True,
                ) as is_reachable,
                patch.object(app, "post_notice") as post_notice,
            ):
                await app._probe_cloud_network_recovery()

            is_reachable.assert_called_once_with(app.config)
            self.assertFalse(app._cloud_network_was_unreachable)
            self.assertEqual(
                app._cloud_signed_out_status_message,
                "iTE Cloud is reachable. Sign in to continue.",
            )
            self.assertFalse(app._cloud_network_watch_enabled)
            post_notice.assert_called_once_with(
                "iTE Cloud",
                "Back online. You can sign in now.",
            )
            self.assertFalse(app._cloud_network_probe_in_flight)

        asyncio.run(run_test())

    def test_network_watcher_refreshes_cloud_caches_after_runtime_recovery(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = True
            app._account_plan_unavailable = True
            app._cloud_network_was_unreachable = True
            auth = CloudAuthStatus(
                state=CloudSessionState.VALID,
                session=object(),  # type: ignore[arg-type]
            )

            with (
                patch("ite.ui.reup.app.get_cloud_auth_status", return_value=auth),
                patch.object(app, "_set_account_plan_badge_state") as set_badge,
                patch.object(app, "_prefetch_cloud_caches") as prefetch,
                patch.object(app, "post_notice") as post_notice,
            ):
                await app._probe_cloud_network_recovery()

            set_badge.assert_called_once_with(None, unavailable=False)
            prefetch.assert_called_once()
            post_notice.assert_called_once_with(
                "iTE Cloud",
                "Back online. Cloud features are available.",
            )
            self.assertFalse(app._cloud_network_probe_in_flight)

        asyncio.run(run_test())

    def test_network_watcher_is_scoped_to_recovery_states(self) -> None:
        app = self._app()
        app.config.cloud_auth_enabled = True
        self.assertFalse(app._should_probe_cloud_network_recovery())

        app._account_plan_unavailable = True
        self.assertTrue(app._should_probe_cloud_network_recovery())

        app._cloud_network_probe_in_flight = True
        self.assertFalse(app._should_probe_cloud_network_recovery())

    def test_signed_out_network_watcher_stops_after_reachable_probe(self) -> None:
        app = self._app()
        app.config.cloud_auth_enabled = True
        app._cloud_signed_out = True
        app._cloud_network_watch_enabled = False
        app._cloud_signed_out_status_message = (
            "iTE Cloud is reachable. Sign in to continue."
        )

        self.assertFalse(app._should_probe_cloud_network_recovery())

    def test_signed_out_status_alone_does_not_probe_network(self) -> None:
        app = self._app()
        app.config.cloud_auth_enabled = True
        app._cloud_signed_out = True

        self.assertFalse(app._should_probe_cloud_network_recovery())

    def test_network_watcher_monitors_known_online_plan_state(self) -> None:
        app = self._app()
        app.config.cloud_auth_enabled = True

        app._account_plan_is_pro = False
        self.assertTrue(app._should_probe_cloud_network_recovery())

        app._account_plan_is_pro = True
        self.assertTrue(app._should_probe_cloud_network_recovery())

    def test_network_watcher_uses_fast_cadence_while_offline(self) -> None:
        app = self._app()
        app.config.cloud_auth_enabled = True

        app._account_plan_unavailable = True
        self.assertEqual(app._cloud_network_recovery_probe_interval(), 2.0)

        app._account_plan_unavailable = False
        app._cloud_signed_out = True
        app._cloud_network_watch_enabled = True
        self.assertEqual(app._cloud_network_recovery_probe_interval(), 2.0)

    def test_network_watcher_uses_slower_cadence_while_online(self) -> None:
        app = self._app()
        app.config.cloud_auth_enabled = True
        app._account_plan_is_pro = True

        self.assertEqual(app._cloud_network_recovery_probe_interval(), 15.0)

    def test_network_watcher_marks_active_cloud_session_offline(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = True
            app._account_plan_is_pro = False
            app._account_plan_unavailable = False
            auth = CloudAuthStatus(
                state=CloudSessionState.NETWORK_ERROR,
                message="network down",
            )

            with (
                patch("ite.ui.reup.app.get_cloud_auth_status", return_value=auth),
                patch.object(app, "refresh_header") as refresh_header,
                patch.object(app, "post_notice") as post_notice,
            ):
                await app._probe_cloud_network_recovery()

            self.assertIsNone(app._account_plan_is_pro)
            self.assertTrue(app._account_plan_unavailable)
            self.assertTrue(app._cloud_network_was_unreachable)
            refresh_header.assert_called_once()
            post_notice.assert_called_once_with(
                "iTE Cloud",
                "Offline. Cloud features will reconnect automatically.",
            )

        asyncio.run(run_test())

    def test_perform_quit_does_not_hang_on_remote_shutdown(self) -> None:
        async def run_test() -> None:
            app = self._app()

            async def _never_finishes() -> None:
                await asyncio.sleep(10)

            app._remote_server = SimpleNamespace(
                stop=AsyncMock(side_effect=_never_finishes)
            )

            with (
                patch.object(app, "auto_save", AsyncMock()),
                patch.object(app, "_shutdown_agents", AsyncMock()) as shutdown_agents,
                patch.object(app, "exit") as exit_app,
            ):
                await asyncio.wait_for(app._perform_quit(), timeout=2.5)

            shutdown_agents.assert_awaited_once()
            exit_app.assert_called_once()
            self.assertIsNone(app._remote_server)

        asyncio.run(run_test())

    def test_perform_quit_resolves_pending_plan_question(self) -> None:
        async def run_test() -> None:
            app = self._app()
            plan_question_future = asyncio.get_running_loop().create_future()
            app._plan_question_future = plan_question_future

            with (
                patch.object(app, "auto_save", AsyncMock()),
                patch.object(app, "_shutdown_remote_server", AsyncMock()),
                patch.object(app, "_shutdown_agents", AsyncMock()),
                patch.object(app, "exit"),
            ):
                await app._perform_quit()

            self.assertEqual(
                plan_question_future.result(),
                {"selected_option": "", "free_text": "", "selected_index": None},
            )
            self.assertIsNone(app._plan_question_future)

        asyncio.run(run_test())

    def test_perform_quit_skips_model_title_generation(self) -> None:
        async def run_test() -> None:
            app = self._app()
            session = SimpleNamespace(
                turn_count=1,
                name=None,
                name_source=None,
                name_locked=False,
                name_last_generated_turn=0,
                session_id="session-1",
                name_generation_context=lambda: {"first_user": "Investigate exit bug."},
                set_auto_name=lambda value: setattr(session, "name", value),
                should_refresh_auto_name=lambda: False,
                snapshot_kwargs=lambda workspace_path: {
                    "session_id": "session-1",
                    "name": session.name,
                    "name_source": session.name_source,
                    "name_locked": session.name_locked,
                    "name_last_generated_turn": session.name_last_generated_turn,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                    "turn_count": 1,
                    "workspace_path": workspace_path,
                    "messages": [],
                    "total_usage": TokenUsage(),
                },
            )
            app.agent = SimpleNamespace(session=session)

            with (
                patch.object(
                    app, "generate_session_name", AsyncMock()
                ) as generate_name,
                patch.object(app, "refresh_header"),
                patch.object(app, "_shutdown_remote_server", AsyncMock()),
                patch.object(app, "_shutdown_agents", AsyncMock()),
                patch.object(app, "exit"),
                patch("ite.ui.reup.app.SessionManager") as session_manager,
            ):
                await app._perform_quit()

            generate_name.assert_not_awaited()
            self.assertEqual(session.name, "Investigate Exit Bug")
            session_manager.return_value.save_session.assert_called_once()

        asyncio.run(run_test())

    def test_shutdown_agents_closes_open_sessions_concurrently(self) -> None:
        async def run_test() -> None:
            app = self._app()

            async def _slow_close(_exc_type, _exc, _tb) -> None:
                await asyncio.sleep(10)

            agents = [
                SimpleNamespace(__aexit__=AsyncMock(side_effect=_slow_close))
                for _ in range(3)
            ]
            app._session_agents = {
                f"session-{idx}": agent for idx, agent in enumerate(agents)
            }

            started = time.monotonic()
            await asyncio.wait_for(app._shutdown_agents(), timeout=3.0)
            elapsed = time.monotonic() - started

            self.assertLess(elapsed, 2.8)
            for agent in agents:
                agent.__aexit__.assert_awaited_once()

        asyncio.run(run_test())

    def test_bootstrap_shows_onboarding_without_starting_agent(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = True
            app.config.onboarding_completed = False
            name_input = SimpleNamespace(focus=lambda: None)

            with (
                patch.object(app, "_apply_shell_surface"),
                patch.object(app, "_set_signed_out_state"),
                patch.object(app, "_set_onboarding_state") as set_onboarding_state,
                patch.object(app, "_set_loading_state"),
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch.object(app, "run_worker"),
                patch(
                    "ite.ui.reup.app.asyncio.to_thread",
                    AsyncMock(side_effect=[True, True]),
                ),
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#onboarding-name": name_input,
                    }[selector],
                ),
            ):
                await app._bootstrap_after_mount()

            set_onboarding_state.assert_called_once_with(True)
            ensure_agent.assert_not_awaited()

        asyncio.run(run_test())

    def test_bootstrap_requires_sign_in_without_cloud_session(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = True
            app.config.onboarding_completed = False

            with (
                patch.object(app, "_apply_shell_surface"),
                patch.object(app, "_set_signed_out_state") as set_signed_out_state,
                patch.object(app, "_set_onboarding_state") as set_onboarding_state,
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_schedule_runtime_update_check"),
                patch.object(app, "run_worker"),
                patch(
                    "ite.ui.reup.app.asyncio.to_thread",
                    AsyncMock(return_value=False),
                ),
            ):
                await app._bootstrap_after_mount()

            set_signed_out_state.assert_called_once_with(True)
            set_onboarding_state.assert_not_called()
            self.assertTrue(app._cloud_network_watch_enabled)

        asyncio.run(run_test())

    def test_mount_suppresses_workspace_hint_during_cloud_bootstrap(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = True
            refresh_states: list[bool] = []
            toggle = SimpleNamespace(display=True)

            def consume_work(work, **_kwargs):
                if asyncio.iscoroutine(work):
                    work.close()
                return None

            with (
                patch.object(app, "watch_theme"),
                patch.object(app, "query_one", return_value=toggle),
                patch.object(app, "refresh_header"),
                patch.object(app, "_set_loading_state"),
                patch.object(
                    app,
                    "_refresh_empty_state",
                    side_effect=lambda: refresh_states.append(
                        app._cloud_bootstrap_busy
                    ),
                ),
                patch.object(app, "_resize_composer_for_prompt"),
                patch.object(app, "_apply_aside_panel_state"),
                patch.object(app, "_apply_change_review_panel_state"),
                patch.object(app, "_apply_hooks_panel_state"),
                patch.object(app, "set_interval"),
                patch.object(app, "run_worker", side_effect=consume_work),
            ):
                await app.on_mount()

            self.assertEqual(refresh_states, [True])

        asyncio.run(run_test())

    def test_signed_out_surface_clears_workspace_hint_toasts(self) -> None:
        app = self._app()
        app._cloud_signed_out = True

        def widget() -> SimpleNamespace:
            return SimpleNamespace(
                display=True,
                disabled=False,
                label="",
                styles=SimpleNamespace(padding=None),
                update=lambda _value: None,
            )

        widgets = {
            "#conversation": widget(),
            "#empty-state": widget(),
            "#startup-state": widget(),
            "#signed-out-state": widget(),
            "#update-required-state": widget(),
            "#onboarding-state": widget(),
            "#session-switch-state": widget(),
            "#composer": widget(),
            "#topbar": widget(),
            "#chat-body": widget(),
            "#prompt": widget(),
            "#session-tabs-scroll": widget(),
            "#cloud-sign-in": widget(),
            "#startup-status": widget(),
            "#signed-out-copy": widget(),
            "#signed-out-status": widget(),
        }

        with (
            patch.object(
                app,
                "query_one",
                side_effect=lambda selector, *_args: widgets.get(selector, widget()),
            ),
            patch.object(app, "clear_notifications") as clear_notifications,
            patch.object(app, "_apply_aside_panel_state"),
            patch.object(app, "_apply_change_review_panel_state"),
            patch.object(app, "_apply_thread_switcher_button_state"),
            patch.object(app, "refresh_header"),
        ):
            app._apply_shell_surface()

        clear_notifications.assert_called_once()

    def test_bootstrap_clears_startup_surface_after_agent_ready(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = False
            app.config.onboarding_completed = True
            prompt = SimpleNamespace(focus=lambda: None)

            with (
                patch.object(app, "_apply_shell_surface") as apply_shell_surface,
                patch.object(app, "ensure_agent", AsyncMock()),
                patch.object(app, "_schedule_usage_meta_refresh"),
                patch.object(app, "_refresh_change_review_source", AsyncMock()),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_sync_command_palette"),
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#prompt": prompt,
                    }[selector],
                ),
            ):
                await app._bootstrap_after_mount()

            self.assertFalse(app._startup_active)
            apply_shell_surface.assert_called()

        asyncio.run(run_test())

    def test_bootstrap_posts_workspace_hint_when_agents_file_is_missing(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = False
            app.config.onboarding_completed = True
            prompt = SimpleNamespace(focus=lambda: None)
            empty_state = SimpleNamespace(display=False, update=lambda _value: None)

            with (
                patch.object(app, "_apply_shell_surface"),
                patch.object(app, "ensure_agent", AsyncMock()),
                patch.object(app, "_schedule_usage_meta_refresh"),
                patch.object(app, "_refresh_change_review_source", AsyncMock()),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_sync_command_palette"),
                patch.object(app, "post_notice") as post_notice,
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#prompt": prompt,
                        "#empty-state": empty_state,
                    }[selector],
                ),
            ):
                await app._bootstrap_after_mount()
                app._refresh_empty_state()

            post_notice.assert_called_once()
            _, message = post_notice.call_args.args
            self.assertIn("/init", message)

        asyncio.run(run_test())

    def test_bootstrap_does_not_repeat_workspace_hint_during_same_visit(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = False
            app.config.onboarding_completed = True
            prompt = SimpleNamespace(focus=lambda: None)
            empty_state = SimpleNamespace(display=False, update=lambda _value: None)

            with (
                patch.object(app, "_apply_shell_surface"),
                patch.object(app, "ensure_agent", AsyncMock()),
                patch.object(app, "_schedule_usage_meta_refresh"),
                patch.object(app, "_refresh_change_review_source", AsyncMock()),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_sync_command_palette"),
                patch.object(app, "post_notice") as post_notice,
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#prompt": prompt,
                        "#empty-state": empty_state,
                    }[selector],
                ),
            ):
                await app._bootstrap_after_mount()
                app._refresh_empty_state()
                app._refresh_empty_state()

            post_notice.assert_called_once()

        asyncio.run(run_test())

    def test_stale_workspace_hint_reappears_after_switching_away_and_back(self) -> None:
        async def run_test() -> None:
            stale_workspace = self.cwd / "stale"
            fresh_workspace = self.cwd / "fresh"
            stale_workspace.mkdir()
            fresh_workspace.mkdir()
            stale_agents = stale_workspace / "AGENTS.md"
            stale_agents.write_text("# AGENTS.md\n", encoding="utf-8")
            stale_time = datetime.now(timezone.utc) - timedelta(days=20)
            stale_timestamp = stale_time.timestamp()
            os.utime(str(stale_agents), (stale_timestamp, stale_timestamp))
            (fresh_workspace / "AGENTS.md").write_text(
                "# AGENTS.md\n", encoding="utf-8"
            )

            app = ReupApp(Config(cwd=stale_workspace))
            app.config.cloud_auth_enabled = False
            app.config.onboarding_completed = True
            prompt = SimpleNamespace(focus=lambda: None)
            title = SimpleNamespace(update=lambda _value: None)
            meta = SimpleNamespace(update=lambda _value: None)
            plan_badge = SimpleNamespace(display=True, update=lambda _value: None)
            composer_meta_line = SimpleNamespace(update=lambda _value: None)
            empty_state = SimpleNamespace(display=False, update=lambda _value: None)

            def _consume(coro, **_kwargs):
                try:
                    coro.close()
                except Exception:
                    pass
                return None

            def _query(selector, *_args):
                return {
                    "#prompt": prompt,
                    "#title": title,
                    "#plan-badge": plan_badge,
                    "#header-meta": meta,
                    "#composer-meta-line": composer_meta_line,
                    "#empty-state": empty_state,
                }[selector]

            with (
                patch.object(app, "_apply_shell_surface"),
                patch.object(app, "ensure_agent", AsyncMock()),
                patch.object(app, "_schedule_usage_meta_refresh"),
                patch.object(app, "_refresh_change_review_source", AsyncMock()),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_sync_command_palette"),
                patch.object(app, "_queue_session_tabs_refresh"),
                patch.object(app, "run_worker", side_effect=_consume),
                patch.object(app, "post_notice") as post_notice,
                patch.object(app, "query_one", side_effect=_query),
            ):
                await app._bootstrap_after_mount()
                app._refresh_empty_state()
                app.config.cwd = fresh_workspace
                app.refresh_header()
                app._refresh_empty_state()
                app.config.cwd = stale_workspace
                app.refresh_header()
                app._refresh_empty_state()

            self.assertEqual(post_notice.call_count, 2)

        asyncio.run(run_test())

    def test_new_thread_does_not_trigger_workspace_hint(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = False
            app.config.onboarding_completed = True
            app._startup_active = False
            app._suppress_agents_recommendation_once = True
            empty_state = SimpleNamespace(display=False, update=lambda _value: None)

            with (
                patch.object(app, "post_notice") as post_notice,
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#empty-state": empty_state,
                    }[selector],
                ),
            ):
                app._refresh_empty_state()

            post_notice.assert_not_called()
            self.assertFalse(app._suppress_agents_recommendation_once)

        asyncio.run(run_test())

    def test_has_valid_cloud_auth_returns_false_when_session_check_fails(self) -> None:
        config = Config(cwd=self.cwd)
        session = SimpleNamespace(api_url="http://127.0.0.1:4000")

        with (
            patch("ite.cloud.auth._load_cloud_session", return_value=session),
            patch(
                "ite.cloud.auth._verify_cloud_session",
                side_effect=CloudAuthError("network down"),
            ),
        ):
            self.assertFalse(has_valid_cloud_auth(config))

    def test_bootstrap_allows_runtime_with_stored_cloud_session(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.onboarding_completed = True
            toggle = SimpleNamespace(display=True)
            prompt = SimpleNamespace(focus=lambda: None)

            with (
                patch("ite.ui.reup.app.load_theme", return_value=None),
                patch.object(app, "refresh_header"),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "_refresh_empty_state"),
                patch.object(app, "_resize_composer_for_prompt"),
                patch.object(app, "_apply_aside_panel_state"),
                patch.object(app, "_apply_change_review_panel_state"),
                patch.object(app, "set_interval"),
                patch.object(app, "set_timer"),
                patch.object(app, "_set_startup_phase"),
                patch.object(app, "_set_startup_state"),
                patch.object(app, "_set_signed_out_state") as set_signed_out_state,
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch.object(
                    app, "_refresh_change_review_source", AsyncMock()
                ) as refresh_change_review,
                patch.object(app, "_sync_command_palette") as sync_command_palette,
                patch.object(app, "_schedule_usage_meta_refresh"),
                patch(
                    "ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=True)
                ),
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
                await app._bootstrap_after_mount()

            self.assertGreaterEqual(set_signed_out_state.call_count, 1)
            self.assertTrue(
                all(
                    call.args == (False,)
                    for call in set_signed_out_state.call_args_list
                )
            )
            ensure_agent.assert_awaited_once()
            refresh_change_review.assert_awaited_once()
            sync_command_palette.assert_called_once_with("")

        asyncio.run(run_test())

    def test_bootstrap_requires_sign_in_without_cloud_session_after_onboarding(
        self,
    ) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = True
            app.config.onboarding_completed = True

            with (
                patch.object(app, "_apply_shell_surface"),
                patch.object(app, "_set_startup_state") as set_startup_state,
                patch.object(app, "_set_signed_out_state") as set_signed_out_state,
                patch.object(app, "_set_loading_state") as set_loading_state,
                patch.object(app, "_schedule_runtime_update_check"),
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch(
                    "ite.ui.reup.app.asyncio.to_thread",
                    AsyncMock(return_value=False),
                ),
            ):
                await app._bootstrap_after_mount()

            set_startup_state.assert_called_once_with(False)
            set_signed_out_state.assert_called_once_with(True)
            set_loading_state.assert_called_once_with("idle", busy=False)
            ensure_agent.assert_not_awaited()

        asyncio.run(run_test())

    def test_cloud_logout_marks_explicit_signed_out_state(self) -> None:
        async def run_test() -> None:
            app = self._app()

            with (
                patch.object(app, "_reset_runtime_after_cloud_logout", AsyncMock()),
                patch("ite.ui.reup.app.clear_cloud_auth") as clear_auth,
                patch("ite.ui.reup.app.mark_cloud_signed_out") as mark_signed_out,
                patch.object(app, "_set_signed_out_state") as set_signed_out_state,
            ):
                await app._run_cloud_logout_flow()

            clear_auth.assert_called_once()
            mark_signed_out.assert_called_once()
            set_signed_out_state.assert_called_once_with(True)

        asyncio.run(run_test())

    def test_onboarding_submit_advances_to_next_field_before_finishing(self) -> None:
        app = self._app()
        name_input = SimpleNamespace(id="onboarding-name")
        role_select = SimpleNamespace(focus=lambda: None)

        with (
            patch.object(app, "query_one", return_value=role_select) as query_one,
            patch.object(app, "run_worker") as run_worker,
        ):
            app.on_onboarding_input_submitted(SimpleNamespace(input=name_input))

        query_one.assert_called_once_with("#onboarding-role-select", unittest.mock.ANY)
        run_worker.assert_not_called()

    def test_cloud_login_shows_onboarding_before_starting_agent(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.onboarding_completed = False
            name_input = SimpleNamespace(focus=lambda: None)
            conversation = SimpleNamespace(remove_children=AsyncMock())

            with (
                patch.object(app, "_set_signed_out_state"),
                patch.object(app, "_set_onboarding_state") as set_onboarding_state,
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
                patch.object(app, "_reset_session_local_ui_state"),
                patch(
                    "ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=None)
                ),
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#conversation": conversation,
                        "#onboarding-name": name_input,
                    }[selector],
                ),
            ):
                await app._run_cloud_login_flow()

            set_onboarding_state.assert_called_once_with(True)
            ensure_agent.assert_not_awaited()
            conversation.remove_children.assert_awaited_once()

        asyncio.run(run_test())

    def test_onboarding_submit_finishes_on_last_field(self) -> None:
        app = self._app()
        use_case_input = SimpleNamespace(id="onboarding-use-case-other")

        def _consume(coro, **_kwargs):
            coro.close()
            return None

        with patch.object(app, "run_worker", side_effect=_consume) as run_worker:
            app.on_onboarding_input_submitted(SimpleNamespace(input=use_case_input))

        run_worker.assert_called_once()

    def test_onboarding_role_select_shows_other_input_when_selected(self) -> None:
        app = self._app()
        other_input = SimpleNamespace(display=False, value="", focus=lambda: None)

        with patch.object(app, "query_one", return_value=other_input):
            app.on_onboarding_role_select_changed(
                SimpleNamespace(value=ONBOARDING_OTHER_VALUE)
            )

        self.assertTrue(other_input.display)

    def test_onboarding_role_select_hides_other_input_for_preset_choice(self) -> None:
        app = self._app()
        other_input = SimpleNamespace(
            display=True, value="Custom role", focus=lambda: None
        )
        use_case_select = SimpleNamespace(focus=lambda: None)

        with patch.object(
            app,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#onboarding-role-other": other_input,
                "#onboarding-use-case-select": use_case_select,
            }[selector],
        ):
            app.on_onboarding_role_select_changed(SimpleNamespace(value="Founder"))

        self.assertFalse(other_input.display)
        self.assertEqual(other_input.value, "")

    def test_continue_requires_remaining_onboarding_fields(self) -> None:
        async def run_test() -> None:
            app = self._app()
            status = SimpleNamespace(update=lambda _msg: None)
            name_input = SimpleNamespace(value="David", focus=lambda: None)
            role_select = SimpleNamespace(value=Select.BLANK, focus=lambda: None)
            role_other = SimpleNamespace(value="", focus=lambda: None)
            use_case_select = SimpleNamespace(value=Select.BLANK, focus=lambda: None)
            use_case_other = SimpleNamespace(value="", focus=lambda: None)

            with (
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#onboarding-status": status,
                        "#onboarding-name": name_input,
                        "#onboarding-role-select": role_select,
                        "#onboarding-role-other": role_other,
                        "#onboarding-use-case-select": use_case_select,
                        "#onboarding-use-case-other": use_case_other,
                    }[selector],
                ),
                patch.object(app, "ensure_agent", AsyncMock()) as ensure_agent,
            ):
                await app._finish_onboarding_flow(skip=False)

            ensure_agent.assert_not_awaited()

        asyncio.run(run_test())

    def test_skip_bypasses_onboarding_validation(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.agent = SimpleNamespace(session=SimpleNamespace())
            prompt = SimpleNamespace(focus=lambda: None)
            status = SimpleNamespace(update=lambda _msg: None)

            with (
                patch.object(app, "_apply_shell_surface"),
                patch.object(app, "_set_onboarding_state"),
                patch.object(app, "_refresh_empty_state"),
                patch.object(app, "_open_setup_modal", AsyncMock()) as open_setup_modal,
                patch.object(app, "post_notice") as post_notice,
                patch.object(app, "ensure_agent", AsyncMock()),
                patch(
                    "ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=None)
                ),
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#onboarding-status": status,
                        "#prompt": prompt,
                    }[selector],
                ),
            ):
                await app._finish_onboarding_flow(skip=True)

            self.assertTrue(app.config.onboarding_completed)
            open_setup_modal.assert_not_awaited()
            post_notice.assert_called_once()
            self.assertIn("/setup", post_notice.call_args.args[1])

        asyncio.run(run_test())

    def test_ensure_agent_survives_agent_field_cleared_during_enter(self) -> None:
        async def run_test() -> None:
            app = self._app()
            session = SimpleNamespace(session_id="session-race")

            class FakeAgent:
                def __init__(self) -> None:
                    self.session = session

                async def __aenter__(self):
                    app.agent = None
                    return self

            fake_agent = FakeAgent()

            with (
                patch.object(app, "_build_session_agent", return_value=fake_agent),
                patch.object(app, "_remember_open_session") as remember_open_session,
                patch.object(app, "_broadcast_remote_state", AsyncMock()),
            ):
                await app.ensure_agent()

            self.assertIs(app.agent, fake_agent)
            remember_open_session.assert_called_once_with(session, agent=fake_agent)

        asyncio.run(run_test())

    def test_tick_top_indicator_animates_onboarding_save_status(self) -> None:
        app = self._app()
        app._account_plan_is_pro = False
        app._onboarding_busy = True
        app._onboarding_skip_busy = False
        status = SimpleNamespace(value=None, update=lambda value: setattr(status, "value", value))

        with patch.object(
            app,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#onboarding-status": status,
            }[selector],
        ):
            app._tick_top_indicator()

        self.assertIn(app._top_spinner_frames[1], status.value.plain)
        self.assertIn("Saving your first-run setup", status.value.plain)

    def test_tick_top_indicator_animates_onboarding_skip_status(self) -> None:
        app = self._app()
        app._account_plan_is_pro = False
        app._onboarding_busy = True
        app._onboarding_skip_busy = True
        status = SimpleNamespace(value=None, update=lambda value: setattr(status, "value", value))

        with patch.object(
            app,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#onboarding-status": status,
            }[selector],
        ):
            app._tick_top_indicator()

        self.assertIn(app._top_spinner_frames[1], status.value.plain)
        self.assertIn("Skipping first-run setup", status.value.plain)

    def test_tick_top_indicator_animates_signed_out_status(self) -> None:
        app = self._app()
        app._account_plan_is_pro = False
        app._cloud_signed_out = True
        app._cloud_auth_busy = True
        status = SimpleNamespace(value=None, update=lambda value: setattr(status, "value", value))

        with patch.object(
            app,
            "query_one",
            side_effect=lambda selector, *_args: {
                "#signed-out-status": status,
            }[selector],
        ):
            app._tick_top_indicator()

        self.assertIn(app._top_spinner_frames[1], status.value.plain)
        self.assertIn("Opening your browser", status.value.plain)


if __name__ == "__main__":
    unittest.main()
