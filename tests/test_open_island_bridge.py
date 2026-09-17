from __future__ import annotations

import asyncio
import itertools
import unittest
from pathlib import Path
from typing import Any

from ite.agent.events import AgentEvent
from ite.integrations.open_island import bridge as bridge_module
from ite.integrations.open_island import payloads
from ite.integrations.open_island.bridge import OpenIslandBridge, build_bridge
from ite.integrations.open_island.terminal import TerminalContext
from ite.tools.base import ToolResult

_TERMINAL = TerminalContext(app="iTerm", tty="/dev/ttys001")


class _RecordingClient:
    """Captures bridge commands so tests can assert on the emitted protocol."""

    def __init__(
        self,
        fail: bool = False,
        interactive_response: dict[str, Any] | None = None,
        fail_interactive: bool = False,
    ) -> None:
        self.commands: list[dict[str, Any]] = []
        self.fail = fail
        self.sync_commands: list[dict[str, Any]] = []
        self.interactive_commands: list[dict[str, Any]] = []
        self.interactive_timeouts: list[float] = []
        self.interactive_response = interactive_response
        self.fail_interactive = fail_interactive

    async def try_send(
        self, command: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any] | None:
        if self.fail:
            raise RuntimeError("bridge unavailable")
        self.commands.append(command)
        return {"type": "acknowledged"}

    async def send_interactive(
        self, command: dict[str, Any], *, timeout: float
    ) -> dict[str, Any] | None:
        self.interactive_commands.append(command)
        self.interactive_timeouts.append(timeout)
        if self.fail_interactive:
            raise RuntimeError("bridge unavailable")
        return self.interactive_response

    def send_sync(
        self, command: dict[str, Any], *, timeout: float = 2.0
    ) -> dict[str, Any] | None:
        self.sync_commands.append(command)
        return {"type": "acknowledged"}

    def hooks(self) -> list[dict[str, Any]]:
        return [c["claudeHook"] for c in self.commands]

    def interactive_hooks(self) -> list[dict[str, Any]]:
        return [c["claudeHook"] for c in self.interactive_commands]

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
    """Wait until the bridge worker has processed every queued event.

    Waiting on `queue.join()` (which waits for `task_done`) rather than polling
    `queue.empty()` — the latter goes true as soon as the worker *pops* an item,
    before the send has completed, which makes assertions racy.
    """
    if bridge._worker is None:
        return

    try:
        await asyncio.wait_for(bridge._queue.join(), timeout=2.0)
    except TimeoutError:
        pass

    # Let the worker reach its next await point after the final send.
    await asyncio.sleep(0)


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
        """Exactly one prompt per turn.

        The island renders the *first* prompt as the headline topic and the
        *latest* as the "You:" line. Sending the prompt more than once per turn
        would be a wire-level bug (the user-visible duplicate the row shows for
        single-prompt sessions is a separate, upstream rendering behaviour —
        see plan §3.6).
        """
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


class ActivityLabelWiringTests(unittest.IsolatedAsyncioTestCase):
    """The island's status line is derived only from `currentTool`.

    A reasoning turn has no tool, so without an explicit activity payload the
    island shows its generic "Thinking" while iTE's TUI shows a gerund.
    """

    async def test_agent_start_emits_an_activity_payload(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("do the thing"))
        await _drain(bridge)

        activity = client.events_of("PreToolUse")
        self.assertEqual(len(activity), 1)
        label = payloads.island_status_text(activity[0])
        self.assertTrue(label)
        self.assertNotEqual(label, "Thinking")

    async def test_activity_is_last_so_it_wins_current_tool(self) -> None:
        """UserPromptSubmit can clear `currentTool` upstream; order matters."""
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("do the thing"))
        await _drain(bridge)

        names = [h["hook_event_name"] for h in client.hooks()]
        self.assertEqual(names[-1], "PreToolUse")

    async def test_real_tool_still_reports_its_own_name(self) -> None:
        """The activity shim must not mask genuine tool calls."""
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("go"))
        await _drain(bridge)
        bridge.observe(
            AgentEvent.tool_call_start("call-1", "read_file", {"path": "a.py"})
        )
        await _drain(bridge)

        last = client.events_of("PreToolUse")[-1]
        self.assertEqual(last["tool_name"], "read_file")
        self.assertEqual(payloads.island_status_text(last), "Read File a.py")

    async def test_compaction_reports_its_own_wording(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.context_compacted(1000, 128000, 500))
        await _drain(bridge)

        labels = [
            payloads.island_status_text(h) for h in client.events_of("PreToolUse")
        ]
        self.assertIn("Compacting context", labels)


class ActivityRotationTests(unittest.IsolatedAsyncioTestCase):
    """The TUI rotates its gerund on a timer, not on events.

    `app.py:825` ticks every 4.5s purely to advance a counter, so no event
    stream can reproduce it. Without an equivalent timer the island freezes on
    whichever word it showed first.
    """

    async def asyncSetUp(self) -> None:
        self._original_interval = bridge_module._ROTATION_INTERVAL_SECONDS
        bridge_module._ROTATION_INTERVAL_SECONDS = 0.02

    async def asyncTearDown(self) -> None:
        bridge_module._ROTATION_INTERVAL_SECONDS = self._original_interval

    async def test_rotation_starts_with_the_turn(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("go"))
        await _drain(bridge)

        self.assertIsNotNone(bridge._rotation_task)
        await bridge.aclose()

    async def test_rotation_keeps_emitting_as_time_passes(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("go"))
        await _drain(bridge)
        initial = len(client.events_of("PreToolUse"))

        await asyncio.sleep(0.15)
        later = len(client.events_of("PreToolUse"))

        self.assertGreater(later, initial)
        await bridge.aclose()

    async def test_rotation_pauses_while_a_tool_is_in_flight(self) -> None:
        """A live tool's label must not be overwritten by a gerund."""
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("go"))
        await _drain(bridge)
        bridge.observe(
            AgentEvent.tool_call_start("call-1", "read_file", {"path": "a.py"})
        )
        await _drain(bridge)

        settled = len(client.commands)
        await asyncio.sleep(0.15)

        self.assertEqual(len(client.commands), settled)
        await bridge.aclose()

    async def test_rotation_resumes_after_the_tool_finishes(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("go"))
        await _drain(bridge)
        bridge.observe(
            AgentEvent.tool_call_start("call-1", "read_file", {"path": "a.py"})
        )
        await _drain(bridge)
        bridge.observe(
            AgentEvent.tool_call_complete(
                "call-1", "read_file", ToolResult(success=True, output="ok")
            )
        )
        await _drain(bridge)

        settled = len(client.commands)
        await asyncio.sleep(0.15)

        self.assertGreater(len(client.commands), settled)
        await bridge.aclose()

    async def test_rotation_stops_when_the_turn_ends(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("go"))
        await _drain(bridge)
        bridge.observe(AgentEvent.agent_end(response="done"))
        await _drain(bridge)

        self.assertIsNone(bridge._rotation_task)

        settled = len(client.commands)
        await asyncio.sleep(0.15)

        self.assertEqual(len(client.commands), settled)

    async def test_rotation_stops_on_error(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("go"))
        await _drain(bridge)
        bridge.observe(AgentEvent.agent_error("kaboom"))
        await _drain(bridge)

        self.assertIsNone(bridge._rotation_task)

    async def test_aclose_cancels_rotation(self) -> None:
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("go"))
        await _drain(bridge)

        await bridge.aclose()

        self.assertIsNone(bridge._rotation_task)

    async def test_labels_do_not_repeat_back_to_back(self) -> None:
        bridge = _bridge(_RecordingClient())

        labels = [bridge._next_activity_label() for _ in range(12)]

        for previous, current in itertools.pairwise(labels):
            self.assertNotEqual(previous, current)

    async def test_rotation_is_stable_within_a_turn(self) -> None:
        """The first label of a turn is not rewritten by the worker."""
        client = _RecordingClient()
        bridge = _bridge(client)

        bridge.observe(AgentEvent.agent_start("go"))
        await _drain(bridge)

        # Before any rotation tick, exactly one activity label exists.
        self.assertEqual(len(client.events_of("PreToolUse")), 1)
        await bridge.aclose()

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


class BridgeInteractiveTests(unittest.IsolatedAsyncioTestCase):
    """Approvals and questions parked on the notch.

    The tri-state/fail-open contract is the important part: an unanswered
    island must never be mistaken for a denial.
    """

    def _directive(self, decision: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "claudeHookDirective",
            "directive": {"type": "permissionRequest", "directive": decision},
        }

    async def test_disabled_bridge_yields_unavailable(self) -> None:
        bridge = _bridge(_RecordingClient(), enabled=False)

        self.assertEqual(
            await bridge.request_approval(tool_name="shell", preview="Delete report.txt"),
            "unavailable",
        )
        self.assertIsNone(
            await bridge.request_question(question="q", options=["a", "b"])
        )

    async def test_approval_allow_maps_to_approved(self) -> None:
        client = _RecordingClient(interactive_response=self._directive({"behavior": "allow"}))
        bridge = _bridge(client)

        self.assertEqual(
            await bridge.request_approval(tool_name="shell", preview="Delete report.txt"),
            "approved",
        )

    async def test_approval_deny_maps_to_denied(self) -> None:
        client = _RecordingClient(
            interactive_response=self._directive(
                {"behavior": "deny", "message": "denied"}
            )
        )
        bridge = _bridge(client)

        self.assertEqual(
            await bridge.request_approval(tool_name="shell", preview="Delete report.txt"),
            "denied",
        )

    async def test_socket_failure_is_unavailable_not_denied(self) -> None:
        bridge = _bridge(_RecordingClient(fail_interactive=True))

        self.assertEqual(
            await bridge.request_approval(tool_name="shell", preview="Delete report.txt"),
            "unavailable",
        )

    async def test_unrecognised_response_is_unavailable(self) -> None:
        bridge = _bridge(_RecordingClient(interactive_response={"type": "acknowledged"}))

        self.assertEqual(
            await bridge.request_approval(tool_name="shell", preview="Delete report.txt"),
            "unavailable",
        )

    async def test_permission_payload_omits_tool_name(self) -> None:
        client = _RecordingClient(interactive_response=self._directive({"behavior": "allow"}))
        bridge = _bridge(client)

        await bridge.request_approval(tool_name="shell", preview="Delete report.txt")

        hook = client.interactive_hooks()[0]
        self.assertEqual(hook["hook_event_name"], "PermissionRequest")
        self.assertNotIn("tool_name", hook)
        # The card renders `tool_input.command`, not `message` — both carry it,
        # but only `command` is what the user actually sees.
        self.assertEqual(hook["tool_input"]["command"], "Delete report.txt")
        self.assertEqual(hook["message"], "Delete report.txt")

    async def test_permission_carries_cached_tool_use_id(self) -> None:
        client = _RecordingClient(interactive_response=self._directive({"behavior": "allow"}))
        bridge = _bridge(client)

        bridge.observe(
            AgentEvent.tool_call_start("call-9", "shell", {"command": "rm -rf x"})
        )
        await _drain(bridge)
        await bridge.request_approval(tool_name="shell", preview="Delete x")

        hook = client.interactive_hooks()[0]
        self.assertEqual(hook["tool_use_id"], "call-9")

    async def test_pre_tool_use_lands_before_the_interactive_send(self) -> None:
        client = _RecordingClient(interactive_response=self._directive({"behavior": "allow"}))
        bridge = _bridge(client)

        bridge.observe(AgentEvent.tool_call_start("call-1", "shell", {"command": "ls"}))
        await bridge.request_approval(tool_name="shell", preview="List files")

        # The drain must have flushed PreToolUse before the interactive command.
        self.assertTrue(client.commands)
        self.assertTrue(client.interactive_commands)

    async def test_question_selection_maps_back(self) -> None:
        updated = {"answers": {"Which colour?": "Blue"}}
        client = _RecordingClient(
            interactive_response=self._directive(
                {"behavior": "allow", "updatedInput": updated}
            )
        )
        bridge = _bridge(client)

        result = await bridge.request_question(
            question="Which colour?", options=["Red", "Blue"], recommended_index=1
        )

        self.assertEqual(
            result,
            {"selected_option": "Blue", "free_text": "", "selected_index": 1},
        )
        hook = client.interactive_hooks()[0]
        self.assertEqual(hook["tool_name"], "AskUserQuestion")
        self.assertEqual(
            hook["tool_input"]["questions"][0]["options"][1]["description"],
            "Recommended",
        )

    async def test_question_free_text_maps_back(self) -> None:
        updated = {"answers": {"Which colour?": "Chartreuse"}}
        client = _RecordingClient(
            interactive_response=self._directive(
                {"behavior": "allow", "updatedInput": updated}
            )
        )
        bridge = _bridge(client)

        result = await bridge.request_question(
            question="Which colour?", options=["Red", "Blue"]
        )

        self.assertEqual(
            result,
            {"selected_option": "", "free_text": "Chartreuse", "selected_index": None},
        )

    async def test_question_unavailable_returns_none(self) -> None:
        bridge = _bridge(_RecordingClient(fail_interactive=True))

        self.assertIsNone(
            await bridge.request_question(question="q", options=["a", "b"])
        )

    async def test_question_deny_returns_none(self) -> None:
        client = _RecordingClient(
            interactive_response=self._directive({"behavior": "deny"})
        )
        bridge = _bridge(client)

        self.assertIsNone(
            await bridge.request_question(question="q", options=["a", "b"])
        )


if __name__ == "__main__":
    unittest.main()
