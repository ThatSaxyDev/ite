import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from ite.agent.subagent_runtime import SubagentRuntime
from ite.config.config import Config
from ite.tools.base import ToolInvocation
from ite.tools.base import ToolResult
from ite.tools.registry import create_default_registry


class SubagentRuntimeToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_tempdir)
        self.cwd = Path(self._td.name)
        self.config = Config(cwd=self.cwd, api_key="test")
        self.registry = create_default_registry(self.config)
        self.runtime = SubagentRuntime(
            config=self.config,
            session_id="parent_session_1",
            tool_registry=self.registry,
        )
        for name in (
            "spawn_subagent",
            "spawn_subagents",
            "wait_subagent",
            "list_subagents",
            "cancel_subagent",
            "subagent_metrics",
        ):
            tool = self.registry.get(name)
            assert tool is not None
            tool.set_runtime(self.runtime)  # type: ignore[attr-defined]

    async def _cleanup_tempdir(self) -> None:
        await self.runtime.shutdown()
        self._td.cleanup()

    async def test_spawn_wait_and_list_subagents(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        async def fake_execute_with_progress(
            invocation: ToolInvocation,
            progress_callback=None,
        ) -> ToolResult:
            if progress_callback is not None:
                maybe = progress_callback(
                    {
                        "phase": "tool_call_start",
                        "tool_name": "read_file",
                        "arguments": {"path": "README.md"},
                    }
                )
                if maybe is not None:
                    await maybe
            await asyncio.sleep(0.01)
            payload = {
                "status": "ok",
                "subagent": "codebase_investigator",
                "termination": "goal",
                "tools_used": ["grep"],
                "summary": "done",
                "findings": ["one"],
                "actions": ["next"],
            }
            trace = {
                "child_session_id": "child_1",
                "duration_ms": 10,
                "child_turn_count": 2,
                "termination": "goal",
            }
            return ToolResult.success_result(
                json.dumps(payload),
                metadata={"subagent_result": payload, "subagent_trace": trace},
            )

        tool._execute_with_progress = fake_execute_with_progress  # type: ignore[method-assign]

        spawn = self.registry.get("spawn_subagent")
        wait = self.registry.get("wait_subagent")
        listing = self.registry.get("list_subagents")
        assert spawn and wait and listing

        spawned = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "inspect tools"},
                cwd=self.cwd,
                call_id="call_1",
                session_id="parent_session_1",
            )
        )
        self.assertTrue(spawned.success, msg=spawned.error)
        run_id = spawned.metadata["run"]["run_id"]

        waited = await wait.execute(
            ToolInvocation(
                params={"run_ids": [run_id], "timeout_seconds": 1, "return_when": "all_completed"},
                cwd=self.cwd,
            )
        )
        self.assertTrue(waited.success, msg=waited.error)
        runs = waited.metadata.get("runs", [])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "completed")
        self.assertEqual(runs[0]["child_session_id"], "child_1")
        self.assertEqual(runs[0]["current_activity"], "done")
        self.assertTrue(runs[0]["activity_history"])
        self.assertEqual(runs[0]["activity_history"][-1]["message"], "done")

        listed = await listing.execute(
            ToolInvocation(params={}, cwd=self.cwd)
        )
        self.assertTrue(listed.success, msg=listed.error)
        self.assertEqual(listed.metadata.get("count"), 1)
        self.assertEqual(listed.metadata["runs"][0]["run_id"], run_id)

        metrics_tool = self.registry.get("subagent_metrics")
        assert metrics_tool is not None
        metrics = await metrics_tool.execute(ToolInvocation(params={}, cwd=self.cwd))
        self.assertTrue(metrics.success, msg=metrics.error)
        totals = metrics.metadata["totals"]
        self.assertEqual(totals["spawn_requests"], 1)
        self.assertEqual(totals["spawned_runs"], 1)
        self.assertEqual(totals["completed"], 1)
        self.assertEqual(totals["active_runs"], 0)
        per = metrics.metadata["per_subagent"]["codebase_investigator"]
        self.assertEqual(per["avg_duration_ms"], 10)
        self.assertEqual(per["avg_turns"], 2.0)

    async def test_cancel_subagent_marks_run_cancelled(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        async def slow_execute_with_progress(
            invocation: ToolInvocation,
            progress_callback=None,
        ) -> ToolResult:
            await asyncio.sleep(60)
            return ToolResult.success_result("{}")

        tool._execute_with_progress = slow_execute_with_progress  # type: ignore[method-assign]

        spawn = self.registry.get("spawn_subagent")
        cancel = self.registry.get("cancel_subagent")
        wait = self.registry.get("wait_subagent")
        assert spawn and cancel and wait

        spawned = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "inspect tools"},
                cwd=self.cwd,
            )
        )
        run_id = spawned.metadata["run"]["run_id"]

        cancelled = await cancel.execute(
            ToolInvocation(params={"run_ids": [run_id]}, cwd=self.cwd)
        )
        self.assertTrue(cancelled.success, msg=cancelled.error)
        self.assertEqual(cancelled.metadata.get("cancelled_run_ids"), [run_id])

        waited = await wait.execute(
            ToolInvocation(
                params={"run_ids": [run_id], "timeout_seconds": 0, "return_when": "all_completed"},
                cwd=self.cwd,
            )
        )
        self.assertTrue(waited.success, msg=waited.error)
        self.assertEqual(waited.metadata["runs"][0]["status"], "cancelled")

    async def test_spawn_subagent_falls_back_to_codebase_investigator_for_unknown_name(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        async def fake_execute_with_progress(
            invocation: ToolInvocation,
            progress_callback=None,
        ) -> ToolResult:
            payload = {
                "status": "ok",
                "subagent": "codebase_investigator",
                "termination": "goal",
                "tools_used": ["grep"],
                "summary": "done",
                "findings": [],
                "actions": [],
            }
            trace = {
                "child_session_id": "child_1",
                "duration_ms": 1,
                "child_turn_count": 1,
                "termination": "goal",
            }
            return ToolResult.success_result(
                json.dumps(payload),
                metadata={"subagent_result": payload, "subagent_trace": trace},
            )

        tool._execute_with_progress = fake_execute_with_progress  # type: ignore[method-assign]
        spawn = self.registry.get("spawn_subagent")
        assert spawn is not None

        spawned = await spawn.execute(
            ToolInvocation(
                params={"subagent": "registry", "goal": "inspect registry internals"},
                cwd=self.cwd,
            )
        )

        self.assertTrue(spawned.success, msg=spawned.error)
        self.assertEqual(spawned.metadata["run"]["subagent"], "codebase_investigator")
        self.assertEqual(spawned.metadata["requested_subagent"], "registry")
        self.assertEqual(spawned.metadata["selected_subagent"], "codebase_investigator")

    async def test_spawn_subagent_reuses_matching_active_run(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        async def slow_execute_with_progress(
            invocation: ToolInvocation,
            progress_callback=None,
        ) -> ToolResult:
            if progress_callback is not None:
                maybe = progress_callback(
                    {
                        "phase": "tool_call_start",
                        "tool_name": "grep",
                        "arguments": {"pattern": "Session", "path": "src"},
                    }
                )
                if maybe is not None:
                    await maybe
            await asyncio.sleep(0.05)
            payload = {
                "status": "ok",
                "subagent": "codebase_investigator",
                "termination": "goal",
                "tools_used": ["grep"],
                "summary": "done",
                "findings": [],
                "actions": [],
            }
            trace = {
                "child_session_id": "child_1",
                "duration_ms": 50,
                "child_turn_count": 1,
                "termination": "goal",
            }
            return ToolResult.success_result(
                json.dumps(payload),
                metadata={"subagent_result": payload, "subagent_trace": trace},
            )

        tool._execute_with_progress = slow_execute_with_progress  # type: ignore[method-assign]
        spawn = self.registry.get("spawn_subagent")
        wait = self.registry.get("wait_subagent")
        assert spawn is not None and wait is not None

        first = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "inspect registry internals"},
                cwd=self.cwd,
            )
        )
        second = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "  inspect   registry internals "},
                cwd=self.cwd,
            )
        )

        self.assertTrue(first.success, msg=first.error)
        self.assertTrue(second.success, msg=second.error)
        self.assertFalse(first.metadata["reused_existing"])
        self.assertTrue(second.metadata["reused_existing"])
        self.assertEqual(first.metadata["run"]["run_id"], second.metadata["run"]["run_id"])

        waited = await wait.execute(
            ToolInvocation(
                params={
                    "run_ids": [first.metadata["run"]["run_id"]],
                    "timeout_seconds": 1,
                    "return_when": "all_completed",
                },
                cwd=self.cwd,
            )
        )
        self.assertTrue(waited.success, msg=waited.error)

    async def test_spawn_subagents_launches_multiple_runs(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        async def slow_execute_with_progress(
            invocation: ToolInvocation,
            progress_callback=None,
        ) -> ToolResult:
            await asyncio.sleep(0.05)
            payload = {
                "status": "ok",
                "subagent": "codebase_investigator",
                "termination": "goal",
                "tools_used": ["grep"],
                "summary": invocation.params["goal"],
                "findings": [],
                "actions": [],
            }
            trace = {
                "child_session_id": "child_1",
                "duration_ms": 50,
                "child_turn_count": 1,
                "termination": "goal",
            }
            return ToolResult.success_result(
                json.dumps(payload),
                metadata={"subagent_result": payload, "subagent_trace": trace},
            )

        tool._execute_with_progress = slow_execute_with_progress  # type: ignore[method-assign]
        spawn_many = self.registry.get("spawn_subagents")
        assert spawn_many is not None

        spawned = await spawn_many.execute(
            ToolInvocation(
                params={
                    "requests": [
                        {"subagent": "codebase_investigator", "goal": "inspect registry"},
                        {"subagent": "codebase_investigator", "goal": "inspect reup"},
                    ]
                },
                cwd=self.cwd,
            )
        )

        self.assertTrue(spawned.success, msg=spawned.error)
        self.assertEqual(spawned.metadata["count"], 2)
        self.assertEqual(len(spawned.metadata["runs"]), 2)
        self.assertNotEqual(
            spawned.metadata["runs"][0]["run_id"],
            spawned.metadata["runs"][1]["run_id"],
        )

    async def test_spawn_subagents_rejects_oversized_batch(self) -> None:
        spawn_many = self.registry.get("spawn_subagents")
        assert spawn_many is not None

        spawned = await spawn_many.execute(
            ToolInvocation(
                params={
                    "requests": [
                        {"subagent": "codebase_investigator", "goal": f"inspect target {index}"}
                        for index in range(9)
                    ]
                },
                cwd=self.cwd,
            )
        )

        self.assertFalse(spawned.success)
        self.assertIn("Too many subagents requested", spawned.error or "")
        self.assertEqual(spawned.metadata["max_batch_size"], 8)
        self.assertEqual(spawned.metadata["requested_count"], 9)

    async def test_runtime_prunes_finished_tasks(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        async def fast_execute_with_progress(
            invocation: ToolInvocation,
            progress_callback=None,
        ) -> ToolResult:
            payload = {
                "status": "ok",
                "subagent": "codebase_investigator",
                "termination": "goal",
                "tools_used": [],
                "summary": "done",
                "findings": [],
                "actions": [],
            }
            trace = {
                "child_session_id": "child_1",
                "duration_ms": 1,
                "child_turn_count": 1,
                "termination": "goal",
            }
            return ToolResult.success_result(
                json.dumps(payload),
                metadata={"subagent_result": payload, "subagent_trace": trace},
            )

        tool._execute_with_progress = fast_execute_with_progress  # type: ignore[method-assign]
        spawn = self.registry.get("spawn_subagent")
        wait = self.registry.get("wait_subagent")
        assert spawn is not None and wait is not None

        spawned = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "inspect cleanup"},
                cwd=self.cwd,
            )
        )
        run_id = spawned.metadata["run"]["run_id"]
        self.assertIn(run_id, self.runtime._tasks)

        waited = await wait.execute(
            ToolInvocation(
                params={"run_ids": [run_id], "timeout_seconds": 1, "return_when": "all_completed"},
                cwd=self.cwd,
            )
        )
        self.assertTrue(waited.success, msg=waited.error)
        await asyncio.sleep(0)
        self.assertNotIn(run_id, self.runtime._tasks)

    async def test_runtime_prunes_old_terminal_runs(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        async def fast_execute_with_progress(
            invocation: ToolInvocation,
            progress_callback=None,
        ) -> ToolResult:
            payload = {
                "status": "ok",
                "subagent": "codebase_investigator",
                "termination": "goal",
                "tools_used": [],
                "summary": invocation.params["goal"],
                "findings": [],
                "actions": [],
            }
            trace = {
                "child_session_id": "child_1",
                "duration_ms": 1,
                "child_turn_count": 1,
                "termination": "goal",
            }
            return ToolResult.success_result(
                json.dumps(payload),
                metadata={"subagent_result": payload, "subagent_trace": trace},
            )

        tool._execute_with_progress = fast_execute_with_progress  # type: ignore[method-assign]
        spawn = self.registry.get("spawn_subagent")
        wait = self.registry.get("wait_subagent")
        assert spawn is not None and wait is not None

        original_limit = self.runtime.MAX_TERMINAL_RUNS
        self.runtime.MAX_TERMINAL_RUNS = 2
        self.addCleanup(setattr, self.runtime, "MAX_TERMINAL_RUNS", original_limit)

        run_ids: list[str] = []
        for index in range(4):
            spawned = await spawn.execute(
                ToolInvocation(
                    params={"subagent": "codebase_investigator", "goal": f"inspect run {index}"},
                    cwd=self.cwd,
                )
            )
            run_ids.append(spawned.metadata["run"]["run_id"])

        waited = await wait.execute(
            ToolInvocation(
                params={"run_ids": run_ids, "timeout_seconds": 1, "return_when": "all_completed"},
                cwd=self.cwd,
            )
        )
        self.assertTrue(waited.success, msg=waited.error)
        await asyncio.sleep(0)

        remaining = [run.run_id for run in self.runtime.list_runs()]
        self.assertEqual(len(remaining), 2)
        self.assertEqual(remaining, run_ids[-2:])

    async def test_circuit_breaker_blocks_repeated_failures(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        async def failing_execute_with_progress(
            invocation: ToolInvocation,
            progress_callback=None,
        ) -> ToolResult:
            payload = {
                "status": "error",
                "subagent": "codebase_investigator",
                "termination": "timeout",
                "tools_used": [],
                "summary": "timed out",
                "findings": [],
                "actions": [],
            }
            trace = {
                "child_session_id": "child_1",
                "duration_ms": 1,
                "child_turn_count": 1,
                "termination": "timeout",
            }
            return ToolResult.error_result(
                output=json.dumps(payload),
                error="Sub-agent 'codebase_investigator' timed out",
                metadata={"subagent_result": payload, "subagent_trace": trace},
            )

        tool._execute_with_progress = failing_execute_with_progress  # type: ignore[method-assign]
        spawn = self.registry.get("spawn_subagent")
        wait = self.registry.get("wait_subagent")
        assert spawn is not None and wait is not None

        original_threshold = self.runtime.CIRCUIT_FAILURE_THRESHOLD
        original_window = self.runtime.CIRCUIT_WINDOW_SECONDS
        original_open = self.runtime.CIRCUIT_OPEN_SECONDS
        self.runtime.CIRCUIT_FAILURE_THRESHOLD = 2
        self.runtime.CIRCUIT_WINDOW_SECONDS = 600
        self.runtime.CIRCUIT_OPEN_SECONDS = 300
        self.addCleanup(setattr, self.runtime, "CIRCUIT_FAILURE_THRESHOLD", original_threshold)
        self.addCleanup(setattr, self.runtime, "CIRCUIT_WINDOW_SECONDS", original_window)
        self.addCleanup(setattr, self.runtime, "CIRCUIT_OPEN_SECONDS", original_open)

        for index in range(2):
            spawned = await spawn.execute(
                ToolInvocation(
                    params={"subagent": "codebase_investigator", "goal": f"inspect failure {index}"},
                    cwd=self.cwd,
                )
            )
            self.assertTrue(spawned.success, msg=spawned.error)
            run_id = spawned.metadata["run"]["run_id"]
            waited = await wait.execute(
                ToolInvocation(
                    params={"run_ids": [run_id], "timeout_seconds": 1, "return_when": "all_completed"},
                    cwd=self.cwd,
                )
            )
            self.assertTrue(waited.success, msg=waited.error)

        blocked = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "inspect after breaker"},
                cwd=self.cwd,
            )
        )
        self.assertFalse(blocked.success)
        self.assertTrue(blocked.metadata["circuit_open"])
        self.assertEqual(blocked.metadata["failure_count"], 2)
        self.assertIn("temporarily paused", blocked.error or "")

        metrics_tool = self.registry.get("subagent_metrics")
        assert metrics_tool is not None
        metrics = await metrics_tool.execute(ToolInvocation(params={}, cwd=self.cwd))
        totals = metrics.metadata["totals"]
        self.assertEqual(totals["timeout"], 2)
        self.assertEqual(totals["circuit_breaker_trips"], 1)
        self.assertEqual(totals["circuit_breaker_blocks"], 1)

    async def test_metrics_count_reuse_and_retry_recovery(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        async def slow_success_with_retry_metadata(
            invocation: ToolInvocation,
            progress_callback=None,
        ) -> ToolResult:
            await asyncio.sleep(0.05)
            payload = {
                "status": "ok",
                "subagent": "codebase_investigator",
                "termination": "goal",
                "tools_used": ["read_file"],
                "summary": "recovered",
                "findings": [],
                "actions": [],
                "attempt_count": 2,
                "retries_used": 1,
                "recovered_after_retry": True,
            }
            trace = {
                "child_session_id": "child_1",
                "duration_ms": 50,
                "child_turn_count": 3,
                "termination": "goal",
                "attempt_count": 2,
                "retries_used": 1,
                "recovered_after_retry": True,
            }
            return ToolResult.success_result(
                json.dumps(payload),
                metadata={"subagent_result": payload, "subagent_trace": trace},
            )

        tool._execute_with_progress = slow_success_with_retry_metadata  # type: ignore[method-assign]
        spawn = self.registry.get("spawn_subagent")
        wait = self.registry.get("wait_subagent")
        metrics_tool = self.registry.get("subagent_metrics")
        assert spawn is not None and wait is not None and metrics_tool is not None

        first = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "inspect metrics"},
                cwd=self.cwd,
            )
        )
        second = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "inspect metrics"},
                cwd=self.cwd,
            )
        )
        self.assertTrue(first.success, msg=first.error)
        self.assertTrue(second.success, msg=second.error)
        self.assertTrue(second.metadata["reused_existing"])

        waited = await wait.execute(
            ToolInvocation(
                params={"run_ids": [first.metadata["run"]["run_id"]], "timeout_seconds": 1, "return_when": "all_completed"},
                cwd=self.cwd,
            )
        )
        self.assertTrue(waited.success, msg=waited.error)

        metrics = await metrics_tool.execute(ToolInvocation(params={}, cwd=self.cwd))
        totals = metrics.metadata["totals"]
        self.assertEqual(totals["spawn_requests"], 2)
        self.assertEqual(totals["spawned_runs"], 1)
        self.assertEqual(totals["reused_existing"], 1)
        self.assertEqual(totals["retries_used"], 1)
        self.assertEqual(totals["recovered_after_retry"], 1)

    async def test_runtime_state_restore_preserves_historical_metrics(self) -> None:
        state = {
            "counter": 4,
            "runs": [
                {
                    "run_id": "agent_004",
                    "subagent": "codebase_investigator",
                    "goal": "inspect",
                    "status": "completed",
                    "created_at": "2026-03-04T11:46:07+00:00",
                    "finished_at": "2026-03-04T11:46:10+00:00",
                    "duration_ms": 3000,
                    "child_turn_count": 4,
                    "summary": "done",
                    "activity_history": [],
                }
            ],
            "metrics": {
                "totals": {"spawned_runs": 4, "completed": 4, "active_runs": 0, "retained_runs": 1},
                "per_subagent": {
                    "codebase_investigator": {
                        "spawned_runs": 4,
                        "completed": 4,
                        "total_duration_ms": 12000,
                        "total_turns": 16,
                        "terminal_runs": 4,
                    }
                },
            },
        }

        self.runtime.restore_state(state)
        metrics_tool = self.registry.get("subagent_metrics")
        assert metrics_tool is not None
        metrics = await metrics_tool.execute(ToolInvocation(params={}, cwd=self.cwd))
        self.assertTrue(metrics.success, msg=metrics.error)
        totals = metrics.metadata["totals"]
        self.assertEqual(totals["spawned_runs"], 4)
        self.assertEqual(totals["completed"], 4)
        self.assertEqual(totals["retained_runs"], 1)
        self.assertEqual(metrics.metadata["per_subagent"]["codebase_investigator"]["avg_turns"], 4.0)

    async def test_circuit_breaker_recovers_after_window(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        state = {"mode": "fail"}

        async def toggled_execute_with_progress(
            invocation: ToolInvocation,
            progress_callback=None,
        ) -> ToolResult:
            if state["mode"] == "fail":
                payload = {
                    "status": "error",
                    "subagent": "codebase_investigator",
                    "termination": "timeout",
                    "tools_used": [],
                    "summary": "timed out",
                    "findings": [],
                    "actions": [],
                }
                trace = {
                    "child_session_id": "child_1",
                    "duration_ms": 1,
                    "child_turn_count": 1,
                    "termination": "timeout",
                }
                return ToolResult.error_result(
                    output=json.dumps(payload),
                    error="Sub-agent 'codebase_investigator' timed out",
                    metadata={"subagent_result": payload, "subagent_trace": trace},
                )
            payload = {
                "status": "ok",
                "subagent": "codebase_investigator",
                "termination": "goal",
                "tools_used": [],
                "summary": "recovered",
                "findings": [],
                "actions": [],
            }
            trace = {
                "child_session_id": "child_2",
                "duration_ms": 1,
                "child_turn_count": 1,
                "termination": "goal",
            }
            return ToolResult.success_result(
                json.dumps(payload),
                metadata={"subagent_result": payload, "subagent_trace": trace},
            )

        tool._execute_with_progress = toggled_execute_with_progress  # type: ignore[method-assign]
        spawn = self.registry.get("spawn_subagent")
        wait = self.registry.get("wait_subagent")
        assert spawn is not None and wait is not None

        original_threshold = self.runtime.CIRCUIT_FAILURE_THRESHOLD
        original_window = self.runtime.CIRCUIT_WINDOW_SECONDS
        original_open = self.runtime.CIRCUIT_OPEN_SECONDS
        self.runtime.CIRCUIT_FAILURE_THRESHOLD = 1
        self.runtime.CIRCUIT_WINDOW_SECONDS = 600
        self.runtime.CIRCUIT_OPEN_SECONDS = 1
        self.addCleanup(setattr, self.runtime, "CIRCUIT_FAILURE_THRESHOLD", original_threshold)
        self.addCleanup(setattr, self.runtime, "CIRCUIT_WINDOW_SECONDS", original_window)
        self.addCleanup(setattr, self.runtime, "CIRCUIT_OPEN_SECONDS", original_open)

        spawned = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "trip breaker"},
                cwd=self.cwd,
            )
        )
        run_id = spawned.metadata["run"]["run_id"]
        waited = await wait.execute(
            ToolInvocation(
                params={"run_ids": [run_id], "timeout_seconds": 1, "return_when": "all_completed"},
                cwd=self.cwd,
            )
        )
        self.assertTrue(waited.success, msg=waited.error)

        blocked = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "still blocked"},
                cwd=self.cwd,
            )
        )
        self.assertFalse(blocked.success)
        self.assertTrue(blocked.metadata["circuit_open"])

        await asyncio.sleep(1.05)
        state["mode"] = "success"
        recovered = await spawn.execute(
            ToolInvocation(
                params={"subagent": "codebase_investigator", "goal": "after cooldown"},
                cwd=self.cwd,
            )
        )
        self.assertTrue(recovered.success, msg=recovered.error)


if __name__ == "__main__":
    unittest.main()
