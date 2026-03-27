import tempfile
import unittest
import os
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import PropertyMock
from unittest.mock import patch
from rich.console import Console

from ite.agent.agent import Agent
from ite.commands import CommandContext
from ite.commands.info import cmd_mcp
from ite.config.config import Config
from ite.config.config import MCPServerConfig
from ite.config.loader import load_config
from ite.tools.base import ToolRiskLevel
from ite.tools.base import ToolInvocation
from ite.tools.mcp.client import MCPClient
from ite.tools.mcp.client import MCPServerStatus
from ite.tools.mcp.client import MCPToolInfo
from ite.tools.mcp.mcp_manager import MCPManager
from ite.tools.mcp.oauth import FileAsyncKeyValueStore
from ite.tools.mcp.mcp_tool import MCPTool
from ite.ui.tool_narrative import activity_title
from ite.ui.reup.tool_views import parse_nested_json_payload
from ite.ui.reup.tool_views import summarize_mcp_success


class MCPClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_fails_fast_when_required_env_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            original = os.environ.pop("MCP_MISSING_TOKEN", None)
            try:
                client = MCPClient(
                    name="netlify",
                    config=MCPServerConfig(
                        command="npx",
                        args=["-y", "@netlify/mcp"],
                        env={"NETLIFY_PERSONAL_ACCESS_TOKEN": "${MCP_MISSING_TOKEN}"},
                    ),
                    cwd=cwd,
                )

                with self.assertRaisesRegex(RuntimeError, "Missing environment variables: MCP_MISSING_TOKEN"):
                    await client.connect()

                self.assertEqual(client.status, MCPServerStatus.ERROR)
                self.assertEqual(client.status_detail, "Missing environment variables: MCP_MISSING_TOKEN")
            finally:
                if original is not None:
                    os.environ["MCP_MISSING_TOKEN"] = original

    async def test_failed_connect_cleans_up_entered_client(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            client = MCPClient(
                name="demo",
                config=MCPServerConfig(command="python3"),
                cwd=cwd,
            )

            entered_client = AsyncMock()
            entered_client.__aenter__ = AsyncMock(return_value=entered_client)
            entered_client.__aexit__ = AsyncMock(return_value=None)
            entered_client.list_tools = AsyncMock(side_effect=RuntimeError("boom"))

            with patch("ite.tools.mcp.client.Client", return_value=entered_client):
                with self.assertRaisesRegex(RuntimeError, "failed to connect: boom"):
                    await client.connect()

            self.assertEqual(client.status, MCPServerStatus.ERROR)
            entered_client.__aexit__.assert_awaited_once()
            self.assertIsNone(client._client)
            self.assertEqual(client.tools, [])

    async def test_stdio_connect_failure_includes_server_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            client = MCPClient(
                name="netlify",
                config=MCPServerConfig(
                    command="npx",
                    args=["-y", "@netlify/mcp"],
                ),
                cwd=cwd,
            )

            entered_client = AsyncMock()
            entered_client.__aenter__ = AsyncMock(return_value=entered_client)
            entered_client.__aexit__ = AsyncMock(return_value=None)
            entered_client.list_tools = AsyncMock(side_effect=RuntimeError("Connection closed"))

            with patch("ite.tools.mcp.client.Client", return_value=entered_client), patch.object(
                client,
                "_read_stdio_log_tail",
                return_value="Netlify MCP requires NETLIFY_PERSONAL_ACCESS_TOKEN",
            ):
                with self.assertRaisesRegex(RuntimeError, "Server stderr"):
                    await client.connect()

            self.assertEqual(
                client.status_detail,
                "Connection closed: Netlify MCP requires NETLIFY_PERSONAL_ACCESS_TOKEN",
            )

    async def test_streamable_http_transport_uses_headers_and_auth(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            client = MCPClient(
                name="remote",
                config=MCPServerConfig(
                    url="https://example.com/mcp",
                    headers={"X-Test": "123"},
                    auth="token-value",
                    sse_read_timeout_sec=15,
                ),
                cwd=cwd,
            )

            transport = client._create_transport()

            self.assertEqual(type(transport).__name__, "StreamableHttpTransport")
            self.assertEqual(str(transport.url), "https://example.com/mcp")
            self.assertEqual(transport.headers["X-Test"], "123")
            self.assertEqual(type(transport.auth).__name__, "BearerAuth")

    async def test_sse_transport_selected_for_sse_url(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            client = MCPClient(
                name="remote",
                config=MCPServerConfig(url="https://example.com/sse"),
                cwd=cwd,
            )

            transport = client._create_transport()

            self.assertEqual(type(transport).__name__, "SSETransport")

    async def test_stdio_transport_sets_private_npm_cache_for_npx_servers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            client = MCPClient(
                name="netlify",
                config=MCPServerConfig(
                    command="npx",
                    args=["-y", "@netlify/mcp"],
                ),
                cwd=cwd,
            )

            transport = client._create_transport()

            self.assertEqual(type(transport).__name__, "StdioTransport")
            self.assertIn("npm_config_cache", transport.env)
            self.assertTrue(transport.env["npm_config_cache"])
            self.assertEqual(transport.env["npm_config_update_notifier"], "false")

    async def test_oauth_auth_uses_oauth_provider(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            client = MCPClient(
                name="remote",
                config=MCPServerConfig(
                    url="https://example.com/mcp",
                    auth="oauth",
                    oauth_scopes=["read", "write"],
                    oauth_client_name="iTE Test",
                    oauth_callback_port=3333,
                ),
                cwd=cwd,
            )

            with patch("ite.tools.mcp.client.build_oauth_provider", return_value=SimpleNamespace(kind="oauth")) as mocked:
                transport = client._create_transport()

            self.assertEqual(type(transport).__name__, "StreamableHttpTransport")
            self.assertEqual(transport.auth.kind, "oauth")
            mocked.assert_called_once()

    async def test_oauth_progress_updates_status_detail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            client = MCPClient(
                name="vercel",
                config=MCPServerConfig(url="https://example.com/mcp", auth="oauth"),
                cwd=cwd,
            )
            updates: list[dict[str, str | None]] = []

            async def callback(payload: dict[str, str | None]) -> None:
                updates.append(payload)

            client._status_callback = callback
            await client._oauth_progress("opening_browser", "Opening browser for authorization.")

            self.assertEqual(client.auth_phase, "opening_browser")
            self.assertEqual(client.status, MCPServerStatus.CONNECTING)
            self.assertEqual(client.status_detail, "Opening browser for authorization.")
            self.assertEqual(updates[-1]["detail"], "Opening browser for authorization.")


class MCPToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_hint_is_exposed_as_low_risk_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tool = MCPTool(
                config=Config(cwd=cwd, api_key="test"),
                client=MagicMock(),
                tool_info=MCPToolInfo(
                    name="list_issues",
                    description="List issues",
                    output_schema={"type": "array"},
                    annotations={"readOnlyHint": True},
                ),
                name="github__list_issues",
            )

            metadata = tool.get_metadata({})

            self.assertFalse(tool.is_mutating({}))
            self.assertEqual(metadata.risk_level, ToolRiskLevel.LOW)
            self.assertTrue(metadata.allowed_in_plan_mode)
            self.assertEqual(metadata.output_schema, {"type": "array"})

    async def test_destructive_hint_remains_high_risk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tool = MCPTool(
                config=Config(cwd=cwd, api_key="test"),
                client=MagicMock(),
                tool_info=MCPToolInfo(
                    name="delete_issue",
                    description="Delete issue",
                    annotations={"destructiveHint": True, "readOnlyHint": True},
                ),
                name="github__delete_issue",
            )

            metadata = tool.get_metadata({})

            self.assertTrue(tool.is_mutating({}))
            self.assertEqual(metadata.risk_level, ToolRiskLevel.HIGH)
            self.assertFalse(metadata.allowed_in_plan_mode)

    async def test_mcp_validation_error_is_marked_recoverable_with_ui_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            client = MagicMock()
            client.call_tool = AsyncMock(
                side_effect=RuntimeError(
                    'MCP error -32602: Input validation error: Invalid arguments for tool netlify-deploy-services-reader: expected "get-deploy"'
                )
            )
            tool = MCPTool(
                config=Config(cwd=cwd, api_key="test"),
                client=client,
                tool_info=MCPToolInfo(
                    name="netlify-deploy-services-reader",
                    description="Read deploys",
                    server_name="netlify",
                ),
                name="netlify__netlify-deploy-services-reader",
            )

            result = await tool.execute(ToolInvocation(params={}, cwd=cwd))

            self.assertFalse(result.success)
            self.assertTrue(result.metadata["recoverable"])
            self.assertEqual(result.metadata["ui_summary"], "That Netlify call used the wrong input.")
            self.assertEqual(
                result.metadata["ui_detail"],
                "Trying the `get-deploy` action instead.",
            )

    async def test_mcp_404_error_gets_calm_ui_copy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            client = MagicMock()
            client.call_tool = AsyncMock(
                return_value={
                    "output": "MCP tool failed: Failed to fetch API: 404",
                    "is_error": True,
                }
            )
            tool = MCPTool(
                config=Config(cwd=cwd, api_key="test"),
                client=client,
                tool_info=MCPToolInfo(
                    name="netlify-project-services-reader",
                    description="Read project",
                    server_name="netlify",
                ),
                name="netlify__netlify-project-services-reader",
            )

            result = await tool.execute(ToolInvocation(params={}, cwd=cwd))

            self.assertFalse(result.success)
            self.assertTrue(result.metadata["recoverable"])
            self.assertEqual(
                result.metadata["ui_summary"],
                "That Netlify item wasn't found.",
            )

    async def test_mcp_chrome_connect_error_gets_chrome_specific_copy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            client = MagicMock()
            client.call_tool = AsyncMock(
                side_effect=RuntimeError("MCP tool failed: Could not connect to Chrome")
            )
            tool = MCPTool(
                config=Config(cwd=cwd, api_key="test"),
                client=client,
                tool_info=MCPToolInfo(
                    name="navigate_page",
                    description="Navigate page",
                    server_name="chrome-devtools",
                ),
                name="chrome-devtools__navigate_page",
            )

            result = await tool.execute(ToolInvocation(params={}, cwd=cwd))

            self.assertFalse(result.success)
            self.assertTrue(result.metadata["recoverable"])
            self.assertEqual(result.metadata["ui_summary"], "Chrome isn't ready yet.")
            self.assertEqual(
                result.metadata["ui_detail"],
                "Open Chrome and allow the debugging session, then try again.",
            )


class MCPUiRenderingTests(unittest.TestCase):
    def test_activity_title_for_mcp_success_is_not_generic(self) -> None:
        title = activity_title(
            "netlify__netlify-project-services-reader",
            stage="complete",
            success=True,
            metadata={"mcp_server": "netlify"},
        )

        self.assertEqual(title, "Netlify updated")

    def test_activity_title_humanizes_mcp_server_name(self) -> None:
        title = activity_title(
            "chrome-devtools__navigate_page",
            stage="complete",
            success=False,
            metadata={"mcp_server": "chrome-devtools"},
        )

        self.assertEqual(title, "Chrome Devtools failed")

    def test_parse_nested_json_payload_decodes_stringified_json(self) -> None:
        parsed = parse_nested_json_payload(
            '"[{\\"id\\":\\"1\\",\\"name\\":\\"ite\\",\\"site_id\\":\\"site-1\\"}]"'
        )

        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed[0]["name"], "ite")

    def test_summarize_mcp_success_compacts_list_payload(self) -> None:
        summary, blocks, truncated = summarize_mcp_success(
            server_name="netlify",
            tool_name="netlify__netlify-project-services-reader",
            payload_text='"[{\\"id\\":\\"1\\",\\"name\\":\\"ite\\",\\"site_id\\":\\"site-1\\"}]"',
        )

        self.assertEqual(summary, "Loaded 1 result from Netlify.")
        self.assertFalse(truncated)
        self.assertTrue(blocks)


class MCPManagerTests(unittest.TestCase):
    def test_server_counts_track_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            manager = MCPManager(Config(cwd=cwd, api_key="test"))
            manager._clients = {
                "github": SimpleNamespace(
                    status=MCPServerStatus.CONNECTED,
                    tools=[1, 2],
                    config=SimpleNamespace(auto_connect=True),
                ),
                "slack": SimpleNamespace(
                    status=MCPServerStatus.ERROR,
                    tools=[],
                    config=SimpleNamespace(auto_connect=True),
                ),
            }

            self.assertEqual(manager.configured_server_count, 2)
            self.assertEqual(manager.connected_server_count, 1)
            self.assertEqual(manager.failed_server_count, 1)
            self.assertEqual(manager.total_tool_count, 2)
            self.assertFalse(manager.all_startup_servers_failed)

    def test_initialize_leaves_manual_servers_ready(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as td:
                cwd = Path(td)
                manager = MCPManager(
                    Config(
                        cwd=cwd,
                        api_key="test",
                        mcp_servers={"vercel": MCPServerConfig(url="https://example.com/mcp")},
                    )
                )

                await manager.initialize()

                self.assertEqual(manager.startup_server_count, 0)
                self.assertEqual(manager.connected_server_count, 0)
                self.assertEqual(manager.get_all_servers()[0]["status"], "ready")

        import asyncio

        asyncio.run(run_test())

    def test_timeout_marks_server_as_error(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as td:
                cwd = Path(td)
                manager = MCPManager(Config(cwd=cwd, api_key="test"))
                client = AsyncMock()
                client.name = "filesystem"
                client.config = SimpleNamespace(
                    startup_timeout_sec=0.01,
                    oauth_timeout_sec=300,
                    auth=None,
                )
                client.status = MCPServerStatus.CONNECTING
                client.connect = AsyncMock(side_effect=TimeoutError())
                client.disconnect = AsyncMock(return_value=None)

                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    await manager._connect_client(client)

                self.assertEqual(client.status, MCPServerStatus.ERROR)
                client.disconnect.assert_awaited_once()

        import asyncio

        asyncio.run(run_test())

    def test_oauth_uses_oauth_timeout(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as td:
                cwd = Path(td)
                manager = MCPManager(Config(cwd=cwd, api_key="test"))
                client = AsyncMock()
                client.name = "vercel"
                client.config = SimpleNamespace(
                    startup_timeout_sec=10,
                    oauth_timeout_sec=300,
                    auth="oauth",
                )
                client.connect = AsyncMock(return_value=None)

                seen: dict[str, float] = {}

                async def fake_wait_for(awaitable, timeout):
                    seen["timeout"] = timeout
                    return await awaitable

                with patch("ite.tools.mcp.mcp_manager.asyncio.wait_for", new=fake_wait_for):
                    await manager._connect_client(client)

                self.assertEqual(seen["timeout"], 300)

        import asyncio

        asyncio.run(run_test())

    def test_get_all_servers_includes_detail_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            manager = MCPManager(Config(cwd=cwd, api_key="test"))
            manager._clients = {
                "vercel": SimpleNamespace(
                    status=MCPServerStatus.CONNECTING,
                    status_detail="Waiting for OAuth callback on localhost:3333.",
                    auth_phase="waiting_for_callback",
                    last_error=None,
                    tools=[],
                    config=SimpleNamespace(
                        auto_connect=False,
                        effective_transport="streamable_http",
                        url="https://mcp.vercel.com",
                    ),
                )
            }

            servers = manager.get_all_servers()

            self.assertEqual(servers[0]["detail"], "Waiting for OAuth callback on localhost:3333.")
            self.assertEqual(servers[0]["auth_phase"], "waiting_for_callback")

    def test_get_all_servers_reports_missing_env_for_ready_server(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            original = os.environ.pop("MCP_READY_MISSING", None)
            try:
                manager = MCPManager(Config(cwd=cwd, api_key="test"))
                manager._clients = {
                    "netlify": SimpleNamespace(
                        status=MCPServerStatus.READY,
                        status_detail=None,
                        auth_phase=None,
                        last_error=None,
                        tools=[],
                        config=MCPServerConfig(
                            command="npx",
                            args=["-y", "@netlify/mcp"],
                            env={"NETLIFY_PERSONAL_ACCESS_TOKEN": "${MCP_READY_MISSING}"},
                        ),
                    )
                }

                servers = manager.get_all_servers()

                self.assertEqual(servers[0]["detail"], "Missing env: MCP_READY_MISSING")
                self.assertEqual(servers[0]["missing_env"], ["MCP_READY_MISSING"])
            finally:
                if original is not None:
                    os.environ["MCP_READY_MISSING"] = original


class MCPSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_marks_mcp_degraded_when_all_servers_fail_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            agent = Agent(
                Config(
                    cwd=cwd,
                    api_key="test",
                    mcp_servers={"demo": MCPServerConfig(command="python3")},
                )
            )
            assert agent.session is not None

            with patch.object(agent.session.mcp_manager, "initialize", AsyncMock(return_value=None)):
                with patch.object(
                    MCPManager,
                    "all_startup_servers_failed",
                    new_callable=PropertyMock,
                    return_value=True,
                ):
                    with patch.object(
                        MCPManager,
                        "startup_server_count",
                        new_callable=PropertyMock,
                        return_value=1,
                    ):
                        await agent.session.initialize()

            self.assertIn("mcp", agent.session.runtime_status.disabled_capabilities)
            self.assertIn("mcp unavailable", agent.session.runtime_summary().lower())

    async def test_session_does_not_degrade_for_manual_mcp_servers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            agent = Agent(
                Config(
                    cwd=cwd,
                    api_key="test",
                    mcp_servers={"vercel": MCPServerConfig(url="https://example.com/mcp")},
                )
            )
            assert agent.session is not None

            await agent.session.initialize()

            self.assertNotIn("mcp", agent.session.runtime_status.disabled_capabilities)


class MCPConfigTests(unittest.TestCase):
    def test_url_defaults_to_streamable_http(self) -> None:
        config = MCPServerConfig(url="https://example.com/mcp")
        self.assertEqual(config.effective_transport, "streamable_http")

    def test_command_defaults_to_stdio(self) -> None:
        config = MCPServerConfig(command="npx")
        self.assertEqual(config.effective_transport, "stdio")

    def test_env_vars_expand_in_remote_config(self) -> None:
        original = os.environ.get("MCP_TEST_TOKEN")
        os.environ["MCP_TEST_TOKEN"] = "secret-token"
        try:
            config = MCPServerConfig(
                url="https://example.com/${MCP_TEST_TOKEN}",
                headers={"Authorization": "Bearer ${MCP_TEST_TOKEN}"},
                auth="${MCP_TEST_TOKEN}",
            )
        finally:
            if original is None:
                os.environ.pop("MCP_TEST_TOKEN", None)
            else:
                os.environ["MCP_TEST_TOKEN"] = original

        self.assertEqual(config.url, "https://example.com/secret-token")
        self.assertEqual(config.headers["Authorization"], "Bearer secret-token")
        self.assertEqual(config.auth, "secret-token")

    def test_unresolved_env_vars_detect_missing_placeholders(self) -> None:
        original = os.environ.pop("MCP_NOT_SET", None)
        try:
            config = MCPServerConfig(
                command="npx",
                args=["-y", "@netlify/mcp", "--token=${MCP_NOT_SET}"],
                env={"NETLIFY_PERSONAL_ACCESS_TOKEN": "${MCP_NOT_SET}"},
            )
        finally:
            if original is not None:
                os.environ["MCP_NOT_SET"] = original

        self.assertEqual(config.unresolved_env_vars(), ["MCP_NOT_SET"])

    def test_ws_rejects_headers_and_auth(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not support configured headers or auth"):
            MCPServerConfig(
                url="wss://example.com/mcp",
                transport="ws",
                headers={"Authorization": "Bearer token"},
            )

    def test_oauth_requires_url_server(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a URL-based MCP server"):
            MCPServerConfig(command="npx", auth="oauth")

    def test_oauth_specific_settings_require_oauth_auth(self) -> None:
        with self.assertRaisesRegex(ValueError, "OAuth-specific MCP settings require auth = 'oauth'"):
            MCPServerConfig(
                url="https://example.com/mcp",
                oauth_scopes=["read"],
            )

    def test_load_config_merges_system_and_workspace_mcp_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as sys_td:
            cwd = Path(td)
            ite_dir = cwd / ".ite"
            ite_dir.mkdir(parents=True, exist_ok=True)
            (ite_dir / "config.toml").write_text(
                "\n".join(
                    [
                        "[mcp_servers.netlify]",
                        'command = "npx"',
                        'args = ["-y", "@netlify/mcp"]',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (ite_dir / "secrets.toml").write_text(
                "\n".join(
                    [
                        "[mcp_env.netlify]",
                        'NETLIFY_PERSONAL_ACCESS_TOKEN = "workspace-token"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            system_dir = Path(sys_td)
            (system_dir / "secrets.toml").write_text(
                "\n".join(
                    [
                        "[mcp_env.netlify]",
                        'keys = ["NETLIFY_PERSONAL_ACCESS_TOKEN", "NETLIFY_TEAM_ID"]',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            fake_keyring = {
                ("ite.mcp.netlify", "NETLIFY_PERSONAL_ACCESS_TOKEN"): "global-token",
                ("ite.mcp.netlify", "NETLIFY_TEAM_ID"): "team-123",
            }
            with patch("ite.config.loader.get_config_dir", return_value=system_dir), patch(
                "ite.config.loader.keyring.get_password",
                side_effect=lambda service, key: fake_keyring.get((service, key)),
            ):
                config = load_config(cwd)

            env = config.mcp_servers["netlify"].env
            self.assertEqual(env["NETLIFY_PERSONAL_ACCESS_TOKEN"], "workspace-token")
            self.assertEqual(env["NETLIFY_TEAM_ID"], "team-123")


class MCPEnvCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_env_import_defaults_to_global_scope_and_reloads_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as sys_td:
            cwd = Path(td)
            ite_dir = cwd / ".ite"
            ite_dir.mkdir(parents=True, exist_ok=True)
            (ite_dir / "config.toml").write_text(
                "\n".join(
                    [
                        "[mcp_servers.netlify]",
                        'command = "npx"',
                        'args = ["-y", "@netlify/mcp"]',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            console_output = io.StringIO()
            console = Console(file=console_output, force_terminal=False, width=160)
            config = Config(
                cwd=cwd,
                api_key="test",
                mcp_servers={"netlify": MCPServerConfig(command="npx", args=["-y", "@netlify/mcp"])},
            )
            manager = SimpleNamespace(
                _clients={
                    "netlify": SimpleNamespace(config=config.mcp_servers["netlify"])
                }
            )
            ctx = CommandContext(
                config=config,
                agent=SimpleNamespace(
                    session=SimpleNamespace(
                        mcp_manager=manager,
                        tool_registry=SimpleNamespace(),
                    )
                ),
                tui=SimpleNamespace(),
                console=console,
            )

            original = os.environ.get("NETLIFY_PERSONAL_ACCESS_TOKEN")
            os.environ["NETLIFY_PERSONAL_ACCESS_TOKEN"] = "imported-token"
            written: dict[tuple[str, str], str] = {}
            try:
                with patch("ite.config.loader.get_config_dir", return_value=Path(sys_td)), patch(
                    "ite.config.loader.keyring.set_password",
                    side_effect=lambda service, key, value: written.__setitem__((service, key), value),
                ), patch(
                    "ite.config.loader.keyring.get_password",
                    side_effect=lambda service, key: written.get((service, key)),
                ):
                    await cmd_mcp(ctx, ["env", "import", "netlify", "NETLIFY_PERSONAL_ACCESS_TOKEN"])
            finally:
                if original is None:
                    os.environ.pop("NETLIFY_PERSONAL_ACCESS_TOKEN", None)
                else:
                    os.environ["NETLIFY_PERSONAL_ACCESS_TOKEN"] = original

            secrets_path = Path(sys_td) / "secrets.toml"
            self.assertTrue(secrets_path.exists())
            self.assertIn("NETLIFY_PERSONAL_ACCESS_TOKEN", secrets_path.read_text(encoding="utf-8"))
            self.assertEqual(
                written[("ite.mcp.netlify", "NETLIFY_PERSONAL_ACCESS_TOKEN")],
                "imported-token",
            )
            self.assertEqual(
                ctx.config.mcp_servers["netlify"].env["NETLIFY_PERSONAL_ACCESS_TOKEN"],
                "imported-token",
            )


class MCPOAuthStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_async_key_value_store_persists_values(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tokens.json"
            first = FileAsyncKeyValueStore(path)
            second = FileAsyncKeyValueStore(path)

            await first.put(
                "token-key",
                {"access_token": "abc"},
                collection="mcp-oauth-token",
                ttl=60,
            )

            value = await second.get("token-key", collection="mcp-oauth-token")

            self.assertEqual(value, {"access_token": "abc"})

    async def test_file_async_key_value_store_expires_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tokens.json"
            store = FileAsyncKeyValueStore(path)

            await store.put(
                "token-key",
                {"access_token": "abc"},
                collection="mcp-oauth-token",
                ttl=0,
            )

            value = await store.get("token-key", collection="mcp-oauth-token")

            self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
