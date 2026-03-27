import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from rich.console import Console

from ite.commands import CommandContext
from ite.commands.info import _format_mcp_status_line, _tool_section_name, cmd_tools
from ite.config.config import Config
from ite.tools.builtin.read_file import ReadFileTool
from ite.tools.mcp.client import MCPToolInfo
from ite.tools.mcp.mcp_tool import MCPTool
from ite.tools.subagent import SubagentDefinition
from ite.tools.subagent import SubagentTool


class InfoCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_cmd_tools_groups_tools_by_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            console_output = io.StringIO()
            console = Console(file=console_output, force_terminal=False, width=160)

            builtin_tool = ReadFileTool(Config(cwd=cwd, api_key="test"))
            subagent_tool = SubagentTool(
                Config(cwd=cwd, api_key="test"),
                SubagentDefinition(
                    name="reviewer",
                    description="Reviews code.",
                    goal_prompt="Review code.",
                ),
            )
            mcp_tool = MCPTool(
                config=Config(cwd=cwd, api_key="test"),
                client=MagicMock(),
                tool_info=MCPToolInfo(
                    name="list_projects",
                    description="List projects in Vercel.",
                    annotations={"readOnlyHint": True},
                ),
                name="vercel__list_projects",
            )

            ctx = CommandContext(
                config=Config(cwd=cwd, api_key="test"),
                agent=SimpleNamespace(
                    session=SimpleNamespace(
                        tool_registry=SimpleNamespace(
                            get_tools=lambda: [builtin_tool, subagent_tool, mcp_tool]
                        )
                    )
                ),
                tui=SimpleNamespace(),
                console=console,
            )

            await cmd_tools(ctx, [])

            rendered = console_output.getvalue()
            self.assertIn("Built-in", rendered)
            self.assertIn("Subagent Specialists", rendered)
            self.assertIn("MCP Tools", rendered)
            self.assertIn("vercel", rendered)
            self.assertIn("1 tools", rendered)
            self.assertIn("list_projects", rendered)

    def test_tool_section_name_classifies_sources(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            builtin_tool = ReadFileTool(Config(cwd=cwd, api_key="test"))
            subagent_tool = SubagentTool(
                Config(cwd=cwd, api_key="test"),
                SubagentDefinition(
                    name="reviewer",
                    description="Reviews code.",
                    goal_prompt="Review code.",
                ),
            )
            mcp_tool = MCPTool(
                config=Config(cwd=cwd, api_key="test"),
                client=MagicMock(),
                tool_info=MCPToolInfo(name="list_projects", description="List projects."),
                name="vercel__list_projects",
            )

            class CustomTool(ReadFileTool):
                pass

            CustomTool.__module__ = "discovered_tool_demo"
            custom_tool = CustomTool(Config(cwd=cwd, api_key="test"))

            self.assertEqual(_tool_section_name(builtin_tool), "Built-in")
            self.assertEqual(_tool_section_name(subagent_tool), "Subagent Specialists")
            self.assertEqual(_tool_section_name(mcp_tool), "MCP")
            self.assertEqual(_tool_section_name(custom_tool), "Custom")

    def test_format_mcp_status_line_hides_transport_detail_for_connecting(self) -> None:
        rendered = _format_mcp_status_line("netlify", "connecting", "Connecting.")

        self.assertIn("netlify", rendered.plain)
        self.assertIn("connecting", rendered.plain)
        self.assertNotIn("stdio", rendered.plain)
        self.assertNotIn("⠋", rendered.plain)


if __name__ == "__main__":
    unittest.main()
