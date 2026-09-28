"""Telegram inline keyboard builders for remote protocol approval requests."""
from __future__ import annotations

from typing import Any


def approval_keyboard(request_id: str) -> dict[str, Any]:
    """Build an InlineKeyboardMarkup for a tool approval request.

    Returns a dict suitable for passing to telegram.Bot.send_message(reply_markup=...).
    """
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve:{request_id}"},
                {"text": "❌ Deny", "callback_data": f"deny:{request_id}"},
            ]
        ]
    }


def plan_question_keyboard(
    request_id: str,
    options: list[str],
    recommended_index: int | None,
    allow_free_text: bool,
) -> dict[str, Any]:
    """Build an InlineKeyboardMarkup for a plan question.

    Each option is a button. If free text is allowed, a "Skip / Type answer" button is added.
    """
    keyboard: list[list[dict[str, Any]]] = []

    for i, option in enumerate(options):
        label = f"{'⭐ ' if i == recommended_index else ''}{option}"
        keyboard.append([
            {"text": label[:100], "callback_data": f"pq:{request_id}:{i}"}
        ])

    if allow_free_text:
        keyboard.append([
            {"text": "💬 Free text answer", "callback_data": f"pq_free:{request_id}"}
        ])

    return {"inline_keyboard": keyboard}


def plan_ready_keyboard(request_id: str) -> dict[str, Any]:
    """Build an InlineKeyboardMarkup for plan ready approval."""
    return {
        "inline_keyboard": [
            [
                {"text": "🚀 Implement", "callback_data": f"pr_yes:{request_id}"},
                {"text": "📝 Keep planning", "callback_data": f"pr_no:{request_id}"},
            ]
        ]
    }
