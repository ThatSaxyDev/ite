from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import difflib
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "changes": [change.to_dict() for change in self.changes],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChangeSet":
        changes = payload.get("changes", [])
        return cls(
            id=str(payload.get("id", "")),
            label=str(payload.get("label", "Apply changes")),
            changes=[
                FileDiff.from_dict(change)
                for change in changes
                if isinstance(change, dict)
            ],
        )


class ChangeConflictError(RuntimeError):
    pass


class ChangeHistory:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self.undo_stack: list[ChangeSet] = []
        self.redo_stack: list[ChangeSet] = []
        self._pending_label: str | None = None
        self._pending_changes: list[FileDiff] = []
        self.last_turn_change_set: ChangeSet | None = None

    def begin_batch(self, label: str) -> None:
        self._pending_label = label.strip() or "Apply changes"
        self._pending_changes = []
        self.last_turn_change_set = None

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
            self.last_turn_change_set = None
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
        self.last_turn_change_set = change_set
        return change_set

    def discard_pending_batch(self) -> None:
        self._pending_changes = []
        self._pending_label = None
        self.last_turn_change_set = None

    def history(self) -> list[ChangeSet]:
        return list(reversed(self.undo_stack))

    def latest(self) -> ChangeSet | None:
        if not self.undo_stack:
            return None
        return self.undo_stack[-1]

    def export_state(self) -> dict[str, Any]:
        return {
            "undo_stack": [change.to_dict() for change in self.undo_stack],
            "redo_stack": [change.to_dict() for change in self.redo_stack],
        }

    def load_state(self, payload: dict[str, Any] | None) -> None:
        data = payload if isinstance(payload, dict) else {}
        undo_stack = data.get("undo_stack", [])
        redo_stack = data.get("redo_stack", [])
        self.undo_stack = [
            ChangeSet.from_dict(item)
            for item in undo_stack
            if isinstance(item, dict)
        ]
        self.redo_stack = [
            ChangeSet.from_dict(item)
            for item in redo_stack
            if isinstance(item, dict)
        ]
        self.last_turn_change_set = None

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
        self.last_turn_change_set = None
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
        self.last_turn_change_set = None
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


def compact_change_summary(
    change_set: ChangeSet | None,
    *,
    cwd: Path | None = None,
    max_items: int = 3,
) -> tuple[str, list[str], int]:
    if change_set is None:
        return "", [], 0

    names: list[str] = []
    base = cwd.resolve() if cwd else None
    for change in change_set.changes:
        path = change.path.resolve()
        label = path.name
        if base is not None:
            try:
                rel = path.relative_to(base)
                label = str(rel)
            except ValueError:
                label = path.name
        names.append(label)

    shown = names[:max_items]
    extra = max(0, len(names) - len(shown))
    summary = " · ".join(shown)
    if extra:
        summary = f"{summary} · +{extra} more" if summary else f"+{extra} more"
    return summary, shown, extra


def change_entries_with_stats(
    change_set: ChangeSet | None,
    *,
    cwd: Path | None = None,
    max_items: int = 3,
) -> tuple[list[tuple[str, int, int]], int]:
    if change_set is None:
        return [], 0

    base = cwd.resolve() if cwd else None
    entries: list[tuple[str, int, int]] = []
    for change in change_set.changes[:max_items]:
        path = change.path.resolve()
        label = path.name
        if base is not None:
            try:
                label = str(path.relative_to(base))
            except ValueError:
                label = path.name
        additions, deletions = _line_delta_stats(change)
        entries.append((label, additions, deletions))

    extra = max(0, len(change_set.changes) - len(entries))
    return entries, extra


def _line_delta_stats(change: FileDiff) -> tuple[int, int]:
    old_lines = change.old_content.splitlines()
    new_lines = change.new_content.splitlines()
    additions = 0
    deletions = 0
    for line in difflib.ndiff(old_lines, new_lines):
        if line.startswith("+ "):
            additions += 1
        elif line.startswith("- "):
            deletions += 1
    return additions, deletions


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
