import asyncio
import tempfile
import unittest
from pathlib import Path

from ite.config.config import Config
from ite.agent.subagent_runtime import SubagentRuntime
from ite.hooks.hook_system import HookSystem
from ite.tools.base import ToolInvocation
from ite.tools.base import ToolResult
from ite.tools.builtin.apply_patch import ApplyPatchTool
from ite.tools.discovery import ToolDiscoveryManager
from ite.tools.policy import ToolSelectionPolicy
from ite.tools.registry import ToolRegistry
from ite.tools.registry import _validate_subagent_definition
from ite.tools.registry import create_default_registry
from ite.tools.registry import refresh_subagent_tools
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

    async def test_read_file_json_is_redirected_to_read_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "read_file",
                {"path": "package.json"},
                cwd,
                hook_system,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("policy_blocked"))
            self.assertEqual(result.metadata.get("redirect_to"), "read_json")

    async def test_spawn_subagent_alias_params_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            spawn = registry.get("spawn_subagent")
            codebase = registry.get("subagent_codebase_investigator")
            self.assertIsNotNone(spawn)
            self.assertIsNotNone(codebase)
            runtime = SubagentRuntime(
                config=config,
                session_id="parent_session_1",
                tool_registry=registry,
            )
            spawn.set_runtime(runtime)  # type: ignore[attr-defined]
            self.addAsyncCleanup(runtime.shutdown)

            async def fake_execute_with_progress(invocation: ToolInvocation, progress_callback=None):
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
                    "{}",
                    metadata={"subagent_result": payload, "subagent_trace": trace},
                )

            codebase._execute_with_progress = fake_execute_with_progress  # type: ignore[method-assign]

            result = await registry.invoke(
                "spawn_subagent",
                {"specialist": "registry", "task": "inspect registry internals"},
                cwd,
                hook_system,
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(result.metadata["requested_subagent"], "registry")
            self.assertEqual(result.metadata["selected_subagent"], "codebase_investigator")

    async def test_spawn_subagent_raw_alias_params_are_salvaged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            spawn = registry.get("spawn_subagent")
            codebase = registry.get("subagent_codebase_investigator")
            self.assertIsNotNone(spawn)
            self.assertIsNotNone(codebase)
            runtime = SubagentRuntime(
                config=config,
                session_id="parent_session_1",
                tool_registry=registry,
            )
            spawn.set_runtime(runtime)  # type: ignore[attr-defined]
            self.addAsyncCleanup(runtime.shutdown)

            async def fake_execute_with_progress(invocation: ToolInvocation, progress_callback=None):
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
                    "{}",
                    metadata={"subagent_result": payload, "subagent_trace": trace},
                )

            codebase._execute_with_progress = fake_execute_with_progress  # type: ignore[method-assign]

            result = await registry.invoke(
                "spawn_subagent",
                {
                    "raw_arguments": '{"specialist":"registry","task":"inspect registry internals"',
                },
                cwd,
                hook_system,
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(result.metadata["requested_subagent"], "registry")
            self.assertEqual(result.metadata["selected_subagent"], "codebase_investigator")

    async def test_spawn_subagents_alias_list_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            spawn_many = registry.get("spawn_subagents")
            codebase = registry.get("subagent_codebase_investigator")
            self.assertIsNotNone(spawn_many)
            self.assertIsNotNone(codebase)
            runtime = SubagentRuntime(
                config=config,
                session_id="parent_session_1",
                tool_registry=registry,
            )
            spawn_many.set_runtime(runtime)  # type: ignore[attr-defined]
            self.addAsyncCleanup(runtime.shutdown)

            async def fake_execute_with_progress(invocation: ToolInvocation, progress_callback=None):
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
                    "duration_ms": 1,
                    "child_turn_count": 1,
                    "termination": "goal",
                }
                return ToolResult.success_result(
                    "{}",
                    metadata={"subagent_result": payload, "subagent_trace": trace},
                )

            codebase._execute_with_progress = fake_execute_with_progress  # type: ignore[method-assign]

            result = await registry.invoke(
                "spawn_subagents",
                {
                    "items": [
                        {"specialist": "registry", "task": "inspect registry internals"},
                        {"specialist": "reup", "task": "inspect reup rendering"},
                    ]
                },
                cwd,
                hook_system,
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(result.metadata["count"], 2)

    async def test_read_file_toml_is_redirected_to_read_toml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "read_file",
                {"path": "pyproject.toml"},
                cwd,
                hook_system,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("policy_blocked"))
            self.assertEqual(result.metadata.get("redirect_to"), "read_toml")

    async def test_read_file_env_is_redirected_to_read_env(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / ".env").write_text("DEBUG=true\n", encoding="utf-8")
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "read_file",
                {"path": ".env"},
                cwd,
                hook_system,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("policy_blocked"))
            self.assertEqual(result.metadata.get("redirect_to"), "read_env")

    async def test_read_file_pdf_is_redirected_to_read_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "report.pdf").write_bytes(b"%PDF-1.4")
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "read_file",
                {"path": "report.pdf"},
                cwd,
                hook_system,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("policy_blocked"))
            self.assertEqual(result.metadata.get("redirect_to"), "read_pdf")

    async def test_read_file_image_is_redirected_to_read_image(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "screen.png").write_bytes(b"fake")
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "read_file",
                {"path": "screen.png"},
                cwd,
                hook_system,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("policy_blocked"))
            self.assertEqual(result.metadata.get("redirect_to"), "read_image")

    async def test_read_file_office_document_is_redirected_to_read_document(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "report.docx").write_bytes(b"fake")
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "read_file",
                {"path": "report.docx"},
                cwd,
                hook_system,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("policy_blocked"))
            self.assertEqual(result.metadata.get("redirect_to"), "read_document")

    async def test_read_file_json_with_line_window_is_still_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "read_file",
                {"path": "package.json", "offset": 1, "limit": 5},
                cwd,
                hook_system,
            )

            self.assertTrue(result.success, msg=result.error)

    async def test_edit_json_file_is_redirected_to_edit_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "edit",
                {
                    "path": "package.json",
                    "old_string": '"name":"demo"',
                    "new_string": '"name":"demo-app"',
                },
                cwd,
                hook_system,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("policy_blocked"))
            self.assertEqual(result.metadata.get("redirect_to"), "edit_json")

    async def test_edit_toml_file_is_redirected_to_write_toml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "edit",
                {
                    "path": "pyproject.toml",
                    "old_string": 'name = "demo"',
                    "new_string": 'name = "demo-app"',
                },
                cwd,
                hook_system,
            )

            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("policy_blocked"))
            self.assertEqual(result.metadata.get("redirect_to"), "write_toml")

    async def test_edit_json_create_style_call_is_still_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            hook_system = HookSystem(config)

            result = await registry.invoke(
                "edit",
                {
                    "path": "package.json",
                    "old_string": "",
                    "new_string": '{"name":"demo"}\n',
                },
                cwd,
                hook_system,
            )

            self.assertTrue(result.success, msg=result.error)

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
            _validate_subagent_definition(definition, {})

    def test_subagent_definition_rejects_subagent_ineligible_tools(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            registry = ToolRegistry(config)
            apply_patch = ApplyPatchTool(config)
            registry.register(apply_patch)

            definition = SubagentDefinition(
                name="bad",
                description="bad",
                goal_prompt="bad",
                allowed_tools=["apply_patch"],
            )
            with self.assertRaises(ValueError):
                _validate_subagent_definition(
                    definition, {"apply_patch": apply_patch}
                )

    def test_refresh_subagents_allows_discovered_custom_tools(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tool_dir = cwd / ".ite" / "tools"
            subagent_dir = cwd / ".ite" / "subagents"
            tool_dir.mkdir(parents=True, exist_ok=True)
            subagent_dir.mkdir(parents=True, exist_ok=True)

            (tool_dir / "custom_tool.py").write_text(
                """
from pydantic import BaseModel

from ite.tools.base import Tool, ToolResult, ToolInvocation


class Params(BaseModel):
    value: str


class CustomTool(Tool):
    name = "custom_tool"
    description = "Custom tool"
    schema = Params

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        return ToolResult.success_result(invocation.params["value"])
""".strip()
                + "\n",
                encoding="utf-8",
            )

            (subagent_dir / "custom_helper.toml").write_text(
                """
name = "custom_helper"
description = "Uses the discovered custom tool"
allowed_tools = ["custom_tool"]

goal_prompt = \"\"\"
Use the custom tool.
\"\"\"
""".strip()
                + "\n",
                encoding="utf-8",
            )

            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            self.assertIsNone(registry.get("subagent_custom_helper"))

            ToolDiscoveryManager(config, registry).discover_all()
            refresh_subagent_tools(registry, config)

            tool = registry.get("subagent_custom_helper")
            self.assertIsNotNone(tool)
            self.assertIsInstance(tool, SubagentTool)
            assert isinstance(tool, SubagentTool)
            self.assertEqual(tool.allowed_tools, ["custom_tool"])

    def test_refresh_subagents_excludes_recursive_tools_from_open_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            subagent_dir = cwd / ".ite" / "subagents"
            subagent_dir.mkdir(parents=True, exist_ok=True)

            (subagent_dir / "wide_open.toml").write_text(
                """
name = "wide_open"
description = "No explicit allowlist"

goal_prompt = \"\"\"
Investigate broadly.
\"\"\"
""".strip()
                + "\n",
                encoding="utf-8",
            )

            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            refresh_subagent_tools(registry, config)

            tool = registry.get("subagent_wide_open")
            self.assertIsNotNone(tool)
            self.assertIsInstance(tool, SubagentTool)
            assert isinstance(tool, SubagentTool)
            self.assertIsNotNone(tool.allowed_tools)
            self.assertIn("grep", tool.allowed_tools or [])
            self.assertNotIn("apply_patch", tool.allowed_tools or [])
            self.assertNotIn("subagent_code_reviewer", tool.allowed_tools or [])

    def test_refresh_subagents_uses_tool_metadata_for_mutation_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            subagent_dir = cwd / ".ite" / "subagents"
            subagent_dir.mkdir(parents=True, exist_ok=True)

            (subagent_dir / "json_editor.toml").write_text(
                """
name = "json_editor"
description = "Edits JSON files"
allowed_tools = ["edit_json"]

goal_prompt = \"\"\"
Edit JSON files safely.
\"\"\"
""".strip()
                + "\n",
                encoding="utf-8",
            )

            config = Config(cwd=cwd, api_key="test")
            registry = create_default_registry(config)
            refresh_subagent_tools(registry, config)

            tool = registry.get("subagent_json_editor")
            self.assertIsNotNone(tool)
            self.assertIsInstance(tool, SubagentTool)
            assert isinstance(tool, SubagentTool)
            self.assertTrue(tool.is_mutating({"goal": "edit package metadata"}))
            self.assertFalse(
                tool.get_metadata({"goal": "edit package metadata"}).allowed_in_plan_mode
            )

    def test_refresh_subagents_skips_incompatible_defaults_for_restricted_registry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(
                cwd=cwd,
                api_key="test",
                allowed_tools=["read_file", "grep", "glob", "list_dir"],
            )

            registry = create_default_registry(config)

            self.assertIsNotNone(registry.get("subagent_codebase_investigator"))
            self.assertIsNotNone(registry.get("subagent_code_reviewer"))
            self.assertIsNotNone(registry.get("subagent_tooling_guardian"))
            self.assertIsNone(registry.get("subagent_verification_reviewer"))


class ApplyPatchToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_patch_is_not_registered_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            registry = create_default_registry(Config(cwd=Path(td), api_key="test"))
            tool_names = {tool.name for tool in registry.get_tools()}

            self.assertNotIn("apply_patch", tool_names)

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

    async def test_apply_patch_accepts_unified_diff(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            update_file = cwd / "update.txt"
            update_file.write_text("hello\nworld\n", encoding="utf-8")

            config = Config(cwd=cwd, api_key="test")
            tool = ApplyPatchTool(config)
            patch = """--- a/update.txt
+++ b/update.txt
@@ -1,2 +1,2 @@
 hello
-world
+there
"""

            result = await tool.execute(
                ToolInvocation(params={"patch": patch, "dry_run": False}, cwd=cwd)
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(update_file.read_text(encoding="utf-8"), "hello\nthere\n")

    async def test_apply_patch_accepts_embedded_unified_headers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            update_file = cwd / "update.txt"
            update_file.write_text("hello\nworld\n", encoding="utf-8")

            config = Config(cwd=cwd, api_key="test")
            tool = ApplyPatchTool(config)
            patch = """*** Begin Patch
*** Update File: update.txt
--- a/update.txt
+++ b/update.txt
@@ -1,2 +1,2 @@
 hello
-world
+there
*** End Patch
"""

            result = await tool.execute(
                ToolInvocation(params={"patch": patch, "dry_run": False}, cwd=cwd)
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(update_file.read_text(encoding="utf-8"), "hello\nthere\n")

    async def test_apply_patch_ignores_leading_blank_line_before_hunk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            update_file = cwd / "update.txt"
            update_file.write_text("[build-system]\nhello\n", encoding="utf-8")

            config = Config(cwd=cwd, api_key="test")
            tool = ApplyPatchTool(config)
            patch = """*** Begin Patch
*** Update File: update.txt

@@
 [build-system]
-hello
+there
*** End Patch
"""

            result = await tool.execute(
                ToolInvocation(params={"patch": patch, "dry_run": False}, cwd=cwd)
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(update_file.read_text(encoding="utf-8"), "[build-system]\nthere\n")

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
    async def test_subagent_parses_structured_json_response_and_emits_trace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            definition = SubagentDefinition(
                name="json_test",
                description="json",
                goal_prompt="json",
                allowed_tools=["read_file"],
            )
            tool = SubagentTool(config, definition)

            async def structured_run(*, prompt, subagent_config, tool_calls):
                tool_calls.extend(["read_file", "grep"])
                return (
                    "goal",
                    '{"summary":"Investigated the workspace","findings":["A","B"],"actions":["Do X"]}',
                    None,
                    "child-session-1",
                    3,
                )

            tool._run_subagent_agent = structured_run  # type: ignore[method-assign]
            result = await tool.execute(
                ToolInvocation(
                    params={"goal": "investigate"},
                    cwd=cwd,
                    call_id="call_123",
                    session_id="parent_session_1",
                )
            )

            self.assertTrue(result.success, msg=result.error)
            payload = result.metadata.get("subagent_result", {})
            self.assertEqual(payload.get("summary"), "Investigated the workspace")
            self.assertEqual(payload.get("findings"), ["A", "B"])
            self.assertEqual(payload.get("actions"), ["Do X"])
            trace = result.metadata.get("subagent_trace", {})
            self.assertEqual(trace.get("parent_tool_call_id"), "call_123")
            self.assertEqual(trace.get("parent_session_id"), "parent_session_1")
            self.assertEqual(trace.get("child_session_id"), "child-session-1")
            self.assertEqual(trace.get("child_turn_count"), 3)
            self.assertEqual(trace.get("termination"), "goal")

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
                return "goal", "ok", None, "child-session-timeout", 1

            tool._run_subagent_agent = slow_run  # type: ignore[method-assign]
            result = await tool.execute(
                ToolInvocation(params={"goal": "run"}, cwd=cwd)
            )

            self.assertFalse(result.success)
            self.assertIn("timed out", result.error or "")
            payload = result.metadata.get("subagent_result", {})
            self.assertEqual(payload.get("termination"), "timeout")

    async def test_subagent_inactivity_timeout_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            definition = SubagentDefinition(
                name="inactive_test",
                description="inactive",
                goal_prompt="inactive",
                allowed_tools=["read_file"],
                timeout_seconds=1.0,
                inactivity_timeout_seconds=0.01,
            )
            tool = SubagentTool(config, definition)

            async def stalled_run(*, prompt, subagent_config, tool_calls, progress_callback=None):
                tool_calls.append("read_file")
                if progress_callback is not None:
                    maybe = progress_callback(
                        {
                            "phase": "tool_call_start",
                            "tool_name": "read_file",
                            "arguments": {"path": "lib/sms_notifier.dart"},
                        }
                    )
                    if maybe is not None:
                        await maybe
                await asyncio.sleep(0.1)
                return "goal", "ok", None, "child-session-inactive", 1

            tool._run_subagent_agent = stalled_run  # type: ignore[method-assign]
            result = await tool.execute(
                ToolInvocation(
                    params={"goal": "investigate notifier stall"},
                    cwd=cwd,
                    call_id="call_inactive",
                )
            )

            self.assertFalse(result.success)
            self.assertIn("timed out", result.error or "")
            payload = result.metadata.get("subagent_result", {})
            self.assertEqual(payload.get("termination"), "timeout")

    async def test_subagent_retries_after_max_turns_with_carried_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            definition = SubagentDefinition(
                name="retry_turns",
                description="retry",
                goal_prompt="retry goal",
                allowed_tools=["read_file"],
                retry_attempts=1,
            )
            tool = SubagentTool(config, definition)
            prompts: list[str] = []
            attempts = {"count": 0}

            async def flaky_run(*, prompt, subagent_config, tool_calls, progress_callback=None):
                prompts.append(prompt)
                attempts["count"] += 1
                tool_calls.append("read_file")
                if attempts["count"] == 1:
                    return (
                        "error",
                        "Finding: inspected registry wiring\nAction: finish runtime audit",
                        "Maximum turns (10) reached",
                        "child-session-1",
                        10,
                    )
                return (
                    "goal",
                    '{"summary":"Finished audit","findings":["Recovered prior work"],"actions":["Ship it"]}',
                    None,
                    "child-session-2",
                    4,
                )

            tool._run_subagent_agent = flaky_run  # type: ignore[method-assign]
            result = await tool.execute(
                ToolInvocation(
                    params={"goal": "finish the audit"},
                    cwd=cwd,
                    call_id="call_retry_turns",
                    session_id="parent_session_retry",
                )
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(attempts["count"], 2)
            self.assertEqual(len(prompts), 2)
            self.assertIn("CONTINUATION CONTEXT FROM PRIOR ATTEMPT(S):", prompts[1])
            self.assertIn("Maximum turns (10) reached", prompts[1])
            self.assertIn("finish runtime audit", prompts[1])
            payload = result.metadata.get("subagent_result", {})
            trace = result.metadata.get("subagent_trace", {})
            self.assertEqual(payload.get("summary"), "Finished audit")
            self.assertEqual(payload.get("retries_used"), 1)
            self.assertEqual(payload.get("attempt_count"), 2)
            self.assertTrue(payload.get("recovered_after_retry"))
            self.assertEqual(trace.get("retries_used"), 1)
            self.assertEqual(trace.get("attempt_count"), 2)
            self.assertTrue(trace.get("recovered_after_retry"))

    async def test_subagent_retries_after_timeout_with_carried_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            definition = SubagentDefinition(
                name="retry_timeout",
                description="retry timeout",
                goal_prompt="retry timeout",
                allowed_tools=["read_file"],
                timeout_seconds=0.01,
                retry_attempts=1,
            )
            tool = SubagentTool(config, definition)
            prompts: list[str] = []
            attempts = {"count": 0}
            child_session_ids: list[str] = []

            async def flaky_timeout_run(*, prompt, subagent_config, tool_calls, agent=None, progress_callback=None):
                prompts.append(prompt)
                attempts["count"] += 1
                tool_calls.append("read_file")
                if agent is not None and agent.session is not None:
                    child_session_ids.append(agent.session.session_id)
                if attempts["count"] == 1:
                    if progress_callback is not None:
                        maybe = progress_callback(
                            {
                                "phase": "tool_call_start",
                                "tool_name": "read_file",
                                "arguments": {"path": "src/ite/agent/session.py"},
                            }
                        )
                        if maybe is not None:
                            await maybe
                    await asyncio.sleep(0.1)
                    return "goal", "slow", None, "child-session-timeout", 1
                return (
                    "goal",
                    '{"summary":"Recovered after timeout","findings":["Used previous path"],"actions":["Done"]}',
                    None,
                    "child-session-timeout-2",
                    2,
                )

            tool._run_subagent_agent = flaky_timeout_run  # type: ignore[method-assign]
            result = await tool.execute(
                ToolInvocation(
                    params={"goal": "resume after timeout"},
                    cwd=cwd,
                    call_id="call_retry_timeout",
                    session_id="parent_session_retry",
                )
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(attempts["count"], 2)
            self.assertEqual(len(prompts), 2)
            self.assertEqual(len(set(child_session_ids)), 1)
            self.assertIn("CONTINUATION CONTEXT FROM PRIOR ATTEMPT(S):", prompts[1])
            self.assertIn("termination=timeout", prompts[1])
            self.assertIn("Reading session.py.", prompts[1])
            payload = result.metadata.get("subagent_result", {})
            trace = result.metadata.get("subagent_trace", {})
            self.assertEqual(payload.get("summary"), "Recovered after timeout")
            self.assertEqual(payload.get("retries_used"), 1)
            self.assertEqual(trace.get("retries_used"), 1)
            self.assertEqual(trace.get("attempt_count"), 2)

    async def test_subagent_retries_after_inactivity_timeout_with_carried_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            config = Config(cwd=cwd, api_key="test")
            definition = SubagentDefinition(
                name="retry_inactive",
                description="retry inactivity",
                goal_prompt="retry inactivity",
                allowed_tools=["read_file"],
                timeout_seconds=1.0,
                inactivity_timeout_seconds=0.01,
                retry_attempts=1,
            )
            tool = SubagentTool(config, definition)
            prompts: list[str] = []
            attempts = {"count": 0}
            child_session_ids: list[str] = []

            async def flaky_inactive_run(*, prompt, subagent_config, tool_calls, agent=None, progress_callback=None):
                prompts.append(prompt)
                attempts["count"] += 1
                tool_calls.append("read_file")
                if agent is not None and agent.session is not None:
                    child_session_ids.append(agent.session.session_id)
                if attempts["count"] == 1:
                    if progress_callback is not None:
                        maybe = progress_callback(
                            {
                                "phase": "tool_call_start",
                                "tool_name": "read_file",
                                "arguments": {"path": "lib/shared/shared_prefs_helper.dart"},
                            }
                        )
                        if maybe is not None:
                            await maybe
                    await asyncio.sleep(0.1)
                    return "goal", "slow", None, "child-session-inactive", 1
                return (
                    "goal",
                    '{"summary":"Recovered after inactivity timeout","findings":["Resumed stalled investigation"],"actions":["Done"]}',
                    None,
                    "child-session-inactive-2",
                    2,
                )

            tool._run_subagent_agent = flaky_inactive_run  # type: ignore[method-assign]
            result = await tool.execute(
                ToolInvocation(
                    params={"goal": "resume after inactivity timeout"},
                    cwd=cwd,
                    call_id="call_retry_inactive",
                    session_id="parent_session_retry",
                )
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(attempts["count"], 2)
            self.assertEqual(len(prompts), 2)
            self.assertEqual(len(set(child_session_ids)), 1)
            self.assertIn("CONTINUATION CONTEXT FROM PRIOR ATTEMPT(S):", prompts[1])
            self.assertIn("termination=timeout", prompts[1])
            self.assertIn("Reading shared_prefs_helper.dart.", prompts[1])
            payload = result.metadata.get("subagent_result", {})
            trace = result.metadata.get("subagent_trace", {})
            self.assertEqual(payload.get("summary"), "Recovered after inactivity timeout")
            self.assertEqual(payload.get("retries_used"), 1)
            self.assertEqual(trace.get("retries_used"), 1)
            self.assertEqual(trace.get("attempt_count"), 2)


if __name__ == "__main__":
    unittest.main()
