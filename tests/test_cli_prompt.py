import unittest
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ite.config.config import Config
from ite.main import CLI


class CLIPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def _config(self) -> Config:
        return Config(cwd=self.cwd, api_key="test-key")

    def test_command_names_include_aliases(self) -> None:
        cli = CLI(self._config())

        names = cli._command_names()

        self.assertIn("/help", names)
        self.assertIn("/exit", names)
        self.assertIn("/quit", names)
        self.assertEqual(len(names), len(set(names)))

    def test_prompt_toolkit_reader_is_used_when_available(self) -> None:
        cli = CLI(self._config())

        class FakeSession:
            async def prompt_async(self, *_args, **_kwargs) -> str:
                return " /help "

        with patch.object(cli, "_get_prompt_session", return_value=FakeSession()):
            self.assertEqual(asyncio.run(cli._read_user_message()), "/help")

    def test_legacy_reader_fallback_still_works(self) -> None:
        cli = CLI(self._config())

        with (
            patch.object(cli, "_get_prompt_session", return_value=None),
            patch("builtins.input", return_value="/help"),
        ):
            self.assertEqual(asyncio.run(cli._read_user_message()), "/help")


if __name__ == "__main__":
    unittest.main()
