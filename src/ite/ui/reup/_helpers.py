"""Standalone helpers shared across mixins and app.py.
These cannot live in app.py because mixins import from here and app.py imports mixins.
"""
from __future__ import annotations

import ssl
from typing import Any

from textual.widget import Widget
from textual.widgets import Input, TextArea

_VOICE_TRANSIENT_ERROR_MARKERS = (
    "sslv3_alert_bad_record_mac",
    "ssl/tls alert bad record mac",
    "ssl: decryption_failed_or_bad_record_mac",
    "connection reset by peer",
    "remote end closed connection",
    "broken pipe",
    "incomplete chunked read",
    "timeout",
    "timed out",
    "temporary",
    "unavailable",
    "rate limit",
    "ratelimited",
    "overloaded",
    "capacity",
    "try again",
    "retry",
    "busy",
)


def _is_transient_voice_error(exc: BaseException) -> bool:
    """Check whether an exception is a transient network/SSL error worth retrying silently."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None:
        if id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return True
        current = current.__cause__ or current.__context__

    text = str(exc).lower()
    return any(marker in text for marker in _VOICE_TRANSIENT_ERROR_MARKERS)


def insert_voice_text_into_widget(widget: Widget, text: str) -> bool:
    if not text:
        return False
    if isinstance(widget, TextArea):
        widget.insert(text)
        return True
    if isinstance(widget, Input):
        widget.insert_text_at_cursor(text)
        return True
    return False


def redact_sensitive_command_text(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped:
        return ""
    lowered = stripped.lower()
    if lowered.startswith("/flow setup "):
        return "/flow setup [redacted]"
    if lowered.startswith("/voice setup "):
        return "/voice setup [redacted]"
    return stripped


def _skills_action_title(action: str) -> str:
    action_map = {
        "use": "Skill activated",
        "activate": "Skill activated",
        "drop": "Skill deactivated",
        "deactivate": "Skill deactivated",
        "clear": "Skills cleared",
        "trust": "Workspace trusted",
        "untrust": "Workspace untrusted",
        "add": "Skills installed",
    }
    return action_map.get(str(action or "").strip().lower(), "Skills update")
