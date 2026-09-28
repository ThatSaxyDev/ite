import tempfile
import unittest
from pathlib import Path

from ite.config.config import Config
from ite.hooks.hook_system import HookSystem
from ite.tools.base import ToolInvocation
from ite.tools.builtin.todo import TodosTool
from ite.tools.registry import create_default_registry


class TodosToolScopedTests(unittest.IsolatedAsyncioTestCase):
    async def test_scope_isolation_and_lifecycle_actions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tool = TodosTool(Config(cwd=cwd, api_key="test"))

            add_exec = await tool.execute(
                ToolInvocation(
                    params={"action": "add", "scope": "execution", "items": ["Task A", "Task B"]},
                    cwd=cwd,
                )
            )
            self.assertTrue(add_exec.success, msg=add_exec.error)
            self.assertEqual(add_exec.metadata.get("scope"), "execution")
            exec_ids = add_exec.metadata.get("changed_ids", [])
            self.assertEqual(len(exec_ids), 2)

            add_plan = await tool.execute(
                ToolInvocation(
                    params={"action": "add", "scope": "planning", "content": "Plan task"},
                    cwd=cwd,
                )
            )
            self.assertTrue(add_plan.success, msg=add_plan.error)
            plan_id = add_plan.metadata.get("changed_ids", [None])[0]
            self.assertIsNotNone(plan_id)

            wrong_scope = await tool.execute(
                ToolInvocation(
                    params={"action": "complete", "scope": "planning", "id": exec_ids[0]},
                    cwd=cwd,
                )
            )
            self.assertFalse(wrong_scope.success)

            complete_exec = await tool.execute(
                ToolInvocation(
                    params={"action": "complete", "scope": "execution", "id": exec_ids[0]},
                    cwd=cwd,
                )
            )
            self.assertTrue(complete_exec.success, msg=complete_exec.error)

            update_exec = await tool.execute(
                ToolInvocation(
                    params={
                        "action": "update",
                        "scope": "execution",
                        "id": exec_ids[1],
                        "new_content": "Task B updated",
                    },
                    cwd=cwd,
                )
            )
            self.assertTrue(update_exec.success, msg=update_exec.error)

            reopen_exec = await tool.execute(
                ToolInvocation(
                    params={"action": "reopen", "scope": "execution", "id": exec_ids[0]},
                    cwd=cwd,
                )
            )
            self.assertTrue(reopen_exec.success, msg=reopen_exec.error)

            remove_plan = await tool.execute(
                ToolInvocation(
                    params={"action": "remove", "scope": "planning", "id": plan_id},
                    cwd=cwd,
                )
            )
            self.assertTrue(remove_plan.success, msg=remove_plan.error)

            list_exec = await tool.execute(
                ToolInvocation(params={"action": "list", "scope": "execution"}, cwd=cwd)
            )
            self.assertIn("Scope: execution", list_exec.output)

    async def test_export_and_load_state_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tool = TodosTool(Config(cwd=cwd, api_key="test"))
            await tool.execute(
                ToolInvocation(
                    params={"action": "add", "scope": "execution", "items": ["One"]},
                    cwd=cwd,
                )
            )
            await tool.execute(
                ToolInvocation(
                    params={"action": "add", "scope": "planning", "items": ["Two"]},
                    cwd=cwd,
                )
            )
            state = tool.export_state()

            restored = TodosTool(Config(cwd=cwd, api_key="test"))
            restored.load_state(state)
            roundtrip = restored.export_state()

            self.assertEqual(roundtrip.get("version"), 1)
            self.assertEqual(len(roundtrip.get("planning", [])), 1)
            self.assertEqual(len(roundtrip.get("execution", [])), 1)


class TodosPolicyRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_defaults_scope_by_phase_and_blocks_execution_scope_in_planning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            in_plan = await registry.invoke(
                "todos",
                {"action": "add", "content": "Plan item"},
                cwd,
                hook_system,
                plan_mode_enabled=True,
                plan_phase="asking_questions",
            )
            self.assertTrue(in_plan.success, msg=in_plan.error)
            self.assertEqual(in_plan.metadata.get("scope"), "planning")

            blocked = await registry.invoke(
                "todos",
                {"action": "add", "scope": "execution", "content": "Exec item"},
                cwd,
                hook_system,
                plan_mode_enabled=True,
                plan_phase="asking_questions",
            )
            self.assertFalse(blocked.success)
            self.assertTrue(blocked.metadata.get("policy_blocked"))

            exec_mode = await registry.invoke(
                "todos",
                {"action": "add", "content": "Exec item"},
                cwd,
                hook_system,
                plan_mode_enabled=False,
                plan_phase="idle",
            )
            self.assertTrue(exec_mode.success, msg=exec_mode.error)
            self.assertEqual(exec_mode.metadata.get("scope"), "execution")


if __name__ == "__main__":
    unittest.main()

