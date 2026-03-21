import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from ite.config.config import Config
from ite.tools.base import ToolInvocation
from ite.tools.builtin.config_tools import ReadEnvTool
from ite.tools.builtin.config_tools import ReadTomlTool
from ite.tools.builtin.config_tools import ReadYamlTool
from ite.tools.builtin.config_tools import WriteEnvTool
from ite.tools.builtin.config_tools import WriteTomlTool
from ite.tools.builtin.config_tools import WriteYamlTool
from ite.tools.registry import create_default_registry


class ConfigToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_toml_reads_nested_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            path = cwd / "pyproject.toml"
            path.write_text('[project]\nname = "demo"\n', encoding="utf-8")

            tool = ReadTomlTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(params={"path": "pyproject.toml", "key_path": "project.name"}, cwd=cwd)
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(json.loads(result.output), "demo")

    async def test_write_toml_sets_nested_value(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            path = cwd / "pyproject.toml"
            path.write_text('[project]\nname = "demo"\n', encoding="utf-8")

            tool = WriteTomlTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(
                    params={
                        "path": "pyproject.toml",
                        "key_path": "project.version",
                        "operation": "set",
                        "value": "0.1.0",
                        "create_missing": True,
                    },
                    cwd=cwd,
                )
            )

            self.assertTrue(result.success, msg=result.error)
            text = path.read_text(encoding="utf-8")
            self.assertIn('version = "0.1.0"', text)

    async def test_read_env_reads_whole_document(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            path = cwd / ".env"
            path.write_text("API_KEY=test-key\nDEBUG=true\n", encoding="utf-8")

            tool = ReadEnvTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(ToolInvocation(params={"path": ".env"}, cwd=cwd))

            self.assertTrue(result.success, msg=result.error)
            payload = json.loads(result.output)
            self.assertEqual(payload["API_KEY"], "test-key")
            self.assertEqual(payload["DEBUG"], "true")

    async def test_write_env_preserves_comments_and_updates_value(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            path = cwd / ".env"
            path.write_text("# local config\nAPI_KEY=old\n", encoding="utf-8")

            tool = WriteEnvTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(
                    params={"path": ".env", "key": "API_KEY", "operation": "set", "value": "new value"},
                    cwd=cwd,
                )
            )

            self.assertTrue(result.success, msg=result.error)
            text = path.read_text(encoding="utf-8")
            self.assertIn("# local config", text)
            self.assertIn('API_KEY="new value"', text)

    async def test_config_tools_are_registered(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            registry = create_default_registry(Config(cwd=cwd, api_key="test"))
            tool_names = {tool.name for tool in registry.get_tools()}

            self.assertTrue(
                {"read_toml", "write_toml", "read_env", "write_env", "read_yaml", "write_yaml"}.issubset(tool_names)
            )

    @unittest.skipUnless(importlib.util.find_spec("yaml") is not None, "PyYAML not installed")
    async def test_read_yaml_reads_nested_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            path = cwd / "ci.yaml"
            path.write_text("jobs:\n  build:\n    steps:\n      - name: test\n", encoding="utf-8")

            tool = ReadYamlTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(params={"path": "ci.yaml", "key_path": "jobs.build.steps[0].name"}, cwd=cwd)
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(json.loads(result.output), "test")

    @unittest.skipUnless(importlib.util.find_spec("yaml") is not None, "PyYAML not installed")
    async def test_write_yaml_sets_nested_value(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            path = cwd / "compose.yaml"
            path.write_text("services:\n  api:\n    image: demo:old\n", encoding="utf-8")

            tool = WriteYamlTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(
                    params={
                        "path": "compose.yaml",
                        "key_path": "services.api.image",
                        "operation": "set",
                        "value": "demo:new",
                        "create_missing": True,
                    },
                    cwd=cwd,
                )
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertIn("demo:new", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
