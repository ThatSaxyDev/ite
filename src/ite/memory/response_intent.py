from __future__ import annotations

import re
from dataclasses import dataclass


def _normalize_text(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return " ".join(text.split())


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text)


def _stem(token: str) -> str:
    stem = token.lower().strip("'")
    if len(stem) <= 4:
        return stem
    for suffix in ("ingly", "edly", "ation", "ingly", "ments", "ment", "ingly", "ness", "fully", "fully", "able", "ible", "edly", "edly", "edly", "ing", "ers", "ies", "ied", "ed", "ly", "es", "s"):
        if stem.endswith(suffix) and len(stem) - len(suffix) >= 3:
            if suffix in {"ies", "ied"}:
                return stem[:-3] + "y"
            return stem[: -len(suffix)]
    return stem


def _phrase_count(text: str, phrases: tuple[str, ...]) -> int:
    return sum(1 for phrase in phrases if phrase in text)


@dataclass(frozen=True)
class ResponseIntent:
    query: str
    contexts: tuple[str, ...]
    requested_controls: dict[str, str]
    task_mode: str = "general"
    explicitly_wants_bullets: bool = False


_CONTEXT_TOKENS: dict[str, dict[str, float]] = {
    "debugging": {
        "debug": 1.6,
        "error": 1.5,
        "fail": 1.5,
        "crash": 1.5,
        "bug": 1.4,
        "trace": 1.2,
        "exception": 1.2,
        "inspect": 1.1,
        "check": 0.8,
        "leak": 1.5,
        "broken": 1.3,
        "fix": 0.8,
    },
    "architecture": {
        "architecture": 2.2,
        "architectur": 2.2,
        "design": 1.8,
        "system": 1.2,
        "structure": 1.2,
        "overview": 1.2,
        "interact": 1.3,
        "flow": 1.0,
        "repo": 0.9,
        "codebase": 1.0,
        "project": 0.8,
        "organize": 1.0,
        "layer": 1.1,
        "component": 1.0,
    },
    "implementation": {
        "implement": 2.0,
        "build": 1.8,
        "code": 1.0,
        "write": 0.8,
        "change": 0.9,
        "ship": 0.8,
        "add": 0.8,
        "create": 0.8,
    },
    "explanation": {
        "explain": 2.0,
        "walk": 1.0,
        "through": 0.8,
        "describe": 1.5,
        "tell": 0.9,
        "understand": 1.0,
        "about": 0.7,
        "mean": 0.7,
        "proper": 0.8,
    },
}

_CONTEXT_PHRASES: dict[str, tuple[str, ...]] = {
    "debugging": (
        "failing test",
        "check first",
        "stack trace",
        "why is this",
        "what broke",
        "what is broken",
    ),
    "architecture": (
        "big picture",
        "high level",
        "how this fits together",
        "session and memory handling",
        "how these parts interact",
        "what this codebase is about",
        "what this repo is about",
    ),
    "implementation": (
        "write the code",
        "make the change",
        "start building",
        "go implement",
    ),
    "explanation": (
        "walk me through",
        "tell me about",
        "help me understand",
    ),
}

_DETAILED_TOKENS: dict[str, float] = {
    "detail": 1.8,
    "detailed": 2.0,
    "extensive": 2.0,
    "thorough": 1.8,
    "comprehensive": 1.8,
    "proper": 1.2,
    "deep": 1.1,
    "full": 0.8,
    "complete": 0.9,
    "step": 0.8,
    "breakdown": 1.4,
    "overview": 0.9,
}

_DETAILED_PHRASES: tuple[str, ...] = (
    "in detail",
    "deep dive",
    "step by step",
    "tell me everything",
    "break it down",
    "end to end",
    "full breakdown",
    "big picture",
    "high level overview",
)

_SHORT_TOKENS: dict[str, float] = {
    "brief": 1.7,
    "briefly": 1.7,
    "short": 1.6,
    "concise": 1.8,
    "quick": 1.1,
    "gist": 1.4,
    "summary": 1.1,
}

_SHORT_PHRASES: tuple[str, ...] = (
    "short answer",
    "keep it short",
    "quick summary",
    "just the gist",
    "in brief",
)

_BULLET_PHRASES: tuple[str, ...] = (
    "bullet",
    "bullets",
    "bullet list",
    "bullet lists",
    "as a list",
    "list them",
)

_EXECUTION_PHRASES: tuple[str, ...] = (
    # Explicit action phrases - these unambiguously mean "implement now"
    "make the change",
    "write the code",
    "implement this",
    "fix this",
    "patch this",
    "update the code",
    "edit the file",
    "change the code",
    "build this",
    "finish the",
    "complete the",
    "go ahead",
    "go ahead and",
    "proceed with",
    "proceed to",
    "continue and",
    "continue to",
    "continue with",
    "let's implement",
    "lets implement",
    "let's fix",
    "lets fix",
    "let's build",
    "lets build",
    "let's add",
    "lets add",
    "let's update",
    "lets update",
    "let's edit",
    "lets edit",
    "please implement",
    "please fix",
    "please add",
    "please update",
    "please edit",
    "do it",
    "do that",
    "do this now",
    "do this",
    "apply the changes",
    "apply the fix",
    "apply changes",
    "apply fix",
    "get on with it",
    "get on with this",
    "move forward",
    "get this done",
    "make it so",
    "ship it",
    "can you implement",
    "can you fix",
    "can you add",
    "can you update",
    "can you edit",
    "help me implement",
    "help me fix",
    "help me add",
    "now implement",
    "now fix",
    "now add",
    "now update",
)

_READ_ONLY_PHRASES: tuple[str, ...] = (
    "read this",
    "tell me what is in",
    "tell me what's in",
    "what is in the codebase",
    "what's in the codebase",
    "summarize this file",
    "explain this file",
    "review this md file",
    "check on this",
    "check this",
    "check in the",
    "research",
    "investigate",
    "analyze the",
    "audit the",
    "investigate the",
    "find out about",
    "look into",
    "examine the",
)


def resolve_response_intent(query: str | None) -> ResponseIntent:
    normalized = _normalize_text(query)
    tokens = [_stem(token) for token in _tokenize(normalized)]
    contexts = _resolve_contexts(normalized, tokens)
    requested_controls = _resolve_requested_controls(normalized, tokens, contexts)
    task_mode = _resolve_task_mode(normalized, tokens, contexts)

    explicitly_wants_bullets = any(phrase in normalized for phrase in _BULLET_PHRASES)
    return ResponseIntent(
        query=normalized,
        contexts=contexts,
        requested_controls=requested_controls,
        task_mode=task_mode,
        explicitly_wants_bullets=explicitly_wants_bullets,
    )


def _resolve_contexts(text: str, tokens: list[str]) -> tuple[str, ...]:
    scores: dict[str, float] = {}
    for context in _CONTEXT_TOKENS:
        token_score = sum(_CONTEXT_TOKENS[context].get(token, 0.0) for token in tokens)
        phrase_score = _phrase_count(text, _CONTEXT_PHRASES.get(context, ())) * 1.6
        scores[context] = token_score + phrase_score

    contexts: list[str] = []
    for context, score in scores.items():
        threshold = 1.4 if context == "explanation" else 1.8
        if score >= threshold:
            contexts.append(context)

    # Questions about the repo/codebase/project explanation should also count as architecture.
    if "explanation" in contexts and any(token in tokens for token in ("codebase", "repo", "project")):
        if "architecture" not in contexts:
            contexts.append("architecture")

    return tuple(dict.fromkeys(contexts))


def _resolve_requested_controls(
    text: str,
    tokens: list[str],
    contexts: tuple[str, ...],
) -> dict[str, str]:
    requested: dict[str, str] = {}

    detailed_score = (
        sum(_DETAILED_TOKENS.get(token, 0.0) for token in tokens)
        + _phrase_count(text, _DETAILED_PHRASES) * 1.7
    )
    short_score = (
        sum(_SHORT_TOKENS.get(token, 0.0) for token in tokens)
        + _phrase_count(text, _SHORT_PHRASES) * 1.7
    )

    # Explanation or architecture requests without an explicit brevity cue should lean detailed.
    if ("architecture" in contexts or "explanation" in contexts) and short_score < 1.4:
        detailed_score += 0.9

    if detailed_score > short_score and detailed_score >= 1.3:
        requested["answer_length"] = "detailed"
    elif short_score > detailed_score and short_score >= 1.3:
        requested["answer_length"] = "short"

    if any(phrase in text for phrase in _BULLET_PHRASES):
        requested["bullet_style"] = "helpful"

    return requested


def _resolve_task_mode(
    text: str,
    tokens: list[str],
    contexts: tuple[str, ...],
) -> str:
    """Determine if user wants research-only or code execution.

    Defaults to "read_only" for safety. Only returns "execute" for explicit
    action phrases or high-confidence execution signals.
    """
    context_set = set(contexts)

    # Explicit read-only phrases take highest precedence
    if any(phrase in text for phrase in _READ_ONLY_PHRASES):
        return "read_only"

    # Explicit write phrases trigger execution
    if any(phrase in text for phrase in _EXECUTION_PHRASES):
        return "execute"

    # Architecture/explanation requests are research-only (unless overwritten by EXECUTION_PHRASES above)
    if "architecture" in context_set or "explanation" in context_set:
        return "read_only"

    # Read-only tokens require only one match to trigger
    read_only_tokens = {"read", "explain", "describe", "summarize", "overview", "understand", "check", "look", "find", "search", "audit", "analyze", "review", "investigate"}
    if any(token in read_only_tokens for token in tokens):
        return "read_only"

    # Execution tokens require TWO+ matches or strong context to trigger
    # This prevents false positives from single keywords like "fix" in research contexts
    imperative_execution_tokens = {"fix", "implement", "edit", "update", "change", "build", "add", "remove", "refactor", "patch", "write", "create", "delete"}
    execution_matches = sum(1 for token in tokens if token in imperative_execution_tokens)
    if execution_matches >= 2:
        return "execute"

    # "Implementation" context alone is not enough - needs explicit write phrase above
    if "implementation" in context_set:
        return "read_only"

    # "Debugging" context needs explicit action phrase or strong signal
    if "debugging" in context_set:
        # Debugging questions are research, "fix the bug" would trigger EXECUTION_PHRASES
        return "read_only"

    # Default to safe mode
    return "read_only"
