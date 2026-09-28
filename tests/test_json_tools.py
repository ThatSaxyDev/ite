import json
import tempfile
import unittest
from pathlib import Path

from ite.config.config import Config
from ite.tools.base import ToolInvocation
from ite.tools.builtin.json_tools import EditJsonTool
from ite.tools.builtin.json_tools import ReadJsonTool


class JsonToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_json_reads_nested_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            payload = {
                "scripts": {"test": "python3 -m unittest"},
                "name": "demo",
            }
            path = cwd / "package.json"
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            tool = ReadJsonTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(
                    params={"path": "package.json", "json_path": "scripts.test"},
                    cwd=cwd,
                )
            )

            self.assertTrue(result.success, msg=result.error)
            self.assertEqual(json.loads(result.output), "python3 -m unittest")

    async def test_edit_json_sets_nested_value(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            path = cwd / "package.json"
            path.write_text(
                json.dumps({"scripts": {"test": "old"}}, indent=2) + "\n",
                encoding="utf-8",
            )

            tool = EditJsonTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(
                    params={
                        "path": "package.json",
                        "json_path": "scripts.test",
                        "operation": "set",
                        "value": "new",
                    },
                    cwd=cwd,
                )
            )

            self.assertTrue(result.success, msg=result.error)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["scripts"]["test"], "new")

    async def test_edit_json_appends_to_array_with_create_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            path = cwd / "config.json"
            path.write_text(json.dumps({}, indent=2), encoding="utf-8")

            tool = EditJsonTool(Config(cwd=cwd, api_key="test"))
            result = await tool.execute(
                ToolInvocation(
                    params={
                        "path": "config.json",
                        "json_path": "items",
                        "operation": "append",
                        "value": "alpha",
                        "create_missing": True,
                    },
                    cwd=cwd,
                )
            )

            self.assertTrue(result.success, msg=result.error)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["items"], ["alpha"])


if __name__ == "__main__":
    unittest.main()
