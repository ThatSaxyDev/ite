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
from ite.tools.builtin.apply_patch import ApplyPatchTool
from ite.tools.builtin.git_tools import GitBranchTool
from ite.tools.builtin.git_tools import GitCommitTool
from ite.tools.builtin.git_tools import GitDiffTool
from ite.tools.builtin.git_tools import GitLogTool
from ite.tools.builtin.git_tools import GitPushTool
from ite.tools.builtin.git_tools import GitRemoteTool
from ite.tools.builtin.git_tools import GitStatusTool
from ite.tools.builtin.json_tools import EditJsonTool
from ite.tools.builtin.json_tools import ReadJsonTool
from ite.tools.builtin.verification_tools import RunLinterTool
from ite.tools.builtin.verification_tools import RunTestsTool
from ite.tools.builtin.verification_tools import RunTypecheckTool

__all__ = [
    "ReadFileTool",
    "WriteFileTool",
    "EditTool",
    "ShellTool",
    "ApplyPatchTool",
    "ListDirTool",
    "GrepTool",
    "GlobTool",
    "WebSearchTool",
    "WebFetchTool",
    "TodosTool",
    "MemoryTool",
    "PlanQuestionTool",
    "GitStatusTool",
    "GitDiffTool",
    "GitLogTool",
    "GitBranchTool",
    "GitCommitTool",
    "GitPushTool",
    "GitRemoteTool",
    "ReadJsonTool",
    "EditJsonTool",
    "RunTestsTool",
    "RunLinterTool",
    "RunTypecheckTool",
]


def get_all_builtin_tools() -> list[type]:
    return [
        ReadFileTool,
        WriteFileTool,
        EditTool,
        ShellTool,
        ApplyPatchTool,
        ListDirTool,
        GrepTool,
        GlobTool,
        WebSearchTool,
        WebFetchTool,
        TodosTool,
        MemoryTool,
        PlanQuestionTool,
        GitStatusTool,
        GitDiffTool,
        GitLogTool,
        GitBranchTool,
        GitCommitTool,
        GitPushTool,
        GitRemoteTool,
        ReadJsonTool,
        EditJsonTool,
        RunTestsTool,
        RunLinterTool,
        RunTypecheckTool,
    ]
