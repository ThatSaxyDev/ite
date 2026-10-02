"""Conventional Commit validation for AI-generated messages."""

from __future__ import annotations

import re

_SUBJECT = re.compile(
    r"(?:feat|fix|refactor|style|chore|docs|test|perf|ci|build|revert)"
    r"(?:\([^()\s]+\))?!?: \S[^\r\n]*"
)
FORMAT_ERROR = (
    "Use a Conventional Commit: type(scope): description, for example "
    "fix(ui): restore the offline badge. Scope is optional; add ! before "
    "the colon for a breaking change. Types: feat, fix, refactor, style, "
    "chore, docs, test, perf, ci, build, revert."
)


def validate_commit_message(message: str) -> str:
    """Return a trimmed message, rejecting subjects outside the generated format."""
    normalized = message.strip()
    lines = normalized.splitlines()
    if not lines or not _SUBJECT.fullmatch(lines[0]):
        raise ValueError(FORMAT_ERROR)
    if len(lines) > 1 and lines[1].strip():
        raise ValueError("Separate the commit subject and body with a blank line.")
    return normalized
