import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ite.agent.agent import Agent
from ite.config.config import Config


class ExecutionTodoProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cwd = Path(self.temp_dir.name)
        self.agent = Agent(Config(cwd=self.cwd, api_key="test"))

    def test_should_refresh_execution_todos_for_completed_list(self) -> None:
        items = [
            {"content": "Implement requested changes", "completed": True},
            {"content": "Run verification checks (tests/lint/build as applicable)", "completed": True},
            {"content": "Summarize outcome and changed files", "completed": True},
        ]

        self.assertTrue(self.agent._should_refresh_execution_todos(items))

    def test_should_refresh_execution_todos_for_generic_stale_list(self) -> None:
        items = [
            {"content": "Implement requested changes", "completed": True},
            {"content": "Run verification checks (tests/lint/build as applicable)", "completed": False},
            {"content": "Summarize outcome and changed files", "completed": False},
        ]

        self.assertTrue(self.agent._should_refresh_execution_todos(items))

    def test_should_not_refresh_specific_pending_execution_todos(self) -> None:
        items = [
            {"content": "Update the first part of OVERVIEW.md", "completed": False},
            {"content": "Run markdown verification", "completed": False},
            {"content": "Summarize changed files", "completed": False},
        ]

        self.assertFalse(self.agent._should_refresh_execution_todos(items))
