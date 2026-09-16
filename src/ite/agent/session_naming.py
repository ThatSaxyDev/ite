from __future__ import annotations

import re

MAX_SESSION_TITLE_CHARS = 60
MAX_SESSION_TITLE_WORDS = 8

_URL_RE = re.compile(r"https?://\S+")
_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?:the\s+)?(?:session\s+)?title\s*(?::|-|is\b|would\s+be\b)\s*",
    re.IGNORECASE,
)
_TRAILING_CONJUNCTION_RE = re.compile(
    r"\s+(?:and|or|but|so|because|while|when|with|for|to|the|a|an)$",
    re.IGNORECASE,
)
_LEADING_FILLER_RE = re.compile(
    r"^(?:hi|hey|hello|ok(?:ay)?|so|um|well|please|"
    r"can you|could you|would you|will you|"
    r"i want you to|i want to|i need you to|i need to|"
    r"i'd like you to|i'd like to|i would like you to|i would like to|"
    r"help me to|help me|let's|lets|"
    r"i did some work on|i did some work|i've been working on|"
    r"i have been working on|i was working on|i'm working on|"
    r"i am working on|i worked on|i've been|i have been|working on|"
    r"i was|i am|i'm|we are|we're)\b[\s,:\-]*",
    re.IGNORECASE,
)

_GENERIC_TITLES = {
    "new chat",
    "new thread",
    "new session",
    "untitled",
    "untitled thread",
    "coding help",
    "code help",
    "user request",
    "session title",
    "session",
    "conversation",
    "chat",
    "assistant",
    "help",
    "question",
    "request",
    "task",
    "general",
    "misc",
}


def sanitize_model_session_title(value: str) -> str:
    title = _normalize_text(value)
    title = _TITLE_PREFIX_RE.sub("", title).strip()
    if (
        (title.startswith('"') and title.endswith('"'))
        or (title.startswith("'") and title.endswith("'"))
    ):
        title = title[1:-1].strip()
    title = title.strip("\"'“”‘’").strip()
    title = re.sub(r"[.!?;:,]+$", "", title).strip()
    if not title or "\n" in title or len(title) > MAX_SESSION_TITLE_CHARS:
        return ""
    if len(title.split()) > MAX_SESSION_TITLE_WORDS:
        return ""
    lowered = title.lower()
    if lowered in _GENERIC_TITLES:
        return ""
    if "return only" in lowered or lowered.startswith("here is"):
        return ""
    return title


def build_fallback_session_title(value: str) -> str:
    """Deterministic, always-available title derived from the first user message.

    Used as a floor so a session is never shown as "Untitled thread" while the
    model title is being generated (or if it keeps failing). It is intentionally
    replaced by the model title as soon as one validates.
    """
    text = _normalize_text(value)
    if not text:
        return ""

    previous = None
    while previous != text:
        previous = text
        text = _LEADING_FILLER_RE.sub("", text).strip()

    first_clause = re.split(r"(?<=[.!?])\s+|\s+[-–—]\s+|\s*;\s*", text, maxsplit=1)[0].strip()
    if not first_clause:
        first_clause = text
    if len(first_clause) > MAX_SESSION_TITLE_CHARS:
        first_clause = first_clause[:MAX_SESSION_TITLE_CHARS].rsplit(" ", 1)[0].strip()
    first_clause = _TRAILING_CONJUNCTION_RE.sub("", first_clause).strip()
    first_clause = re.sub(r"[.!?,;:]+$", "", first_clause).strip()
    if not first_clause:
        return ""
    return first_clause[0].upper() + first_clause[1:]


def build_session_title_messages(
    context: dict[str, str],
    *,
    current_title: str | None = None,
) -> list[dict[str, str]]:
    """Build a small, single-line title request for the session's own model."""
    system = (
        "You name engineering chat sessions. You are given a digest of the session: "
        "the user's first request, a short summary of the answer, and the tools that "
        "were used. Reply with ONLY the title on a single line. Rules: 3 to 6 words; "
        "specific and concrete; name the actual task, system, file, or technology "
        "involved; no quotes; no end punctuation; no 'Title:' prefix; never use "
        "generic words like 'help', 'question', 'coding', or 'session'. Match the "
        "language of the user."
    )

    lines: list[str] = []

    def add(label: str, key: str, limit: int) -> None:
        value = " ".join(str(context.get(key) or "").split())
        if value:
            lines.append(f"{label}: {value[:limit]}")

    add("First request", "first_user", 300)
    add("Answer summary", "first_assistant", 400)
    add("Tools used", "first_turn_tools", 200)
    add("Latest request", "latest_user", 300)
    add("Current focus", "focus_hint", 200)
    add("Turns so far", "turn_count", 12)
    if current_title:
        lines.append(f"Current title: {current_title}")

    user = (
        "Here is the session context.\n\n"
        + "\n".join(lines)
        + "\n\nIf the current title already fits, repeat it exactly. "
        "Otherwise return the single best session title."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _normalize_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = _URL_RE.sub(" ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", " ")
    text = re.sub(r"[*_#>~]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
