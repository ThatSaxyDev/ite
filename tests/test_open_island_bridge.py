from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from typing import Any

from ite.agent.events import AgentEvent
from ite.integrations.open_island.bridge import OpenIslandBridge, build_bridge
from ite.integrations.open_island.terminal import TerminalContext
from ite.tools.base import ToolResult

_TERMINAL = TerminalContext(app="iTerm", tty="/dev/ttys001")


class _RecordingClient:
    """Captures bridge commands so tests can assert on the emitted protocol."""

    def __init__(self, fail: bool = False) -> None:
        self.commands: list[dict[str, Any]] = []
        self.fail = fail
        self.sync_commands: list[dict[str, Any]] = []

    async def try_send(
        self, command: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any] | None:
        if self.fail:
            raise RuntimeError("bridge unavailable")
        self.commands.append(command)
        return {"type": "acknowledged"}

    def send_sync(
        self, command: dict[str, Any], *, timeout: float = 2.0
    ) -> dict[str, Any] | None:
        self.sync_commands.append(command)
        return {"type": "acknowledged"}

    def hooks(self) -> list[dict[str, Any]]:
        return [c["claudeHook"] for c in self.commands]

    def events_of(self, event_name: str) -> list[dict[str, Any]]:
        return [h for h in self.hooks() if h["hook_event_name"] == event_name]


def _bridge(client: Any, *, enabled: bool = True) -> OpenIslandBridge:
    return OpenIslandBridge(
        session_id="sid-1",
        cwd="/tmp/project",
        enabled=enabled,
        client=client,
        terminal=_TERMINAL,
        platform="darwin",
    )


async def _drain(bridge: OpenIslandBridge) -> None:
    """Let the bridge worker consume queued events."""
    await asyncio.sleep(0)
    for _ in range(20):
        if bridge._queue.empty():
            break
        await asyncio.sleep(0.01)


class BridgeDisabledTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_bridge_emits_nothing(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client, enabled=False)

        bridge.observe(AgentEvent.agent_start("hello"))
        await _drain(bridge)

        self.assertEqual(client.commands, [])

    async def test_disabled_bridge_does_not_start_worker(self) -> None:
        bridge = _bridge(_RecordingClient(), enabled=False)
        bridge.observe(AgentEvent.agent_start("hello"))

        self.assertIsNone(bridge._worker)


class BridgeMappingTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_start_emits_session_start_and_prompt(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("do the thing"))
        await _drain(bridge)

        starts = client.events_of("SessionStart")
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["session_id"], "sid-1")
        self.assertEqual(starts[0]["terminal_app"], "iTerm")

        prompts = client.events_of("UserPromptSubmit")
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["prompt"], "do the thing")

    async def test_session_start_only_emitted_once_per_session(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("first"))
        await _drain(bridge)
        bridge.observe(AgentEvent.agent_end(response="done"))
        await _drain(bridge)
        bridge.observe(AgentEvent.agent_start("second"))
        await _drain(bridge)

        self.assertEqual(len(client.events_of("SessionStart")), 1)
        self.assertEqual(len(client.events_of("UserPromptSubmit")), 2)

    async def test_tool_start_emits_pre_tool_use(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.tool_call_start("call-1", "read_file", {"path": "a.py"}))
        await _drain(bridge)

        events = client.events_of("PreToolUse")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tool_name"], "read_file")
        self.assertEqual(events[0]["tool_use_id"], "call-1")

    async def test_tool_complete_success_emits_post_tool_use(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(
            AgentEvent.tool_call_complete(
                "call-1", "read_file", ToolResult(success=True, output="contents")
            )
        )
        await _drain(bridge)

        events = client.events_of("PostToolUse")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tool_response"], "contents")

    async def test_tool_complete_failure_emits_failure_event(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(
            AgentEvent.tool_call_complete(
                "call-1", "shell", ToolResult(success=False, output="", error="boom")
            )
        )
        await _drain(bridge)

        events = client.events_of("PostToolUseFailure")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["error"], "boom")

    async def test_agent_end_emits_stop(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_end(response="all done"))
        await _drain(bridge)

        events = client.events_of("Stop")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["last_assistant_message"], "all done")

    async def test_agent_error_emits_stop_failure(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_error("kaboom"))
        await _drain(bridge)

        events = client.events_of("StopFailure")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["error"], "kaboom")

    async def test_context_compacted_emits_pre_compact(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.context_compacted(1000, 128000, 500))
        await _drain(bridge)

        self.assertEqual(len(client.events_of("PreCompact")), 1)

    async def test_unmapped_events_produce_no_traffic(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.text_delta("streaming..."))
        bridge.observe(AgentEvent.usage_update({"total_tokens": 10}))
        await _drain(bridge)

        self.assertEqual(client.commands, [])


class BridgeFailOpenTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_failure_does_not_raise(self) -> None:
        bridge = _bridge(_RecordingClient(fail=True))

        bridge.observe(AgentEvent.agent_start("hello"))
        await _drain(bridge)

    async def test_teardown_sends_session_end_synchronously(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.close()

        self.assertEqual(len(client.sync_commands), 1)
        self.assertEqual(
            client.sync_commands[0]["claudeHook"]["hook_event_name"], "SessionEnd"
        )

    async def test_teardown_is_idempotent(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.close()
        bridge.close()

        self.assertEqual(len(client.sync_commands), 1)


class BuildBridgeTests(unittest.TestCase):
    def test_returns_none_when_disabled(self) -> None:
        self.assertIsNone(
            build_bridge("sid", Path("/tmp"), enabled=False, client=_RecordingClient())
        )

    def test_returns_none_without_session_id(self) -> None:
        self.assertIsNone(
            build_bridge(None, Path("/tmp"), enabled=True, client=_RecordingClient())
        )

    def test_returns_bridge_when_enabled(self) -> None:
        bridge = build_bridge(
            "sid", Path("/tmp"), enabled=True, client=_RecordingClient()
        )
        self.assertIsNotNone(bridge)


class BridgeNoEventLoopTests(unittest.TestCase):
    """Covers observe() being called with no running loop.

    The agent always runs inside a loop, but constructing a bridge from a
    synchronous context must not raise or leave a half-started worker.
    """

    def test_observe_without_running_loop_is_safe(self) -> None:
        bridge = _bridge(_RecordingClient())

        bridge.observe(AgentEvent.agent_start("hello"))

        self.assertFalse(bridge._started)
        self.assertIsNone(bridge._worker)

    def test_observe_without_loop_disables_bridge(self) -> None:
        bridge = _bridge(_RecordingClient())

        bridge.observe(AgentEvent.agent_start("hello"))

        self.assertFalse(bridge.enabled)
        self.assertEqual(bridge._queue.qsize(), 0)


if __name__ == "__main__":
    unittest.main()
