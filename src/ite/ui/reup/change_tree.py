from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.widgets import Tree


@dataclass(frozen=True)
class ChangeTreeNodeData:
    kind: str
    rel_path: str | None = None


class ChangedFilesTree(Tree[ChangeTreeNodeData]):
    """Git-aware tree grouped by staged and unstaged sections."""

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            Text("Files", style="bold #edf1f7"),
            data=ChangeTreeNodeData(kind="root"),
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self.show_root = False
        self.auto_expand = True

    def populate_groups(
        self,
        groups: list[tuple[str, list[str]]],
        *,
        selected_rel_path: str | None = None,
    ) -> str | None:
        self.clear()
        first_file_node = None
        selected_file_node = None

        for label, rel_paths in groups:
            if not rel_paths:
                continue
            group_node = self.root.add(
                Text(label, style="bold #b7c8e1"),
                data=ChangeTreeNodeData(kind="group"),
                expand=True,
            )
            directories: dict[tuple[str, ...], object] = {(): group_node}

            for rel_path in sorted(rel_paths):
                path = Path(rel_path)
                parent = group_node
                prefix: tuple[str, ...] = ()
                for part in path.parts[:-1]:
                    prefix = (*prefix, part)
                    existing = directories.get(prefix)
                    if existing is None:
                        existing = parent.add(
                            Text(part, style="#8c93a1"),
                            data=ChangeTreeNodeData(kind="dir"),
                            expand=True,
                        )
                        directories[prefix] = existing
                    parent = existing
                file_node = parent.add_leaf(
                    Text(path.name, style="bold #edf1f7"),
                    data=ChangeTreeNodeData(kind="file", rel_path=rel_path),
                )
                if first_file_node is None:
                    first_file_node = file_node
                if selected_rel_path and rel_path == selected_rel_path:
                    selected_file_node = file_node

        self.root.expand()
        target_node = selected_file_node or first_file_node
        if target_node is not None:
            self.select_node(target_node)
            self.move_cursor(target_node, animate=False)
            self.call_after_refresh(
                lambda: self.scroll_to(
                    x=self.max_scroll_x,
                    animate=False,
                    force=True,
                    immediate=True,
                )
            )
            return target_node.data.rel_path
        return None
