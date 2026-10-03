from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import tomllib
from contextlib import ExitStack
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from textual.app import App, ComposeResult
from textual.widgets import Button, Input, OptionList, Select, Static

from ite.config.config import Config, MCPServerConfig
from ite.config.loader import (
    clear_mcp_env_vars,
    invalidate_mcp_keyring_cache,
    load_mcp_keyring_env_vars,
    load_mcp_server_config,
    save_mcp_env_var,
    save_mcp_server_config,
)
from ite.tools.mcp.catalog import CONNECTION_CATALOG
from ite.tools.mcp.client import MCPClient, MCPServerStatus
from ite.tools.mcp.credentials import CredentialStore
from ite.tools.mcp.mcp_manager import MCPManager
from ite.tools.mcp.mcp_tool import MCPTool
from ite.tools.mcp.oauth import KeyringAsyncKeyValueStore
from ite.tools.mcp.service import ConnectionsService
from ite.tools.registry import ToolRegistry
from ite.ui.reup._helpers import redact_sensitive_command_text
from ite.ui.reup.connection_modals import (
    ConnectionCredentialsModal,
    ConnectionSetupModal,
)
from ite.ui.reup.connections import ConnectionsPanel
from ite.ui.reup.settings import SettingsPanel
from ite.ui.reup.widgets.action_button import FlatActionButton


class ConnectionsTestApp(App[None]):
    CSS_PATH = "../src/ite/ui/reup/styles/settings.tcss"

    def __init__(self, service: ConnectionsService) -> None:
        super().__init__()
        self.config = service.config
        self._cloud_signed_out = True
        self._standalone_connections_service = service

    def compose(self) -> ComposeResult:
        yield SettingsPanel(id="settings-panel")


class ConnectionsTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = self.root / "workspace"
        self.cwd.mkdir()
        self.config = Config(cwd=self.cwd, api_key="fixture")
        self.manager = MCPManager(self.config)
        self.registry = ToolRegistry(self.config)
        self.service = ConnectionsService(self.config, self.manager, self.registry)
        self.keyring: dict[tuple[str, str], str] = {}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("ite.config.loader.get_config_dir", return_value=self.root / "global"))
        for module in ("credentials", "trust", "client", "oauth", "service"):
            self.stack.enter_context(patch(f"ite.tools.mcp.{module}.get_data_dir", return_value=self.root / "data"))
        self.stack.enter_context(patch("keyring.get_password", side_effect=lambda service, name: self.keyring.get((service, name))))
        self.stack.enter_context(patch("keyring.set_password", side_effect=lambda service, name, value: self.keyring.__setitem__((service, name), value)))
        self.stack.enter_context(patch("keyring.delete_password", side_effect=lambda service, name: self.keyring.pop((service, name), None)))
        invalidate_mcp_keyring_cache()
        self.addCleanup(invalidate_mcp_keyring_cache)

    async def asyncTearDown(self) -> None:
        await self.manager.shutdown()

    async def test_secret_changes_preserve_other_credentials_and_refresh_cache(self) -> None:
        secret_path = self.cwd / ".ite" / "secrets.toml"
        secret_path.parent.mkdir()
        secret_path.write_text('[openrouter]\napi_key="fixture-other"\n[mcp_client_credentials.demo]\nclient_credentials_client_secret="fixture-machine"\n')
        save_mcp_env_var(cwd=self.cwd, scope="workspace", server="contains.dot", key="TOKEN", value="fixture-token")
        payload = tomllib.loads(secret_path.read_text())
        self.assertEqual(payload["openrouter"]["api_key"], "fixture-other")
        self.assertIn("demo", payload["mcp_client_credentials"])
        self.assertEqual(payload["mcp_env"]["contains.dot"]["TOKEN"], "fixture-token")
        self.assertEqual(load_mcp_keyring_env_vars("demo"), {})
        save_mcp_env_var(cwd=self.cwd, scope="global", server="demo", key="TOKEN", value="new-value")
        self.assertEqual(load_mcp_keyring_env_vars("demo"), {"TOKEN": "new-value"})

    async def test_create_disable_remove_and_preserve_neighbor(self) -> None:
        a = await self.service.save("contains.dot", "workspace", {"url": "https://example.com/mcp"})
        b = await self.service.save("other", "workspace", {"url": "https://other.example/mcp"})
        await self.service.set_credentials(a.key, {"headers": {"Authorization": "Bearer fixture-a"}})
        await self.service.set_credentials(b.key, {"headers": {"Authorization": "Bearer fixture-b"}})
        await self.service.set_enabled(a.key, False)
        self.assertEqual(self.service.snapshot(self.service.record(a.key))["status"], "disabled")
        await self.service.remove(a.key)
        self.assertEqual([record.name for record in self.service.records()], ["other"])
        self.assertEqual(CredentialStore(b.config.credential_ref).read()["headers"]["Authorization"], "Bearer fixture-b")
        self.assertIn("other", self.manager._clients)

    async def test_legacy_reset_preserves_scope_definitions_and_neighbors(self) -> None:
        for scope, url in (("global", "https://global.example/mcp"), ("workspace", "https://project.example/mcp")):
            save_mcp_server_config(cwd=self.cwd, scope=scope, server="legacy.name",
                                   config={"url": url, "env": {"TOKEN": f"{scope}-secret"}})
            save_mcp_env_var(cwd=self.cwd, scope=scope, server="neighbor", key="TOKEN", value="keep")
        clear_mcp_env_vars("legacy.name", cwd=self.cwd, scope="workspace")
        global_definition = load_mcp_server_config(cwd=self.cwd, scope="global", server="legacy.name")
        workspace_definition = load_mcp_server_config(cwd=self.cwd, scope="workspace", server="legacy.name")
        self.assertEqual(global_definition["url"], "https://global.example/mcp")
        self.assertEqual(workspace_definition["url"], "https://project.example/mcp")
        self.assertEqual(global_definition["env"], {"TOKEN": "global-secret"})
        self.assertFalse(workspace_definition.get("env"))
        clear_mcp_env_vars("legacy.name", cwd=self.cwd)
        self.assertEqual(load_mcp_server_config(cwd=self.cwd, scope="global", server="legacy.name")["url"], "https://global.example/mcp")
        self.assertEqual(load_mcp_keyring_env_vars("neighbor"), {"TOKEN": "keep"})

    async def test_github_recipe_credentials_survive_reload_and_stay_private(self) -> None:
        recipe = CONNECTION_CATALOG["github"]
        record = await self.service.save("github", "workspace", {"url": recipe.url, "provider": "github"})
        await self.service.set_credentials(record.key, {"headers": {"Authorization": "Bearer fixture-github"}})
        definition = load_mcp_server_config(cwd=self.cwd, scope="workspace", server="github")
        self.assertNotIn("fixture-github", json.dumps(definition))
        async def connect(client, status_callback=None):
            self.assertEqual(client.config.url, "https://api.githubcopilot.com/mcp/")
            self.assertEqual(client.config.headers["Authorization"], "Bearer fixture-github")
            client.status = MCPServerStatus.CONNECTED
        with patch.object(self.manager, "_connect_client", side_effect=connect):
            await self.service.connect(record.key)
        self.assertEqual(self.service.snapshot(self.service.record(record.key))["status"], "connected")

    async def test_notion_recipe_oauth_isolated_by_connection_and_scope(self) -> None:
        recipe = CONNECTION_CATALOG["notion"]
        records = [await self.service.save("notion", scope, {"url": recipe.url, "auth": recipe.auth, "provider": "notion"})
                   for scope in ("global", "workspace")]
        stores = [KeyringAsyncKeyValueStore(record.config.credential_ref) for record in records]
        for index, store in enumerate(stores):
            await store.put(recipe.url + "/tokens", {"access_token": f"fixture-notion-{index}"}, collection="mcp-oauth-token")
        await self.service.sign_out(records[1].key)
        self.assertEqual((await stores[0].get(recipe.url + "/tokens", collection="mcp-oauth-token"))["access_token"], "fixture-notion-0")
        self.assertIsNone(await stores[1].get(recipe.url + "/tokens", collection="mcp-oauth-token"))
        self.assertEqual(self.service.snapshot(self.service.record(records[0].key))["status"], "overridden")

    async def test_invalid_entries_are_visible_and_can_be_repaired(self) -> None:
        path = self.cwd / ".ite" / "config.toml"
        path.parent.mkdir()
        path.write_text('[mcp_servers.invalid]\nenabled=true\n')
        record = self.service.records()[0]
        self.assertEqual(self.service.snapshot(record)["status"], "needs_setup")
        await self.service.save("invalid", "workspace", {"url": "https://example.com/mcp"}, replace=True)
        self.assertIsNotNone(self.service.record(record.key).config)

    async def test_real_stdio_lifecycle_and_capability_selection(self) -> None:
        fixture = self.root / "fixture.py"
        fixture.write_text('from fastmcp import FastMCP\nmcp=FastMCP("fixture")\n@mcp.tool\ndef greet(name: str) -> str:\n return f"Hello, {name}"\nmcp.run(transport="stdio")\n')
        record = await self.service.save("fixture", "workspace", {"command": sys.executable, "args": [str(fixture)], "startup_timeout_sec": 15})
        with self.assertRaisesRegex(RuntimeError, "Review"):
            await self.service.connect(record.key)
        await self.service.connect(record.key, approve_local=True)
        result = await self.manager._clients["fixture"].call_tool("greet", {"name": "iTE"})
        self.assertIn("Hello, iTE", result["output"])
        self.assertEqual(self.registry.mcp_tool_count, 1)
        await self.service.select_tools(record.key, [])
        self.assertIsNone(self.registry.get("fixture__greet"))
        await self.service.select_tools(record.key, ["greet"])
        self.assertIsNotNone(self.registry.get("fixture__greet"))
        await self.service.disconnect(record.key)
        self.assertEqual(self.registry.mcp_tool_count, 0)

    async def test_cancellation_cleans_partial_connection(self) -> None:
        record = await self.service.save("slow", "workspace", {"url": "https://example.com/mcp"})
        entered = asyncio.Event()

        async def slow_connect(*args, **kwargs):
            entered.set()
            await asyncio.sleep(30)

        client = self.manager._clients["slow"]
        with patch.object(client, "connect", side_effect=slow_connect):
            task = asyncio.create_task(self.service.connect(record.key))
            await entered.wait()
            await self.service.cancel(record.key)
            self.assertTrue(task.cancelled())
            self.assertNotEqual(self.service.snapshot(record)["status"], "connecting")

    async def test_schema_and_structured_result_are_preserved(self) -> None:
        from ite.tools.mcp.client import MCPToolInfo

        schema = {"type": "object", "$defs": {"Id": {"type": "string"}},
                  "properties": {"id": {"$ref": "#/$defs/Id"}}, "additionalProperties": False}
        client = MCPClient("demo", MCPServerConfig(url="https://example.com/mcp"), self.cwd)
        tool = MCPTool(self.config, client, MCPToolInfo("read", "Read", input_schema=schema), "demo__read")
        self.assertEqual(tool.schema, schema)
        client.status = MCPServerStatus.CONNECTED
        client._client = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(content=[], structured_content={"answer": 42}, is_error=False)))
        self.assertEqual(json.loads((await client.call_tool("read", {}))["output"]), {"answer": 42})
        client._client = None

    async def test_token_entry_is_not_recalled_in_history(self) -> None:
        self.assertNotIn("fixture-secret", redact_sensitive_command_text("/mcp env set demo TOKEN fixture-secret"))

    async def test_native_settings_add_flow_without_cloud_or_commands(self) -> None:
        with patch.object(SettingsPanel, "refresh_cloud_data"), patch.object(SettingsPanel, "_populate_context"):
            app = ConnectionsTestApp(self.service)
            async with app.run_test(size=(80, 24)) as pilot:
                panel = app.query_one(SettingsPanel)
                await panel.open_connections()
                await pilot.pause()
                connections = app.query_one(ConnectionsPanel)
                self.assertTrue(connections.display)
                await pilot.click("#connections-add")
                await pilot.pause()
                modal = app.screen
                self.assertIsInstance(modal, ConnectionSetupModal)
                modal.query_one("#connection-kind", Select).value = "notion"
                await pilot.pause()
                self.assertEqual(modal.query_one("#connection-url", Input).value, "https://mcp.notion.com/mcp")
                self.assertEqual(modal.query_one("#connection-auth", Select).value, "oauth")
                modal.query_one("#connection-name", Input).value = "Test notes"
                await pilot.click("#connection-save")
                await pilot.pause()
                self.assertEqual(self.service.records()[0].label, "Test notes")
                self.assertTrue(app.query_one("#connection-connect", Button).display)
                self.assertEqual(str(connections.query_one("#connections-title", Static).content), "Test notes")
                self.assertFalse(connections.query_one("#connections-add").display)
                self.assertFalse(connections.query_one("#connections-summary").display)
                await pilot.press("escape")
                await pilot.pause()
                self.assertTrue(app.query_one("#connections-list", OptionList).display)
                self.assertEqual(str(connections.query_one("#connections-title", Static).content), "Connections")
                self.assertTrue(connections.query_one("#connections-add").display)
                self.assertTrue(connections.query_one("#connections-summary").display)
                await pilot.press("escape")
                await pilot.pause()
                self.assertTrue(app.query_one("#settings-content").display)

    async def test_narrow_form_keeps_save_and_cancel_visible(self) -> None:
        with patch.object(SettingsPanel, "refresh_cloud_data"), patch.object(SettingsPanel, "_populate_context"):
            app = ConnectionsTestApp(self.service)
            async with app.run_test(size=(60, 20)) as pilot:
                await app.query_one(SettingsPanel).open_connections()
                await pilot.pause()
                await pilot.click("#connections-add")
                await pilot.pause()
                save = app.screen.query_one("#connection-save", Button)
                cancel = app.screen.query_one("#connection-cancel", Button)
                self.assertGreater(save.region.width, 0)
                self.assertLessEqual(save.region.bottom, 20)
                self.assertLessEqual(cancel.region.bottom, 20)

    async def test_mcp_action_buttons_fit_small_terminals_and_follow_theme(self) -> None:
        record = await self.service.save("github", "workspace", {"url": CONNECTION_CATALOG["github"].url})
        for size, theme in (((80, 24), "textual-dark"), ((60, 20), "textual-light"),
                            ((240, 50), "textual-dark")):
            with self.subTest(size=size, theme=theme), patch.object(SettingsPanel, "refresh_cloud_data"), patch.object(SettingsPanel, "_populate_context"):
                app = ConnectionsTestApp(self.service)
                app.theme = theme
                async with app.run_test(size=size) as pilot:
                    panel = app.query_one(SettingsPanel)
                    manage = panel.query_one("#settings-connections-manage", Button)
                    self.assertIsInstance(manage, FlatActionButton)
                    await panel.open_connections()
                    await pilot.pause()
                    connections = app.query_one(ConnectionsPanel)
                    connections._selected = record.key
                    connections.refresh_connections()
                    connections.query_one("#connections-pages").current = "connections-detail"
                    await pilot.pause()
                    pages = connections.query_one("#connections-pages")
                    self.assertEqual(pages.region.width, min(connections.region.width, 200))
                    left_space = pages.region.x - connections.region.x
                    right_space = connections.region.right - pages.region.right
                    self.assertLessEqual(abs(left_space - right_space), 1)
                    self.assertEqual(connections.query_one(".connections-header").region.width, pages.region.width)
                    for button in connections.query(FlatActionButton):
                        if not button.display:
                            continue
                        self.assertEqual(button.region.height, 1)
                        self.assertEqual(button.styles.border.spacing.width, 0)
                        self.assertGreaterEqual(button.content_region.width, len(str(button.label)))
                    for column in (("connect", "edit", "doctor"),
                                   ("disconnect", "enable", "refresh"),
                                   ("credentials", "signout", "remove")):
                        buttons = [connections.query_one(f"#connection-{name}", Button) for name in column]
                        for above, below in pairwise(buttons):
                            self.assertEqual(below.region.y - above.region.bottom, 1)
                    app.push_screen(ConnectionCredentialsModal(record))
                    await pilot.pause()
                    save = app.screen.query_one("#credential-save", Button)
                    cancel = app.screen.query_one("#credential-cancel", Button)
                    for button in (save, cancel):
                        self.assertEqual(button.region.height, 1)
                        self.assertLessEqual(button.region.bottom, size[1])
                        self.assertEqual(button.styles.border.spacing.width, 0)
                    cancel.focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIs(app.screen, app.screen_stack[0])
