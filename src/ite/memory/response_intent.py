from __future__ import annotations

import re
from dataclasses import dataclass


def _normalize_text(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return " ".join(text.split())


@dataclass(frozen=True)
class ResponseIntent:
    query: str
    contexts: tuple[str, ...]
    requested_controls: dict[str, str]
    explicitly_wants_bullets: bool = False


_CONTEXT_PATTERNS: dict[str, tuple[str, ...]] = {
    "debugging": (
        "debug",
        "failing test",
        "error",
        "crash",
        "bug",
        "inspect",
        "check first",
        "stack trace",
        "exception",
        "leak",
        "why is",
        "broken",
        "fix this failure",
    ),
    "architecture": (
        "architecture",
        "architectural",
        "design",
        "system",
        "how .* interact",
        "session and memory handling",
        "codebase",
        "repo structure",
    ),
    "implementation": (
        "implement",
        "implementation",
        "build",
        "coding",
        "write the code",
        "make the change",
    ),
    "explanation": (
        "explain",
        "explanation",
        "walk me through",
        "tell me about",
        "what this codebase is about",
        "what this repo is about",
    ),
}

_DETAILED_REQUEST_PATTERNS: tuple[str, ...] = (
    "extensive",
    "extensively",
    "in detail",
    "detailed",
    "deep dive",
    "comprehensive",
    "step by step",
    "thorough",
    "thoroughly",
    "full breakdown",
    "tell me everything",
    "break it down",
)

_SHORT_REQUEST_PATTERNS: tuple[str, ...] = (
    "briefly",
    "short answer",
    "keep it short",
    "concise",
    "quick summary",
    "brief explanation",
)

_BULLET_REQUEST_PATTERNS: tuple[str, ...] = (
    "bullet",
    "bullets",
    "bullet list",
    "bullet lists",
    "as a list",
    "list them",
)


def resolve_response_intent(query: str | None) -> ResponseIntent:
    normalized = _normalize_text(query)
    contexts: list[str] = []

    for context, patterns in _CONTEXT_PATTERNS.items():
        for pattern in patterns:
            if _matches_pattern(normalized, pattern):
                contexts.append(context)
                break

    requested_controls: dict[str, str] = {}
    if any(_matches_pattern(normalized, pattern) for pattern in _DETAILED_REQUEST_PATTERNS):
        requested_controls["answer_length"] = "detailed"
    if any(_matches_pattern(normalized, pattern) for pattern in _SHORT_REQUEST_PATTERNS):
        requested_controls["answer_length"] = "short"
    if any(_matches_pattern(normalized, pattern) for pattern in _BULLET_REQUEST_PATTERNS):
        requested_controls["bullet_style"] = "helpful"

    return ResponseIntent(
        query=normalized,
        contexts=tuple(dict.fromkeys(contexts)),
        requested_controls=requested_controls,
        explicitly_wants_bullets="bullet" in normalized or "list" in normalized,
    )


def _matches_pattern(text: str, pattern: str) -> bool:
    if not text or not pattern:
        return False
    if ".*" in pattern:
        return re.search(pattern, text) is not None
    return pattern in text
