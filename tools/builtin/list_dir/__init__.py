from utils.paths import resolve_path
from tools.base import ToolResult
from tools.base import ToolInvocation
from tools.base import ToolKind
from pydantic import BaseModel, Field
from tools.base import Tool


class ListDirParams(BaseModel):
    path: str = Field(
        ".", description="Directory path to list (default: current directory)"
    )
    include_hidden: bool = Field(
        False,
        description="Whether to include hidden files and directories (default: false",
    )


class ListDirTool(Tool):
    name = "list_dir"
    description = "List the contents of a directory."
    kind = ToolKind.READ
    schema = ListDirParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ListDirParams(**invocation.params)

        dir_path = resolve_path(invocation.cwd, params.path)

        if not dir_path.exists() or not dir_path.is_dir():
            return ToolResult.error_result(f"Directory: '{dir_path}' does not exist.")

        try:
            items = sorted(
                dir_path.iterdir(),
                key=lambda p: (
                    not p.is_dir(),
                    p.name.lower(),
                ),
            )
        except Exception as e:
            return ToolResult.error_result(f"Error listing directory: {e}")

        if not params.include_hidden:
            items = [item for item in items if not item.name.startswith(".")]

        if not items:
            return ToolResult.success_result(
                f"Directory: '{dir_path}' is empty.",
                metadata={
                    "path": dir_path,
                    "entries": 0,
                },
            )

        lines = []
        for item in items:
            if item.is_dir():
                lines.append(f"🗂️ {item.name}/")
            else:
                lines.append(f"📄 {item.name}")

        content = "\n".join(lines)

        return ToolResult.success_result(
            content,
            metadata={
                "path": str(dir_path),
                "entries": len(items),
            },
        )
