import asyncio
import tempfile
import unittest
from pathlib import Path

from ite.config.config import Config
from ite.hooks.hook_system import HookSystem
from ite.tools.base import ToolInvocation
from ite.tools.builtin.apply_patch import ApplyPatchTool
from ite.tools.discovery import ToolDiscoveryManager
from ite.tools.policy import ToolSelectionPolicy
from ite.tools.registry import ToolRegistry
from ite.tools.registry import _validate_subagent_definition
from ite.tools.registry import create_default_registry
from ite.tools.subagent import SubagentDefinition
from ite.tools.subagent import SubagentTool


class ToolRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_tool_lists_available(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "not_a_tool",
                {},
                cwd,
                hook_system,
            )

            self.assertFalse(result.success)
            self.assertIn("Available tools", result.error or "")
            self.assertIn("available_tools", result.metadata)

    async def test_subagent_simple_lookup_blocked_by_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "subagent_codebase_investigator",
                {"goal": "find where SessionManager is defined"},
                cwd,
                hook_system,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("policy_blocked"))
            self.assertEqual(result.metadata.get("redirect_to"), "grep")

    def test_read_only_subagent_allowed_in_plan_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            tool = SubagentTool(
                config,
                SubagentDefinition(
                    name="codebase_investigator",
                    description="Investigate codebase",
                    goal_prompt="Use read tools only.",
                    allowed_tools=["read_file", "grep", "glob", "list_dir"],
                ),
            )
            metadata = tool.get_metadata({"goal": "review architecture"})
            self.assertTrue(metadata.allowed_in_plan_mode)

            decision = ToolSelectionPolicy().evaluate(
                tool_name=tool.name,
                params={"goal": "review architecture"},
                metadata=metadata,
                plan_mode_enabled=True,
                plan_phase="asking_questions",
            )
            self.assertTrue(decision.allowed)

    def test_mutating_subagent_still_blocked_in_plan_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            tool = SubagentTool(
                config,
                SubagentDefinition(
                    name="mutating_helper",
                    description="Mutates code",
                    goal_prompt="Use edit tools.",
                    allowed_tools=["read_file", "edit"],
                ),
            )
            metadata = tool.get_metadata({"goal": "make changes"})
            self.assertFalse(metadata.allowed_in_plan_mode)

            decision = ToolSelectionPolicy().evaluate(
                tool_name=tool.name,
                params={"goal": "make changes"},
                metadata=metadata,
                plan_mode_enabled=True,
                plan_phase="asking_questions",
            )
            self.assertFalse(decision.allowed)


class DiscoveryAndSubagentValidationTests(unittest.TestCase):
    def test_discovery_records_import_errors(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tool_dir = cwd / ".ite" / "tools"
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "broken_tool.py").write_text("def oops(:\n", encoding="utf-8")

            config = Config(cwd=cwd, api_key="test")
            registry = ToolRegistry(config)
            manager = ToolDiscoveryManager(config, registry)
            manager.discover_from_directory(cwd)

            self.assertTrue(manager.errors)
            self.assertIn("broken_tool.py", manager.errors[0])

    def test_subagent_definition_rejects_invalid_allowed_tools(self) -> None:
        definition = SubagentDefinition(
            name="bad",
            description="bad",
            goal_prompt="bad",
            allowed_tools=["readfile"],
        )
        with self.assertRaises(ValueError):
            _validate_subagent_definition(definition, {"read_file", "grep"})


class ApplyPatchToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_patch_mixed_operations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            update_file = cwd / "update.txt"
            delete_file = cwd / "delete.txt"
            update_file.write_text("hello\nworld\n", encoding="utf-8")
            delete_file.write_text("remove me\n", encoding="utf-8")

            config = Config(cwd=cwd, api_key="test")
            tool = ApplyPatchTool(config)
            patch = """*** Begin Patch
*** Add File: created.txt
+first line
+second line
*** Update File: update.txt
@@
 hello
-world
+there
*** Delete File: delete.txt
*** End Patch
"""
            result = await tool.execute(
                ToolInvocation(params={"patch": patch, "dry_run": False}, cwd=cwd)
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertTrue((cwd / "created.txt").exists())
            self.assertEqual(update_file.read_text(encoding="utf-8"), "hello\nthere\n")
            self.assertFalse(delete_file.exists())
            self.assertEqual(len(result.metadata.get("actions", [])), 3)

    async def test_apply_patch_rejects_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            tool = ApplyPatchTool(config)
            bad_patch = "*** Start Patch\n*** Update File: x\nbad\n*** End Patch\n"

            result = await tool.execute(
                ToolInvocation(params={"patch": bad_patch, "dry_run": False}, cwd=cwd)
            )
            self.assertFalse(result.success)
            self.assertIn("Invalid patch", result.error or "")

    async def test_apply_patch_blocks_outside_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            outside = cwd.parent / "outside_apply_patch_test.txt"
            config = Config(cwd=cwd, api_key="test")
            tool = ApplyPatchTool(config)
            patch = f"""*** Begin Patch
*** Add File: {outside}
+outside
*** End Patch
"""
            result = await tool.execute(
                ToolInvocation(params={"patch": patch, "dry_run": False}, cwd=cwd)
            )
            self.assertFalse(result.success)
            self.assertIn("outside the project sandbox", result.error or "")


class SubagentTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_subagent_timeout_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            definition = SubagentDefinition(
                name="timeout_test",
                description="timeout",
                goal_prompt="timeout",
                allowed_tools=["read_file"],
                timeout_seconds=0.01,
            )
            tool = SubagentTool(config, definition)

            async def slow_run(*, prompt, subagent_config, tool_calls):
                await asyncio.sleep(0.1)
                return "goal", "ok", None

            tool._run_subagent_agent = slow_run  # type: ignore[method-assign]
            result = await tool.execute(
                ToolInvocation(params={"goal": "run"}, cwd=cwd)
            )

            self.assertFalse(result.success)
            self.assertIn("timed out", result.error or "")
            payload = result.metadata.get("subagent_result", {})
            self.assertEqual(payload.get("termination"), "timeout")


if __name__ == "__main__":
    unittest.main()
