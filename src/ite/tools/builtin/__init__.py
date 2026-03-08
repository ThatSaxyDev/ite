from ite.tools.builtin.memory import MemoryTool
from ite.tools.builtin.plan_question import PlanQuestionTool
from ite.tools.builtin.todo import TodosTool
from ite.tools.builtin.web_fetch import WebFetchTool
from ite.tools.builtin.web_search import WebSearchTool
from ite.tools.builtin.glob import GlobTool
from ite.tools.builtin.grep import GrepTool
from ite.tools.builtin.list_dir import ListDirTool
from ite.tools.builtin.edit_file import EditTool
from ite.tools.builtin.write_file import WriteFileTool
from ite.tools.builtin.read_file import ReadFileTool
from ite.tools.builtin.shell import ShellTool

__all__ = [
    "ReadFileTool",
    "WriteFileTool",
    "EditTool",
    "ShellTool",
    "ListDirTool",
    "GrepTool",
    "GlobTool",
    "WebSearchTool",
    "WebFetchTool",
    "TodosTool",
    "MemoryTool",
    "PlanQuestionTool",
]


def get_all_builtin_tools() -> list[type]:
    return [
        ReadFileTool,
        WriteFileTool,
        EditTool,
        ShellTool,
        ListDirTool,
        GrepTool,
        GlobTool,
        WebSearchTool,
        WebFetchTool,
        TodosTool,
        MemoryTool,
        PlanQuestionTool,
    ]
