"""Real registry authorization, persistence, and the mounted permissions picker."""

from __future__ import annotations

import asyncio
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from unittest.mock import AsyncMock, patch

from rich.console import Console
from textual.widgets import OptionList, TextArea

from ite.commands import CommandContext, build_registry
from ite.config.config import ApprovalPolicy, Config, PermissionMode
from ite.config.loader import load_config, save_global_permission_mode
from ite.hooks.hook_system import HookSystem
from ite.safety.approval import ApprovalManager
from ite.safety.permissions import apply_mode, current_mode
from ite.safety.sandbox import invocation_paths
from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from ite.tools.builtin.read_file import ReadFileTool
from ite.tools.builtin.write_file import WriteFileTool
from ite.tools.registry import ToolRegistry
from ite.ui.reup.app import ReupApp
from ite.ui.reup.permissions_picker import PermissionsPickerModal


class InternetTool(Tool):
    name = "test_internet"
    description = "Test a read-only internet capability"
    kind = ToolKind.NETWORK
    schema: ClassVar = {"type": "object", "properties": {}}

    def is_mutating(self, params):
        return False

    async def execute(self, invocation: ToolInvocation):
        return ToolResult.success_result("internet called")


class PermissionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_boundaries_decline_approval_scope_and_modes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            external = root / "outside.txt"
            external.write_text("private")
            cfg = Config(cwd=workspace, permissions=PermissionMode.AUTOMATIC)
            registry = ToolRegistry(cfg)
            read = ReadFileTool(cfg)
            write = WriteFileTool(cfg)
            internet = InternetTool(cfg)
            for tool in (read, write, internet):
                registry.register(tool)
            callback = AsyncMock(return_value=False)
            manager = ApprovalManager(cfg.approval, workspace, callback)
            hooks = HookSystem(cfg)

            async def invoke(name, params):
                return await registry.invoke(name, params, workspace, hooks, manager)

            result = await invoke(
                "write_file", {"path": "inside.txt", "content": "ours"}
            )
            self.assertTrue(result.success, result.error)
            callback.assert_not_called()
            with patch.object(read, "execute", wraps=read.execute) as execute:
                result = await invoke("read_file", {"path": str(external)})
                self.assertFalse(result.success)
                execute.assert_not_called()
            callback.return_value = True
            result = await invoke("read_file", {"path": str(external)})
            self.assertTrue(result.success, result.error)
            self.assertIn("private", result.output)
            self.assertEqual(invocation_paths.get(), ())
            self.assertEqual(cfg.sandbox.allowed_paths, [])
            callback.return_value = False
            result = await invoke("read_file", {"path": str(external)})
            self.assertFalse(result.success)
            callback.reset_mock()
            result = await invoke("test_internet", {})
            self.assertFalse(result.success)
            callback.assert_awaited_once()
            callback.return_value = True
            self.assertTrue((await invoke("test_internet", {})).success)
            apply_mode(cfg, PermissionMode.ASK)
            callback.return_value = False
            self.assertFalse(
                (
                    await invoke("write_file", {"path": "blocked.txt", "content": "no"})
                ).success
            )
            self.assertFalse((workspace / "blocked.txt").exists())
            self.assertTrue((await invoke("read_file", {"path": "inside.txt"})).success)
            apply_mode(cfg, PermissionMode.FULL)
            callback.reset_mock()
            self.assertTrue(
                (await invoke("read_file", {"path": str(external)})).success
            )
            self.assertTrue((await invoke("test_internet", {})).success)
            callback.assert_not_called()
            self.assertFalse(cfg.sandbox.enabled)
            apply_mode(cfg, PermissionMode.AUTOMATIC)
            self.assertTrue(cfg.sandbox.enabled)
            manager.confirmation_callback = None
            self.assertFalse((await invoke("test_internet", {})).success)
            self.assertFalse(await manager.request_confirmation(None))

    async def test_parallel_grants_and_learning_cannot_inherit_access(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "secret.txt"
            outside.write_text("secret")
            cfg = Config(cwd=workspace, permissions=PermissionMode.AUTOMATIC)
            registry = ToolRegistry(cfg)
            registry.register(ReadFileTool(cfg))
            hooks = HookSystem(cfg)
            allow = ApprovalManager(
                cfg.approval, workspace, AsyncMock(return_value=True)
            )
            deny = ApprovalManager(
                cfg.approval, workspace, AsyncMock(return_value=False)
            )
            approved, declined = await asyncio.gather(
                *(
                    registry.invoke(
                        "read_file", {"path": str(outside)}, workspace, hooks, manager
                    )
                    for manager in (allow, deny)
                )
            )
            self.assertTrue(approved.success)
            self.assertFalse(declined.success)
            registry.register(WriteFileTool(cfg))
            registry.learning_enabled = lambda: True
            apply_mode(cfg, PermissionMode.FULL)
            result = await registry.invoke(
                "write_file",
                {"path": "no.txt", "content": "no"},
                workspace,
                hooks,
                allow,
            )
            self.assertFalse(result.success)
            self.assertFalse((workspace / "no.txt").exists())

    async def test_persistence_legacy_custom_and_command(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            path.write_text(
                'approval = "never"\n[model]\nname = "keep"\n[ sandbox ]\nenabled = true\n'
            )
            with patch("ite.config.loader.get_system_config_path", return_value=path):
                save_global_permission_mode("full")
                loaded = load_config(root)
                self.assertEqual(loaded.permissions, PermissionMode.FULL)
                self.assertFalse(loaded.sandbox.enabled)
                self.assertEqual(loaded.model.name, "keep")
                save_global_permission_mode(None)
                loaded = load_config(root)
                self.assertIsNone(current_mode(loaded))
                self.assertEqual(loaded.approval, ApprovalPolicy.NEVER)
                cfg = Config(cwd=root)
                ctx = CommandContext(cfg, None, None, Console(file=StringIO()))
                await build_registry().dispatch("/permissions", ["ask"], ctx)
                self.assertEqual(current_mode(cfg), PermissionMode.ASK)
                self.assertIn('permissions = "ask"', path.read_text())
                self.assertIn('name = "keep"', path.read_text())

    async def test_mounted_picker_keyboard_scrim_resize_and_composer_click(self):
        with TemporaryDirectory() as directory:
            cfg = Config(cwd=Path(directory), cloud_auth_enabled=False)
            app = ReupApp(cfg)

            async def bootstrap():
                app._set_startup_state(False)
                app._set_loading_state("idle", busy=False)
                app.query_one("#prompt", TextArea).focus()

            with patch.object(app, "_bootstrap_after_mount", bootstrap):
                async with app.run_test(size=(110, 40)) as pilot:
                    await pilot.pause()
                    app.run_worker(app.run_command("/permissions"))
                    await pilot.pause()
                    self.assertIsInstance(app.screen, PermissionsPickerModal)
                    self.assertEqual(app.screen.query_one(OptionList).highlighted, 1)
                    self.assertEqual(len(app.screen_stack), 2)
                    self.assertFalse(app.screen.query("Collapsible"))
                    self.assertLess(app.screen.styles.background.a, 1)
                    await pilot.press("down")
                    self.assertEqual(app.screen.query_one(OptionList).highlighted, 2)
                    # Cancel must leave the old settings untouched.
                    await pilot.press("escape")
                    self.assertEqual(cfg.permissions, PermissionMode.AUTOMATIC)
                    await pilot.pause()
                    app._update_composer_meta_line()
                    self.assertNotIn("context", app._composer_meta_text().plain)
                    self.assertEqual(app._composer_context_hitbox, (0, 0))
                    start, end = app._composer_permissions_hitbox
                    self.assertGreater(end, start)
                    await pilot.click("#composer-meta-line", offset=(start, 0))
                    await pilot.pause()
                    self.assertIsInstance(app.screen, PermissionsPickerModal)
                    await pilot.resize_terminal(80, 24)
                    await pilot.pause()
                    modal = app.screen.query_one(".permissions-modal")
                    self.assertLessEqual(modal.region.bottom, 24)
                    self.assertLessEqual(
                        app.screen.query_one("#permission-cancel").region.bottom,
                        modal.region.bottom - 1,
                    )
                    self.assertTrue(app.screen.query_one("#permission-cancel").visible)
                    self.assertEqual(
                        app.screen.query_one("#permission-cancel").size.height, 1
                    )
                    app.save_screenshot("permissions-narrow.svg", path="/tmp")
                    app.theme = "textual-light"
                    await pilot.pause()
                    self.assertLess(app.screen.styles.background.a, 1)
                    await pilot.press("escape")

    async def test_picker_selection_updates_real_session_and_saves(self):
        from ite.agent.agent import Agent
        from ite.agent.session import Session

        with TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = Config(
                cwd=root,
                cloud_auth_enabled=False,
                api_key="test",
                base_url="https://provider.example.test/v1",
            )
            session = Session(cfg.model_copy(deep=True))
            agent = Agent(session.config, session=session)
            self.addAsyncCleanup(session.client.close)
            app = ReupApp(cfg)

            async def bootstrap():
                app._set_startup_state(False)
                app._set_loading_state("idle", busy=False)
                app.agent = agent
                app._session_agents[session.session_id] = agent
                app.query_one("#prompt", TextArea).focus()

            with (
                patch.object(app, "_bootstrap_after_mount", bootstrap),
                patch.object(app, "ensure_agent", AsyncMock()),
                patch(
                    "ite.config.loader.get_system_config_path",
                    return_value=root / "config.toml",
                ),
            ):
                async with app.run_test(size=(110, 40)) as pilot:
                    await pilot.pause()
                    app.run_worker(app.run_command("/permissions"))
                    await pilot.pause()
                    await pilot.press("down", "enter")
                    await pilot.pause()
                    self.assertNotIsInstance(app.screen, PermissionsPickerModal)
                    self.assertEqual(current_mode(cfg), PermissionMode.FULL)
                    self.assertEqual(current_mode(session.config), PermissionMode.FULL)
                    self.assertEqual(
                        session.approval_manager.approval_policy, ApprovalPolicy.YOLO
                    )
                    self.assertIn(
                        'permissions = "full"', (root / "config.toml").read_text()
                    )
                    app._update_composer_meta_line()
                    self.assertIn("full access", app._composer_meta_text().plain)
                    from textual.widgets import Static

                    from ite.ui.reup.settings import SettingsPanel
                    from ite.ui.reup.widgets.permissions_status import (
                        PermissionsStatusBody,
                    )

                    body = app.query(PermissionsStatusBody).last()
                    self.assertEqual(
                        str(body.query_one(".permission-value", Static).render()),
                        "Full access",
                    )
                    self.assertTrue(
                        body.query_one(".permission-value").has_class("permission-full")
                    )
                    app.save_screenshot("permissions-status.svg", path="/tmp")
                    panel = app.query_one(SettingsPanel)
                    panel.refresh_permissions_state()
                    self.assertEqual(
                        str(panel._info_permissions._value_widget.render()),
                        "Full access",
                    )
                    await app._open_settings_screen()
                    await pilot.pause()
                    change = app.query_one("#settings-permissions-change")
                    change.scroll_visible(animate=False)
                    await pilot.pause()
                    self.assertGreater(
                        change.region.y,
                        app.query_one("#settings-activity-panel").region.y,
                    )
                    await pilot.click("#settings-permissions-change")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, PermissionsPickerModal)
                    self.assertEqual(app.screen.query_one(OptionList).highlighted, 2)
                    await pilot.press("up", "enter")
                    await pilot.pause()
                    self.assertEqual(current_mode(cfg), PermissionMode.AUTOMATIC)
                    self.assertEqual(
                        str(panel._info_permissions._value_widget.render()), "Automatic"
                    )
                    app.set_settings_active(False)
                    app.run_worker(app.run_command("/permissions ask"))
                    await pilot.pause()
                    self.assertEqual(current_mode(session.config), PermissionMode.ASK)
                    self.assertTrue(session.config.sandbox.enabled)
                    session.turn_active = True
                    app.run_worker(app.run_command("/permissions full"))
                    await pilot.pause()
                    self.assertEqual(current_mode(session.config), PermissionMode.ASK)
                    session.turn_active = False

    async def test_shell_hooks_symlinks_and_cancelled_approval(self):
        from ite.config.config import HookConfig, HookTrigger
        from ite.tools.builtin.shell import ShellTool

        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"
            outside.write_text("outside")
            (workspace / "link.txt").symlink_to(outside)
            cfg = Config(
                cwd=workspace,
                permissions=PermissionMode.AUTOMATIC,
                hooks_enabled=True,
                hooks=[
                    HookConfig(
                        name="test",
                        trigger=HookTrigger.BEFORE_TOOL,
                        command="echo hook",
                        blocking=True,
                    )
                ],
            )
            registry = ToolRegistry(cfg)
            for tool in (ShellTool(cfg), ReadFileTool(cfg), WriteFileTool(cfg)):
                registry.register(tool)
            hooks = HookSystem(cfg)
            self.assertTrue(hooks.snapshot()["suspended"])
            callback = AsyncMock(return_value=False)
            manager = ApprovalManager(cfg.approval, workspace, callback)
            with patch.object(
                hooks, "_run_command", AsyncMock(return_value=("", "", 0, False))
            ) as hook_run:
                denied = await registry.invoke(
                    "shell", {"command": "pwd"}, workspace, hooks, manager
                )
                self.assertFalse(denied.success)
                callback.assert_awaited_once()
                callback.reset_mock()
                denied = await registry.invoke(
                    "read_file", {"path": "link.txt"}, workspace, hooks, manager
                )
                self.assertFalse(denied.success)
                callback.assert_awaited_once()
                callback.return_value = True
                approved = await registry.invoke(
                    "shell", {"command": "pwd"}, workspace, hooks, manager
                )
                self.assertTrue(approved.success, approved.error)
                approved = await registry.invoke(
                    "write_file",
                    {"path": str(outside), "content": "updated"},
                    workspace,
                    hooks,
                    manager,
                )
                self.assertTrue(approved.success, approved.error)
                self.assertEqual(outside.read_text(), "updated")
                self.assertEqual(invocation_paths.get(), ())
                hook_run.assert_not_called()
                callback.side_effect = asyncio.CancelledError
                with self.assertRaises(asyncio.CancelledError):
                    await registry.invoke(
                        "read_file", {"path": str(outside)}, workspace, hooks, manager
                    )
                self.assertEqual(invocation_paths.get(), ())
                self.assertEqual(registry.active_invocations, 0)

    async def test_defaults_and_removed_commands(self):
        self.assertEqual(current_mode(Config()), PermissionMode.AUTOMATIC)
        self.assertEqual(
            current_mode(Config(approval=ApprovalPolicy.AUTO)), PermissionMode.AUTOMATIC
        )
        self.assertEqual(
            current_mode(Config(permissions=PermissionMode.FULL)), PermissionMode.FULL
        )
        self.assertIsNone(current_mode(Config(approval=ApprovalPolicy.NEVER)))
        registry = build_registry()
        for command in ("/approval", "/sandbox"):
            self.assertIsNone(registry.get(command))
            self.assertNotIn(command, [item.name for item in registry.all_commands()])
            config = Config()
            ctx = CommandContext(config, None, None, Console(file=StringIO()))
            await registry.dispatch(command, ["off"], ctx)
            self.assertEqual(current_mode(config), PermissionMode.AUTOMATIC)

        with TemporaryDirectory() as directory:
            app = ReupApp(Config(cwd=Path(directory), cloud_auth_enabled=False))
            with (
                patch.object(app, "post_notice") as notice,
                patch.object(app, "ensure_agent", AsyncMock()) as ensure,
            ):
                for command in (
                    "/approval",
                    "/approval yolo",
                    "/sandbox",
                    "/sandbox off",
                ):
                    await app.run_command(command)
                self.assertEqual(notice.call_count, 4)
                ensure.assert_not_called()
                self.assertEqual(current_mode(app.config), PermissionMode.AUTOMATIC)

    async def test_advanced_is_unavailable_and_provider_setup_preserves_mode(self):
        registry = build_registry()
        self.assertNotIn(
            "advanced", [usage for usage, _ in registry.get("/permissions").variants]
        )
        ctx = CommandContext(Config(), None, None, Console(file=StringIO()))
        await registry.dispatch("/permissions", ["advanced"], ctx)
        self.assertEqual(ctx.outcome, "failed")
        self.assertEqual(current_mode(ctx.config), PermissionMode.AUTOMATIC)
        result = {
            "api_key": "test",
            "base_url": "https://provider.example.test/v1",
            "model_name": "test",
            "approval": "auto",
        }
        with TemporaryDirectory() as directory:
            for mode in (PermissionMode.AUTOMATIC, PermissionMode.FULL, None):
                app = ReupApp(
                    Config(
                        cwd=Path(directory), permissions=mode, cloud_auth_enabled=False
                    )
                )
                with (
                    patch("ite.ui.reup._threads.save_system_config"),
                    patch("ite.ui.reup._threads.save_saved_custom_provider"),
                    patch(
                        "ite.ui.reup._threads.save_global_approval_mode"
                    ) as save_approval,
                    patch.object(app, "_reset_active_provider_client", AsyncMock()),
                    patch.object(
                        app, "_resolve_model_vision_support", return_value=False
                    ),
                    patch.object(app, "refresh_header"),
                    patch.object(app, "post_notice"),
                ):
                    await app._apply_setup_result(result)
                    self.assertEqual(
                        current_mode(app.config), mode or PermissionMode.AUTOMATIC
                    )
                    if mode is not None:
                        save_approval.assert_not_called()

    async def test_global_level_overrides_all_workspace_settings(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            global_config = root / "global.toml"
            workspaces = [root / "one", root / "two", root / "new"]
            for workspace, mode in zip(workspaces, ("ask", "full", "automatic")):
                (workspace / ".ite").mkdir(parents=True)
                (workspace / ".ite/config.toml").write_text(
                    f'permissions = "{mode}"\napproval = "never"\n[sandbox]\nenabled = false\n'
                )
            with patch(
                "ite.config.loader.get_system_config_path", return_value=global_config
            ):
                for workspace in workspaces:
                    self.assertEqual(
                        current_mode(load_config(workspace)), PermissionMode.AUTOMATIC
                    )
                for selected in PermissionMode:
                    save_global_permission_mode(selected.value)
                    for workspace in workspaces:
                        self.assertEqual(current_mode(load_config(workspace)), selected)
