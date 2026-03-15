from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


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


def is_memory_probe(message: str) -> bool:
    text = _clean_value(message).lower()
    if not text:
        return False
    patterns = (
        "what phrase should you remember",
        "what should you remember",
        "what do you remember",
        "what did we decide last time",
        "what are we focused on right now",
    )
    return any(pattern in text for pattern in patterns)


def extract_preference_controls(message: str) -> dict[str, Any]:
    text = _clean_value(message).lower()
    if not text:
        return {}

    controls: dict[str, Any] = {}

    if any(phrase in text for phrase in ("keep answers short", "short answers", "concise answers")):
        controls["answer_length"] = "short"
    elif any(
        phrase in text
        for phrase in (
            "detailed answers",
            "more detail",
            "step-by-step answers",
            "detailed step-by-step answers",
            "verbose answers",
        )
    ):
        controls["answer_length"] = "detailed"

    if "avoid bullet lists" in text or "avoid bullets" in text:
        controls["bullet_style"] = "avoid"
    elif "bullet lists by default" in text or "use bullet lists by default" in text:
        controls["bullet_style"] = "default"
    elif "bullet lists when helpful" in text or "use bullet lists when helpful" in text:
        controls["bullet_style"] = "helpful"

    if "absolute file paths" in text:
        controls["file_paths"] = "absolute"

    if "step-by-step" in text:
        controls["explanation_style"] = "step_by_step"

    return controls


def should_reject_durable_memory_capture(store: str, value: str) -> bool:
    if store not in {"long_term", "semantic"}:
        return False

    text = _clean_value(value).lower()
    if not text:
        return True

    weak_markers = (
        "thinking out loud",
        "maybe ",
        "maybe,",
        "might ",
        "perhaps ",
        "or maybe not",
        "considering ",
        "i guess",
        "probably ",
        "not sure",
        "could use",
        "could be",
    )
    if any(marker in text for marker in weak_markers):
        return True

    if "?" in text:
        return True

    return False


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
