import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from click.testing import CliRunner

from ite.config.config import Config, DEFAULT_CLOUD_API_URL
from ite.config.loader import load_config
from ite.main import main


class CLIModeRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def _config(self) -> Config:
        return Config(cwd=self.cwd, api_key="test-key", base_url="http://localhost:11434/v1")

    def test_default_runs_rich_tui(self) -> None:
        async def _fake_run_interactive(_self):
            return None

        fake_cli_type = type("FakeCLI", (), {"__init__": lambda self, config: None, "run_interactive": _fake_run_interactive})

        def _consume_coroutine(coro):
            try:
                coro.close()
            except Exception:
                pass
            return None

        with (
            patch("ite.main.ensure_workspace_layout", return_value=None),
            patch("ite.main.load_config", return_value=self._config()),
            patch("ite.main.CLI", fake_cli_type),
            patch("ite.main.asyncio.run", side_effect=_consume_coroutine) as mock_async_run,
        ):
            result = self.runner.invoke(main, [])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_async_run.assert_called_once()

    def test_gui_flag_uses_gui_runner(self) -> None:
        with (
            patch("ite.main.ensure_workspace_layout", return_value=None),
            patch("ite.main.load_config", return_value=self._config()),
            patch("ite.main.ensure_cloud_auth", return_value=None),
            patch("ite.ui.gui.run_gui", return_value=None) as mock_run_gui,
        ):
            result = self.runner.invoke(main, ["--desktop"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_run_gui.assert_called_once()

    def test_reup_flag_uses_reup_runner(self) -> None:
        with (
            patch("ite.main.ensure_workspace_layout", return_value=None),
            patch("ite.main.load_config", return_value=self._config()),
            patch("ite.ui.reup.run_reup", return_value=None) as mock_run_reup,
        ):
            result = self.runner.invoke(main, [])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_run_reup.assert_called_once()

    def test_default_routes_to_reup_when_byok_config_missing(self) -> None:
        config = Config(cwd=self.cwd)

        with (
            patch("ite.main.ensure_workspace_layout", return_value=None),
            patch("ite.main.load_config", return_value=config),
            patch("ite.ui.reup.run_reup", return_value=None) as mock_run_reup,
        ):
            result = self.runner.invoke(main, [])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_run_reup.assert_called_once_with(config)

    def test_gui_precedence_over_reup(self) -> None:
        with (
            patch("ite.main.ensure_workspace_layout", return_value=None),
            patch("ite.main.load_config", return_value=self._config()),
            patch("ite.main.ensure_cloud_auth", return_value=None),
            patch("ite.ui.gui.run_gui", return_value=None) as mock_run_gui,
            patch("ite.ui.reup.run_reup", return_value=None) as mock_run_reup,
        ):
            result = self.runner.invoke(main, ["--desktop", "--legacy"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_run_gui.assert_called_once()
        mock_run_reup.assert_not_called()

    def test_mcp_add_writes_global_stdio_server(self) -> None:
        system_dir = self.cwd / "system"
        system_dir.mkdir(parents=True, exist_ok=True)

        with (
            patch("ite.main.ensure_workspace_layout", return_value=self.cwd / ".ite"),
            patch("ite.config.loader.get_config_dir", return_value=system_dir),
        ):
            result = self.runner.invoke(
                main,
                ["mcp", "add", "netlify", "npx", "--", "-y", "@netlify/mcp"],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        written = (system_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.netlify]", written)
        self.assertIn('command = "npx"', written)
        self.assertIn('args = ["-y", "@netlify/mcp"]', written)

    def test_mcp_add_writes_workspace_url_server(self) -> None:
        result = self.runner.invoke(
            main,
            [
                "--cwd",
                str(self.cwd),
                "mcp",
                "add",
                "chrome-devtools",
                "https://127.0.0.1:9222/mcp",
                "--scope",
                "workspace",
            ],
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        written = (self.cwd / ".ite" / "config.toml").read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.chrome-devtools]", written)
        self.assertIn('url = "https://127.0.0.1:9222/mcp"', written)

    def test_mcp_add_accepts_explicit_url_and_transport_flags(self) -> None:
        system_dir = self.cwd / "system2"
        system_dir.mkdir(parents=True, exist_ok=True)

        with patch("ite.config.loader.get_config_dir", return_value=system_dir):
            result = self.runner.invoke(
                main,
                [
                    "mcp",
                    "add",
                    "figma",
                    "--url",
                    "https://mcp.figma.com/mcp",
                    "--transport",
                    "streamable_http",
                ],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        written = (system_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.figma]", written)
        self.assertIn('url = "https://mcp.figma.com/mcp"', written)
        self.assertIn('transport = "streamable_http"', written)

    def test_mcp_add_accepts_explicit_command_and_arg_flags(self) -> None:
        system_dir = self.cwd / "system3"
        system_dir.mkdir(parents=True, exist_ok=True)

        with patch("ite.config.loader.get_config_dir", return_value=system_dir):
            result = self.runner.invoke(
                main,
                [
                    "mcp",
                    "add",
                    "netlify",
                    "--command",
                    "npx",
                    "--arg",
                    "-y",
                    "--arg",
                    "@netlify/mcp",
                ],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        written = (system_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.netlify]", written)
        self.assertIn('command = "npx"', written)
        self.assertIn('args = ["-y", "@netlify/mcp"]', written)

    def test_mcp_add_normalizes_doc_style_http_transport_and_user_scope(self) -> None:
        system_dir = self.cwd / "system4"
        system_dir.mkdir(parents=True, exist_ok=True)

        with patch("ite.config.loader.get_config_dir", return_value=system_dir):
            result = self.runner.invoke(
                main,
                [
                    "mcp",
                    "add",
                    "figma",
                    "--scope",
                    "user",
                    "--transport",
                    "http",
                    "--url",
                    "https://mcp.figma.com/mcp",
                ],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        written = (system_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.figma]", written)
        self.assertIn('url = "https://mcp.figma.com/mcp"', written)
        self.assertIn('transport = "streamable_http"', written)
        self.assertNotIn('transport = "http"', written)

    def test_load_config_ignores_persisted_cloud_api_url(self) -> None:
        system_dir = self.cwd / "system5"
        system_dir.mkdir(parents=True, exist_ok=True)
        config_path = system_dir / "config.toml"
        config_path.write_text(
            '\n'.join(
                [
                    'api_key = "test-key"',
                    'base_url = "http://localhost:11434/v1"',
                    'cloud_auth_enabled = true',
                    'cloud_api_url = "http://127.0.0.1:4000"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with patch("ite.config.loader.get_config_dir", return_value=system_dir):
            config = load_config(self.cwd)

        self.assertEqual(config.cloud_api_url, DEFAULT_CLOUD_API_URL)
        rewritten = config_path.read_text(encoding="utf-8")
        self.assertNotIn("cloud_api_url", rewritten)


if __name__ == "__main__":
    unittest.main()
