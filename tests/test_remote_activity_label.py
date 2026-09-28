from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from ite.agent.events import AgentEvent, AgentEventType
from ite.remote.host import HeadlessRuntimeHost


class _FakeServer:
    """Counts state broadcasts so we can assert on publish frequency."""

    def __init__(self) -> None:
        self.state_publishes = 0
        self.events: list[dict[str, Any]] = []

    async def publish_state(self) -> None:
        self.state_publishes += 1

    async def publish_event(self, payload: dict[str, Any]) -> None:
        self.events.append(payload)

    def has_authenticated_clients(self) -> bool:
        return True


def _host() -> tuple[HeadlessRuntimeHost, _FakeServer]:
    # config/cwd are unused by the activity path under test.
    host = HeadlessRuntimeHost(config=None, cwd=Path("/tmp"))  # type: ignore[arg-type]
    server = _FakeServer()
    host._server = server  # type: ignore[attr-defined]
    return host, server


class ActivityLabelTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_start_publishes_the_specific_action(self) -> None:
        host, server = _host()
        host._run_state.activity_label = "Thinking"
        host._published_activity_label = "Thinking"

        await host._handle_event(
            AgentEvent(
                type=AgentEventType.TOOL_CALL_START,
                data={"call_id": "c1", "name": "grep", "arguments": {}},
            ),
            session_id="s1",
            turn_id=1,
        )

        self.assertEqual(host._run_state.activity_label, "Searching code")
        # The label is only useful if the client is actually told about it.
        self.assertGreaterEqual(server.state_publishes, 1)

    async def test_repeated_identical_labels_do_not_republish(self) -> None:
        host, server = _host()
        host._run_state.activity_label = "Thinking"
        host._published_activity_label = "Thinking"

        event = AgentEvent(
            type=AgentEventType.TOOL_CALL_PROGRESS,
            data={"call_id": "c1", "name": "shell", "output": "tick"},
        )
        for _ in range(5):
            await host._handle_event(event, session_id="s1", turn_id=1)

        # Streamed progress must not broadcast the whole state on every tick.
        self.assertEqual(server.state_publishes, 0)
        self.assertEqual(host._run_state.activity_label, "Thinking")

    async def test_progress_does_not_clobber_a_running_tool_label(self) -> None:
        host, _server = _host()
        host._published_activity_label = ""

        await host._handle_event(
            AgentEvent(
                type=AgentEventType.TOOL_CALL_START,
                data={"call_id": "c1", "name": "run_tests", "arguments": {}},
            ),
            session_id="s1",
            turn_id=1,
        )
        self.assertEqual(host._run_state.activity_label, "Running tests")

        await host._handle_event(
            AgentEvent(
                type=AgentEventType.TOOL_CALL_PROGRESS,
                data={"call_id": "c1", "name": "run_tests", "output": "still going"},
            ),
            session_id="s1",
            turn_id=1,
        )

        # A random gerund here would make the label flicker during a long tool.
        self.assertEqual(host._run_state.activity_label, "Running tests")

    async def test_tool_complete_moves_to_a_wrapping_label(self) -> None:
        host, server = _host()
        host._published_activity_label = ""

        await host._handle_event(
            AgentEvent(
                type=AgentEventType.TOOL_CALL_COMPLETE,
                data={"call_id": "c1", "name": "grep", "success": True, "output": ""},
            ),
            session_id="s1",
            turn_id=1,
        )

        self.assertTrue(host._run_state.activity_label)
        self.assertNotEqual(host._run_state.activity_label, "Searching code")
        self.assertGreaterEqual(server.state_publishes, 1)

    async def test_text_delta_reports_writing(self) -> None:
        host, _server = _host()
        host._published_activity_label = "Searching code"

        await host._handle_event(
            AgentEvent(type=AgentEventType.TEXT_DELTA, data={"content": "hi"}),
            session_id="s1",
            turn_id=1,
        )

        self.assertEqual(host._run_state.activity_label, "Writing")


if __name__ == "__main__":
    unittest.main()
