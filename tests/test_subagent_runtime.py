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
            "wait_subagent",
            "list_subagents",
            "cancel_subagent",
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

        async def fake_execute(invocation: ToolInvocation) -> ToolResult:
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

        tool.execute = fake_execute  # type: ignore[method-assign]

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

        listed = await listing.execute(
            ToolInvocation(params={}, cwd=self.cwd)
        )
        self.assertTrue(listed.success, msg=listed.error)
        self.assertEqual(listed.metadata.get("count"), 1)
        self.assertEqual(listed.metadata["runs"][0]["run_id"], run_id)

    async def test_cancel_subagent_marks_run_cancelled(self) -> None:
        tool = self.registry.get("subagent_codebase_investigator")
        assert tool is not None

        async def slow_execute(invocation: ToolInvocation) -> ToolResult:
            await asyncio.sleep(60)
            return ToolResult.success_result("{}")

        tool.execute = slow_execute  # type: ignore[method-assign]

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


if __name__ == "__main__":
    unittest.main()
