import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.config.config import Config
from ite.prompts.system import _shell_command_available
from ite.prompts.system import get_system_prompt


class SystemPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)

    def test_system_prompt_prefers_grep_when_rg_unavailable_in_shell(self) -> None:
        config = Config(cwd=self.cwd, api_key="test")
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}, clear=False):
            _shell_command_available.cache_clear()
            with patch(
                "ite.prompts.system.subprocess.run",
                return_value=type("Result", (), {"returncode": 1})(),
            ):
                prompt = get_system_prompt(config)

        self.assertIn("prefer `grep` instead", prompt)
        self.assertIn("Otherwise use `grep` and `find` directly", prompt)

    def test_system_prompt_prefers_rg_when_available_in_shell(self) -> None:
        config = Config(cwd=self.cwd, api_key="test")
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}, clear=False):
            _shell_command_available.cache_clear()
            with patch(
                "ite.prompts.system.subprocess.run",
                return_value=type("Result", (), {"returncode": 0})(),
            ):
                prompt = get_system_prompt(config)

        self.assertIn("`rg` is available in the shell", prompt)
        self.assertIn("prefer `rg` / `rg --files` only when the environment says `rg` is available in the shell", prompt)


if __name__ == "__main__":
    unittest.main()
