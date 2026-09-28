import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from click.testing import CliRunner

from ite.config.config import Config, DEFAULT_CLOUD_API_URL, DEFAULT_CLOUD_CLIENT_ID
from ite.config.loader import load_config, save_onboarding_settings
from ite.main import main


class CLIModeRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def _config(self) -> Config:
        return Config(cwd=self.cwd, api_key="test-key", base_url="http://localhost:11434/v1")

    def test_default_uses_reup_runner(self) -> None:
        with (
            patch("ite.main.ensure_workspace_layout", return_value=None),
            patch("ite.main.load_config", return_value=self._config()),
            patch("ite.ui.reup.run_reup", return_value=None) as mock_run_reup,
        ):
            result = self.runner.invoke(main, [])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_run_reup.assert_called_once()

    def test_removed_legacy_runtime_flags_are_rejected(self) -> None:
        for flag in ("--desktop", "--legacy"):
            with self.subTest(flag=flag):
                result = self.runner.invoke(main, [flag])

            self.assertNotEqual(result.exit_code, 0, msg=result.output)
            self.assertIn("No such option", result.output)

    def test_resume_last_flag_enables_workspace_resume(self) -> None:
        config = self._config()
        with (
            patch("ite.main.ensure_workspace_layout", return_value=None),
            patch("ite.main.load_config", return_value=config),
            patch("ite.ui.reup.run_reup", return_value=None) as mock_run_reup,
        ):
            result = self.runner.invoke(main, ["--resume-last"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertTrue(config.resume_last_session)
        mock_run_reup.assert_called_once_with(config)

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

    def test_save_onboarding_settings_persists_completion_flag(self) -> None:
        system_dir = self.cwd / "system6"
        system_dir.mkdir(parents=True, exist_ok=True)

        with patch("ite.config.loader.get_config_dir", return_value=system_dir):
            save_onboarding_settings(completed=True)
            config = load_config(self.cwd)

        self.assertTrue(config.onboarding_completed)

    def test_config_uses_hostname_for_default_cloud_device_name(self) -> None:
        with patch("ite.config.config.socket.gethostname", return_value="My-MacBook-Pro.local"):
            config = Config(cwd=self.cwd)

        self.assertEqual(config.cloud_client_id, DEFAULT_CLOUD_CLIENT_ID)
        self.assertEqual(config.cloud_device_name, "My-MacBook-Pro.local")


if __name__ == "__main__":
    unittest.main()
