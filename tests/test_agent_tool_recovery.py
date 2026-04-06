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
