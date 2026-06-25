"""Convert iTE remote protocol frames to Telegram messages.

Handles: agent_event → text/progress, approval_request → inline keyboards,
plan_question_request → inline keyboards, plan_ready_request → inline keyboards.
"""
from __future__ import annotations

from typing import Any


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
    return text[:limit - 1].rstrip() + "…"


def format_agent_event(frame: dict[str, Any]) -> str | None:
    """Convert an agent_event frame to a Telegram MarkdownV2 message.

    Returns None for events that shouldn't produce a message (e.g. text_delta
    during streaming — those are handled by the streaming renderer).
    """
    event = frame.get("event") if isinstance(frame.get("event"), dict) else {}
    event_type = str(event.get("type") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}

    if event_type == "text_delta":
        return None  # handled by streaming

    if event_type == "text_complete":
        content = str(data.get("content") or "")
        if not content.strip():
            return None
        return escape_md(truncate(content))

    if event_type == "tool_call_start":
        name = str(data.get("name") or "tool")
        args = data.get("arguments")
        parts = [f"🔧 *{escape_md(name)}*"]
        if args:
            parts.append(f"```\n{escape_code(truncate(str(args), 800))}\n```")
        return "\n".join(parts)

    if event_type == "tool_call_progress":
        name = str(data.get("name") or "tool")
        output = str(data.get("output") or "")
        return f"⏳ *{escape_md(name)}*\n```\n{escape_code(truncate(output, 2000))}\n```"

    if event_type == "tool_call_complete":
        name = str(data.get("name") or "tool")
        success = data.get("success")
        if success is True:
            output = str(data.get("output") or "")
            if output.strip():
                return f"✅ *{escape_md(name)}*\n```\n{escape_code(truncate(output, 2000))}\n```"
            return f"✅ *{escape_md(name)}* completed"
        elif success is False:
            error = str(data.get("error") or data.get("output") or "failed")
            return f"❌ *{escape_md(name)}* failed\n```\n{escape_code(truncate(error, 2000))}\n```"
        return f"*{escape_md(name)}* finished"

    if event_type == "agent_error":
        error = str(data.get("error") or "Unknown runtime error")
        return f"⚠️ *Error*\n{escape_md(truncate(error))}"

    if event_type == "agent_start":
        message = str(data.get("message") or "Agent started")
        return f"_Agent started: {escape_md(truncate(message, 500))}_"

    if event_type in ("context_compacting", "context_compacted"):
        reason = str(data.get("trigger_reason") or data.get("message", ""))
        if reason:
            return f"_Context compacted: {escape_md(reason)}_"
        return "_Context compacted_"

    if event_type == "loop_detected":
        message = str(data.get("message") or "Retry loop detected")
        return f"🔄 *Loop detected*\n{escape_md(truncate(message))}"

    return None


def format_turn_boundary(
    last_turn_id: int | None,
    current_turn_id: int,
) -> str | None:
    """Return a turn separator if transitioning between turns."""
    if last_turn_id is not None and last_turn_id != current_turn_id:
        return "▬▬▬▬▬▬▬▬▬▬"
    return None
