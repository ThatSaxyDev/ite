import unittest
import asyncio
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, PropertyMock, patch
from types import SimpleNamespace

from ite.agent.events import AgentEvent, AgentEventType
from ite.config.config import Config
from ite.client.response import TokenUsage
from ite.agent.session_manager import SessionSnapshot
from ite.ui.reup.app import ReupApp
from ite.ui.reup.tool_views import shell_session_state, split_shell_payload
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
        self.assertEqual(slash_only[0].name, "/approval")
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
            "✅",
        )
        self.assertEqual(
            ReupApp._shell_card_icon_and_style(
                {"status": "exited", "running": False},
                success=False,
            )[0],
            "❌",
        )

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

    def test_reset_session_local_ui_state_clears_shell_session_cards(self) -> None:
        app = self._app()
        app._shell_session_cards["sh_123"] = Static()
        app._tool_widgets["call_1"] = Static()
        app._tool_args_by_call_id["call_1"] = {"session_id": "sh_123"}

        with patch.object(ReupApp, "is_mounted", new_callable=PropertyMock, return_value=False):
            app._reset_session_local_ui_state()

        self.assertEqual(app._shell_session_cards, {})
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
                    "name": "read_file",
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

    def test_shell_session_cards_track_multiple_active_sessions(self) -> None:
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
                patch.object(app, "_move_card_to_bottom", new=AsyncMock()),
            ):
                await app.add_tool_call_start(
                    call_id="call_1",
                    name="shell_start",
                    tool_kind="shell",
                    arguments={},
                )
                await app.update_tool_call(
                    call_id="call_1",
                    name="shell_start",
                    tool_kind="shell",
                    success=True,
                    output="Started interactive shell session `sh_one`.",
                    error=None,
                    metadata={
                        "session_id": "sh_one",
                        "running": True,
                        "status": "idle",
                        "mode": "shell",
                    },
                    diff=None,
                    truncated=False,
                    exit_code=None,
                )
                await app.add_tool_call_start(
                    call_id="call_2",
                    name="shell_start",
                    tool_kind="shell",
                    arguments={},
                )
                await app.update_tool_call(
                    call_id="call_2",
                    name="shell_start",
                    tool_kind="shell",
                    success=True,
                    output="Started interactive shell session `sh_two`.",
                    error=None,
                    metadata={
                        "session_id": "sh_two",
                        "running": True,
                        "status": "idle",
                        "mode": "shell",
                    },
                    diff=None,
                    truncated=False,
                    exit_code=None,
                )

            self.assertEqual(set(app._shell_session_cards), {"sh_one", "sh_two"})
            self.assertNotEqual(
                app._shell_session_cards["sh_one"],
                app._shell_session_cards["sh_two"],
            )

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
