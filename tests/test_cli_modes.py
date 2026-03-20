import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from click.testing import CliRunner

from ite.config.config import Config
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

    def test_gui_precedence_over_reup(self) -> None:
        with (
            patch("ite.main.ensure_workspace_layout", return_value=None),
            patch("ite.main.load_config", return_value=self._config()),
            patch("ite.ui.gui.run_gui", return_value=None) as mock_run_gui,
            patch("ite.ui.reup.run_reup", return_value=None) as mock_run_reup,
        ):
            result = self.runner.invoke(main, ["--desktop", "--legacy"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_run_gui.assert_called_once()
        mock_run_reup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
