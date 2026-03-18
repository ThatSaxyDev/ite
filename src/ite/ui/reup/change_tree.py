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
        await self._expand_changed_paths(root)
        first_file_node = self._find_first_changed_file_node(self.root)
        if first_file_node is not None:
            self.select_node(first_file_node)
            self.move_cursor(first_file_node, animate=False)

    async def _expand_changed_paths(self, root: Path) -> None:
        directories = sorted(
            {path.parent.resolve() for path in self._changed_files},
            key=lambda path: len(path.parts),
        )
        for directory in directories:
            if directory == root:
                continue
            current = self.root
            try:
                rel_parts = directory.relative_to(root).parts
            except ValueError:
                continue
            for part in rel_parts:
                await self._add_to_load_queue(current)
                next_path = (current.data.path / part).resolve() if current.data is not None else None
                next_node = None
                for child in current.children:
                    data = getattr(child, "data", None)
                    path = getattr(data, "path", None)
                    if isinstance(path, Path) and next_path is not None and path.resolve() == next_path:
                        next_node = child
                        break
                if next_node is None:
                    break
                next_node.expand()
                current = next_node

    def _find_first_changed_file_node(self, node) -> object | None:
        for child in node.children:
            data = getattr(child, "data", None)
            path = getattr(data, "path", None)
            if isinstance(path, Path) and path.resolve() in self._changed_files:
                return child
            found = self._find_first_changed_file_node(child)
            if found is not None:
                return found
        return None

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        for path in paths:
            resolved = path.resolve()
            if path.is_dir():
                if resolved in self._visible_dirs:
                    yield path
            elif resolved in self._changed_files:
                yield path
