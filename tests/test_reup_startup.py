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
from ite.cloud.auth import has_valid_cloud_auth
from ite.client.response import TokenUsage
from ite.config.config import Config
from textual.widgets import Select

from ite.ui.reup.app import ONBOARDING_OTHER_VALUE, ReupApp


class ReupStartupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def _app(self) -> ReupApp:
        return ReupApp(Config(cwd=self.cwd))

    def test_app_init_defers_command_registry_build(self) -> None:
        with patch("ite.ui.reup.app.build_registry") as build_registry:
            ReupApp(Config(cwd=self.cwd))

        build_registry.assert_not_called()

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

    def test_on_mount_uses_detected_light_theme_when_still_on_default_dark(self) -> None:
        async def run_test() -> None:
            with patch("ite.ui.reup.app.detect_host_textual_theme", return_value="textual-light"):
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

    def test_remote_command_requires_bundled_access_before_starting_bridge(self) -> None:
        async def run_test() -> None:
            app = self._app()

            with (
                patch.object(app, "_has_remote_companion_access", AsyncMock(return_value=False)),
                patch.object(app, "post_system") as post_system,
                patch.object(app, "_ensure_remote_server", AsyncMock()) as ensure_remote_server,
            ):
                await app._run_remote_command_native(["on"])

            ensure_remote_server.assert_not_awaited()
            post_system.assert_called_once()
            self.assertIn("bundled access", post_system.call_args.args[1])

        asyncio.run(run_test())

    def test_perform_quit_does_not_hang_on_remote_shutdown(self) -> None:
        async def run_test() -> None:
            app = self._app()

            async def _never_finishes() -> None:
                await asyncio.sleep(10)

            app._remote_server = SimpleNamespace(stop=AsyncMock(side_effect=_never_finishes))

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
                patch.object(app, "generate_session_name", AsyncMock()) as generate_name,
                patch.object(app, "refresh_header"),
                patch.object(app, "_shutdown_remote_server", AsyncMock()),
                patch.object(app, "_shutdown_agents", AsyncMock()),
                patch.object(app, "exit"),
                patch("ite.ui.reup.app.SessionManager") as session_manager,
            ):
                await app._perform_quit()

            generate_name.assert_not_awaited()
            self.assertEqual(session.name, "Investigate exit bug")
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

    def test_bootstrap_does_not_show_onboarding_before_cloud_auth_verifies(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.cloud_auth_enabled = True
            app.config.onboarding_completed = False

            with (
                patch.object(app, "_apply_shell_surface"),
                patch.object(app, "_set_signed_out_state") as set_signed_out_state,
                patch.object(app, "_set_onboarding_state") as set_onboarding_state,
                patch.object(app, "_set_loading_state"),
                patch.object(app, "run_worker"),
                patch(
                    "ite.ui.reup.app.asyncio.to_thread",
                    AsyncMock(return_value=False),
                ),
            ):
                await app._bootstrap_after_mount()

            set_onboarding_state.assert_not_called()
            set_signed_out_state.assert_called_once_with(True)

        asyncio.run(run_test())

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
            (fresh_workspace / "AGENTS.md").write_text("# AGENTS.md\n", encoding="utf-8")

            app = ReupApp(Config(cwd=stale_workspace))
            app.config.cloud_auth_enabled = False
            app.config.onboarding_completed = True
            prompt = SimpleNamespace(focus=lambda: None)
            title = SimpleNamespace(update=lambda _value: None)
            meta = SimpleNamespace(update=lambda _value: None)
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

    def test_on_mount_treats_missing_cloud_session_as_signed_out(self) -> None:
        async def run_test() -> None:
            app = self._app()
            toggle = SimpleNamespace(display=True)

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
                patch.object(app, "_refresh_change_review_source", AsyncMock()) as refresh_change_review,
                patch.object(app, "_sync_command_palette") as sync_command_palette,
                patch("ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=False)),
                patch.object(
                    app,
                    "query_one",
                    side_effect=lambda selector, *_args: {
                        "#aside-toggle": toggle,
                        "#changes-toggle": toggle,
                    }[selector],
                ),
            ):
                await app._bootstrap_after_mount()

            set_signed_out_state.assert_called_once_with(True)
            ensure_agent.assert_not_awaited()
            refresh_change_review.assert_not_awaited()
            sync_command_palette.assert_not_called()

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
                patch("ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=None)),
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
        other_input = SimpleNamespace(display=True, value="Custom role", focus=lambda: None)
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
                patch.object(app, "_open_setup_modal", AsyncMock()),
                patch.object(app, "ensure_agent", AsyncMock()),
                patch("ite.ui.reup.app.asyncio.to_thread", AsyncMock(return_value=None)),
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

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
