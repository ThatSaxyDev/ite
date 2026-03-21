from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text

from ite.agent.change_history import change_entries_with_stats


def change_entry_label(diff: Any, *, mode: str) -> tuple[str, str]:
    if mode == "undone":
        if getattr(diff, "is_new_file", False) and not getattr(diff, "is_deletion", False):
            return "deleted", "#ffb95f"
        if getattr(diff, "is_deletion", False):
            return "restored", "#4edea3"
        return "reverted", "#b7c8e1"

    if mode == "redone":
        if getattr(diff, "is_deletion", False):
            return "deleted", "#ffb95f"
        if getattr(diff, "is_new_file", False) and not getattr(diff, "is_deletion", False):
            return "created", "#4edea3"
        return "reapplied", "#b7c8e1"

    if getattr(diff, "is_deletion", False):
        return "deleted", "#ffb95f"
    if getattr(diff, "is_new_file", False):
        return "created", "#4edea3"
    return "updated", "#b7c8e1"


def build_change_card_body(
    change_set: Any,
    *,
    cwd: Path,
    verb: str,
    footer: str,
    mode: str,
) -> Text:
    diffs = list(getattr(change_set, "changes", []) or [])
    entries, _extra = change_entries_with_stats(
        change_set,
        cwd=cwd,
        max_items=max(1, len(diffs)),
    )
    count = len(diffs)
    files_text = f"{count} file" if count == 1 else f"{count} files"

    body = Text()
    for (name, additions, deletions), diff in zip(entries, diffs[: len(entries)], strict=False):
        action_label, action_color = change_entry_label(diff, mode=mode)
        body.append("• ", style="#7d8591")
        body.append(name, style="bold #edf1f7")
        body.append(f"  {action_label}", style=f"bold {action_color}")
        if mode == "changed" and (additions or deletions):
            if additions:
                body.append(f"  +{additions}", style="bold #4edea3")
            if deletions:
                body.append(f"  -{deletions}", style="bold #ffb95f")
        body.append("\n")
    if entries:
        body.append("\n")
    body.append(f"{verb} {files_text}.", style="#c6c6cd")
    body.append("\n")
    body.append(footer, style="#7d8591")
    return body
