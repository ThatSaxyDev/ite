import unittest
import asyncio
from datetime import datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, PropertyMock, patch
from types import SimpleNamespace

from rich.console import Console
from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.agent.session import Session
from ite.config.config import Config
from ite.cloud.auth import BundledModelsResult, CloudAuthStatus, CloudSessionState
from ite.client.response import TokenUsage
from ite.agent.session_manager import SessionSnapshot
from ite.ui.reup.app import ReupApp
from ite.ui.reup.markdown_widget import CopyableMarkdown
from ite.ui.reup.modals import ConfirmModal
from ite.ui.reup.adapters.registry import StreamingCommandOutput
from ite.ui.reup.tool_views import collapse_terminal_rewrites, render_shell_result_payload, render_skills_payload
from ite.ui.reup.tool_views import shell_session_state, split_shell_payload
from rich.table import Table
from textual.widgets import Static


class ReupCommandPaletteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def _app(self) -> ReupApp:
        return ReupApp(Config(cwd=self.cwd, api_key="test-key"))

    def _bundled_models_result(
        self, models: list[dict[str, object]]
    ) -> BundledModelsResult:
        return BundledModelsResult(
            models=models,
            auth=CloudAuthStatus(state=CloudSessionState.VALID),
        )

    def test_extract_slash_query_only_when_editing_first_token(self) -> None:
        self.assertEqual(ReupApp._extract_slash_query("/ap"), "/ap")
        self.assertEqual(ReupApp._extract_slash_query("   /ap"), "/ap")
        self.assertIsNone(ReupApp._extract_slash_query("hello"))
        self.assertIsNone(ReupApp._extract_slash_query("/approval auto"))
        self.assertIsNone(ReupApp._extract_slash_query("/approval\nauto"))

    def test_extract_at_query_only_when_editing_trailing_token(self) -> None:
        self.assertEqual(ReupApp._extract_at_query("@"), "")
        self.assertEqual(ReupApp._extract_at_query("inspect @sr"), "sr")
        self.assertEqual(ReupApp._extract_at_query("inspect @screenshot 2021"), "screenshot 2021")
        self.assertIsNone(ReupApp._extract_at_query("inspect @src/app.py now"))
        self.assertIsNone(ReupApp._extract_at_query("inspect\n@src"))

    def test_internal_todo_event_detection_matches_seeded_checklist_ids(self) -> None:
        self.assertTrue(ReupApp._is_internal_todo_event("todos_exec_seed_abcd1234"))
        self.assertTrue(ReupApp._is_internal_todo_event("todos_exec_progress_abcd1234"))
        self.assertTrue(ReupApp._is_internal_todo_event("todos_seed_abcd1234"))
        self.assertFalse(ReupApp._is_internal_todo_event("manual_todos_call"))

    def test_plan_intent_requires_explicit_plan_language(self) -> None:
        app = self._app()

        non_plan_messages = [
            "build a dashboard for usage metrics",
            "let's build the remote status view",
            "create a small API endpoint",
            "what steps should we take next",
            "outline the current auth code",
        ]
        for message in non_plan_messages:
            with self.subTest(message=message):
                self.assertFalse(app._detect_plan_intent(message))

        plan_messages = [
            "let's plan the remote cleanup",
            "make a plan before coding this",
            "create an implementation plan",
            "planning first, then implementation",
            "outline the plan for auth",
        ]
        for message in plan_messages:
            with self.subTest(message=message):
                self.assertTrue(app._detect_plan_intent(message))

    def test_confirm_modal_primary_no_makes_enter_choose_no(self) -> None:
        modal = ConfirmModal(
            title="Enable Plan Mode?",
            body="Use Plan mode or send normally?",
            yes_label="Use plan mode",
            no_label="Send normally",
            primary="no",
        )
        dismissed: list[bool] = []
        modal.dismiss = dismissed.append  # type: ignore[method-assign]

        modal.action_accept()
        modal.action_yes()
        modal.action_no()
        modal.action_option_1()
        modal.action_option_2()

        self.assertEqual(dismissed, [False, True, False, True, False])

    def test_confirm_modal_global_enter_respects_primary_no(self) -> None:
        app = self._app()
        modal = ConfirmModal(
            title="Enable Plan Mode?",
            body="Use Plan mode or send normally?",
            yes_label="Use plan mode",
            no_label="Send normally",
            primary="no",
        )
        dismissed: list[bool] = []
        modal.dismiss = dismissed.append  # type: ignore[method-assign]

        class DummyEvent:
            key = "enter"
            stopped = False
            default_prevented = False

            def stop(self) -> None:
                self.stopped = True

            def prevent_default(self) -> None:
                self.default_prevented = True

        event = DummyEvent()
        with patch.object(
            ReupApp, "screen_stack", new_callable=PropertyMock, return_value=[modal]
        ):
            app.on_key(event)  # type: ignore[arg-type]

        self.assertEqual(dismissed, [False])
        self.assertTrue(event.stopped)
        self.assertTrue(event.default_prevented)

    def test_plan_intent_modal_defaults_to_send_normally(self) -> None:
        async def run_test() -> None:
            app = self._app()
            session = SimpleNamespace(
                plan_mode_enabled=False,
                set_plan_mode=unittest.mock.Mock(),
                set_plan_phase=unittest.mock.Mock(),
            )
            app.agent = SimpleNamespace(session=session)

            with patch.object(app, "ensure_agent", AsyncMock()), patch.object(
                app, "_open_modal", AsyncMock(return_value=False)
            ) as open_modal:
                result = await app._apply_intent_assist("let's plan the remote cleanup")

            self.assertEqual(result, "let's plan the remote cleanup")
            session.set_plan_mode.assert_not_called()
            modal = open_modal.call_args.args[0]
            self.assertEqual(modal._yes, "Use plan mode")
            self.assertEqual(modal._no, "Send normally")
            self.assertEqual(modal._primary, "no")

        asyncio.run(run_test())

    def test_loading_state_ignores_remote_broadcast_after_app_stops(self) -> None:
        app = self._app()

        with patch.object(
            app, "run_worker", side_effect=RuntimeError("App is not running")
        ):
            app._set_loading_state("thinking", busy=True)

        self.assertEqual(app._top_state_text, "thinking")
        self.assertTrue(app._top_busy)

    def test_cancel_active_turn_resolves_pending_plan_question(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app._active_turn_task = asyncio.create_task(asyncio.sleep(10))
            app._is_turn_running = True
            plan_question_future = asyncio.get_running_loop().create_future()
            app._plan_question_future = plan_question_future

            with patch.object(app, "_clear_inflight_turn_ui", AsyncMock()), patch.object(
                app, "_set_loading_state"
            ), patch.object(app, "_broadcast_remote_state", AsyncMock()):
                await app.cancel_active_turn()

            self.assertEqual(
                plan_question_future.result(),
                {"selected_option": "", "free_text": "", "selected_index": None},
            )
            self.assertIsNone(app._plan_question_future)
            self.assertIsNone(app._active_turn_task)
            self.assertFalse(app._is_turn_running)

        asyncio.run(run_test())

    def test_filtered_command_palette_matches_registry_commands(self) -> None:
        app = self._app()

        slash_only = app._filtered_command_palette("/")
        filtered = app._filtered_command_palette("/ap")

        self.assertTrue(slash_only)
        self.assertEqual(slash_only, sorted(slash_only, key=lambda entry: entry.name.lower()))
        self.assertGreater(len(slash_only), 8)
        # /activity and /approval are alphabetically first
        self.assertIn(slash_only[0].name, ["/activity", "/approval"])
        self.assertIn("/publish", [entry.name for entry in slash_only])
        self.assertIn("/theme", [entry.name for entry in slash_only])
        self.assertEqual([entry.name for entry in filtered], ["/approval"])
        self.assertEqual(filtered[0].description, "Show or change approval mode")

    def test_filtered_command_palette_can_find_theme_command(self) -> None:
        app = self._app()

        filtered = app._filtered_command_palette("/theme")

        self.assertEqual([entry.name for entry in filtered], ["/theme"])
        self.assertEqual(
            filtered[0].description,
            "Choose a Textual theme for this session",
        )

    def test_filtered_attachment_palette_matches_workspace_files(self) -> None:
        app = self._app()
        (self.cwd / "src").mkdir()
        (self.cwd / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")

        filtered = app._filtered_attachment_palette("inspect @src/a")

        self.assertEqual([entry.name for entry in filtered[:1]], ["@src/app.py"])
        self.assertEqual(filtered[0].insert_text, "@src/app.py")

    def test_attachment_ref_for_path_quotes_spaces_and_uses_absolute_outside_workspace(self) -> None:
        app = self._app()
        inside = self.cwd / "shot one.png"
        inside.write_text("x", encoding="utf-8")

        with TemporaryDirectory() as other:
            outside = Path(other) / "report one.pdf"
            outside.write_text("x", encoding="utf-8")

            self.assertEqual(app._attachment_ref_for_path(inside), '@"shot one.png"')
            self.assertEqual(
                app._attachment_ref_for_path(outside),
                f'@"{outside.resolve()}"',
            )

    def test_insert_attachment_refs_into_prompt_uses_visible_refs(self) -> None:
        app = self._app()
        sample = self.cwd / "Screenshot 2021.png"
        sample.write_text("x", encoding="utf-8")

        class DummyPrompt:
            def __init__(self) -> None:
                self.text = "check this"

            def load_text(self, value: str) -> None:
                self.text = value

            def move_cursor(self, _cursor) -> None:
                return None

        prompt = DummyPrompt()
        with patch.object(app, "query_one", return_value=prompt), patch.object(
            app, "_sync_command_palette"
        ), patch.object(app, "_resize_composer_for_prompt"):
            added = app._insert_attachment_refs_into_prompt([str(sample)])

        self.assertEqual(added, 1)
        self.assertIn('@"Screenshot 2021.png"', prompt.text)

    def test_build_command_result_renderable_omits_generic_label(self) -> None:
        app = self._app()

        rendered = app._build_command_result_renderable("Installed skills: critique")
        text = "".join(getattr(part, "plain", str(part)) for part in rendered.renderables)

        self.assertIn("Installed skills: critique", text)
        self.assertNotIn("slash command result", text)

    def test_build_command_title_widget_separates_kicker_and_name(self) -> None:
        app = self._app()

        title = app._build_command_title_widget("/tools")

        self.assertIn("command-title-row", title.classes)
        children = list(getattr(title, "_pending_children", []))
        self.assertEqual(len(children), 2)
        self.assertEqual(getattr(children[0], "_Static__content", None), "command")
        self.assertEqual(getattr(children[1], "_Static__content", None), "/tools")

    def test_post_native_command_result_marks_stats_cards_for_theme_rerender(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(
            session=SimpleNamespace(
                get_stats=lambda: {
                    "session_id": "s1",
                    "last_compacted_at": "",
                    "token_usage": {},
                    "context_window": 0,
                    "latest_tokens": 0,
                    "latest_cached_tokens": 0,
                    "context_used_pct": 0.0,
                    "context_left_pct": 0.0,
                    "turn_count": 0,
                    "message_count": 0,
                    "compaction_count": 0,
                    "pruned_tool_msgs": 0,
                    "plan_mode_enabled": False,
                    "plan_phase": "idle",
                    "plan_questions_asked": 0,
                    "plan_target_questions": 0,
                    "active_plan_available": False,
                    "pending_plan_available": False,
                    "pending_attachments": 0,
                    "active_skills": 0,
                    "available_skills": 0,
                    "tools_enabled": 0,
                    "mcp_servers": 0,
                }
            )
        )

        with patch.object(app, "run_worker") as run_worker, patch.object(
            app, "add_assistant_card", AsyncMock()
        ) as add_card:
            posted = app._post_native_command_result("/stats", [])
            scheduled = run_worker.call_args.args[0]

        self.assertTrue(posted)
        run_worker.assert_called_once()
        self.assertEqual(run_worker.call_args.kwargs["exclusive"], False)
        add_card.assert_called_once()
        self.assertEqual(add_card.call_args.kwargs["css_class"], "command")
        self.assertEqual(add_card.call_args.kwargs["extra_classes"], "stats")
        scheduled.close()

    def test_build_remote_command_feed_metadata_serializes_workboard(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(
            session=SimpleNamespace(
                plan_mode_enabled=True,
                plan_phase="implementing",
                show_planning_todos=True,
                export_todos_state=lambda: {
                    "execution": [
                        {"content": "Ship fix", "completed": False},
                        {"content": "Verify theme refresh", "completed": True},
                    ],
                    "planning": [
                        {"content": "Review remote card", "completed": False},
                    ],
                },
                current_plan_text=lambda: "1. Patch Reup\n2. Verify remote feed",
            )
        )

        metadata = app._build_remote_command_feed_metadata(
            "/workboard",
            [],
            "Loaded workboard.",
        )

        self.assertEqual(metadata["kind"], "workboard")
        self.assertEqual(metadata["summary"]["completed"], 1)
        self.assertEqual(metadata["summary"]["pending"], 2)
        self.assertEqual(metadata["summary"]["total"], 3)
        self.assertEqual(len(metadata["checklists"]), 2)
        self.assertEqual(metadata["checklists"][0]["scope"], "execution")
        self.assertEqual(
            metadata["checklists"][0]["pending_items"],
            ["Ship fix"],
        )
        self.assertEqual(
            metadata["checklists"][0]["completed_items"],
            ["Verify theme refresh"],
        )
        self.assertEqual(metadata["plan_text"], "1. Patch Reup\n2. Verify remote feed")

    def test_run_command_starts_remote_feed_for_workboard_native_card(self) -> None:
        app = self._app()

        with patch.object(
            app, "_start_remote_command_feed_entry", return_value="cmd-7"
        ) as start_feed, patch.object(
            app, "_run_workboard_command_native", AsyncMock()
        ) as run_workboard:
            asyncio.run(app.run_command("/workboard"))

        start_feed.assert_called_once_with("/workboard")
        run_workboard.assert_awaited_once_with(command_feed_id="cmd-7")

    def test_build_command_result_renderable_dims_box_lines(self) -> None:
        app = self._app()

        rendered = app._build_command_result_renderable("title\n│────│\nvalue")
        renderables = list(rendered.renderables)

        self.assertEqual(len(renderables), 3)
        self.assertEqual(renderables[1].style, app._render_styles()["muted"])

    def test_update_tool_call_list_dir_renders_without_missing_style_locals(self) -> None:
        async def run_test() -> None:
            app = self._app()
            call_id = "call_list_dir_1"
            card = Static()
            app._tool_widgets[call_id] = card
            app._tool_args_by_call_id[call_id] = {"path": str(self.cwd)}

            with (
                patch.object(app, "query_one", return_value=SimpleNamespace()),
                patch.object(app, "_pin_activity_indicator_to_end", AsyncMock()) as pin_end,
            ):
                await app.update_tool_call(
                    call_id=call_id,
                    name="list_dir",
                    tool_kind="read",
                    success=True,
                    output="🗂️ src/\n📄 README.md",
                    error=None,
                    metadata={
                        "path": str(self.cwd),
                        "entries": 2,
                        "tool_name": "list_dir",
                        "tool_metadata": {
                            "mutating": False,
                            "risk_level": "low",
                            "allowed_in_plan_mode": True,
                            "supports_subagent_use": True,
                            "output_schema": {"type": "string"},
                        },
                    },
                    diff=None,
                    truncated=False,
                    exit_code=None,
                )

            pin_end.assert_awaited_once()
            self.assertIn("success", card.classes)

        asyncio.run(run_test())

    def test_composer_meta_text_includes_context_meter(self) -> None:
        app = self._app()
        session = SimpleNamespace(
            plan_mode_enabled=False,
            context_manager=SimpleNamespace(),
            get_stats=lambda: {"context_used_pct": 42.4},
        )
        app.agent = SimpleNamespace(session=session)

        rendered = app._composer_meta_text()

        self.assertIn("context", rendered.plain)
        self.assertNotEqual(app._composer_context_hitbox, (0, 0))

    def test_composer_meta_text_does_not_fetch_bundled_models_during_render(self) -> None:
        app = self._app()
        app.config.model_name = "kimi-k2.6:cloud"
        app.config.model.source_kind = "custom"
        session = SimpleNamespace(
            plan_mode_enabled=False,
            context_manager=SimpleNamespace(),
            get_stats=lambda: {"context_used_pct": 42.4},
        )
        app.agent = SimpleNamespace(session=session)

        with patch("ite.ui.reup.app.get_bundled_models_result") as get_bundled_models:
            rendered = app._composer_meta_text()

        self.assertIn("kimi-k2.6", rendered.plain)
        get_bundled_models.assert_not_called()

    def test_refresh_bundled_models_cache_migrates_legacy_bundled_selection(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "glm-5.1:cloud"
            app.config.model.source_kind = None
            app.config.api_key = ""
            app.config.base_url = ""

            with patch(
                "ite.ui.reup.app.get_bundled_models_result",
                return_value=self._bundled_models_result(
                    [{"model_name": "z-ai/glm-5.1", "label": "GLM-5.1"}]
                ),
            ), patch(
                "ite.ui.reup.app.load_saved_custom_provider", return_value={}
            ), patch(
                "ite.ui.reup.app.save_system_config"
            ) as save_system_config, patch.object(app, "refresh_header"):
                await app._refresh_bundled_models_cache()

            _, kwargs = save_system_config.call_args
            self.assertEqual(kwargs["model_name"], "z-ai/glm-5.1")
            self.assertEqual(kwargs["source_kind"], "bundled")
            self.assertEqual(app.config.model.name, "z-ai/glm-5.1")
            self.assertEqual(app.config.model.source_kind, "bundled")

        asyncio.run(run_test())

    def test_open_model_picker_uses_cached_bundled_models_without_refetch(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app._bundled_models_cache = [
                {"model_name": "minimax/minimax-m2.7", "label": "MiniMax M2.7"}
            ]
            app.config.model.name = "minimax/minimax-m2.7"
            app.config.model.source_kind = "bundled"

            async def fake_open_modal(_modal):
                return None

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.load_saved_custom_provider", return_value={}
            ), patch(
                "ite.ui.reup.app.get_bundled_models_result"
            ) as get_bundled_models, patch.object(
                app, "_open_modal", AsyncMock(side_effect=fake_open_modal)
            ):
                await app._open_model_picker_from_meta()

            get_bundled_models.assert_not_called()

        asyncio.run(run_test())

    def test_open_usage_modal_uses_cached_summary_without_refetch(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "minimax/minimax-m2.7"
            app.config.model.source_kind = "bundled"
            app._bundled_models_cache = [
                {"model_name": "minimax/minimax-m2.7", "label": "MiniMax M2.7"}
            ]
            app._usage_summary_cache = {
                "quotas": {"fiveHour": {"usedUsdCents": 12, "capUsdCents": 20}}
            }

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.get_usage_summary"
            ) as get_usage_summary, patch.object(
                app, "_open_modal", AsyncMock(return_value=None)
            ), patch.object(
                app, "run_worker", side_effect=lambda coro, **_kwargs: coro.close()
            ), patch.object(
                app, "refresh_header"
            ):
                await app._open_usage_modal_from_meta()

            get_usage_summary.assert_not_called()

        asyncio.run(run_test())

    def test_open_activity_modal_uses_cached_payload_without_refetch(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app._activity_cache = {"totals": {}, "daily": [], "by_model": []}

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.get_activity"
            ) as get_activity, patch.object(
                app, "_open_modal", AsyncMock(return_value=None)
            ), patch.object(
                app, "run_worker", side_effect=lambda coro, **_kwargs: coro.close()
            ):
                await app._open_activity_modal_from_meta()

            get_activity.assert_not_called()

        asyncio.run(run_test())

    def test_composer_meta_text_shows_usage_for_canonical_bundled_model(self) -> None:
        app = self._app()
        app.config.model_name = "minimax/minimax-m2.7"
        app.config.model.source_kind = "bundled"
        app.config.api_key = ""
        app.config.base_url = ""
        session = SimpleNamespace(
            plan_mode_enabled=False,
            context_manager=SimpleNamespace(),
            get_stats=lambda: {"context_used_pct": 42.4},
        )
        app.agent = SimpleNamespace(session=session)

        with patch(
            "ite.ui.reup.app.get_bundled_models_result",
            return_value=[{"model_name": "minimax/minimax-m2.7", "label": "MiniMax M2.7"}],
        ), patch("ite.ui.reup.app.load_saved_custom_provider", return_value={}):
            rendered = app._composer_meta_text()

        self.assertIn("usage", rendered.plain)
        self.assertIsNotNone(app._composer_usage_hitbox)
        assert app._composer_usage_hitbox is not None
        self.assertGreater(app._composer_usage_hitbox[1], app._composer_usage_hitbox[0])

    def test_composer_meta_text_clamps_context_drop_during_active_turn(self) -> None:
        app = self._app()
        session = SimpleNamespace(
            plan_mode_enabled=False,
            context_manager=SimpleNamespace(),
            get_stats=lambda: {"context_used_pct": 22.0},
        )
        app.agent = SimpleNamespace(session=session)
        app._run_state().context_meter_floor_pct = 62

        rendered = app._composer_meta_text()

        self.assertIn("context 62%", rendered.plain)

    def test_composer_meta_click_opens_context_modal(self) -> None:
        app = self._app()
        app._composer_attach_hitbox = (0, 0)
        app._composer_model_hitbox = (0, 0)
        app._composer_branch_hitbox = (0, 0)
        app._composer_usage_hitbox = (0, 0)
        app._composer_context_hitbox = (10, 20)
        app._composer_activity_hitbox = (0, 0)
        app._composer_plan_hitbox = (0, 0)

        event = SimpleNamespace(x=12, stop=lambda: None)

        with patch.object(app, "run_worker") as run_worker, patch.object(
            app, "_open_context_modal_from_meta", return_value=None
        ):
            app.on_composer_meta_line_click(event)

        run_worker.assert_called_once()

    def test_live_context_meter_tick_updates_only_while_turn_running(self) -> None:
        app = self._app()

        with patch.object(app, "_update_composer_meta_line") as update_meta, patch.object(
            ReupApp, "is_mounted", new_callable=PropertyMock, return_value=True
        ):
            app._is_turn_running = False
            app._tick_live_context_meter()
            update_meta.assert_not_called()

            app._is_turn_running = True
            app._tick_live_context_meter()
            update_meta.assert_called_once()

    def test_open_model_picker_passes_availability_metadata_and_warns_when_current_bundled_model_is_down(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "minimax/minimax-m2.7"
            app.config.model.source_kind = "bundled"

            async def fake_open_modal(modal):
                self.assertEqual(modal._models[0]["model_name"], "minimax/minimax-m2.7")
                self.assertFalse(modal._models[0]["available"])
                self.assertEqual(
                    modal._models[0]["unavailable_reason"],
                    "Local bundled provider returned 500.",
                )
                self.assertTrue(modal._models[1]["available"])
                return None

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.load_saved_custom_provider", return_value={}
            ), patch(
                "ite.ui.reup.app.get_bundled_models_result",
                return_value=self._bundled_models_result([
                    {
                        "model_name": "minimax/minimax-m2.7",
                        "label": "MiniMax M2.7",
                        "provider": "Bundled",
                        "available": False,
                        "unavailable_reason": "Local bundled provider returned 500.",
                    },
                    {
                        "model_name": "z-ai/glm-5",
                        "label": "GLM-5",
                        "provider": "Bundled",
                        "available": True,
                        "unavailable_reason": "",
                    },
                ]),
            ), patch.object(app, "_open_modal", AsyncMock(side_effect=fake_open_modal)), patch.object(
                app, "post_system"
            ) as post_system:
                await app._open_model_picker_from_meta()

            post_system.assert_not_called()

        asyncio.run(run_test())

    def test_open_model_picker_marks_invalid_cloud_session_signed_out(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "minimax/minimax-m2.7"
            app.config.model.source_kind = "bundled"

            result = BundledModelsResult(
                models=[],
                auth=CloudAuthStatus(
                    state=CloudSessionState.INVALID,
                    message="Stored iTE Cloud session is expired or revoked.",
                ),
                message="Stored iTE Cloud session is expired or revoked.",
            )

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.get_bundled_models_result",
                return_value=result,
            ), patch(
                "ite.ui.reup.app.clear_cloud_auth"
            ) as clear_auth, patch.object(
                app, "_set_signed_out_state"
            ) as set_signed_out, patch.object(
                app, "post_system"
            ) as post_system, patch.object(
                app, "_open_modal", AsyncMock()
            ) as open_modal:
                await app._open_model_picker_from_meta()

            clear_auth.assert_called_once_with(revoke_remote=False)
            set_signed_out.assert_called_once_with(True)
            post_system.assert_called_once()
            open_modal.assert_not_awaited()

        asyncio.run(run_test())

    def test_open_model_picker_includes_saved_custom_provider_when_current_model_is_bundled(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "minimax/minimax-m2.7"
            app.config.model.source_kind = "bundled"

            async def fake_open_modal(modal):
                self.assertEqual(modal._models[0]["model_name"], "unsloth/gemma-4-E4B-it-UD-MLX-4bit")
                self.assertEqual(modal._models[0]["provider"], "localhost")
                self.assertTrue(modal._models[0]["saved_profile"])
                self.assertEqual(modal._models[0]["context_window"], 131072)
                self.assertEqual(modal._models[1]["model_name"], "minimax/minimax-m2.7")
                return None

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.load_saved_custom_provider",
                return_value={
                    "unsloth/gemma-4-E4B-it-UD-MLX-4bit": {
                        "api_key": "custom-key",
                        "base_url": "http://localhost:8080",
                        "model_name": "unsloth/gemma-4-E4B-it-UD-MLX-4bit",
                        "context_window": 131072,
                    }
                },
            ), patch(
                "ite.ui.reup.app.get_bundled_models_result",
                return_value=self._bundled_models_result([
                    {
                        "model_name": "minimax/minimax-m2.7",
                        "label": "MiniMax M2.7",
                        "provider": "Bundled",
                        "available": True,
                        "unavailable_reason": "",
                    }
                ]),
            ), patch.object(app, "_open_modal", AsyncMock(side_effect=fake_open_modal)):
                await app._open_model_picker_from_meta()

        asyncio.run(run_test())

    def test_open_model_picker_keeps_bundled_and_saved_entries_distinct_when_names_match(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "z-ai/glm-5.1"
            app.config.model.source_kind = "bundled"
            app.config.api_key = ""
            app.config.base_url = ""

            async def fake_open_modal(modal):
                self.assertEqual(len(modal._models), 2)
                self.assertEqual(modal._models[0]["model_name"], "z-ai/glm-5.1")
                self.assertEqual(modal._models[0]["provider"], "Bundled")
                self.assertFalse(modal._models[0]["saved_profile"])
                self.assertEqual(modal._models[1]["model_name"], "z-ai/glm-5.1")
                self.assertEqual(modal._models[1]["provider"], "OpenRouter")
                self.assertTrue(modal._models[1]["saved_profile"])
                return {"action": "select", "entry_id": "saved:z-ai/glm-5.1"}

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.load_saved_custom_provider",
                return_value={
                    "z-ai/glm-5.1": {
                        "api_key": "openrouter-key",
                        "base_url": "https://openrouter.ai/api/v1",
                        "model_name": "z-ai/glm-5.1",
                        "context_window": 196608,
                    }
                },
            ), patch(
                "ite.ui.reup.app.get_bundled_models_result",
                return_value=self._bundled_models_result([
                    {
                        "model_name": "z-ai/glm-5.1",
                        "label": "GLM-5.1",
                        "provider": "Bundled",
                        "available": True,
                        "unavailable_reason": "",
                    }
                ]),
            ), patch(
                "ite.ui.reup.app.save_system_config"
            ) as save_system_config, patch.object(
                app, "_open_modal", AsyncMock(side_effect=fake_open_modal)
            ), patch.object(app, "refresh_header"), patch.object(app, "post_notice"):
                await app._open_model_picker_from_meta()

            _, kwargs = save_system_config.call_args
            self.assertEqual(kwargs["api_key"], "openrouter-key")
            self.assertEqual(kwargs["base_url"], "https://openrouter.ai/api/v1")
            self.assertEqual(kwargs["model_name"], "z-ai/glm-5.1")

        asyncio.run(run_test())

    def test_open_model_picker_keeps_bundled_and_saved_entries_distinct_for_minimax_free(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "minimax/minimax-m2.5:free"
            app.config.model.source_kind = "bundled"
            app.config.api_key = ""
            app.config.base_url = ""

            async def fake_open_modal(modal):
                self.assertEqual(len(modal._models), 2)
                self.assertEqual(modal._models[0]["model_name"], "minimax/minimax-m2.5:free")
                self.assertEqual(modal._models[0]["provider"], "Bundled")
                self.assertFalse(modal._models[0]["saved_profile"])
                self.assertEqual(modal._models[1]["model_name"], "minimax/minimax-m2.5:free")
                self.assertEqual(modal._models[1]["provider"], "OpenRouter")
                self.assertTrue(modal._models[1]["saved_profile"])
                return {"action": "select", "entry_id": "saved:minimax/minimax-m2.5:free"}

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.load_saved_custom_provider",
                return_value={
                    "minimax/minimax-m2.5:free": {
                        "api_key": "openrouter-key",
                        "base_url": "https://openrouter.ai/api/v1",
                        "model_name": "minimax/minimax-m2.5:free",
                        "context_window": 196608,
                    }
                },
            ), patch(
                "ite.ui.reup.app.get_bundled_models_result",
                return_value=self._bundled_models_result([
                    {
                        "model_name": "minimax/minimax-m2.5:free",
                        "label": "MiniMax M2.5 (free)",
                        "provider": "Bundled",
                        "available": True,
                        "unavailable_reason": "",
                    }
                ]),
            ), patch(
                "ite.ui.reup.app.save_system_config"
            ) as save_system_config, patch.object(
                app, "_open_modal", AsyncMock(side_effect=fake_open_modal)
            ), patch.object(app, "refresh_header"), patch.object(app, "post_notice"):
                await app._open_model_picker_from_meta()

            _, kwargs = save_system_config.call_args
            self.assertEqual(kwargs["api_key"], "openrouter-key")
            self.assertEqual(kwargs["base_url"], "https://openrouter.ai/api/v1")
            self.assertEqual(kwargs["model_name"], "minimax/minimax-m2.5:free")

        asyncio.run(run_test())

    def test_open_model_picker_preserves_ollama_cloud_named_model_as_saved_byok(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "minimax-m2.5:cloud"
            app.config.model.source_kind = "saved"
            app.config.api_key = "ollama"
            app.config.base_url = "http://localhost:11434/v1"
            session_config = Config(
                cwd=self.cwd,
                model={"name": "minimax-m2.5:cloud", "source_kind": "saved"},
                api_key="ollama",
                base_url="http://localhost:11434/v1",
            )
            app.agent = SimpleNamespace(
                session=SimpleNamespace(
                    config=session_config,
                    client=SimpleNamespace(close=AsyncMock()),
                )
            )

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.load_saved_custom_provider",
                return_value={
                    "minimax-m2.5:cloud": {
                        "api_key": "ollama",
                        "base_url": "http://localhost:11434/v1",
                        "model_name": "minimax-m2.5:cloud",
                        "context_window": 200000,
                    }
                },
            ), patch(
                "ite.ui.reup.app.get_bundled_models_result",
                return_value=self._bundled_models_result([
                    {
                        "model_name": "minimax/minimax-m2.5",
                        "label": "MiniMax M2.5",
                        "provider": "Bundled",
                        "available": True,
                        "unavailable_reason": "",
                    }
                ]),
            ), patch(
                "ite.ui.reup.app.save_system_config"
            ) as save_system_config, patch.object(
                app,
                "_open_modal",
                AsyncMock(
                    return_value={
                        "action": "select",
                        "entry_id": "saved:minimax-m2.5:cloud",
                        "model_name": "minimax-m2.5:cloud",
                        "source_kind": "saved",
                    }
                ),
            ), patch.object(app, "refresh_header"), patch.object(app, "post_notice"):
                await app._open_model_picker_from_meta()

            save_system_config.assert_not_called()
            self.assertEqual(app.config.model.source_kind, "saved")
            self.assertEqual(app.config.api_key, "ollama")
            self.assertEqual(app.config.base_url, "http://localhost:11434/v1")
            self.assertEqual(session_config.model.source_kind, "saved")
            self.assertEqual(session_config.api_key, "ollama")
            self.assertEqual(session_config.base_url, "http://localhost:11434/v1")

        asyncio.run(run_test())

    def test_open_model_picker_selects_bundled_minimax_without_byok_credentials(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "minimax-m2.5:cloud"
            app.config.model.source_kind = "saved"
            app.config.api_key = "ollama"
            app.config.base_url = "http://localhost:11434/v1"
            session_config = Config(
                cwd=self.cwd,
                model={"name": "minimax-m2.5:cloud", "source_kind": "saved"},
                api_key="ollama",
                base_url="http://localhost:11434/v1",
            )
            app.agent = SimpleNamespace(
                session=SimpleNamespace(
                    config=session_config,
                    client=SimpleNamespace(close=AsyncMock()),
                )
            )

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.load_saved_custom_provider",
                return_value={
                    "minimax-m2.5:cloud": {
                        "api_key": "ollama",
                        "base_url": "http://localhost:11434/v1",
                        "model_name": "minimax-m2.5:cloud",
                        "context_window": 200000,
                    }
                },
            ), patch(
                "ite.ui.reup.app.get_bundled_models_result",
                return_value=self._bundled_models_result([
                    {
                        "model_name": "minimax/minimax-m2.5",
                        "label": "MiniMax M2.5",
                        "provider": "Bundled",
                        "available": True,
                        "unavailable_reason": "",
                    }
                ]),
            ), patch(
                "ite.ui.reup.app.save_system_config"
            ) as save_system_config, patch.object(
                app,
                "_open_modal",
                AsyncMock(
                    return_value={
                        "action": "select",
                        "entry_id": "bundled:minimax/minimax-m2.5",
                        "model_name": "minimax/minimax-m2.5",
                        "source_kind": "bundled",
                    }
                ),
            ), patch.object(app, "refresh_header"), patch.object(app, "post_notice"):
                await app._open_model_picker_from_meta()

            save_system_config.assert_called_once()
            _, kwargs = save_system_config.call_args
            self.assertEqual(kwargs["api_key"], "")
            self.assertEqual(kwargs["base_url"], "")
            self.assertEqual(kwargs["model_name"], "minimax/minimax-m2.5")
            self.assertEqual(kwargs["source_kind"], "bundled")
            self.assertEqual(app.config.api_key, "")
            self.assertEqual(app.config.base_url, "")
            self.assertEqual(app.config.model.source_kind, "bundled")
            self.assertEqual(session_config.api_key, "")
            self.assertEqual(session_config.base_url, "")
            self.assertEqual(session_config.model.name, "minimax/minimax-m2.5")
            self.assertEqual(session_config.model.source_kind, "bundled")

        asyncio.run(run_test())

    def test_open_model_picker_restores_saved_custom_provider_credentials(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "minimax/minimax-m2.7"
            app.config.model.source_kind = "bundled"
            app.config.api_key = "runtime-key"
            app.config.base_url = "http://127.0.0.1:4000/v1"

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.load_saved_custom_provider",
                return_value={
                    "unsloth/gemma-4-E4B-it-UD-MLX-4bit": {
                        "api_key": "custom-key",
                        "base_url": "http://localhost:8080",
                        "model_name": "unsloth/gemma-4-E4B-it-UD-MLX-4bit",
                        "context_window": 131072,
                    }
                },
            ), patch(
                "ite.ui.reup.app.get_bundled_models_result",
                return_value=self._bundled_models_result([
                    {
                        "model_name": "minimax/minimax-m2.7",
                        "label": "MiniMax M2.7",
                        "provider": "Bundled",
                        "available": True,
                        "unavailable_reason": "",
                    }
                ]),
            ), patch(
                "ite.ui.reup.app.save_system_config"
            ) as save_system_config, patch.object(
                app,
                "_open_modal",
                AsyncMock(
                    return_value={
                        "action": "select",
                        "model_name": "unsloth/gemma-4-E4B-it-UD-MLX-4bit",
                    }
                ),
            ), patch.object(app, "refresh_header"), patch.object(app, "post_notice"):
                await app._open_model_picker_from_meta()

            save_system_config.assert_called_once()
            _, kwargs = save_system_config.call_args
            self.assertEqual(kwargs["api_key"], "custom-key")
            self.assertEqual(kwargs["base_url"], "http://localhost:8080")
            self.assertEqual(kwargs["model_name"], "unsloth/gemma-4-E4B-it-UD-MLX-4bit")
            self.assertEqual(kwargs["context_window"], 131072)
            self.assertEqual(app.config.api_key, "custom-key")
            self.assertEqual(app.config.base_url, "http://localhost:8080")
            self.assertEqual(app.config.model.name, "unsloth/gemma-4-E4B-it-UD-MLX-4bit")
            self.assertEqual(app.config.model.context_window, 131072)

        asyncio.run(run_test())

    def test_open_model_picker_clears_custom_provider_credentials_for_bundled_cloud_model(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.config.model.name = "arcee-ai/trinity-large-preview:free"
            app.config.api_key = "openrouter-key"
            app.config.base_url = "https://openrouter.ai/api/v1"
            app.agent = SimpleNamespace(
                session=SimpleNamespace(client=SimpleNamespace(close=AsyncMock()))
            )

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.load_saved_custom_provider",
                return_value={
                    "arcee-ai/trinity-large-preview:free": {
                        "api_key": "openrouter-key",
                        "base_url": "https://openrouter.ai/api/v1",
                        "model_name": "arcee-ai/trinity-large-preview:free",
                        "context_window": 196608,
                    }
                },
            ), patch(
                "ite.ui.reup.app.get_bundled_models_result",
                return_value=self._bundled_models_result([
                    {
                        "model_name": "z-ai/glm-5.1",
                        "label": "GLM-5.1",
                        "provider": "Bundled",
                        "available": True,
                        "unavailable_reason": "",
                    }
                ]),
            ), patch(
                "ite.ui.reup.app.save_system_config"
            ) as save_system_config, patch.object(
                app,
                "_open_modal",
                AsyncMock(return_value={"action": "select", "model_name": "z-ai/glm-5.1"}),
            ), patch.object(app, "refresh_header"), patch.object(app, "post_notice"):
                await app._open_model_picker_from_meta()

            save_system_config.assert_called_once()
            _, kwargs = save_system_config.call_args
            self.assertEqual(kwargs["api_key"], "")
            self.assertEqual(kwargs["base_url"], "")
            self.assertEqual(kwargs["model_name"], "z-ai/glm-5.1")
            self.assertEqual(kwargs["context_window"], 256000)
            self.assertEqual(app.config.api_key, "")
            self.assertEqual(app.config.base_url, "")
            self.assertEqual(app.config.model.name, "z-ai/glm-5.1")
            self.assertEqual(app.config.model.context_window, 256000)
            app.agent.session.client.close.assert_awaited_once()

        asyncio.run(run_test())

    def test_build_streaming_command_renderable_shows_spinner_without_label(self) -> None:
        app = self._app()

        rendered = app._build_streaming_command_renderable(
            [],
            pending_active=True,
            pending_text="",
            spinner_index=0,
        )

        text = "".join(getattr(part, "plain", str(part)) for part in rendered.renderables)
        self.assertIn("⠋", text)

    def test_build_streaming_command_renderable_hides_generic_spinner_once_lines_exist(self) -> None:
        app = self._app()

        rendered = app._build_streaming_command_renderable(
            ["netlify  connecting"],
            pending_active=True,
            pending_text="",
            spinner_index=0,
        )

        text = "".join(getattr(part, "plain", str(part)) for part in rendered.renderables)
        self.assertEqual(text.count("⠋"), 1)

    def test_build_streaming_command_renderable_animates_prefix_on_first_line(self) -> None:
        app = self._app()

        first = app._build_streaming_command_renderable(
            ["netlify  connecting"],
            pending_active=True,
            pending_text="",
            spinner_index=0,
        )
        second = app._build_streaming_command_renderable(
            ["netlify  connecting"],
            pending_active=True,
            pending_text="",
            spinner_index=1,
        )

        first_text = "".join(getattr(part, "plain", str(part)) for part in first.renderables)
        second_text = "".join(getattr(part, "plain", str(part)) for part in second.renderables)
        self.assertIn("⠋", first_text)
        self.assertIn("⠙", second_text)

    def test_suppresses_empty_todos_add_failure_card(self) -> None:
        app = self._app()

        self.assertTrue(
            app._should_suppress_malformed_tool_card(
                "todos",
                "'content' or 'items' is required for 'add' action",
            )
        )

    def test_tool_start_splits_streaming_assistant_segment(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.agent = SimpleNamespace(
                session=SimpleNamespace(
                    plan_mode_enabled=False,
                    plan_phase="idle",
                    tool_registry=SimpleNamespace(get=lambda _name: None),
                )
            )
            app._active_session_id = lambda: "s1"  # type: ignore[method-assign]
            app._run_state("s1").active_turn_id = 1

            class DummyConversation:
                def __init__(self) -> None:
                    self.mounted: list[object] = []

                async def mount(self, widget) -> None:
                    self.mounted.append(widget)

            conversation = DummyConversation()

            def fake_query_one(selector, *_args, **_kwargs):
                if selector == "#conversation":
                    return conversation
                raise AssertionError(f"Unexpected selector: {selector}")

            with patch.object(app, "query_one", side_effect=fake_query_one), patch.object(
                app, "_pin_activity_indicator_to_end", AsyncMock()
            ), patch.object(app, "_refresh_empty_state"), patch.object(
                app, "get_tool_kind", return_value=None
            ), patch.object(app, "_hide_activity_indicator", AsyncMock()), patch.object(
                app, "_cancel_activity_resume_timer"
            ), patch.object(app, "_set_loading_state"), patch.object(
                app, "_progress_state_label", return_value="Reading file"
            ):
                await app.stream_assistant_delta("First segment.")
                first_widget = app._streaming_widget
                await app.handle_agent_event(
                    AgentEvent.tool_call_start(
                        "call_read_1",
                        "read_file",
                        {"path": "src/ite/ui/reup/app.py"},
                    ),
                    "s1",
                    1,
                )
                self.assertIsNone(app._streaming_widget)
                await app.stream_assistant_delta("Second segment.")
                second_widget = app._streaming_widget

            self.assertIsNotNone(first_widget)
            self.assertIsNotNone(second_widget)
            self.assertIsNot(first_widget, second_widget)
            self.assertEqual(len(conversation.mounted), 3)

        asyncio.run(run_test())

    def test_tick_top_indicator_advances_streaming_command_spinner_without_top_busy(self) -> None:
        app = self._app()
        widget = Static()
        app._streaming_command_cards["/mcp"] = (SimpleNamespace(), widget, [], True, "")
        app._top_busy = False
        app._aside_pending_widgets = {}
        before = app._top_spinner_index

        app._tick_top_indicator()

        self.assertEqual(app._top_spinner_index, before + 1)

    def test_finalize_streaming_message_prefers_final_text_over_stream_buffer(self) -> None:
        async def run_test() -> None:
            app = self._app()

            class DummyConversation:
                def __init__(self) -> None:
                    self.mounted: list[object] = []

                async def mount(self, widget) -> None:
                    self.mounted.append(widget)

            class FakeMarkdown(Static):
                def __init__(self, text: str) -> None:
                    super().__init__(text)
                    self.source_text = text

            class RemovableStatic(Static):
                async def remove(self) -> None:
                    return None

            conversation = DummyConversation()
            app._streaming_widget = RemovableStatic()
            app._streaming_buffer = "Alpha\nAlpha\nBeta"

            with patch.object(app, "query_one", return_value=conversation), patch.object(
                app, "_pin_activity_indicator_to_end", AsyncMock()
            ), patch("ite.ui.reup.app.CopyableMarkdown", FakeMarkdown):
                await app.finalize_streaming_message("Alpha\nBeta")

            self.assertIsNone(app._streaming_widget)
            self.assertEqual(app._streaming_buffer, "")
            self.assertEqual(len(conversation.mounted), 1)
            mounted = conversation.mounted[0]
            body = list(getattr(mounted, "_pending_children", []))[0]
            self.assertEqual(body.source_text, "Alpha\nBeta")

        asyncio.run(run_test())

    def test_streaming_assistant_delta_uses_copyable_markdown_widget(self) -> None:
        async def run_test() -> None:
            app = self._app()

            class DummyConversation:
                def __init__(self) -> None:
                    self.mounted: list[object] = []

                async def mount(self, widget) -> None:
                    self.mounted.append(widget)

            conversation = DummyConversation()
            with patch.object(app, "query_one", return_value=conversation), patch.object(
                app, "_pin_activity_indicator_to_end", AsyncMock()
            ):
                await app.stream_assistant_delta("Hello `code`")

            self.assertEqual(len(conversation.mounted), 1)
            mounted = conversation.mounted[0]
            self.assertIs(app._streaming_widget, mounted)
            body = list(getattr(mounted, "_pending_children", []))[0]
            self.assertIsInstance(body, CopyableMarkdown)

        asyncio.run(run_test())

    def test_append_streaming_command_marks_card_as_error_on_failure(self) -> None:
        async def run_test() -> None:
            app = self._app()

            class DummyConversation:
                async def mount(self, _card) -> None:
                    return None

            with patch.object(app, "query_one", return_value=DummyConversation()), patch.object(
                app, "_pin_activity_indicator_to_end", AsyncMock()
            ), patch.object(app, "_refresh_empty_state"):
                await app._append_command_result_card("/mcp", "Failed to start MCP server 'netlify'")

            card, _body, _lines, _pending_active, _pending_text = app._streaming_command_cards["/mcp"]
            self.assertIn("command-error", card.classes)

        asyncio.run(run_test())

    def test_run_command_routes_generic_output_to_command_card(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(session=SimpleNamespace())

        async def fake_dispatch(_command, _args, ctx):
            ctx.console.print("Command finished.")

        with patch.object(app, "ensure_agent", AsyncMock()), patch.object(
            app._command_registry,
            "dispatch",
            AsyncMock(side_effect=fake_dispatch),
        ), patch.object(app, "post_command_result") as post_command, patch.object(
            app, "_post_skills_command_result", return_value=True
        ) as post_skills:
            asyncio.run(app.run_command("/demo"))

        post_command.assert_called_once_with("/demo", "Command finished.")
        post_skills.assert_not_called()

    def test_run_command_routes_tools_output_to_native_command_view(self) -> None:
        app = self._app()
        session = SimpleNamespace(
            tool_registry=SimpleNamespace(get_tools=lambda: []),
            get_stats=lambda: {},
            mcp_manager=SimpleNamespace(get_all_servers=lambda: []),
            export_todos_state=lambda: {},
            show_planning_todos=False,
            plan_mode_enabled=False,
            plan_phase="idle",
            current_plan_text=lambda: "",
        )
        app.agent = SimpleNamespace(session=session)

        async def fake_dispatch(_command, _args, ctx):
            ctx.console.print("legacy boxed output")

        with patch.object(app, "ensure_agent", AsyncMock()), patch.object(
            app._command_registry,
            "dispatch",
            AsyncMock(side_effect=fake_dispatch),
        ), patch.object(app, "post_command_result") as post_command, patch.object(
            app, "_post_skills_command_result", return_value=False
        ), patch.object(app, "add_assistant_card", AsyncMock()) as add_card:
            asyncio.run(app.run_command("/tools"))

        post_command.assert_not_called()
        add_card.assert_called_once()

    def test_run_command_routes_memory_output_to_native_command_view(self) -> None:
        app = self._app()
        session = SimpleNamespace(
            session_id="sess_123",
            tool_registry=SimpleNamespace(get_tools=lambda: []),
            get_stats=lambda: {},
            mcp_manager=SimpleNamespace(get_all_servers=lambda: []),
            export_todos_state=lambda: {},
            show_planning_todos=False,
            plan_mode_enabled=False,
            plan_phase="idle",
            current_plan_text=lambda: "",
        )
        app.agent = SimpleNamespace(session=session)

        manager = SimpleNamespace(
            load_active_controls=lambda: {},
            list_entries=lambda _store: [],
            list_episodes=lambda: [],
            debug_prompt_memory=lambda query: {"controls": {}, "episodic": [], "long_term": {}, "semantic": {}, "short_term": {}, "query": query},
        )

        async def fake_dispatch(_command, _args, ctx):
            ctx.console.print("legacy memory output")

        with patch.object(app, "ensure_agent", AsyncMock()), patch.object(
            app._command_registry,
            "dispatch",
            AsyncMock(side_effect=fake_dispatch),
        ), patch("ite.ui.reup.app.MemoryManager", return_value=manager), patch.object(
            app, "post_command_result"
        ) as post_command, patch.object(
            app, "_post_skills_command_result", return_value=False
        ), patch.object(app, "add_assistant_card", AsyncMock()) as add_card:
            asyncio.run(app.run_command("/memory"))

        post_command.assert_not_called()
        add_card.assert_called_once()

    def test_run_command_routes_skills_output_to_specialized_card(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(session=SimpleNamespace())

        async def fake_dispatch(_command, _args, ctx):
            ctx.console.print("Skills updated.")

        with patch.object(app, "ensure_agent", AsyncMock()), patch.object(
            app._command_registry,
            "dispatch",
            AsyncMock(side_effect=fake_dispatch),
        ), patch.object(app, "post_command_result") as post_command, patch.object(
            app, "_post_skills_command_result", return_value=True
        ) as post_skills:
            asyncio.run(app.run_command("/skills"))

        post_skills.assert_called_once_with([], "Skills updated.")
        post_command.assert_not_called()

    def test_streaming_command_output_emits_lines_immediately(self) -> None:
        emitted: list[str] = []
        output = StreamingCommandOutput(on_line=emitted.append)

        output.write("first line\nsecond")
        output.write(" line\n")
        output.flush_pending()

        self.assertEqual(emitted, ["first line", "second line"])
        self.assertTrue(output.had_live_output)

    def test_run_command_streams_mcp_start_updates_via_single_stream_path(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(session=SimpleNamespace())

        async def fake_dispatch(_command, _args, ctx):
            ctx.console.print("step one")
            ctx.console.print("step two")

        with patch.object(app, "ensure_agent", AsyncMock()), patch.object(
            app._command_registry,
            "dispatch",
            AsyncMock(side_effect=fake_dispatch),
        ), patch.object(app, "post_streaming_command_result") as post_stream, patch.object(
            app, "post_command_result"
        ) as post_command:
            asyncio.run(app.run_command("/mcp start vercel"))

        self.assertEqual(
            [call.args for call in post_stream.call_args_list],
            [("/mcp", "step one"), ("/mcp", "step two")],
        )
        post_command.assert_not_called()

    def test_run_command_posts_compaction_notice_flow_for_manual_compact(self) -> None:
        app = self._app()
        context_manager = SimpleNamespace(
            compaction_count=0,
            latest_usage=SimpleNamespace(prompt_tokens=1234),
        )
        session = SimpleNamespace(context_manager=context_manager)
        app.agent = SimpleNamespace(session=session)

        async def fake_dispatch(_command, _args, ctx):
            context_manager.compaction_count = 1
            ctx.console.print("Compacted.")

        with patch.object(app, "ensure_agent", AsyncMock()), patch.object(
            app._command_registry,
            "dispatch",
            AsyncMock(side_effect=fake_dispatch),
        ), patch.object(app, "post_notice") as post_notice, patch.object(
            app, "post_system"
        ) as post_system, patch.object(app, "post_command_result") as post_command:
            asyncio.run(app.run_command("/compact"))

        post_notice.assert_called_once_with("Context", "Compacting context")
        post_system.assert_called_once()
        self.assertEqual(post_system.call_args.args[0], "Context compacted")
        self.assertEqual(post_system.call_args.args[1], "Context compacted.")
        post_command.assert_not_called()

    def test_run_command_retry_dispatches_saved_retryable_payload(self) -> None:
        app = self._app()
        run_state = app._run_state("s1")
        run_state.retryable_turn_payload = {
            "message": "Explain repository architecture.",
            "display_message": "Explain repository architecture.",
            "attachments": [],
        }
        app.agent = SimpleNamespace(session=SimpleNamespace())
        app._active_session_id = lambda: "s1"  # type: ignore[method-assign]

        with patch.object(app, "_dispatch_payload", AsyncMock()) as dispatch, patch.object(
            app, "post_notice"
        ) as post_notice:
            asyncio.run(app.run_command("/retry"))

        dispatch.assert_awaited_once()
        post_notice.assert_called_once_with("Retry", "Retrying last turn.")
        self.assertIsNone(run_state.retryable_turn_payload)

    def test_agent_error_marks_retryable_bundled_failure_and_posts_notice(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.agent = SimpleNamespace(
                session=SimpleNamespace(
                    plan_mode_enabled=False,
                    plan_phase="idle",
                )
            )
            app._active_session_id = lambda: "s1"  # type: ignore[method-assign]
            run_state = app._run_state("s1")
            run_state.active_turn_id = 1
            run_state.last_turn_payload = {
                "message": "Explain repository architecture.",
                "display_message": "Explain repository architecture.",
                "attachments": [],
            }

            with patch.object(app, "post_system") as post_system, patch.object(
                app, "post_notice"
            ) as post_notice, patch.object(
                app, "post_recovery_status"
            ) as post_recovery, patch.object(app, "refresh_header"), patch.object(
                app, "_schedule_usage_meta_refresh_for_cloud_model"
            ), patch.object(app, "_cancel_activity_resume_timer"), patch.object(
                app, "_hide_activity_indicator", AsyncMock()
            ):
                await app.handle_agent_event(
                    AgentEvent.agent_error(
                        "Bundled inference provider failed (minimax) with status 500. Ref: abc-123."
                    ),
                    "s1",
                    1,
                )

            self.assertEqual(
                run_state.retryable_turn_payload,
                {
                    "message": "Explain repository architecture.",
                    "display_message": "Explain repository architecture.",
                    "attachments": [],
                },
            )
            self.assertIsNone(run_state.failure_recovery_payload)
            post_system.assert_not_called()
            post_notice.assert_not_called()
            post_recovery.assert_called_once_with(
                error_message="Bundled inference provider failed (minimax) with status 500. Ref: abc-123.",
                recovering=False,
                retry_available=True,
            )

        asyncio.run(run_test())

    def test_agent_error_after_progress_queues_hidden_followup_recovery(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.agent = SimpleNamespace(
                session=SimpleNamespace(
                    plan_mode_enabled=False,
                    plan_phase="idle",
                )
            )
            app._active_session_id = lambda: "s1"  # type: ignore[method-assign]
            run_state = app._run_state("s1")
            run_state.active_turn_id = 1
            run_state.last_turn_payload = {
                "message": "Audit the repo.",
                "display_message": "Audit the repo.",
                "attachments": [],
            }
            run_state.turn_made_progress = True

            with patch.object(app, "post_system") as post_system, patch.object(
                app, "post_notice"
            ) as post_notice, patch.object(
                app, "post_recovery_status"
            ) as post_recovery, patch.object(app, "refresh_header"), patch.object(
                app, "_schedule_usage_meta_refresh_for_cloud_model"
            ), patch.object(app, "_cancel_activity_resume_timer"), patch.object(
                app, "_hide_activity_indicator", AsyncMock()
            ):
                await app.handle_agent_event(
                    AgentEvent.agent_error(
                        "Bundled inference provider failed (ollama-dev) with status 500. Ref: abc-123."
                    ),
                    "s1",
                    1,
                )

            self.assertEqual(run_state.failure_recovery_attempts, 1)
            self.assertEqual(
                run_state.failure_recovery_payload,
                {
                    "message": (
                        "Continue from the last successful step only. "
                        "Do not repeat completed tool work, repeated file reads, or already-finished analysis. "
                        "Use the existing results already in the conversation and finish the interrupted task."
                    ),
                    "display_message": "",
                    "attachments": [],
                    "suppress_user_echo": True,
                },
            )
            post_system.assert_not_called()
            post_notice.assert_not_called()
            post_recovery.assert_called_once_with(
                error_message="Bundled inference provider failed (ollama-dev) with status 500. Ref: abc-123.",
                recovering=True,
                retry_available=False,
            )

        asyncio.run(run_test())

    def test_context_compacting_starts_live_context_card(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.agent = SimpleNamespace(
                session=SimpleNamespace(
                    plan_mode_enabled=False,
                    plan_phase="idle",
                )
            )
            app._active_session_id = lambda: "s1"  # type: ignore[method-assign]
            run_state = app._run_state("s1")
            run_state.active_turn_id = 1
            run_state.is_turn_running = True

            with patch.object(app, "_cancel_activity_resume_timer"), patch.object(
                app, "_hide_activity_indicator", new=AsyncMock()
            ) as hide_indicator, patch.object(
                app, "_start_live_compaction_card", new=AsyncMock()
            ) as start_card:
                await app.handle_agent_event(
                    AgentEvent(type=AgentEventType.CONTEXT_COMPACTING, data={}),
                    "s1",
                    1,
                )

            hide_indicator.assert_awaited_once()
            start_card.assert_awaited_once_with("Compacting context")

        asyncio.run(run_test())

    def test_context_compacted_auto_resume_queues_hidden_continue(self) -> None:
        async def run_test() -> None:
            app = self._app()
            app.agent = SimpleNamespace(
                session=SimpleNamespace(
                    plan_mode_enabled=False,
                    plan_phase="idle",
                )
            )
            app._active_session_id = lambda: "s1"  # type: ignore[method-assign]
            run_state = app._run_state("s1")
            run_state.active_turn_id = 1
            run_state.is_turn_running = True

            with patch.object(
                app, "_finish_live_compaction_card", new=AsyncMock()
            ) as finish_card, patch.object(app, "refresh_header"):
                await app.handle_agent_event(
                    AgentEvent.context_compacted(
                        trigger_tokens=170000,
                        context_window=200000,
                        summary_chars=1200,
                        auto_resume_required=True,
                    ),
                    "s1",
                    1,
                )

            finish_card.assert_awaited_once()
            self.assertEqual(
                run_state.auto_resume_payload,
                {
                    "message": Agent.POST_COMPACTION_CONTINUE_PROMPT,
                    "display_message": "",
                    "attachments": [],
                    "suppress_user_echo": True,
                },
            )

        asyncio.run(run_test())

    def test_auto_resume_payload_dispatches_before_queued_payload(self) -> None:
        app = self._app()
        run_state = app._run_state("s1")
        app._active_session_id = lambda: "s1"  # type: ignore[method-assign]
        expected_payload = {
            "message": Agent.POST_COMPACTION_CONTINUE_PROMPT,
            "display_message": "",
            "attachments": [],
            "suppress_user_echo": True,
        }
        run_state.auto_resume_payload = dict(expected_payload)
        run_state.queued_turn_payload = {
            "message": "visible queued draft",
            "display_message": "visible queued draft",
            "attachments": [],
        }

        async def scenario() -> None:
            with patch.object(app, "_dispatch_payload", new=AsyncMock()) as dispatch, patch.object(
                app, "post_notice"
            ) as post_notice, patch.object(app, "_set_loading_state") as set_loading:
                await app._dispatch_queued_payload_if_ready()
                set_loading.assert_called_once_with("resuming after compaction", busy=True)
                dispatch.assert_awaited_once_with(expected_payload)
                post_notice.assert_not_called()

        asyncio.run(scenario())

    def test_run_agent_message_dispatches_compaction_auto_resume_after_turn(self) -> None:
        app = self._app()
        run_state = app._run_state("s1")
        app._active_session_id = lambda: "s1"  # type: ignore[method-assign]
        app.agent = SimpleNamespace(
            session=SimpleNamespace(
                pending_attachment_paths=[],
                get_stats=lambda: {"context_used_pct": 0.0},
                plan_mode_enabled=False,
                plan_phase="idle",
            )
        )

        expected_payload = {
            "message": Agent.POST_COMPACTION_CONTINUE_PROMPT,
            "display_message": "",
            "attachments": [],
            "suppress_user_echo": True,
        }

        async def fake_agent_turn(*_args, **_kwargs) -> None:
            run_state.auto_resume_payload = dict(expected_payload)

        async def scenario() -> None:
            with patch.object(app, "ensure_agent", new=AsyncMock()), patch.object(
                app, "_prepare_attachments_for_turn", return_value=("hello", None, None, None)
            ), patch.object(app, "add_user_message", new=AsyncMock()), patch.object(
                app, "auto_save", new=AsyncMock()
            ), patch.object(app, "_dispatch_payload", new=AsyncMock()) as dispatch, patch.object(
                app, "_set_loading_state"
            ) as set_loading, patch.object(app, "refresh_header"), patch.object(
                app, "_agent_turn", new=AsyncMock(side_effect=fake_agent_turn)
            ):
                await app.run_agent_message("hello")
                dispatch.assert_awaited_once_with(expected_payload)
                self.assertIsNone(run_state.auto_resume_payload)
                self.assertIn(
                    unittest.mock.call("resuming after compaction", busy=True),
                    set_loading.call_args_list,
                )

        asyncio.run(scenario())

    def test_failure_recovery_payload_dispatches_before_queued_payload(self) -> None:
        app = self._app()
        run_state = app._run_state("s1")
        app._active_session_id = lambda: "s1"  # type: ignore[method-assign]
        expected_payload = {
            "message": "Continue from the last successful step only.",
            "display_message": "",
            "attachments": [],
            "suppress_user_echo": True,
        }
        run_state.failure_recovery_payload = dict(expected_payload)
        run_state.queued_turn_payload = {
            "message": "visible queued draft",
            "display_message": "visible queued draft",
            "attachments": [],
        }

        async def scenario() -> None:
            with patch.object(app, "_dispatch_payload", new=AsyncMock()) as dispatch, patch.object(
                app, "post_notice"
            ) as post_notice, patch.object(app, "_set_loading_state") as set_loading:
                await app._dispatch_queued_payload_if_ready()
                set_loading.assert_called_once_with(
                    "continuing after transient failure", busy=True
                )
                dispatch.assert_awaited_once_with(expected_payload)
                post_notice.assert_not_called()

        asyncio.run(scenario())

    def test_render_skills_payload_formats_show_output_instead_of_raw_json(self) -> None:
        rendered = render_skills_payload(
            output="""
{
  "action": "show",
  "available_count": 21,
  "active_skills": ["audit"],
  "skill": "frontend-design",
  "name": "frontend-design",
  "description": "Create distinctive production interfaces.",
  "user_invocable": false,
  "argument_hint": "",
  "reference_files": ["reference/color-and-contrast.md"],
  "trusted": true,
  "requires_trust": false,
  "instructions": "Use strong hierarchy."
}
            """.strip(),
            success=True,
        )

        console = Console(file=StringIO(), force_terminal=False, width=120)
        console.print(rendered)
        text = console.file.getvalue()
        self.assertIn("frontend-design", text)
        self.assertIn("inspected", text)
        self.assertIn("Create distinctive production interfaces.", text)
        self.assertNotIn("audit", text)
        self.assertNotIn("does not activate it", text)

    def test_render_skills_payload_formats_truncated_list_json(self) -> None:
        rendered = render_skills_payload(
            output="""
{
  "action": "list",
  "available_count": 21,
  "active_skills": ["audit"],
  "skills": [
    {
      "identifier": "animate",
      "description": "Review a feature and enhance it with purposeful motion.",
      "source": "shared-project",
      "user_invocable": "true",
      "trusted": "true",
      "requires_trust": "false"
    },
    {
      "identifier": "frontend-design",
      "description": "Create distinctive production interfaces.",
      "source": "shared-project",
      "user_invocable": "false",
      "trusted": "true",
      "requires_trust": "false"
    }
  ]
}
            """.strip(),
            success=True,
        )

        console = Console(file=StringIO(), force_terminal=False, width=120)
        console.print(rendered)
        text = console.file.getvalue()
        self.assertIn("skills", text)
        self.assertIn("animate", text)
        self.assertIn("frontend-design", text)
        self.assertNotIn('"identifier": "animate"', text)

    def test_consume_dropped_path_text_inserts_refs_instead_of_hidden_queue(self) -> None:
        app = self._app()
        sample = self.cwd / "report.pdf"
        sample.write_text("x", encoding="utf-8")
        app.agent = SimpleNamespace(session=SimpleNamespace(pending_attachment_paths=[]))

        with patch.object(app, "_insert_attachment_refs_into_prompt", return_value=1) as insert_refs, patch.object(
            app, "post_attachment_note"
        ):
            handled = app._consume_dropped_path_text(str(sample))

        self.assertTrue(handled)
        insert_refs.assert_called_once_with([str(sample)])

    def test_attachment_palette_selection_clears_palette(self) -> None:
        app = self._app()

        class DummyPrompt:
            def __init__(self) -> None:
                self.text = "inspect @rep"

            def load_text(self, value: str) -> None:
                self.text = value

            def move_cursor(self, _cursor) -> None:
                return None

        prompt = DummyPrompt()
        with patch.object(app, "query_one", return_value=prompt), patch.object(
            app, "_clear_command_palette"
        ) as clear_palette, patch.object(app, "_resize_composer_for_prompt"):
            app._apply_attachment_palette_selection(
                SimpleNamespace(insert_text='@"report one.pdf"', name='@"report one.pdf"')
            )

        self.assertIn('@"report one.pdf"', prompt.text)
        clear_palette.assert_called_once()

    def test_palette_selection_clamps_at_bounds(self) -> None:
        app = self._app()
        app._filtered_command_palette_options = app._filtered_command_palette("/")
        app._command_palette_index = 0

        app._move_command_palette_selection(-1)
        self.assertEqual(app._command_palette_index, 0)

        app._command_palette_index = len(app._filtered_command_palette_options) - 1
        app._move_command_palette_selection(1)
        self.assertEqual(
            app._command_palette_index,
            len(app._filtered_command_palette_options) - 1,
        )

    def test_plan_render_dedupe_tracks_last_rendered_text(self) -> None:
        app = self._app()

        self.assertTrue(app._should_render_plan_text("Plan body"))
        app._last_rendered_plan_text = app._normalize_plan_text("Plan body")
        self.assertFalse(app._should_render_plan_text("Plan body"))
        self.assertFalse(app._should_render_plan_text("  Plan body  "))

    def test_shell_session_helpers_identify_session_tools(self) -> None:
        app = self._app()

        self.assertTrue(app._is_session_shell_tool("shell_start"))
        self.assertTrue(app._is_session_shell_tool("shell_poll"))
        self.assertFalse(app._is_session_shell_tool("shell"))
        self.assertEqual(
            app._shell_session_id_for_tool(
                name="shell_send",
                arguments={"session_id": "sh_123"},
            ),
            "sh_123",
        )
        self.assertIsNone(
            app._shell_session_id_for_tool(
                name="shell_start",
                metadata={"session_id": "sh_123"},
            )
        )

    def test_shell_payload_split_strips_stderr_markers(self) -> None:
        stdout, stderr = split_shell_payload(
            "\n--- STDERR ---\nwarning one\n\n--- STDERR ---\nwarning two\n"
        )

        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "warning one\nwarning two")

    def test_collapse_terminal_rewrites_keeps_latest_carriage_return_frame(self) -> None:
        collapsed = collapse_terminal_rewrites(
            "Uploading wheel\n0%\r15%\r71%\r100%\nDone\n"
        )

        self.assertEqual(collapsed, "Uploading wheel\n100%\nDone")

    def test_collapse_terminal_rewrites_compacts_stacked_progress_frames(self) -> None:
        collapsed = collapse_terminal_rewrites(
            "Uploading wheel\n"
            "0% ===== 0.0/856.6 kB\n"
            "0% ===== 0.0/856.6 kB\n"
            "15% ==== 131.1/856.6 kB\n"
            "17% ==== 147.5/856.6 kB\n"
            "17% ==== 147.5/856.6 kB\n"
        )

        self.assertEqual(
            collapsed,
            "Uploading wheel\n17% ==== 147.5/856.6 kB",
        )

    def test_collapse_terminal_rewrites_applies_cursor_up_and_clear_line(self) -> None:
        collapsed = collapse_terminal_rewrites(
            "Uploading wheel\n"
            "100% ===== 856.6/856.6 kB\n"
            "Uploading source\n"
            "\x1b[2A\x1b[2K\r48% ==== 3.4/7.0 MB\n"
        )

        self.assertEqual(
            collapsed,
            "Uploading wheel\n48% ==== 3.4/7.0 MB\nUploading source",
        )

    def test_render_shell_result_payload_uses_compact_terminal_body(self) -> None:
        rendered = render_shell_result_payload(
            payload="Uploading wheel\n0%\r15%\r71%\r100%\nDone\n",
            metadata={
                "session_id": "sh_123",
                "status": "completed",
                "running": False,
                "has_new_output": True,
            },
            exit_code=0,
        )

        console = Console(file=StringIO(), force_terminal=False, width=120)
        for block in rendered:
            console.print(block)
        text = console.file.getvalue()

        self.assertIn("sh_123", text)
        self.assertIn("exit 0", text)
        self.assertIn("100%", text)
        self.assertNotIn("15%", text)
        self.assertNotIn("stdout", text)

    def test_shell_session_state_uses_backend_status_when_present(self) -> None:
        self.assertEqual(
            shell_session_state({"status": "command_running", "running": True}),
            "command_running",
        )
        self.assertEqual(
            shell_session_state({"running": True, "has_new_output": False}),
            "idle",
        )
        self.assertEqual(
            shell_session_state({"running": False}),
            "exited",
        )

    def test_shell_card_icon_tracks_shell_state(self) -> None:
        self.assertEqual(
            ReupApp._shell_card_icon_and_style(
                {"status": "command_running", "running": True},
                success=True,
            )[0],
            "⌛",
        )

    def test_shell_session_card_content_shows_idle_when_running_without_new_output(self) -> None:
        app = self._app()

        header, body = app._build_shell_session_card_content(
            name="shell_poll",
            arguments={"session_id": "sh_123"},
            metadata={
                "session_id": "sh_123",
                "running": True,
                "status": "idle",
                "has_new_output": False,
            },
            payload="Uploading wheel\n100%\n",
            success=True,
            exit_code=None,
        )

        console = Console(file=StringIO(), force_terminal=False, width=120)
        console.print(header)
        console.print(body)
        text = console.file.getvalue()
        self.assertIn("idle", text)
        self.assertNotIn("command running", text)

    def test_render_wait_subagent_running_card_shows_live_run_state(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(
            session=SimpleNamespace(
                subagent_runtime=SimpleNamespace(
                    list_runs=lambda: [
                        SimpleNamespace(
                            run_id="agent_001",
                            status="running",
                            summary="Inspect tool registry internals",
                            goal="Inspect tool registry internals",
                            current_activity="Searching code in src/ite.",
                            started_at="2026-03-22T00:00:00+00:00",
                            last_update_at="2026-03-22T00:00:01+00:00",
                            activity_history=[
                                {
                                    "at": "2026-03-22T00:00:00+00:00",
                                    "message": "Starting specialist session.",
                                },
                                {
                                    "at": "2026-03-22T00:00:01+00:00",
                                    "message": "Searching code in src/ite.",
                                },
                            ],
                        )
                    ]
                )
            )
        )

        rendered = app._render_wait_subagent_running_card(
            args={"run_ids": ["agent_001"], "return_when": "all_completed"},
            spinner_index=0,
        )

        text = "".join(
            getattr(part, "plain", str(part))
            for part in rendered.renderables
        )
        self.assertIn("Waiting on specialists", text)
        self.assertIn("recent activity", text.lower())
        self.assertIn("Searching code in src/ite.", text)
        self.assertTrue(any(isinstance(part, Table) for part in rendered.renderables))
        self.assertEqual(
            ReupApp._shell_card_icon_and_style(
                {"status": "idle", "running": True},
                success=True,
            )[0],
            "💤",
        )
        self.assertEqual(
            ReupApp._shell_card_icon_and_style(
                {"status": "stopped", "running": False},
                success=True,
            )[0],
            "⏹",
        )
        self.assertEqual(
            ReupApp._shell_card_icon_and_style(
                {"status": "exited", "running": False},
                success=True,
            )[0],
            "▫️",
        )
        self.assertEqual(
            ReupApp._shell_card_icon_and_style(
                {"status": "exited", "running": False},
                success=False,
            )[0],
            "❌",
        )

    def test_shell_session_card_content_shows_idle_when_running_without_new_output(self) -> None:
        app = self._app()

        header, body = app._build_shell_session_card_content(
            name="shell_poll",
            arguments={"session_id": "sh_123"},
            metadata={
                "session_id": "sh_123",
                "running": True,
                "status": "idle",
                "has_new_output": False,
            },
            payload="Uploading wheel\n100%\n",
            success=True,
            exit_code=None,
        )

        console = Console(file=StringIO(), force_terminal=False, width=120)
        console.print(header)
        console.print(body)
        text = console.file.getvalue()
        self.assertIn("idle", text)
        self.assertNotIn("command running", text)

    def test_render_wait_subagent_running_card_prioritizes_more_runs_over_extra_history(self) -> None:
        app = self._app()
        runs = []
        for index in range(4):
            runs.append(
                SimpleNamespace(
                    run_id=f"agent_{index + 1:03d}",
                    status="running",
                    summary=f"Summary {index + 1}",
                    goal=f"Goal {index + 1}",
                    current_activity=f"Activity {index + 1}",
                    started_at="2026-03-22T00:00:00+00:00",
                    last_update_at="2026-03-22T00:00:01+00:00",
                    activity_history=[
                        {
                            "at": "2026-03-22T00:00:00+00:00",
                            "message": "Starting specialist session.",
                        },
                        {
                            "at": "2026-03-22T00:00:01+00:00",
                            "message": f"Activity {index + 1}",
                        },
                    ],
                )
            )
        app.agent = SimpleNamespace(
            session=SimpleNamespace(
                subagent_runtime=SimpleNamespace(list_runs=lambda: runs)
            )
        )

        rendered = app._render_wait_subagent_running_card(
            args={"return_when": "all_completed"},
            spinner_index=0,
        )

        table = next(part for part in rendered.renderables if isinstance(part, Table))
        self.assertEqual(len(table.rows), 4)
        text = "".join(getattr(part, "plain", str(part)) for part in rendered.renderables)
        self.assertIn("agent_001 · Goal 1 recent activity", text)
        self.assertIn("agent_002 · Goal 2 recent activity", text)
        self.assertIn("agent_003 · Goal 3 recent activity", text)
        self.assertIn("agent_004 · Goal 4 recent activity", text)

    def test_render_wait_subagent_running_card_compacts_completed_result_to_one_line(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(
            session=SimpleNamespace(
                subagent_runtime=SimpleNamespace(
                    list_runs=lambda: [
                        SimpleNamespace(
                            run_id="agent_002",
                            status="completed",
                            summary="## Subagent Session & Runtime Behavior - Findings Report\n\n## 1. Session Creation\nMore details here.",
                            goal="Inspect runtime wiring",
                            current_activity="## Subagent Session & Runtime Behavior - Findings Report\n\n## 1. Session Creation",
                            started_at="2026-03-22T00:00:00+00:00",
                            last_update_at="2026-03-22T00:00:01+00:00",
                            activity_history=[],
                        )
                    ]
                )
            )
        )

        rendered = app._render_wait_subagent_running_card(
            args={"return_when": "all_completed"},
            spinner_index=0,
        )

        text = "".join(getattr(part, "plain", str(part)) for part in rendered.renderables)
        self.assertNotIn("Session Creation", text)
        table = next(part for part in rendered.renderables if isinstance(part, Table))
        self.assertEqual(len(table.rows), 1)

    def test_render_subagent_running_card_shows_live_specialist_activity(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(
            session=SimpleNamespace(
                tool_registry=SimpleNamespace(
                    get=lambda _name: SimpleNamespace(
                        get_live_progress=lambda _call_id: {
                            "current_activity": "Reading subagent.py.",
                            "last_update_at": "2026-03-22T00:00:01+00:00",
                            "child_session_id": "child-session-1",
                            "activity_history": [
                                {
                                    "at": "2026-03-22T00:00:00+00:00",
                                    "message": "Starting specialist session.",
                                },
                                {
                                    "at": "2026-03-22T00:00:01+00:00",
                                    "message": "Reading subagent.py.",
                                },
                            ],
                        }
                    )
                )
            )
        )

        rendered = app._render_subagent_running_card(
            call_id="call_1",
            name="subagent_codebase_investigator",
            args={"goal": "Inspect subagent architecture"},
            spinner_index=0,
        )

        text = "".join(getattr(part, "plain", str(part)) for part in rendered.renderables)
        self.assertIn("Asking specialist", text)
        self.assertIn("Inspect subagent architecture", text)
        self.assertIn("Reading subagent.py.", text)
        self.assertIn("child session child-session-1", text)
        self.assertIn("Recent activity", text)

    def test_render_wait_subagent_running_card_shows_three_recent_entries_per_run(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(
            session=SimpleNamespace(
                subagent_runtime=SimpleNamespace(
                    list_runs=lambda: [
                        SimpleNamespace(
                            run_id="agent_001",
                            status="running",
                            summary="Summary 1",
                            goal="Goal 1",
                            current_activity="Reading subagent.py.",
                            started_at="2026-03-22T00:00:00+00:00",
                            last_update_at="2026-03-22T00:00:03+00:00",
                            activity_history=[
                                {"at": "2026-03-22T00:00:00+00:00", "message": "Looking through the workspace."},
                                {"at": "2026-03-22T00:00:01+00:00", "message": "Finding files matching `*subagent*.py`."},
                                {"at": "2026-03-22T00:00:02+00:00", "message": "Reading subagent_loader.py."},
                                {"at": "2026-03-22T00:00:03+00:00", "message": "Reading subagent.py."},
                            ],
                        )
                    ]
                )
            )
        )

        rendered = app._render_wait_subagent_running_card(
            args={"return_when": "all_completed"},
            spinner_index=0,
        )

        text = "".join(getattr(part, "plain", str(part)) for part in rendered.renderables)
        self.assertIn("Finding files matching `*subagent*.py`.", text)
        self.assertIn("Reading subagent_loader.py.", text)
        self.assertIn("Reading subagent.py.", text)

    def test_tool_completion_icon_tracks_tool_category_and_outcome(self) -> None:
        self.assertEqual(
            ReupApp._tool_completion_icon_and_style(
                "read_file",
                success=True,
                policy_redirect=False,
                recoverable=False,
            )[0],
            "📖",
        )
        self.assertEqual(
            ReupApp._tool_completion_icon_and_style(
                "write_file",
                success=True,
                policy_redirect=False,
                recoverable=False,
            )[0],
            "💾",
        )
        self.assertEqual(
            ReupApp._tool_completion_icon_and_style(
                "web_search",
                success=True,
                policy_redirect=False,
                recoverable=False,
            )[0],
            "🌐",
        )
        self.assertEqual(
            ReupApp._tool_completion_icon_and_style(
                "run_tests",
                success=True,
                policy_redirect=False,
                recoverable=False,
            )[0],
            "🧪",
        )
        self.assertEqual(
            ReupApp._tool_completion_icon_and_style(
                "git_commit",
                success=True,
                policy_redirect=False,
                recoverable=False,
            )[0],
            "📦",
        )
        self.assertEqual(
            ReupApp._tool_completion_icon_and_style(
                "read_file",
                success=False,
                policy_redirect=True,
                recoverable=True,
            )[0],
            "↪",
        )
        self.assertEqual(
            ReupApp._tool_completion_icon_and_style(
                "read_file",
                success=False,
                policy_redirect=False,
                recoverable=True,
            )[0],
            "↺",
        )
        self.assertEqual(
            ReupApp._tool_completion_icon_and_style(
                "read_file",
                success=False,
                policy_redirect=False,
                recoverable=False,
            )[0],
            "❌",
        )

    def test_malformed_tool_card_suppression_matches_agent_rules(self) -> None:
        self.assertTrue(
            ReupApp._should_suppress_malformed_tool_card(
                "read_file",
                "Invalid parameters: Parameter 'path': Field required",
            )
        )
        self.assertTrue(
            ReupApp._should_suppress_malformed_tool_card(
                "read_image",
                "Invalid parameters: Parameter 'path': Field required",
            )
        )
        self.assertTrue(
            ReupApp._should_suppress_malformed_tool_card(
                "read_toml",
                "Invalid parameters: Parameter 'path': Field required",
            )
        )
        self.assertTrue(
            ReupApp._should_suppress_malformed_tool_card(
                "read_pdf",
                "Invalid parameters: Parameter 'path': Field required",
            )
        )
        self.assertTrue(
            ReupApp._should_suppress_malformed_tool_card(
                "read_file",
                "Error: Invalid parameters: Parameter 'path': Field required",
            )
        )
        self.assertTrue(
            ReupApp._should_suppress_malformed_tool_card(
                "read_file",
                "Error: Invalid parameters: Parameter 'path': Field required\n\nOutput:\nRetry this tool with all required arguments.",
            )
        )
        self.assertTrue(
            ReupApp._should_suppress_malformed_tool_card(
                "skills",
                "Invalid parameters: Parameter '': Value error, skill is required for show, activate, and deactivate",
            )
        )
        self.assertFalse(
            ReupApp._should_suppress_malformed_tool_card(
                "read_file",
                "Invalid parameters: Parameter 'offset': Input should be greater than 0",
            )
        )

    def test_normalize_tool_start_arguments_summarizes_truncated_read_paths(self) -> None:
        self.assertEqual(
            ReupApp._normalize_tool_start_arguments(
                "read_file",
                {
                    "raw_arguments": '{"path":"poems/river.md"}{"path":"poems/silence.md"}{"path":"poems/wanderer.md"}'
                },
            ),
            {"path": "poems/river.md (+2 more)"},
        )

    def test_reset_session_local_ui_state_clears_tool_widgets(self) -> None:
        app = self._app()
        app._tool_widgets["call_1"] = Static()
        app._tool_args_by_call_id["call_1"] = {"session_id": "sh_123"}

        with patch.object(ReupApp, "is_mounted", new_callable=PropertyMock, return_value=False):
            app._reset_session_local_ui_state()

        self.assertEqual(app._tool_widgets, {})
        self.assertEqual(app._tool_args_by_call_id, {})

    def test_hydrate_snapshot_skips_legacy_malformed_tool_cards(self) -> None:
        app = self._app()

        class DummyConversation:
            async def remove_children(self) -> None:
                return None

        async def scenario() -> None:
            messages = [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "content": "Invalid parameters: Parameter 'path': Field required",
                    "tool_ui": {
                        "name": "read_file",
                        "success": False,
                        "error": "Invalid parameters: Parameter 'path': Field required",
                    },
                },
            ]
            with (
                patch.object(app, "query_one", return_value=DummyConversation()),
                patch.object(app, "_refresh_empty_state"),
                patch.object(app, "_reset_session_local_ui_state"),
                patch.object(app, "add_assistant_card", new=AsyncMock()),
                patch.object(app, "add_tool_call_start", new=AsyncMock()) as add_start,
                patch.object(app, "update_tool_call", new=AsyncMock()) as update_call,
            ):
                await app._hydrate_chat_from_snapshot(messages)
                add_start.assert_awaited_once()
                update_call.assert_not_awaited()

        asyncio.run(scenario())

    def test_add_tool_call_start_reuses_existing_card_for_same_call_id(self) -> None:
        app = self._app()

        class DummyConversation:
            def __init__(self) -> None:
                self.children: list[object] = []

            async def mount(self, child: object) -> None:
                self.children.append(child)

        async def scenario() -> None:
            conversation = DummyConversation()
            with (
                patch.object(app, "query_one", return_value=conversation),
                patch.object(app, "_refresh_empty_state"),
                patch.object(app, "_pin_activity_indicator_to_end", new=AsyncMock()),
                patch.object(app, "_move_card_to_bottom", new=AsyncMock()) as move_bottom,
            ):
                await app.add_tool_call_start(
                    call_id="call_1",
                    name="read_file",
                    tool_kind="read",
                    arguments={"path": "poems/river.md"},
                )
                first_card = app._tool_widgets["call_1"]
                await app.add_tool_call_start(
                    call_id="call_1",
                    name="read_file",
                    tool_kind="read",
                    arguments={
                        "raw_arguments": '{"path":"poems/river.md"}{"path":"poems/silence.md"}'
                    },
                )

                self.assertIs(app._tool_widgets["call_1"], first_card)
                self.assertEqual(len(conversation.children), 1)
                move_bottom.assert_awaited_once()

        asyncio.run(scenario())

    def test_live_malformed_required_arg_completion_is_not_rendered(self) -> None:
        app = self._app()
        app._session_run_states["s1"] = app._run_state("s1")
        app._run_state("s1").active_turn_id = 1
        app.agent = SimpleNamespace(
            session=SimpleNamespace(
                session_id="s1",
                plan_mode_enabled=False,
                plan_phase="executing",
            )
        )

        async def scenario() -> None:
            event = AgentEvent(
                type=AgentEventType.TOOL_CALL_COMPLETE,
                data={
                    "call_id": "call_1",
                    "name": "read_image",
                    "success": False,
                    "output": "Error: Invalid parameters: Parameter 'path': Field required\n\nOutput:\nRetry this tool with all required arguments.",
                    "error": "Error: Invalid parameters: Parameter 'path': Field required",
                    "metadata": {"recoverable": True, "suppressed": True},
                    "diff": None,
                    "truncated": False,
                    "exit_code": None,
                },
            )
            with (
                patch.object(app, "_set_loading_state"),
                patch.object(app, "update_tool_call", new=AsyncMock()) as update_call,
                patch.object(app, "_active_session_id", return_value="s1"),
            ):
                await app.handle_agent_event(event, "s1", 1)
                update_call.assert_not_awaited()

        asyncio.run(scenario())


    def test_plan_ready_enter_is_not_implicit_approval(self) -> None:
        app = self._app()

        class DummyEvent:
            def __init__(self, key: str) -> None:
                self.key = key
                self.stopped = False
                self.default_prevented = False

            def stop(self) -> None:
                self.stopped = True

            def prevent_default(self) -> None:
                self.default_prevented = True

        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        app._plan_ready_future = loop.create_future()

        event = DummyEvent("enter")
        with patch.object(ReupApp, "focused", new_callable=PropertyMock, return_value=None):
            app.on_key(event)  # type: ignore[arg-type]

        self.assertFalse(event.stopped)
        self.assertFalse(app._plan_ready_future.done())

    def test_plan_question_choice_only_shows_status_for_custom_answer(self) -> None:
        app = self._app()
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)

        class DummyButton:
            def __init__(self) -> None:
                self.disabled = False
                self.variant = "default"
                self.classes = set()

            def add_class(self, name: str) -> None:
                self.classes.add(name)

        class DummyStatus:
            def __init__(self) -> None:
                self.display = False
                self.value = ""

            def update(self, value: str) -> None:
                self.value = value

        app._plan_question_future = loop.create_future()
        option_buttons = [DummyButton(), DummyButton()]
        app._plan_question_option_buttons = option_buttons
        app._plan_question_custom_input = SimpleNamespace(disabled=False)
        app._plan_question_custom_submit = DummyButton()
        app._plan_question_status = DummyStatus()

        loop.run_until_complete(
            app._resolve_plan_question_choice(
                selected_index=0,
                selected_option="Option A",
                free_text="",
            )
        )

        self.assertEqual(option_buttons[0].variant, "primary")

        app._plan_question_future = loop.create_future()
        app._plan_question_option_buttons = [DummyButton(), DummyButton()]
        app._plan_question_custom_input = SimpleNamespace(disabled=False)
        app._plan_question_custom_submit = DummyButton()
        status = DummyStatus()
        app._plan_question_status = status

        loop.run_until_complete(
            app._resolve_plan_question_choice(
                selected_index=None,
                selected_option="",
                free_text="Custom path",
            )
        )

        self.assertTrue(status.display)
        self.assertIn("Custom answer", status.value)

    def test_recommended_suffix_can_be_present_without_primary_styling(self) -> None:
        recommended_index = 1
        options = ["First", "Second"]
        labels = [
            f"{idx + 1}. {option}{' (recommended)' if recommended_index == idx else ''}"
            for idx, option in enumerate(options)
        ]

        self.assertEqual(labels[0], "1. First")
        self.assertEqual(labels[1], "2. Second (recommended)")

    def test_handle_send_asks_for_resolution_instead_of_auto_cancel(self) -> None:
        app = self._app()
        app._is_turn_running = True

        class DummyPrompt:
            def __init__(self, text: str) -> None:
                self.text = text

        prompt = DummyPrompt("follow up message")

        async def scenario() -> None:
            with (
                patch.object(app, "query_one", return_value=prompt),
                patch.object(app, "_resolve_active_turn_send", new=AsyncMock(return_value=True)) as resolve,
                patch.object(app, "cancel_active_turn", new=AsyncMock()) as cancel,
            ):
                await app.handle_send()
                resolve.assert_awaited_once()
                cancel.assert_not_called()

        asyncio.run(scenario())

    def test_cancel_active_turn_cancels_active_session_subagents(self) -> None:
        app = self._app()
        runtime = SimpleNamespace(cancel=AsyncMock(return_value={"cancelled_run_ids": ["agent_001"]}))
        app.agent = SimpleNamespace(session=SimpleNamespace(subagent_runtime=runtime))

        async def scenario() -> None:
            blocker = asyncio.Event()

            async def wait_forever() -> None:
                await blocker.wait()

            task = asyncio.create_task(wait_forever())
            app._active_turn_task = task
            app._is_turn_running = True

            with (
                patch.object(app, "_clear_inflight_turn_ui", new=AsyncMock()),
                patch.object(app, "_set_loading_state"),
            ):
                await app.cancel_active_turn()

            runtime.cancel.assert_awaited_once_with(run_ids=None)
            self.assertIsNone(app._active_turn_task)
            self.assertFalse(app._is_turn_running)

        asyncio.run(scenario())

    def test_run_agent_message_auto_dispatches_queued_payload_after_clean_finish(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(session=SimpleNamespace(session_id="s1"))
        app._queued_turn_payload = {"message": "next", "attachments": []}

        async def scenario() -> None:
            with (
                patch.object(app, "ensure_agent", new=AsyncMock()),
                patch.object(app, "add_user_message", new=AsyncMock()),
                patch.object(app, "_agent_turn", new=AsyncMock()),
                patch.object(app, "auto_save", new=AsyncMock()),
                patch.object(app, "_progress_state_label", return_value="thinking"),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "refresh_header"),
                patch.object(app, "_dispatch_queued_payload_if_ready", new=AsyncMock()) as dispatch_queued,
                patch.object(app, "_restore_queued_payload_after_unsuccessful_turn") as restore_queued,
            ):
                await app.run_agent_message("hello")
                dispatch_queued.assert_awaited_once()
                restore_queued.assert_not_called()

        asyncio.run(scenario())

    def test_run_agent_message_restores_queued_payload_after_error(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(session=SimpleNamespace(session_id="s1"))
        app._queued_turn_payload = {"message": "next", "attachments": []}

        async def fake_agent_turn(
            _agent,
            _message: str,
            _session_id: str,
            _turn_id: int,
            *,
            user_model_content=None,
            attachment_turn_id=None,
        ) -> None:
            app._turn_had_error = True

        async def scenario() -> None:
            with (
                patch.object(app, "ensure_agent", new=AsyncMock()),
                patch.object(app, "add_user_message", new=AsyncMock()),
                patch.object(app, "_agent_turn", new=fake_agent_turn),
                patch.object(app, "auto_save", new=AsyncMock()),
                patch.object(app, "_progress_state_label", return_value="thinking"),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "refresh_header"),
                patch.object(app, "_dispatch_queued_payload_if_ready", new=AsyncMock()) as dispatch_queued,
                patch.object(app, "_restore_queued_payload_after_unsuccessful_turn") as restore_queued,
            ):
                await app.run_agent_message("hello")
                dispatch_queued.assert_not_called()
                restore_queued.assert_called_once()

        asyncio.run(scenario())

    def test_run_agent_message_marks_turn_complete_before_auto_save(self) -> None:
        app = self._app()
        app.agent = SimpleNamespace(session=SimpleNamespace(session_id="s1"))

        async def auto_save_check() -> None:
            self.assertFalse(app._is_turn_running)

        async def scenario() -> None:
            with (
                patch.object(app, "ensure_agent", new=AsyncMock()),
                patch.object(app, "add_user_message", new=AsyncMock()),
                patch.object(app, "_agent_turn", new=AsyncMock()),
                patch.object(app, "auto_save", new=AsyncMock(side_effect=auto_save_check)) as auto_save,
                patch.object(app, "_progress_state_label", return_value="thinking"),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "refresh_header"),
                patch.object(app, "_dispatch_queued_payload_if_ready", new=AsyncMock()),
                patch.object(app, "_restore_queued_payload_after_unsuccessful_turn"),
            ):
                await app.run_agent_message("hello")
                auto_save.assert_awaited_once()

        asyncio.run(scenario())

    def test_run_agent_message_saves_inactive_thread_without_agent_swap(
        self,
    ) -> None:
        app = self._app()
        active_session = SimpleNamespace(session_id="active", turn_count=1)
        inactive_session = SimpleNamespace(
            session_id="inactive",
            turn_count=1,
            pending_attachment_paths=[],
            get_stats=lambda: {},
        )
        active_agent = SimpleNamespace(session=active_session)
        inactive_agent = SimpleNamespace(session=inactive_session)
        app.agent = active_agent
        app._remember_open_session(
            active_session,
            workspace=self.cwd,
            agent=active_agent,
        )
        app._remember_open_session(
            inactive_session,
            workspace=self.cwd / "inactive",
            agent=inactive_agent,
        )
        add_user = AsyncMock()
        save_session = AsyncMock()

        async def scenario() -> None:
            with (
                patch.object(app, "ensure_agent", new=AsyncMock()),
                patch.object(app, "add_user_message", new=add_user),
                patch.object(app, "_agent_turn", new=AsyncMock()),
                patch.object(app, "_progress_state_label", return_value="thinking"),
                patch.object(app, "_set_loading_state"),
                patch.object(app, "refresh_header"),
                patch.object(app, "_queue_session_tabs_refresh"),
                patch.object(app, "_broadcast_remote_state", new=AsyncMock()),
                patch.object(app, "_auto_save_session", new=save_session),
            ):
                await app.run_agent_message("hello", session_id="inactive")

        asyncio.run(scenario())

        self.assertIs(app.agent, active_agent)
        add_user.assert_not_awaited()
        save_session.assert_awaited_once()
        save_args, save_kwargs = save_session.await_args
        self.assertIs(save_args[0], inactive_session)
        self.assertEqual(
            save_kwargs["workspace"],
            (self.cwd / "inactive").resolve(),
        )
        self.assertFalse(save_kwargs["refresh_ui"])

    def test_dispatch_payload_binds_worker_to_current_thread(self) -> None:
        app = self._app()
        session = SimpleNamespace(session_id="active", pending_attachment_paths=[])
        app.agent = SimpleNamespace(session=session)
        worker_coroutines = []
        send_kwargs = {}

        def run_worker(coro, *, exclusive=False, group=None):
            worker_coroutines.append(coro)
            coro.close()

        async def fake_send(*_args, **_kwargs) -> None:
            return None

        async def scenario() -> None:
            with (
                patch.object(app, "run_worker", side_effect=run_worker),
                patch.object(
                    app,
                    "_handle_agent_send_with_intent",
                    side_effect=fake_send,
                ) as send,
            ):
                await app._dispatch_payload({"message": "hello from active"})
                send.assert_called_once()
                send_kwargs.update(send.call_args.kwargs)

        asyncio.run(scenario())

        self.assertEqual(send_kwargs["session_id"], "active")
        self.assertEqual(len(worker_coroutines), 1)

    def test_session_config_for_workspace_isolates_cwd_between_threads(self) -> None:
        app = self._app()
        first_workspace = self.cwd / "one"
        second_workspace = self.cwd / "two"
        first = Session(config=app._session_config_for_workspace(first_workspace))
        second = Session(config=app._session_config_for_workspace(second_workspace))

        app.config.cwd = self.cwd / "active"

        self.assertEqual(first.config.cwd, first_workspace.resolve())
        self.assertEqual(second.config.cwd, second_workspace.resolve())
        self.assertEqual(app.config.cwd, self.cwd / "active")

    def test_generate_session_name_uses_non_streaming_completion(self) -> None:
        app = self._app()

        async def fake_chat_completion(messages, tools=None, stream=True):
            self.assertFalse(stream)
            self.assertIsNone(tools)
            yield SimpleNamespace(text_delta=SimpleNamespace(content="Portfolio JSON Overview"))

        session = SimpleNamespace(
            client=SimpleNamespace(chat_completion=fake_chat_completion),
            name_generation_context=lambda: {
                "first_user": "Explain this portfolio project",
                "first_assistant": "",
                "latest_user": "Explain this portfolio project",
                "focus_hint": "portfolio structure",
            },
        )

        title = asyncio.run(app.generate_session_name(session))

        self.assertEqual(title, "Portfolio JSON Overview")

    def test_remember_open_session_tracks_order_and_workspace(self) -> None:
        app = self._app()
        first = SimpleNamespace(session_id="s1", name="One", turn_count=1)
        second = SimpleNamespace(session_id="s2", name="Two", turn_count=1)

        app._remember_open_session(first, workspace=self.cwd / "one")
        app._remember_open_session(second, workspace=self.cwd / "two")
        app._remember_open_session(first, workspace=self.cwd / "one")

        self.assertEqual(app._open_session_order, ["s1", "s2"])
        self.assertEqual(app._open_sessions["s1"], first)
        self.assertEqual(app._workspace_for_session_id("s2"), (self.cwd / "two").resolve())

    def test_start_new_thread_keeps_previous_session_open(self) -> None:
        app = self._app()
        previous = SimpleNamespace(
            session_id="s1",
            turn_count=3,
            client=SimpleNamespace(close=AsyncMock()),
            mcp_manager=SimpleNamespace(shutdown=AsyncMock()),
            approval_manager=SimpleNamespace(confirmation_callback="cb"),
        )
        fresh = SimpleNamespace(
            session_id="s2",
            turn_count=0,
            initialize=AsyncMock(),
            approval_manager=SimpleNamespace(confirmation_callback=None),
            client=SimpleNamespace(close=AsyncMock()),
            mcp_manager=SimpleNamespace(shutdown=AsyncMock()),
        )
        conversation = SimpleNamespace(remove_children=AsyncMock())
        app.agent = SimpleNamespace(session=previous)
        app._remember_open_session(previous, workspace=self.cwd)
        fresh_agent = SimpleNamespace(session=fresh, __aenter__=AsyncMock(return_value=None))

        async def scenario() -> None:
            with (
                patch.object(app, "ensure_agent", new=AsyncMock()),
                patch.object(app, "auto_save", new=AsyncMock()) as auto_save,
                patch.object(app, "_build_session_agent", return_value=fresh_agent),
                patch.object(app, "refresh_header"),
                patch.object(app, "post_system"),
                patch.object(app, "_refresh_empty_state"),
                patch.object(app, "_reset_session_local_ui_state"),
                patch.object(app, "query_one", return_value=conversation),
                patch("ite.ui.reup.app.Session", return_value=fresh),
            ):
                await app.start_new_thread()
                auto_save.assert_awaited_once()

        asyncio.run(scenario())

        previous.client.close.assert_not_awaited()
        previous.mcp_manager.shutdown.assert_not_awaited()
        fresh_agent.__aenter__.assert_awaited_once()
        self.assertIs(app.agent, fresh_agent)
        self.assertEqual(app._open_session_order, ["s1", "s2"])
        self.assertIs(app._open_sessions["s1"], previous)
        self.assertIs(app._open_sessions["s2"], fresh)

    def test_resume_snapshot_reuses_already_open_session(self) -> None:
        app = self._app()
        current = SimpleNamespace(
            session_id="current",
            client=SimpleNamespace(close=AsyncMock()),
            mcp_manager=SimpleNamespace(shutdown=AsyncMock()),
        )
        existing = SimpleNamespace(session_id="saved", name="Saved", turn_count=2)
        app.agent = SimpleNamespace(session=current)
        app._remember_open_session(current, workspace=self.cwd)
        app._remember_open_session(existing, workspace=self.cwd / "saved")
        snapshot = SessionSnapshot(
            session_id="saved",
            name="Saved",
            workspace_path=str((self.cwd / "saved").resolve()),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            turn_count=2,
            messages=[],
            total_usage=TokenUsage(),
        )

        async def scenario() -> None:
            with (
                patch.object(app, "ensure_agent", new=AsyncMock()),
                patch.object(app, "_activate_open_session", new=AsyncMock(return_value=True)) as activate,
                patch("ite.ui.reup.app.Session") as session_cls,
            ):
                await app._resume_snapshot(snapshot)
                activate.assert_awaited_once_with(
                    "saved",
                    announce="Switched to already-open thread.",
                )
                session_cls.assert_not_called()

        asyncio.run(scenario())
        current.client.close.assert_not_awaited()
        current.mcp_manager.shutdown.assert_not_awaited()

    def test_resume_snapshot_replaces_empty_active_thread_tab(self) -> None:
        app = self._app()
        conversation = AsyncMock()
        restored_messages = [{"role": "user", "content": "restored from runtime"}]
        current = SimpleNamespace(
            session_id="current",
            turn_count=0,
            client=SimpleNamespace(close=AsyncMock()),
            mcp_manager=SimpleNamespace(shutdown=AsyncMock()),
        )
        current_agent = SimpleNamespace(
            session=current,
            __aexit__=AsyncMock(),
        )
        resumed = SimpleNamespace(
            session_id="saved",
            name="Saved",
            turn_count=2,
            context_manager=SimpleNamespace(
                set_messages=lambda messages: None,
                get_snapshot_messages=lambda: restored_messages,
                total_usage=TokenUsage(),
            ),
            restore_todos_state=lambda state: None,
            restore_change_history_state=lambda state: None,
        )
        resumed_agent = SimpleNamespace(__aenter__=AsyncMock(), __aexit__=AsyncMock())
        app.agent = current_agent
        app._remember_open_session(current, workspace=self.cwd, agent=current_agent)
        snapshot = SessionSnapshot(
            session_id="saved",
            name="Saved",
            workspace_path=str((self.cwd / "saved").resolve()),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            turn_count=2,
            messages=[],
            total_usage=TokenUsage(),
        )

        async def scenario() -> None:
            with (
                patch.object(app, "ensure_agent", new=AsyncMock()),
                patch.object(app, "_build_session_agent", return_value=resumed_agent),
                patch.object(app, "refresh_header"),
                patch.object(app, "_hydrate_chat_from_snapshot", new=AsyncMock()) as hydrate,
                patch.object(app, "_remove_cards_by_title", new=AsyncMock()),
                patch.object(app, "query_one", return_value=conversation),
                patch("ite.ui.reup.app.Session", return_value=resumed),
            ):
                await app._resume_snapshot(snapshot)
                hydrate.assert_awaited_once_with(restored_messages)

        asyncio.run(scenario())

        self.assertEqual(app._open_session_order, ["saved"])
        self.assertNotIn("current", app._open_sessions)
        self.assertIs(app.agent, resumed_agent)
        current_agent.__aexit__.assert_awaited_once()

    def test_resume_snapshot_prefers_restored_transcript_messages_for_hydration(self) -> None:
        app = self._app()
        conversation = AsyncMock()
        restored_messages = [{"role": "assistant", "content": "runtime truth"}]
        snapshot_messages = [{"role": "assistant", "content": "snapshot fallback"}]
        current = SimpleNamespace(
            session_id="current",
            turn_count=1,
            client=SimpleNamespace(close=AsyncMock()),
            mcp_manager=SimpleNamespace(shutdown=AsyncMock()),
        )
        current_agent = SimpleNamespace(session=current)
        resumed_context = SimpleNamespace(
            restore_transcript_state=unittest.mock.Mock(),
            get_snapshot_messages=lambda: restored_messages,
            total_usage=TokenUsage(),
        )
        resumed = SimpleNamespace(
            session_id="saved",
            name="Saved",
            turn_count=2,
            context_manager=resumed_context,
            restore_todos_state=lambda state: None,
            restore_change_history_state=lambda state: None,
        )
        resumed_agent = SimpleNamespace(__aenter__=AsyncMock(), __aexit__=AsyncMock())
        app.agent = current_agent
        app._remember_open_session(current, workspace=self.cwd, agent=current_agent)
        snapshot = SessionSnapshot(
            session_id="saved",
            name="Saved",
            workspace_path=str((self.cwd / "saved").resolve()),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            turn_count=2,
            messages=snapshot_messages,
            transcript_state={"active_start": 0, "events": []},
            total_usage=TokenUsage(),
        )

        async def scenario() -> None:
            with (
                patch.object(app, "ensure_agent", new=AsyncMock()),
                patch.object(app, "_build_session_agent", return_value=resumed_agent),
                patch.object(app, "refresh_header"),
                patch.object(app, "_hydrate_chat_from_snapshot", new=AsyncMock()) as hydrate,
                patch.object(app, "_remove_cards_by_title", new=AsyncMock()),
                patch.object(app, "query_one", return_value=conversation),
                patch("ite.ui.reup.app.Session", return_value=resumed),
            ):
                await app._resume_snapshot(snapshot)
                hydrate.assert_awaited_once_with(restored_messages)

        asyncio.run(scenario())
        resumed_context.restore_transcript_state.assert_called_once_with(
            snapshot.transcript_state
        )


if __name__ == "__main__":
    unittest.main()
