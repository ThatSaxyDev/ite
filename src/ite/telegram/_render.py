"""Convert iTE agent events to Telegram MarkdownV2 messages.

Uses the same natural-language tool descriptions as the runtime TUI
(via ``ite.ui.tool_narrative``) so Telegram users never see raw tool
names or serialised arguments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from telegramify_markdown import markdownify as tg_markdownify

from ite.ui.tool_narrative import activity_title, describe_tool_activity, tool_icon


def escape_md(text: str) -> str:
    """Escape MarkdownV2 special characters for Telegram."""
    special = r"_*[]()~`>#+-=|{}.!"
    result = ""
    for ch in text:
        if ch in special:
            result += "\\" + ch
        else:
            result += ch
    return result


def escape_code(text: str) -> str:
    """Escape backticks inside inline code."""
    return text.replace("`", "\\`").replace("\\", "\\\\")


def truncate(text: str, limit: int = 3500) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


def format_agent_event(
    frame: dict[str, Any],
    *,
    stored_args: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    """Convert an agent event frame to a Telegram MarkdownV2 message.

    Returns ``None`` for events that are handled by the streaming renderer
    or should be suppressed entirely.
    """
    event = frame.get("event") if isinstance(frame.get("event"), dict) else {}
    event_type = str(event.get("type") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}

    # ── Handled by streaming; suppress TUI‑only events ──────────────
    if event_type in ("text_delta", "agent_start"):
        return None

    if event_type == "text_complete":
        content = str(data.get("content") or "")
        if not content.strip():
            return None
        return tg_markdownify(truncate(content))

    # ── Tool calls — use the same natural‑language helpers as the TUI ──
    if event_type == "tool_call_start":
        name = str(data.get("name") or "tool")
        args = data.get("arguments")
        if isinstance(args, dict):
            icon = tool_icon(name)
            title = activity_title(name, stage="start")
            narrative = describe_tool_activity(name, args, stage="start")
            return f"{icon} *{escape_md(title)}*\n_{escape_md(narrative)}_"
        return f"{tool_icon(name)} *{escape_md(name)}*"

    if event_type == "tool_call_complete":
        name = str(data.get("name") or "tool")
        call_id = str(data.get("call_id") or "")
        success = data.get("success")
        args = (stored_args or {}).get(call_id, {})

        if success is True:
            icon = tool_icon(name)
            title = activity_title(name, stage="complete", success=True)
            narrative = describe_tool_activity(
                name, args, stage="complete", success=True
            )
            return f"{icon} *{escape_md(title)}*\n_{escape_md(narrative)}_"

        if success is False:
            icon = tool_icon(name, success=False)
            title = activity_title(name, stage="complete", success=False)
            narrative = describe_tool_activity(
                name, args, stage="complete", success=False
            )
            error = str(data.get("error") or data.get("output") or "failed")
            return (
                f"{icon} *{escape_md(title)}*\n"
                f"_{escape_md(narrative)}_\n"
                f"`{escape_code(truncate(error, 500))}`"
            )

        return f"*{escape_md(name)}* finished"

    # ── Progress events are TUI‑only (live shell output) ────────────
    if event_type == "tool_call_progress":
        return None

    if event_type == "agent_error":
        error = str(data.get("error") or "Unknown runtime error")
        return f"\u26a0\ufe0f *Error*\n{escape_md(truncate(error))}"

    if event_type in ("context_compacting", "context_compacted"):
        reason = str(data.get("trigger_reason") or data.get("message", ""))
        if reason:
            return f"_Context compacted: {escape_md(reason)}_"
        return "_Context compacted_"

    if event_type == "loop_detected":
        message = str(data.get("message") or "Retry loop detected")
        return f"\U0001f504 *Loop detected*\n{escape_md(truncate(message))}"

    return None


def format_turn_boundary(
    last_turn_id: int | None,
    current_turn_id: int,
) -> str | None:
    """Return a turn separator if transitioning between turns."""
    if last_turn_id is not None and last_turn_id != current_turn_id:
        return "\u25ac\u25ac\u25ac\u25ac\u25ac\u25ac\u25ac\u25ac\u25ac\u25ac"
    return None


def format_change_summary(change_set: Any, *, cwd: Path) -> str | None:
    """Build a Telegram MarkdownV2 change summary for end-of-turn.

    Mirrors what the TUI shows in the "Changed" assistant card.
    Returns ``None`` if there are no changes to report.
    """
    from ite.agent.change_history import change_entries_with_stats
    from ite.ui.reup.change_views import change_entry_label

    diffs = list(getattr(change_set, "changes", []) or [])
    if not diffs:
        return None

    entries, extra = change_entries_with_stats(
        change_set,
        cwd=cwd,
        max_items=max(1, len(diffs)),
    )
    count = len(diffs)
    files_text = f"{count} file" if count == 1 else f"{count} files"

    lines: list[str] = []
    for idx, ((name, file_additions, file_deletions), diff) in enumerate(
        zip(entries, diffs[: len(entries)], strict=False)
    ):
        action_label, _ = change_entry_label(diff, mode="changed", is_light=False)
        parts = [f"  • `{escape_code(name)}`  _{action_label}_"]
        if file_additions:
            parts.append(f"`+{file_additions}`")
        if file_deletions:
            parts.append(f"`\\-{file_deletions}`")
        lines.append(" ".join(parts))

    if extra:
        lines.append(f"  _...and {extra} more file{'s' if extra != 1 else ''}_")

    body = "\n".join(lines)
    return f"\U0001f4dd *Changed {files_text}*\n\n{body}"
