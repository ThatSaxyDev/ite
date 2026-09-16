"""End-to-end proof that a real Agent drives real Open Island.

Unlike the unit tests, this exercises the production path:

    real Agent._notify_event_observers()
        -> real OpenIslandBridge
            -> real Unix socket
                -> real Open Island app

It feeds the exact AgentEvent sequence a genuine iTE turn produces, and
reports what actually went over the wire and what the app acknowledged.

Usage:
    python scripts/open_island_demo.py              # full simulated turn
    python scripts/open_island_demo.py --hold       # keep bubble up for inspection
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from ite.agent.agent import Agent
from ite.agent.events import AgentEvent
from ite.config.config import Config
from ite.integrations.open_island.client import OpenIslandClient
from ite.tools.base import ToolResult

_CWD = str(Path(__file__).resolve().parents[1])


class _VerboseClient:
    """Pass-through wrapper that prints the exact hook payload sent."""

    def __init__(self, inner: OpenIslandClient) -> None:
        self._inner = inner

    @property
    def socket_path(self) -> Path:
        return self._inner.socket_path

    async def try_send(self, command, *, timeout=None):
        hook = command.get("claudeHook", {})
        summary = {
            k: v
            for k, v in hook.items()
            if k
            in {
                "hook_event_name",
                "tool_name",
                "terminal_app",
                "source",
            }
        }
        print(f"     wire: {command['type']} {summary}")
        return await self._inner.try_send(command, timeout=timeout)

    def send_sync(self, command, *, timeout: float = 2.0):
        return self._inner.send_sync(command, timeout=timeout)

# The event sequence a real turn emits, in order. Mirrors what Agent._run_stream
# yields for: a prompt, a couple of tool calls, and a final response.
_TURN: list[AgentEvent] = [
    AgentEvent.agent_start("refactor the config loader"),
    AgentEvent.tool_call_start("call-1", "read_file", {"path": "config/loader.py"}),
    AgentEvent.tool_call_complete(
        "call-1", "read_file", ToolResult(success=True, output="import tomli ...")
    ),
    AgentEvent.tool_call_start("call-2", "edit", {"path": "config/loader.py"}),
    AgentEvent.tool_call_complete(
        "call-2", "edit", ToolResult(success=True, output="applied 1 edit")
    ),
    AgentEvent.tool_call_start("call-3", "shell", {"command": "pytest -q"}),
    AgentEvent.tool_call_complete(
        "call-3", "shell", ToolResult(success=False, output="", error="3 failed")
    ),
    AgentEvent.agent_end(response="Refactored the loader; 3 tests still failing."),
]


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hold",
        action="store_true",
        help="leave the session in the notch for inspection instead of ending it",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print the exact hook payload sent for each event",
    )
    args = parser.parse_args()

    client = OpenIslandClient()
    print("Open Island bridge")
    print(f"  socket:          {client.socket_path}")

    if not await client.is_available():
        print("  status:          NOT RUNNING")
        print("\nStart Open Island, then re-run this demo.")
        return 1
    print("  status:          live\n")

    # Real Config, with the integration switched on exactly as a user would.
    config = Config(cwd=Path(_CWD))
    config.integrations.open_island.enabled = True

    # Real Agent. This is the production constructor: it builds the bridge
    # internally via _build_open_island_bridge().
    agent = Agent(config)

    bridge = agent._open_island_bridge
    if bridge is None:
        print("bridge was not attached — integration path is broken")
        return 1

    if args.verbose:
        bridge._client = _VerboseClient(bridge._client)

    print("Agent wiring")
    print(f"  observers:       {len(agent._event_observers)}")
    print(f"  bridge session:  {bridge.session_id}")
    terminal = bridge._resolve_terminal()
    print(f"  terminal app:    {terminal.app}")
    print(f"  terminal tty:    {terminal.tty}")
    print()

    print("Driving a simulated turn through the real Agent observer path:")
    for event in _TURN:
        agent._notify_event_observers(event)
        print(f"  -> {event.type.value}")
        await asyncio.sleep(0.35)

    # Let the worker flush to the socket.
    await asyncio.sleep(1.0)

    print()
    print("Result")
    print(f"  events observed: {len(_TURN)}")
    print(f"  queue drained:   {bridge._queue.empty()}")
    print("  -> check your notch: one 'ite' session, summary showing activity")
    if args.hold:
        print("\n  Holding 60s for inspection (Ctrl-C to stop early)...")
        started = time.monotonic()
        while time.monotonic() - started < 60:
            await asyncio.sleep(1)
    else:
        print("\n  Ending session...")
        await bridge.aclose()
        await asyncio.sleep(0.5)
        print("  -> bubble should now be gone")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
