import tempfile
import unittest
from pathlib import Path

from ite.agent.agent import Agent
from ite.config.config import Config


class AgentToolRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config = Config(cwd=Path(self.temp_dir.name), api_key="test")
        self.agent = Agent(self.config)

    def test_suppresses_malformed_empty_shell_call(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "shell",
                ["Parameter 'command': Field required"],
            )
        )

    def test_suppresses_malformed_empty_read_call(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "read_file",
                ["Parameter 'path': Field required"],
            )
        )

    def test_suppresses_malformed_empty_media_read_calls(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "read_image",
                ["Parameter 'path': Field required"],
            )
        )
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "read_pdf",
                ["Parameter 'path': Field required"],
            )
        )

    def test_does_not_suppress_nonrequired_tool_errors(self) -> None:
        self.assertFalse(
            self.agent._should_suppress_malformed_tool_call(
                "shell",
                ["Parameter 'timeout': Input should be greater than or equal to 1"],
            )
        )

    def test_suppresses_malformed_empty_edit_call(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "edit",
                [
                    "Parameter 'path': Field required",
                    "Parameter 'new_string': Field required",
                ],
            )
        )

    def test_suppresses_malformed_empty_apply_patch_call(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "apply_patch",
                ["Parameter 'patch': Field required"],
            )
        )

    def test_suppresses_malformed_empty_memory_call(self) -> None:
        self.assertTrue(
            self.agent._should_suppress_malformed_tool_call(
                "memory",
                ["Parameter 'action': Field required"],
            )
        )
