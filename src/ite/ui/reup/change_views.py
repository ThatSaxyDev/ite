from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text

from ite.agent.change_history import change_entries_with_stats


def change_entry_label(diff: Any, *, mode: str, is_light: bool = False) -> tuple[str, str]:
    """Return (label, color) for a change entry, adapting to theme."""
    # Theme-aware colors
    if is_light:
        # Darker colors for light backgrounds
        created = "#2c7a55"
        deleted = "#9a6415"
        updated = "#38506a"
        restored = "#2c7a55"
        reapplied = "#38506a"
        reverted = "#38506a"
    else:
        # Original colors for dark backgrounds
        created = "#4edea3"
        deleted = "#ffb95f"
        updated = "#b7c8e1"
        restored = "#4edea3"
        reapplied = "#b7c8e1"
        reverted = "#b7c8e1"

    if mode == "undone":
        if getattr(diff, "is_new_file", False) and not getattr(diff, "is_deletion", False):
            return "deleted", deleted
        if getattr(diff, "is_deletion", False):
            return "restored", restored
        return "reverted", reverted

    if mode == "redone":
        if getattr(diff, "is_deletion", False):
            return "deleted", deleted
        if getattr(diff, "is_new_file", False) and not getattr(diff, "is_deletion", False):
            return "created", created
        return "reapplied", reapplied

    if getattr(diff, "is_deletion", False):
        return "deleted", deleted
    if getattr(diff, "is_new_file", False):
        return "created", created
    return "updated", updated


def build_change_card_body(
    change_set: Any,
    *,
    cwd: Path,
    verb: str,
    footer: str,
    mode: str,
    is_light: bool = False,
) -> Text:
    diffs = list(getattr(change_set, "changes", []) or [])
    entries, _extra = change_entries_with_stats(
        change_set,
        cwd=cwd,
        max_items=max(1, len(diffs)),
    )
    count = len(diffs)
    files_text = f"{count} file" if count == 1 else f"{count} files"

    # Theme-aware colors
    if is_light:
        fg = "#253243"
        muted = "#51657d"
        dim = "#6b7b8e"
        bullet = "#7d8591"
        additions = "#2c7a55"
        deletions = "#9a6415"
    else:
        fg = "#edf1f7"
        muted = "#d7deea"
        dim = "#8c93a1"
        bullet = "#7d8591"
        additions = "#4edea3"
        deletions = "#ffb95f"

    body = Text()
    for (name, file_additions, file_deletions), diff in zip(entries, diffs[: len(entries)], strict=False):
        action_label, action_color = change_entry_label(diff, mode=mode, is_light=is_light)
        body.append("• ", style=bullet)
        body.append(name, style=f"bold {fg}")
        body.append(f"  {action_label}", style=f"bold {action_color}")
        if mode == "changed" and (file_additions or file_deletions):
            if file_additions:
                body.append(f"  +{file_additions}", style=f"bold {additions}")
            if file_deletions:
                body.append(f"  -{file_deletions}", style=f"bold {deletions}")
        body.append("\n")
    if entries:
        body.append("\n")
    body.append(f"{verb} {files_text}.", style=muted)
    body.append("\n")
    body.append(footer, style=dim)
    return body


def build_change_card_payload(
    change_set: Any,
    *,
    cwd: Path,
    title: str,
    verb: str,
    footer: str,
    mode: str,
) -> dict[str, Any]:
    diffs = list(getattr(change_set, "changes", []) or [])
    entries, _extra = change_entries_with_stats(
        change_set,
        cwd=cwd,
        max_items=max(1, len(diffs)),
    )

    items: list[dict[str, Any]] = []
    for (name, file_additions, file_deletions), diff in zip(
        entries, diffs[: len(entries)], strict=False
    ):
        action_label, _ = change_entry_label(diff, mode=mode)
        items.append(
            {
                "path": name,
                "action": action_label,
                "additions": int(file_additions),
                "deletions": int(file_deletions),
            }
        )

    return {
        "title": title,
        "verb": verb,
        "footer": footer,
        "mode": mode,
        "count": len(diffs),
        "items": items,
    }
