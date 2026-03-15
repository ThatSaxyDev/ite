from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ExplicitMemoryInstruction:
    store: str
    key: str
    value: str
    source: str = "explicit_user_instruction"


def parse_explicit_memory_instruction(message: str) -> ExplicitMemoryInstruction | None:
    text = (message or "").strip()
    if not text:
        return None

    lowered = text.lower()

    if "do not remember" in lowered or "don't remember" in lowered:
        return None

    session_match = re.match(
        r"^\s*for this session only,\s*remember(?: that| this)?[:\s]+(.+?)\s*$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if session_match:
        value = _clean_value(session_match.group(1))
        if value:
            return ExplicitMemoryInstruction(
                store="short_term",
                key=_derive_key("session", value),
                value=value,
            )

    workspace_match = re.match(
        r"^\s*remember(?: this)? for this workspace[:\s]+(.+?)\s*$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if workspace_match:
        value = _clean_value(workspace_match.group(1))
        if value:
            return ExplicitMemoryInstruction(
                store="semantic",
                key=_derive_key("workspace", value),
                value=value,
            )

    from_now_on_match = re.match(
        r"^\s*from now on[,:\s]+(.+?)\s*$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if from_now_on_match:
        value = _clean_value(from_now_on_match.group(1))
        if value:
            return ExplicitMemoryInstruction(
                store="long_term",
                key=_derive_key("preference", value),
                value=value,
            )

    return None


def _clean_value(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip(".")


def _derive_key(prefix: str, value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not normalized:
        normalized = "note"
    parts = [part for part in normalized.split("_") if part][:8]
    return f"{prefix}_{'_'.join(parts)}"
