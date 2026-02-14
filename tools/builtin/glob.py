from utils.paths import is_binary_file
from pathlib import Path
import os
from utils.paths import resolve_path
from tools.base import ToolResult
from tools.base import ToolInvocation
from tools.base import ToolKind
from pydantic import BaseModel, Field
from tools.base import Tool


class GlobParams(BaseModel):
    pattern: str = Field(description="Glob pattern to match")
    path: str = Field(
        ".", description="Directory to search in (default: current directory)"
    )


class GlobTool(Tool):
    name = "glob"
    description = (
        "Find files matching a glob pattern. Supports ** for recursive matching"
    )
    kind = ToolKind.READ
    schema = GlobParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GlobParams(**invocation.params)

        search_path = resolve_path(invocation.cwd, params.path)

        if not search_path.exists() or not search_path.is_dir():
            return ToolResult.error_result(f"Path does not exist: '{search_path}'")

        try:
            matches = list(search_path.glob(params.pattern))
            matches = [match for match in matches if match.is_file()]
        except Exception as e:
            return ToolResult.error_result(f"Error searching for files: {e}")

        output_lines = []

        for file_path in matches[:1000]:
            try:
                relative_path = file_path.relative_to(invocation.cwd)
            except Exception:
                relative_path = file_path

            output_lines.append(str(relative_path))
        if len(matches) > 1000:
            output_lines.append(
                f"... limited to 1000 matches; ({len(matches) - 1000} more matches not shown)"
            )

        return ToolResult.success_result(
            "\n".join(output_lines),
            metadata={
                "path": str(search_path),
                "matches": len(matches),
            },
        )

    def _find_files(self, search_path: Path) -> list[Path]:
        files = []

        for root, dirs, filenames in os.walk(search_path):
            dirs[:] = [
                d
                for d in dirs
                if d
                not in {".git", ".venv", "__pycache__", "node_modules", ".git", "venv"}
            ]
            for filename in filenames:
                if filename.startswith("."):
                    continue

                file_path = Path(root) / filename

                if not is_binary_file(file_path):
                    files.append(file_path)
                    if len(files) >= 500:
                        return files

        return files
