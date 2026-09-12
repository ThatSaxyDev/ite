"""Phase 0 contract tests for the headless runtime host.

Guards the interfaces in ``docs/headless-runtime-plan.md``:
- the event wire form preserves the relay ``agent_event`` contract
- the bus isolates client failures
- the approval broker never hangs and applies explicit policy
- ``ite.runtime`` imports without Textual
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ite.agent.events import AgentEvent, AgentEventType
from ite.remote.protocol import serialize_agent_event
from ite.runtime import EventBus, RuntimeEvent, RuntimeEventType
from ite.runtime.approval import ApprovalBroker
from ite.runtime.client import (
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalResolution,
    PlanQuestion,
    PlanReadyRequest,
)


def test_agent_event_wire_form_matches_relay_contract() -> None:
    event = AgentEvent(type=AgentEventType.TEXT_DELTA, data={"content": "hi"})
    wrapped = RuntimeEvent.agent_event(event, session_id="s1", turn_id=3)
    wire = wrapped.to_wire()
    expected = serialize_agent_event(event, session_id="s1", turn_id=3)
    assert wire["timestamp"]
    wire.pop("timestamp")
    expected.pop("timestamp")
    assert wire == expected


def test_non_agent_event_wire_envelope() -> None:
    event = RuntimeEvent.turn_started(session_id="s1", turn_id=2, message="hello")
    wire = event.to_wire()
    assert wire["session_id"] == "s1"
    assert wire["turn_id"] == 2
    assert wire["event"] == {"type": "turn_started", "data": {"message": "hello"}}
    assert "protocol_version" in wire
    assert wire["timestamp"]


def test_event_bus_fanout_isolates_failures() -> None:
    received: list[RuntimeEvent] = []

    class Good:
        name = "good"

        def on_event(self, event: RuntimeEvent) -> None:
            received.append(event)

        def on_state(self, state: dict[str, Any]) -> None:
            pass

        def is_interactive(self) -> bool:
            return False

    class Bad:
        name = "bad"

        def on_event(self, event: RuntimeEvent) -> None:
            raise RuntimeError("boom")

        def on_state(self, state: dict[str, Any]) -> None:
            raise RuntimeError("boom")

        def is_interactive(self) -> bool:
            return False

    bus = EventBus()
    bus.subscribe(Bad())
    bus.subscribe(Good())
    event = RuntimeEvent.turn_ended(session_id="s", turn_id=1)
    bus.publish(event)
    bus.publish_state({"ok": True})
    assert received == [event]


def test_approval_broker_deny_policy_without_client() -> None:
    broker = ApprovalBroker(policy=ApprovalPolicy.DENY)
    approved = asyncio.run(
        broker.request_approval(ApprovalRequest("r1", "s1", "shell", command="rm -rf /"))
    )
    assert approved is False


def test_approval_broker_allow_policy_without_client() -> None:
    broker = ApprovalBroker(policy=ApprovalPolicy.ALLOW)
    assert asyncio.run(broker.request_approval(ApprovalRequest("r1", "s1", "read_file")))


def test_approval_broker_interactive_client_wins() -> None:
    seen: list[str] = []

    class Client:
        name = "phone"

        def on_event(self, event: RuntimeEvent) -> None: ...
        def on_state(self, state: dict[str, Any]) -> None: ...

        async def request_approval(self, request: ApprovalRequest) -> ApprovalResolution:
            seen.append(request.tool_name)
            return ApprovalResolution(request.request_id, True, "client")

        def is_interactive(self) -> bool:
            return True

    broker = ApprovalBroker(policy=ApprovalPolicy.DENY)
    broker.set_interactive_clients([Client()])
    approved = asyncio.run(
        broker.request_approval(ApprovalRequest("r1", "s1", "shell", timeout=5))
    )
    assert approved is True
    assert seen == ["shell"]


def test_approval_broker_timeout_is_false_not_hang() -> None:
    class SilentClient:
        name = "silent"

        def on_event(self, event: RuntimeEvent) -> None: ...
        def on_state(self, state: dict[str, Any]) -> None: ...

        async def request_approval(self, request: ApprovalRequest) -> ApprovalResolution | None:
            await asyncio.sleep(10)
            return None

        def is_interactive(self) -> bool:
            return True

    resolutions: list[tuple[str, bool, str]] = []
    broker = ApprovalBroker(
        policy=ApprovalPolicy.DENY,
        publish=lambda kind, data: resolutions.append(
            (kind, data.get("approved"), data.get("reason", ""))
        ),
    )
    broker.set_interactive_clients([SilentClient()])
    approved = asyncio.run(
        broker.request_approval(ApprovalRequest("r1", "s1", "shell", timeout=0.05))
    )
    assert approved is False
    assert ("approval_resolved", False, "timeout") in resolutions


def test_approval_broker_hold_policy_waits_for_resolve() -> None:
    broker = ApprovalBroker(policy=ApprovalPolicy.HOLD)

    async def scenario() -> bool:
        task = asyncio.create_task(
            broker.request_approval(ApprovalRequest("r1", "s1", "shell", timeout=5))
        )
        await asyncio.sleep(0)
        assert broker.resolve_approval("r1", True, reason="operator")
        return await task

    assert asyncio.run(scenario()) is True


def test_plan_question_without_client_returns_empty() -> None:
    broker = ApprovalBroker(policy=ApprovalPolicy.DENY)
    answer = asyncio.run(
        broker.request_plan_question(PlanQuestion("q1", "s1", "Which?", options=["a", "b"]))
    )
    assert answer == {"selected_option": "", "free_text": "", "selected_index": None}


def test_plan_ready_without_client_is_false() -> None:
    broker = ApprovalBroker(policy=ApprovalPolicy.DENY)
    assert asyncio.run(broker.request_plan_ready(PlanReadyRequest("p1", "s1", "plan"))) is False


def test_runtime_imports_without_textual() -> None:
    """Import guard: the host path must not require Textual."""

    repo_root = Path(__file__).resolve().parents[1]
    code = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'textual' or name.startswith('textual.'):\n"
        "            raise ImportError('textual is blocked by guard')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Block())\n"
        "import ite.runtime\n"
        "assert 'textual' not in sys.modules\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
