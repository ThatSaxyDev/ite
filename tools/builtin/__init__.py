from tools.builtin.write_file import WriteFileTool
from tools.builtin.read_file import ReadFileTool

__all__ = [
    "ReadFileTool",
    "WriteFileTool",
]


def get_all_builtin_tools() -> list[type]:
    return [
        ReadFileTool,
        WriteFileTool,
    ]
