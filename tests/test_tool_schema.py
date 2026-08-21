import unittest
from pathlib import Path

from ite.config.config import Config
from ite.tools.builtin.subagent_runtime_tools import SpawnSubagentsTool


class ToolSchemaTests(unittest.TestCase):
    def test_nested_pydantic_schema_keeps_defs_for_refs(self) -> None:
        tool = SpawnSubagentsTool(
            Config(cwd=Path.cwd(), api_key="test")
        )

        parameters = tool.to_openai_schema()["parameters"]
        requests_schema = parameters["properties"]["requests"]
        request_ref = requests_schema["items"]["$ref"]
        request_name = request_ref.removeprefix("#/$defs/")

        self.assertEqual(request_ref, "#/$defs/SpawnSubagentRequest")
        self.assertIn(request_name, parameters["$defs"])
        self.assertEqual(requests_schema["minItems"], 1)

