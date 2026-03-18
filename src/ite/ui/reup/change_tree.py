from __future__ import annotations

from pathlib import Path
from typing import Iterable

from textual.widgets import DirectoryTree


class ChangedFilesTree(DirectoryTree):
    """Directory tree filtered to only changed files and their parent folders."""

    def __init__(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        root = Path(path).resolve() if isinstance(path, str) else path.resolve()
        super().__init__(root, name=name, id=id, classes=classes, disabled=disabled)
        self._changed_files: set[Path] = set()
        self._visible_dirs: set[Path] = set()
        self.auto_expand = True

    async def set_changed_files(self, files: Iterable[Path]) -> None:
        root = Path(self.path).resolve() if isinstance(self.path, str) else self.path.resolve()
        changed_files = {Path(path).resolve() for path in files}
        visible_dirs: set[Path] = {root}
        for file_path in changed_files:
            current = file_path.parent
            while True:
                visible_dirs.add(current)
                if current == root or root not in current.parents:
                    break
                current = current.parent
        self._changed_files = changed_files
        self._visible_dirs = visible_dirs
        await self.reload()
        self.root.expand()

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        for path in paths:
            resolved = path.resolve()
            if path.is_dir():
                if resolved in self._visible_dirs:
                    yield path
            elif resolved in self._changed_files:
                yield path
