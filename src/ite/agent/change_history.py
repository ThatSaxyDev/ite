from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import uuid

from ite.tools.base import FileDiff
from ite.utils.paths import ensure_parent_dir


@dataclass
class ChangeSet:
    id: str
    label: str
    changes: list[FileDiff] = field(default_factory=list)

    def describe(self) -> str:
        files = len(self.changes)
        return f"{self.label} ({files} file{'s' if files != 1 else ''})"


class ChangeConflictError(RuntimeError):
    pass


class ChangeHistory:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self.undo_stack: list[ChangeSet] = []
        self.redo_stack: list[ChangeSet] = []
        self._pending_label: str | None = None
        self._pending_changes: list[FileDiff] = []

    def begin_batch(self, label: str) -> None:
        self._pending_label = label.strip() or "Apply changes"
        self._pending_changes = []

    def record_file_diffs(self, diffs: list[FileDiff]) -> None:
        seen: dict[str, FileDiff] = {}
        ordered: list[str] = []

        for diff in self._pending_changes:
            key = str(diff.path.resolve())
            if key not in seen:
                ordered.append(key)
                seen[key] = diff

        for diff in diffs:
            key = str(diff.path.resolve())
            if key in seen:
                existing = seen[key]
                seen[key] = FileDiff(
                    path=diff.path.resolve(),
                    old_content=existing.old_content,
                    new_content=diff.new_content,
                    is_new_file=existing.is_new_file,
                    is_deletion=diff.is_deletion,
                )
            else:
                ordered.append(key)
                seen[key] = FileDiff(
                    path=diff.path.resolve(),
                    old_content=diff.old_content,
                    new_content=diff.new_content,
                    is_new_file=diff.is_new_file,
                    is_deletion=diff.is_deletion,
                )

        self._pending_changes = [seen[key] for key in ordered]

    def finalize_batch(self) -> ChangeSet | None:
        if not self._pending_changes:
            self._pending_label = None
            return None

        change_set = ChangeSet(
            id=uuid.uuid4().hex[:8],
            label=self._pending_label or "Apply changes",
            changes=list(self._pending_changes),
        )
        self.undo_stack.append(change_set)
        self.redo_stack.clear()
        self._pending_changes = []
        self._pending_label = None
        return change_set

    def discard_pending_batch(self) -> None:
        self._pending_changes = []
        self._pending_label = None

    def history(self) -> list[ChangeSet]:
        return list(reversed(self.undo_stack))

    def undo(self, force: bool = False) -> ChangeSet:
        if not self.undo_stack:
            raise ChangeConflictError("Nothing to undo.")

        change_set = self.undo_stack.pop()
        try:
            self._apply_reverse(change_set, force=force)
        except Exception:
            self.undo_stack.append(change_set)
            raise
        self.redo_stack.append(change_set)
        return change_set

    def redo(self, force: bool = False) -> ChangeSet:
        if not self.redo_stack:
            raise ChangeConflictError("Nothing to redo.")

        change_set = self.redo_stack.pop()
        try:
            self._apply_forward(change_set, force=force)
        except Exception:
            self.redo_stack.append(change_set)
            raise
        self.undo_stack.append(change_set)
        return change_set

    def _apply_reverse(self, change_set: ChangeSet, *, force: bool) -> None:
        for diff in reversed(change_set.changes):
            self._ensure_expected_state(diff, forward=False, force=force)
            path = diff.path.resolve()
            if diff.is_new_file and not diff.is_deletion:
                if path.exists():
                    path.unlink()
                continue
            ensure_parent_dir(path)
            path.write_text(diff.old_content, encoding="utf-8")

    def _apply_forward(self, change_set: ChangeSet, *, force: bool) -> None:
        for diff in change_set.changes:
            self._ensure_expected_state(diff, forward=True, force=force)
            path = diff.path.resolve()
            if diff.is_deletion:
                if path.exists():
                    path.unlink()
                continue
            ensure_parent_dir(path)
            path.write_text(diff.new_content, encoding="utf-8")

    def _ensure_expected_state(self, diff: FileDiff, *, forward: bool, force: bool) -> None:
        if force:
            return

        path = diff.path.resolve()
        expected_exists = not diff.is_new_file if forward else not diff.is_deletion
        expected_content = diff.old_content if forward else diff.new_content

        if not expected_exists:
            if path.exists():
                raise ChangeConflictError(
                    f"Cannot apply change for {path}: expected file to be absent."
                )
            return

        if not path.exists():
            raise ChangeConflictError(
                f"Cannot apply change for {path}: file is missing."
            )

        current = path.read_text(encoding="utf-8")
        if current != expected_content:
            raise ChangeConflictError(
                f"Cannot apply change for {path}: file content has drifted."
            )


def file_diffs_from_tool_result(result: Any) -> list[FileDiff]:
    file_diffs = getattr(result, "file_diffs", None)
    if isinstance(file_diffs, list) and file_diffs:
        return [diff for diff in file_diffs if isinstance(diff, FileDiff)]

    single = getattr(result, "diff", None)
    if isinstance(single, FileDiff):
        return [single]

    metadata = getattr(result, "metadata", None)
    if not isinstance(metadata, dict):
        return []

    payloads = metadata.get("file_diff_payloads")
    if not isinstance(payloads, list):
        return []

    diffs: list[FileDiff] = []
    for payload in payloads:
        if isinstance(payload, dict):
            diffs.append(FileDiff.from_dict(payload))
    return diffs
