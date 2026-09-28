from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExplicitMemoryInstruction:
    store: str
    key: str
    value: str
    source: str = "explicit_user_instruction"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExactRecallProbe:
    kind: str


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


def parse_explicit_memory_instructions(message: str) -> list[ExplicitMemoryInstruction]:
    conditional = extract_conditional_preference_instructions(message)
    if conditional:
        return conditional

    single = parse_explicit_memory_instruction(message)
    return [single] if single is not None else []


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


def parse_exact_recall_probe(message: str) -> ExactRecallProbe | None:
    text = _clean_value(message).lower()
    if not text:
        return None

    if "what phrase should you remember for this session only" in text:
        return ExactRecallProbe(kind="session_phrase")

    return None


def is_query_anchored_to_key(query: str, key: str) -> bool:
    """Return True when the question plausibly refers to this memory's topic.

    The direct-answer shortcut answers *for* the model, so it must never fire on
    incidental substring overlap with a memory body. Memory keys are derived from
    the stored value, so requiring a distinctive query word to appear in the key
    keeps genuine single-fact recall working while rejecting accidental matches
    (for example, "git" matching inside "gitignored").
    """
    query_tokens = _topic_tokens(query)
    if not query_tokens:
        return False

    key_tokens = _topic_tokens(key)
    if not key_tokens:
        return False

    return any(
        query_token == key_token
        or key_token.startswith(query_token)
        or query_token.startswith(key_token)
        for query_token in query_tokens
        for key_token in key_tokens
    )


def _topic_tokens(value: str) -> list[str]:
    text = _clean_value(value).lower()
    return [token for token in re.findall(r"[a-z0-9]+", text) if len(token) >= 4]


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


def extract_conditional_preference_instructions(
    message: str,
) -> list[ExplicitMemoryInstruction]:
    text = _clean_value(message)
    if not text:
        return []

    if not re.match(
        r"^\s*(remember this preference|update that preference)[:\s]+",
        text,
        flags=re.IGNORECASE,
    ):
        return []

    remainder = re.sub(
        r"^\s*(remember this preference|update that preference)[:\s]+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if not remainder:
        return []

    instructions: list[ExplicitMemoryInstruction] = []
    clauses = [clause.strip() for clause in re.split(r"\s*;\s*", remainder) if clause.strip()]
    for clause in clauses:
        match = re.match(r"^\s*for\s+([^,]+),\s*(.+?)\s*$", clause, flags=re.IGNORECASE)
        if not match:
            continue
        condition = _normalize_condition(match.group(1))
        if not condition:
            continue
        body = _clean_value(match.group(2))
        controls = extract_preference_controls(body)
        if not controls:
            continue
        instructions.append(
            ExplicitMemoryInstruction(
                store="long_term",
                key=f"preference_{condition}",
                value=body,
                metadata={
                    "conditional_preferences": [
                        {
                            "condition": condition,
                            "controls": controls,
                            "raw": body,
                        }
                    ]
                },
            )
        )
    return instructions


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


def _normalize_condition(value: str) -> str | None:
    text = _clean_value(value).lower()
    if not text:
        return None

    if "debug" in text:
        return "debugging"
    if "architect" in text:
        return "architecture"
    if "implement" in text or "coding" in text or "build" in text:
        return "implementation"
    if "explain" in text or "explanation" in text:
        return "explanation"
    return None
