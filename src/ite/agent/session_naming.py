from __future__ import annotations

import re

MAX_SESSION_TITLE_CHARS = 60

_URL_RE = re.compile(r"https?://\S+")


def sanitize_model_session_title(value: str) -> str:
    title = _normalize_text(value)
    if (
        (title.startswith('"') and title.endswith('"'))
        or (title.startswith("'") and title.endswith("'"))
    ):
        title = title[1:-1].strip()
    title = re.sub(r"[.!?;:,]+$", "", title).strip()
    if not title or "\n" in title or len(title) > MAX_SESSION_TITLE_CHARS:
        return ""
    if title.lower() in {
        "new chat",
        "new thread",
        "coding help",
        "user request",
        "session title",
    }:
        return ""
    return title


def _normalize_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = _URL_RE.sub(" ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", " ")
    text = re.sub(r"[*_#>~]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
