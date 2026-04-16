import tempfile
import unittest
from pathlib import Path

from ite.agent.agent import Agent
from ite.agent.events import AgentEventType
from ite.client.response import StreamEvent
from ite.client.response import StreamEventType
from ite.client.response import TextDelta
from ite.client.response import ToolCall
from ite.config.config import Config
from ite.tools.base import Tool
from ite.tools.base import ToolInvocation
from ite.tools.base import ToolKind
from ite.tools.base import ToolResult


class _FakeTool(Tool):
    name = "fake_tool"
    description = "Fake tool"
    kind = ToolKind.WRITE
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        return ToolResult.success_result("tool finished")


class _FakeGlobTool(Tool):
    name = "glob"
    description = "Fake glob tool"
    kind = ToolKind.READ
    schema = {
        "type": "object",
        "properties": {"pattern": {"type": "string"}},
        "required": ["pattern"],
    }

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        return ToolResult.success_result("matched files")


class _FakeListDirTool(Tool):
    name = "list_dir"
    description = "Fake list dir tool"
    kind = ToolKind.READ
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        return ToolResult.success_result("docs/\nite-cloud-api/\nite-cloud-web/")


class _SequenceClient:
    def __init__(self) -> None:
        self.calls = 0

    async def close(self) -> None:
        return None

    async def chat_completion(self, messages, tools=None, stream=True):
        self.calls += 1
        if self.calls == 1:
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id="call_fake_1",
                    name="fake_tool",
                    arguments={"value": "x"},
                ),
            )
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")
            return
        if self.calls == 2:
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")
            return

        yield StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            text_delta=TextDelta(content="Finished the task."),
        )
        yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")


class _ToolOnlyLoopClient:
    def __init__(self) -> None:
        self.calls = 0

    async def close(self) -> None:
        return None

    async def chat_completion(self, messages, tools=None, stream=True):
        self.calls += 1
        system_text = " ".join(
            str(message.get("content") or "")
            for message in messages
            if isinstance(message, dict) and str(message.get("role") or "") == "system"
        )
        if "[SYSTEM NOTICE: Loop Detected]" in system_text:
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(
                    content="Here is the current state and the next unresolved question."
                ),
            )
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")
            return

        yield StreamEvent(
            type=StreamEventType.TOOL_CALL_COMPLETE,
            tool_call=ToolCall(
                call_id=f"call_fake_loop_{self.calls}",
                name="fake_tool",
                arguments={"value": "x"},
            ),
        )
        yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")


class _StatusThenWriteClient:
    def __init__(self) -> None:
        self.calls = 0

    async def close(self) -> None:
        return None

    async def chat_completion(self, messages, tools=None, stream=True):
        self.calls += 1
        if self.calls == 1:
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(
                    content="The providers directory exists but is empty. Starting with the provider files."
                ),
            )
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")
            return
        if self.calls == 2:
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id="call_write_1",
                    name="write_file",
                    arguments={
                        "path": "lib/features/editor/providers/project_provider.dart",
                        "content": "final projectProvider = Object();\n",
                    },
                ),
            )
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")
            return
        yield StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            text_delta=TextDelta(content="Added the missing provider files."),
        )
        yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")


class _RawToolMarkupClient:
    def __init__(self) -> None:
        self.calls = 0

    async def close(self) -> None:
        return None

    async def chat_completion(self, messages, tools=None, stream=True):
        self.calls += 1
        yield StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            text_delta=TextDelta(
                content='<|tool_call|>call:glob{"pattern":"**/*"}<|tool_call|>'
            ),
        )
        yield StreamEvent(
            type=StreamEventType.TOOL_CALL_COMPLETE,
            tool_call=ToolCall(
                call_id="call_glob_1",
                name="glob",
                arguments={"pattern": "**/*"},
            ),
        )
        yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")


class _SplitRawToolMarkupClient:
    def __init__(self) -> None:
        self.calls = 0

    async def close(self) -> None:
        return None

    async def chat_completion(self, messages, tools=None, stream=True):
        self.calls += 1
        for chunk in (
            "<|tool",
            "_call|>call:glob",
            '{"pattern":"**/*"}',
            "<|tool_call|>",
        ):
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(content=chunk),
            )
        yield StreamEvent(
            type=StreamEventType.TOOL_CALL_COMPLETE,
            tool_call=ToolCall(
                call_id="call_glob_2",
                name="glob",
                arguments={"pattern": "**/*"},
            ),
        )
        yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")


class _MalformedClosingToolMarkupClient:
    def __init__(self) -> None:
        self.calls = 0

    async def close(self) -> None:
        return None

    async def chat_completion(self, messages, tools=None, stream=True):
        self.calls += 1
        yield StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            text_delta=TextDelta(
                content='<|tool_call|>call:list_dir{path:<|"|>Docs<|"|>}<tool_call|>'
            ),
        )
        yield StreamEvent(
            type=StreamEventType.TOOL_CALL_COMPLETE,
            tool_call=ToolCall(
                call_id="call_list_dir_1",
                name="list_dir",
                arguments={"path": "Docs"},
            ),
        )
        yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")


class _DuplicateDiscoveryClient:
    def __init__(self) -> None:
        self.calls = 0

    async def close(self) -> None:
        return None

    async def chat_completion(self, messages, tools=None, stream=True):
        self.calls += 1
        if self.calls == 1:
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id="call_list_1",
                    name="list_dir",
                    arguments={"path": "."},
                ),
            )
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id="call_list_2",
                    name="list_dir",
                    arguments={"path": "./"},
                ),
            )
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")
            return

        yield StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            text_delta=TextDelta(content="The deployment docs live in docs/."),
        )
        yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")


class _CrossTurnDuplicateDiscoveryClient:
    def __init__(self) -> None:
        self.calls = 0

    async def close(self) -> None:
        return None

    async def chat_completion(self, messages, tools=None, stream=True):
        self.calls += 1
        if self.calls == 1:
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id="call_list_first",
                    name="list_dir",
                    arguments={"path": "docs"},
                ),
            )
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")
            return
        if self.calls == 2:
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id="call_list_repeat",
                    name="list_dir",
                    arguments={"path": "./docs"},
                ),
            )
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")
            return

        yield StreamEvent(
            type=StreamEventType.TEXT_DELTA,
            text_delta=TextDelta(content="The deployment docs live in docs/."),
        )
        yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")


class _StuckDiscoveryClient:
    def __init__(self) -> None:
        self.calls = 0

    async def close(self) -> None:
        return None

    async def chat_completion(self, messages, tools=None, stream=True):
        self.calls += 1
        if self.calls == 1:
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id="call_list_seed",
                    name="list_dir",
                    arguments={"path": "docs"},
                ),
            )
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")
            return

        yield StreamEvent(
            type=StreamEventType.TOOL_CALL_COMPLETE,
            tool_call=ToolCall(
                call_id=f"call_list_repeat_{self.calls}",
                name="list_dir",
                arguments={"path": "./docs"},
            ),
        )
        yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE, finish_reason="stop")


class AgentToolRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config = Config(cwd=Path(self.temp_dir.name), api_key="test")
        self.agent = Agent(self.config)

    def test_suppresses_malformed_empty_shell_call(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "shell",
                ["Parameter 'command': Field required"],
            )
        )

    def test_suppresses_malformed_empty_read_call(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "read_file",
                ["Parameter 'path': Field required"],
            )
        )

    def test_suppresses_malformed_empty_media_read_calls(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "read_image",
                ["Parameter 'path': Field required"],
            )
        )
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "read_pdf",
                ["Parameter 'path': Field required"],
            )
        )

    def test_does_not_suppress_nonrequired_tool_errors(self) -> None:
        self.assertFalse(
            self.agent._should_suppress_malformed_tool_call(
                "shell",
                ["Parameter 'timeout': Input should be greater than or equal to 1"],
            )
        )

    def test_suppresses_malformed_empty_edit_call(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "edit",
                [
                    "Parameter 'path': Field required",
                    "Parameter 'new_string': Field required",
                ],
            )
        )

    def test_suppresses_malformed_empty_apply_patch_call(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "apply_patch",
                ["Parameter 'patch': Field required"],
            )
        )

    def test_suppresses_malformed_empty_memory_call(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "memory",
                ["Parameter 'action': Field required"],
            )
        )

    def test_rewrites_todo_add_to_list_when_scope_already_seeded(self) -> None:
        self.agent.session.restore_todos_state(
            {
                "version": 1,
                "planning": [],
                "execution": [
                    {"id": "todo1", "content": "Implement retry logic", "completed": False}
                ],
            }
        )

        rewritten, note = self.agent._rewrite_todo_tool_call(
            self.agent.session,
            {"action": "add", "scope": "execution", "content": "Create another checklist"},
        )

        self.assertEqual(
            rewritten,
            {
                "action": "list",
                "scope": "execution",
                "_suppress_ui": True,
                "_runtime_reused_checklist": True,
            },
        )
        self.assertIn("already exists", note or "")

    def test_rewrites_todo_complete_without_id_to_list_when_scope_exists(self) -> None:
        self.agent.session.restore_todos_state(
            {
                "version": 1,
                "planning": [
                    {"id": "todo2", "content": "Clarify requirements", "completed": False}
                ],
                "execution": [],
            }
        )

        rewritten, note = self.agent._rewrite_todo_tool_call(
            self.agent.session,
            {"action": "complete", "scope": "planning"},
        )

        self.assertEqual(
            rewritten,
            {
                "action": "list",
                "scope": "planning",
                "_suppress_ui": True,
                "_runtime_reused_checklist": True,
            },
        )
        self.assertIn("missing", note or "")

    def test_consumes_complete_raw_tool_markup_without_visible_text(self) -> None:
        visible, remainder, inside = self.agent._consume_raw_tool_call_markup(
            '<|tool_call|>call:glob{"pattern":"**/*"}<|tool_call|>',
            inside_markup=False,
            final=True,
        )

        self.assertEqual(visible, "")
        self.assertEqual(remainder, "")
        self.assertFalse(inside)

    def test_consumes_split_raw_tool_markup_without_visible_text(self) -> None:
        visible_1, remainder_1, inside_1 = self.agent._consume_raw_tool_call_markup(
            "<|tool",
            inside_markup=False,
        )
        visible_2, remainder_2, inside_2 = self.agent._consume_raw_tool_call_markup(
            remainder_1 + '_call|>call:glob{"pattern":"**/*"}',
            inside_markup=inside_1,
        )
        visible_3, remainder_3, inside_3 = self.agent._consume_raw_tool_call_markup(
            remainder_2 + "<|tool_call|>",
            inside_markup=inside_2,
            final=True,
        )

        self.assertEqual(visible_1 + visible_2 + visible_3, "")
        self.assertEqual(remainder_3, "")
        self.assertFalse(inside_3)

    def test_consumes_malformed_closing_tool_markup_without_visible_text(self) -> None:
        visible, remainder, inside = self.agent._consume_raw_tool_call_markup(
            '<|tool_call|>call:list_dir{path:<|"|>Docs<|"|>}<tool_call|>',
            inside_markup=False,
            final=True,
        )

        self.assertEqual(visible, "")
        self.assertEqual(remainder, "")
        self.assertFalse(inside)


class AgentEmptyReplyRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config = Config(cwd=Path(self.temp_dir.name), api_key="test")
        self.agent = Agent(self.config)
        await self.agent.__aenter__()
        self.addAsyncCleanup(self.agent.__aexit__, None, None, None)

    async def test_retries_empty_reply_after_tool_execution(self) -> None:
        fake_client = _SequenceClient()
        self.agent.session.client = fake_client
        self.agent.session.tool_registry.register(_FakeTool(self.config))

        events = [event async for event in self.agent.run("do the task")]

        self.assertEqual(fake_client.calls, 3)
        self.assertFalse(any(event.type == AgentEventType.AGENT_ERROR for event in events))
        self.assertTrue(
            any(
                event.type == AgentEventType.TEXT_COMPLETE
                and event.data.get("content") == "Finished the task."
                for event in events
            )
        )

    async def test_forces_summary_after_repeated_tool_only_turns(self) -> None:
        fake_client = _ToolOnlyLoopClient()
        self.agent.session.client = fake_client
        self.agent.session.tool_registry.register(_FakeTool(self.config))

        events = [event async for event in self.agent.run("audit the runtime deeply and keep going")]

        self.assertGreaterEqual(fake_client.calls, 4)
        self.assertFalse(any(event.type == AgentEventType.AGENT_ERROR for event in events))
        self.assertTrue(
            any(
                event.type == AgentEventType.TEXT_COMPLETE
                and "current state" in str(event.data.get("content", "")).lower()
                for event in events
            )
        )

    async def test_pending_execution_work_blocks_status_only_completion(self) -> None:
        fake_client = _StatusThenWriteClient()
        self.agent.session.client = fake_client
        self.agent.session.restore_todos_state(
            {
                "version": 1,
                "planning": [],
                "execution": [
                    {
                        "id": "todo-1",
                        "content": "Create provider files",
                        "completed": False,
                    },
                    {
                        "id": "todo-2",
                        "content": "Summarize outcome and changed files",
                        "completed": False,
                    },
                ],
            }
        )

        events = [event async for event in self.agent.run("finish the provider setup")]

        completed = [
            str(event.data.get("content", ""))
            for event in events
            if event.type == AgentEventType.TEXT_COMPLETE
        ]

        self.assertEqual(fake_client.calls, 3)
        self.assertFalse(any(event.type == AgentEventType.AGENT_ERROR for event in events))
        self.assertEqual(completed, ["Added the missing provider files."])
        self.assertTrue(
            (
                Path(self.temp_dir.name)
                / "lib/features/editor/providers/project_provider.dart"
            ).exists()
        )

    def test_finish_setup_request_is_treated_as_execution_intent(self) -> None:
        from ite.memory.response_intent import resolve_response_intent

        intent = resolve_response_intent("finish the provider setup")

        self.assertEqual(intent.task_mode, "execute")

    async def test_raw_tool_markup_text_is_not_rendered_before_tool_call(self) -> None:
        fake_client = _RawToolMarkupClient()
        self.agent.session.client = fake_client
        self.agent.session.tool_registry.register(_FakeGlobTool(self.config))

        events = [event async for event in self.agent.run("search the workspace")]

        text_events = [
            str(event.data.get("content", ""))
            for event in events
            if event.type in {AgentEventType.TEXT_DELTA, AgentEventType.TEXT_COMPLETE}
        ]

        self.assertEqual(text_events, [])
        self.assertTrue(
            any(
                event.type == AgentEventType.TOOL_CALL_START
                and event.data.get("name") == "glob"
                for event in events
            )
        )

    async def test_split_raw_tool_markup_text_is_not_rendered_before_tool_call(self) -> None:
        fake_client = _SplitRawToolMarkupClient()
        self.agent.session.client = fake_client
        self.agent.session.tool_registry.register(_FakeGlobTool(self.config))

        events = [event async for event in self.agent.run("search the workspace")]

        text_events = [
            str(event.data.get("content", ""))
            for event in events
            if event.type in {AgentEventType.TEXT_DELTA, AgentEventType.TEXT_COMPLETE}
        ]

        self.assertEqual(text_events, [])
        self.assertTrue(
            any(
                event.type == AgentEventType.TOOL_CALL_START
                and event.data.get("name") == "glob"
                for event in events
            )
        )

    async def test_malformed_closing_tool_markup_text_is_not_rendered_before_tool_call(self) -> None:
        fake_client = _MalformedClosingToolMarkupClient()
        self.agent.session.client = fake_client
        self.agent.session.tool_registry.register(_FakeGlobTool(self.config))

        events = [event async for event in self.agent.run("check the docs folder")]

        text_events = [
            str(event.data.get("content", ""))
            for event in events
            if event.type in {AgentEventType.TEXT_DELTA, AgentEventType.TEXT_COMPLETE}
        ]

        self.assertEqual(text_events, [])
        self.assertTrue(
            any(
                event.type == AgentEventType.TOOL_CALL_START
                and event.data.get("name") == "list_dir"
                for event in events
            )
        )

    async def test_duplicate_discovery_call_is_suppressed_with_recovery_hint(self) -> None:
        fake_client = _DuplicateDiscoveryClient()
        self.agent.session.client = fake_client
        self.agent.session.tool_registry.register(_FakeListDirTool(self.config))

        events = [event async for event in self.agent.run("find the deployment docs")]

        starts = [
            event
            for event in events
            if event.type == AgentEventType.TOOL_CALL_START
            and event.data.get("name") == "list_dir"
        ]
        completions = [
            event
            for event in events
            if event.type == AgentEventType.TOOL_CALL_COMPLETE
            and event.data.get("name") == "list_dir"
        ]
        summaries = [
            str(event.data.get("content", ""))
            for event in events
            if event.type == AgentEventType.TEXT_COMPLETE
        ]

        self.assertEqual(fake_client.calls, 2)
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(completions), 2)
        self.assertTrue(
            any(
                bool((event.data.get("metadata") or {}).get("reused_cached_discovery"))
                for event in completions
            )
        )
        self.assertEqual(summaries, ["The deployment docs live in docs/."])

    async def test_cross_turn_duplicate_discovery_call_reuses_cached_result(self) -> None:
        fake_client = _CrossTurnDuplicateDiscoveryClient()
        self.agent.session.client = fake_client
        self.agent.session.tool_registry.register(_FakeListDirTool(self.config))

        events = [event async for event in self.agent.run("find the deployment docs")]

        starts = [
            event
            for event in events
            if event.type == AgentEventType.TOOL_CALL_START
            and event.data.get("name") == "list_dir"
        ]
        completions = [
            event
            for event in events
            if event.type == AgentEventType.TOOL_CALL_COMPLETE
            and event.data.get("name") == "list_dir"
        ]
        summaries = [
            str(event.data.get("content", ""))
            for event in events
            if event.type == AgentEventType.TEXT_COMPLETE
        ]

        self.assertEqual(fake_client.calls, 3)
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(completions), 2)
        self.assertTrue(
            any(
                bool((event.data.get("metadata") or {}).get("reused_cached_discovery"))
                for event in completions
            )
        )
        self.assertEqual(summaries, ["The deployment docs live in docs/."])

    async def test_repeated_cached_discovery_stall_ends_run_with_error(self) -> None:
        fake_client = _StuckDiscoveryClient()
        self.agent.session.client = fake_client
        self.agent.session.tool_registry.register(_FakeListDirTool(self.config))

        events = [event async for event in self.agent.run("find the deployment docs")]

        errors = [
            str(event.data.get("error", ""))
            for event in events
            if event.type == AgentEventType.AGENT_ERROR
        ]

        self.assertEqual(fake_client.calls, 3)
        self.assertTrue(
            any("stuck repeating the same discovery step" in error for error in errors)
        )
