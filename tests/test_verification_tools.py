import tempfile
import unittest
from pathlib import Path

from ite.config.config import Config
from ite.tools.base import ToolInvocation
from ite.tools.builtin.verification_tools import RunLinterTool
from ite.tools.builtin.verification_tools import RunTestsTool
from ite.tools.builtin.verification_tools import RunTypecheckTool
from ite.tools.registry import create_default_registry


class VerificationToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_tests_command_override_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tool = RunTestsTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(
                    params={"command": "python3 -m unittest tests.test_tool_narrative"},
                    cwd=Path("/Users/kiishidavid/Documents/Dev/Projects/ite"),
                )
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(result.metadata.get("command_kind"), "tests")
            self.assertIn("Ran", result.output)

    async def test_run_tests_autodetects_unittest_in_tests_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tests_dir = cwd / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_sample.py").write_text(
                "import unittest\n\n"
                "class Sample(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            tool = RunTestsTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(ToolInvocation(params={}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(
                result.metadata.get("command"),
                "python3 -m unittest discover -s tests",
            )

    async def test_run_linter_and_typecheck_support_command_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)

            linter = RunLinterTool(Config(cwd=cwd, api_key="test"))
            lint_result = await linter.execute(
                ToolInvocation(
                    params={"command": "python3 -c \"print('lint ok')\""},
                    cwd=cwd,
                )
            )
            self.assertTrue(lint_result.success, msg=lint_result.error)

            typecheck = RunTypecheckTool(Config(cwd=cwd, api_key="test"))
            type_result = await typecheck.execute(
                ToolInvocation(
                    params={"command": "python3 -c \"print('type ok')\""},
                    cwd=cwd,
                )
            )
            self.assertTrue(type_result.success, msg=type_result.error)

    async def test_run_linter_marks_missing_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            tool = RunLinterTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(
                    params={"command": "python3 -m definitely_missing_linter"},
                    cwd=cwd,
                )
            )

            self.assertFalse(result.success)
            self.assertEqual(result.metadata.get("missing_dependency"), True)
            self.assertEqual(result.metadata.get("missing_dependency_kind"), "python_module")
            self.assertEqual(result.metadata.get("missing_dependency_name"), "definitely_missing_linter")
            self.assertIn("Ask the user", result.metadata.get("recovery_hint", ""))

    async def test_verification_tools_are_registered(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            registry = create_default_registry(Config(cwd=cwd, api_key="test"))
            tool_names = {tool.name for tool in registry.get_tools()}

            self.assertTrue(
                {"run_tests", "run_linter", "run_typecheck"}.issubset(tool_names)
            )


if __name__ == "__main__":
    unittest.main()
