from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ite.tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from ite.utils.paths import resolve_path


class ListArchiveParams(BaseModel):
    path: str = Field(..., description="Path to a zip or tar archive to inspect.")
    limit: int = Field(
        200,
        ge=1,
        le=1000,
        description="Maximum number of entries to return.",
    )


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _list_zip_archive(path: Path, *, limit: int) -> tuple[str, dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        entries = []
        lines = [f"Archive: {path.name}", f"Format: zip", f"Entries: {len(infos)}", ""]
        for info in infos[:limit]:
            entry = {
                "path": info.filename,
                "size": info.file_size,
                "compressed_size": info.compress_size,
                "is_dir": info.is_dir(),
            }
            entries.append(entry)
            label = "dir" if info.is_dir() else _format_size(info.file_size)
            lines.append(f"{info.filename}  ({label})")
        if len(infos) > limit:
            lines.append(f"... {len(infos) - limit} more entries")
        return "\n".join(lines), {
            "archive_format": "zip",
            "entry_count": len(infos),
            "entries": entries,
        }


def _list_tar_archive(path: Path, *, limit: int) -> tuple[str, dict[str, Any]]:
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        entries = []
        lines = [f"Archive: {path.name}", f"Format: tar", f"Entries: {len(members)}", ""]
        for member in members[:limit]:
            entry = {
                "path": member.name,
                "size": member.size,
                "is_dir": member.isdir(),
            }
            entries.append(entry)
            label = "dir" if member.isdir() else _format_size(member.size)
            lines.append(f"{member.name}  ({label})")
        if len(members) > limit:
            lines.append(f"... {len(members) - limit} more entries")
        return "\n".join(lines), {
            "archive_format": "tar",
            "entry_count": len(members),
            "entries": entries,
        }


class ListArchiveTool(Tool):
    name = "list_archive"
    description = "Inspect a local zip or tar archive and list its entries."
    kind = ToolKind.READ
    schema = ListArchiveParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ListArchiveParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        sandbox_error = self._sandbox_check(path, invocation.cwd)
        if sandbox_error:
            return sandbox_error
        if not path.exists():
            return ToolResult.error_result(f"File not found: {path}")
        if not path.is_file():
            return ToolResult.error_result(f"Path is not a file: {path}")

        try:
            if zipfile.is_zipfile(path):
                output, metadata = _list_zip_archive(path, limit=params.limit)
            elif tarfile.is_tarfile(path):
                output, metadata = _list_tar_archive(path, limit=params.limit)
            else:
                return ToolResult.error_result(
                    f"Unsupported archive format: {path.name}. Expected zip or tar archive."
                )
        except Exception as exc:
            return ToolResult.error_result(
                f"Failed to inspect archive: {exc}",
                metadata={"path": str(path), "archive_error": True},
            )

        metadata["path"] = str(path)
        return ToolResult.success_result(output, metadata=metadata)
