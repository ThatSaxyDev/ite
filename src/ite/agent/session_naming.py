from __future__ import annotations

import re
from collections.abc import Mapping

FALLBACK_SESSION_TITLE = "New thread"
MAX_SESSION_TITLE_CHARS = 60

_FILLER_PREFIX_RE = re.compile(
    r"^(?:hey|hi|hello|okay|ok|alright|so|please|pls|can you|could you|would you|"
    r"i need you to|i want you to|we need to|let'?s|help me|help us)\b[\s,.:;-]*",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://\S+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "this",
    "to",
    "we",
    "what",
    "why",
    "with",
    "you",
    "your",
}


def local_session_title(context: Mapping[str, object]) -> str:
    candidates = (
        str(context.get("focus_hint") or ""),
        str(context.get("latest_user") or ""),
        str(context.get("first_user") or ""),
    )
    for candidate in candidates:
        title = _title_from_text(candidate)
        if title:
            return title
    return FALLBACK_SESSION_TITLE


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


def _title_from_text(value: str) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    sentence = re.split(r"[.!?\n]", text, maxsplit=1)[0]
    previous = ""
    while sentence != previous:
        previous = sentence
        sentence = _FILLER_PREFIX_RE.sub("", sentence).strip()
    tokens = _TOKEN_RE.findall(sentence)
    words: list[str] = []
    for token in tokens:
        normalized = token.strip("._/-")
        if not normalized:
            continue
        if normalized.lower() in _STOPWORDS:
            continue
        if normalized.lower() in {"please", "thanks", "thank"}:
            continue
        words.append(_display_word(normalized))
        if len(words) >= 6:
            break
    while words and words[-1].lower() in _STOPWORDS:
        words.pop()
    title = " ".join(words).strip()
    if len(title) > MAX_SESSION_TITLE_CHARS:
        title = title[:MAX_SESSION_TITLE_CHARS].rsplit(" ", 1)[0].strip()
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


def _display_word(value: str) -> str:
    if value.lower() in {"api", "cli", "ui", "ux", "json", "sql", "http", "https"}:
        return value.upper()
    if value.isupper() or any(char.isdigit() for char in value):
        return value
    if any(char in value for char in "./_-"):
        return value
    return value[:1].upper() + value[1:]
