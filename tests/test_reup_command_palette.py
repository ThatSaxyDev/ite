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
from ite.config.config import Config
from ite.client.response import TokenUsage
from ite.agent.session_manager import SessionSnapshot
from ite.ui.reup.app import ReupApp
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
        self.assertEqual([entry.name for entry in filtered], ["/approval"])
        self.assertEqual(filtered[0].description, "Show or change approval mode")

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

    def test_build_command_result_renderable_dims_box_lines(self) -> None:
        app = self._app()

        rendered = app._build_command_result_renderable("title\n│────│\nvalue")
        renderables = list(rendered.renderables)

        self.assertEqual(len(renderables), 3)
        self.assertEqual(renderables[1].style, "#5f6975")

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
            app.config.model.name = "minimax-m2.7:cloud"

            async def fake_open_modal(modal):
                self.assertEqual(modal._models[0]["model_name"], "minimax-m2.7:cloud")
                self.assertFalse(modal._models[0]["available"])
                self.assertEqual(
                    modal._models[0]["unavailable_reason"],
                    "Local bundled provider returned 500.",
                )
                self.assertTrue(modal._models[1]["available"])
                return None

            with patch.object(app, "ensure_agent", AsyncMock()), patch(
                "ite.ui.reup.app.get_bundled_models",
                return_value=[
                    {
                        "model_name": "minimax-m2.7:cloud",
                        "label": "MiniMax M2.7",
                        "provider": "Bundled",
                        "available": False,
                        "unavailable_reason": "Local bundled provider returned 500.",
                    },
                    {
                        "model_name": "glm-5:cloud",
                        "label": "GLM-5",
                        "provider": "Bundled",
                        "available": True,
                        "unavailable_reason": "",
                    },
                ],
            ), patch.object(app, "_open_modal", AsyncMock(side_effect=fake_open_modal)), patch.object(
                app, "post_system"
            ) as post_system:
                await app._open_model_picker_from_meta()

            post_system.assert_not_called()

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
        self.assertEqual(post_system.call_args.args[0], "Context automatically compacted")
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
                patch.object(app, "_hydrate_chat_from_snapshot", new=AsyncMock()),
                patch.object(app, "_remove_cards_by_title", new=AsyncMock()),
                patch.object(app, "query_one", return_value=conversation),
                patch("ite.ui.reup.app.Session", return_value=resumed),
            ):
                await app._resume_snapshot(snapshot)

        asyncio.run(scenario())

        self.assertEqual(app._open_session_order, ["saved"])
        self.assertNotIn("current", app._open_sessions)
        self.assertIs(app.agent, resumed_agent)
        current_agent.__aexit__.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
