from __future__ import annotations

import json
from typing import Any

from ite.integrations.open_island.terminal import TerminalContext

# The bridge resolves `hook_source` -> AgentTool and falls back to `.claudeCode`
# for anything unrecognised. We send "claude" explicitly so the behaviour is
# pinned rather than relying on that default if upstream changes it.
HOOK_SOURCE = "claude"

# Payload size guard. Tool output can be enormous; Open Island only renders a
# preview, and an unbounded payload risks a slow or rejected write.
MAX_FIELD_CHARS = 4_000


def _truncate(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= MAX_FIELD_CHARS:
        return value
    return value[:MAX_FIELD_CHARS] + "…[truncated]"


def _stringify(value: Any) -> Any:
    """Coerce a tool argument value into something JSON-encodable."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _stringify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify(item) for item in value]
    return str(value)


# Open Island builds its activity summary by picking the first recognised key
# from this list (ClaudeHooks.swift `toolInputPreview`) and falling back to
# serialising the *entire* JSON object when nothing matches.
#
# iTE uses different names for the same concepts, so an unnormalised payload
# renders as a raw blob: `Running read_file: {"path":"src/ite/...",...}`
# instead of `Running read_file: src/ite/...`.
PREVIEW_KEY_PRIORITY = (
    "command",
    "file_path",
    "pattern",
    "query",
    "prompt",
    "description",
    "skill",
    "url",
)

# iTE argument name -> the name Open Island recognises.
_ARG_KEY_ALIASES = {
    "path": "file_path",
    "filepath": "file_path",
    "file": "file_path",
    "target": "file_path",
    "cmd": "command",
    "glob": "pattern",
    "regex": "pattern",
}

# When *no* argument is already recognised, at most one alias is promoted, and
# in this order — most descriptive of the action first. Promoting more than one
# would let a higher-priority key hide the meaningful one.
_PROMOTION_PREFERENCE = ("command", "pattern", "file_path")


def normalize_tool_input(arguments: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rename iTE argument keys to the names Open Island can render.

    Applied uniformly to every event that carries tool input so that the
    ``PermissionRequest`` correlation key (which hashes the serialised input)
    stays stable across ``PreToolUse`` and the permission round trip.

    Deliberately conservative: if the payload already contains a key upstream
    recognises, aliases are left untouched. Otherwise ``grep {pattern, path}``
    would promote ``path`` to ``file_path``, which outranks ``pattern`` in
    upstream's list and would hide the search term the user wants to see.
    """
    if not arguments:
        return arguments

    normalized = dict(_stringify(arguments))

    if any(key in PREVIEW_KEY_PRIORITY for key in normalized):
        return normalized

    for preferred in _PROMOTION_PREFERENCE:
        for alias, canonical in _ARG_KEY_ALIASES.items():
            if canonical != preferred or alias not in normalized:
                continue
            value = normalized.pop(alias)
            normalized[canonical] = value
            return normalized

    return normalized


def summary_preview(tool_name: str, tool_input: dict[str, Any] | None) -> str:
    """Return the activity summary Open Island will display for a tool call.

    Mirrors the upstream ``preToolUse`` rendering so the exact user-visible
    string can be asserted in tests and printed by the demo, rather than
    requiring a screenshot to verify.
    """
    summary = f"Running {tool_name}"
    if not isinstance(tool_input, dict):
        return summary

    for key in PREVIEW_KEY_PRIORITY:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return f"{summary}: {value}"

    # Mirrors the upstream fallback, which serialises the *entire* object.
    # This is the ugly rendering that normalize_tool_input exists to avoid.
    try:
        return f"{summary}: {json.dumps(tool_input, separators=(',', ':'))}"
    except (TypeError, ValueError):
        return summary


def _base(
    event_name: str,
    session_id: str,
    cwd: str,
    terminal: TerminalContext | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "cwd": cwd,
        "hook_event_name": event_name,
        "session_id": session_id,
        "hook_source": HOOK_SOURCE,
    }
    if terminal is not None:
        payload.update(terminal.as_payload_fields())
    return payload


def session_start(
    session_id: str,
    cwd: str,
    terminal: TerminalContext | None = None,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    payload = _base("SessionStart", session_id, cwd, terminal)
    payload["source"] = "startup"
    if model:
        payload["model"] = model
    return payload


def user_prompt_submit(
    session_id: str,
    cwd: str,
    prompt: str,
    terminal: TerminalContext | None = None,
) -> dict[str, Any]:
    payload = _base("UserPromptSubmit", session_id, cwd, terminal)
    payload["prompt"] = _truncate(prompt)
    return payload


def pre_tool_use(
    session_id: str,
    cwd: str,
    tool_name: str,
    tool_input: dict[str, Any] | None,
    tool_use_id: str | None,
    terminal: TerminalContext | None = None,
) -> dict[str, Any]:
    payload = _base("PreToolUse", session_id, cwd, terminal)
    payload["tool_name"] = tool_name
    if tool_input is not None:
        payload["tool_input"] = normalize_tool_input(tool_input)
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    return payload


def post_tool_use(
    session_id: str,
    cwd: str,
    tool_name: str,
    tool_input: dict[str, Any] | None,
    tool_use_id: str | None,
    *,
    output: str | None,
    success: bool,
    error: str | None = None,
    terminal: TerminalContext | None = None,
) -> dict[str, Any]:
    failed = not success
    event_name = "PostToolUseFailure" if failed else "PostToolUse"
    payload = _base(event_name, session_id, cwd, terminal)
    payload["tool_name"] = tool_name
    if tool_input is not None:
        payload["tool_input"] = normalize_tool_input(tool_input)
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    if output is not None:
        payload["tool_response"] = _truncate(output)
    if failed:
        payload["error"] = _truncate(error) or f"{tool_name} failed"
    return payload


def stop(
    session_id: str,
    cwd: str,
    terminal: TerminalContext | None = None,
    *,
    last_assistant_message: str | None = None,
) -> dict[str, Any]:
    payload = _base("Stop", session_id, cwd, terminal)
    if last_assistant_message:
        payload["last_assistant_message"] = _truncate(last_assistant_message)
    return payload


def stop_failure(
    session_id: str,
    cwd: str,
    error: str,
    terminal: TerminalContext | None = None,
) -> dict[str, Any]:
    payload = _base("StopFailure", session_id, cwd, terminal)
    payload["error"] = _truncate(error)
    return payload


def session_end(
    session_id: str,
    cwd: str,
    terminal: TerminalContext | None = None,
    *,
    is_interrupt: bool = False,
) -> dict[str, Any]:
    payload = _base("SessionEnd", session_id, cwd, terminal)
    if is_interrupt:
        payload["is_interrupt"] = True
    return payload


def pre_compact(
    session_id: str,
    cwd: str,
    terminal: TerminalContext | None = None,
) -> dict[str, Any]:
    return _base("PreCompact", session_id, cwd, terminal)


def command(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a hook payload in the `processClaudeHook` bridge command."""
    return {"type": "processClaudeHook", "claudeHook": payload}


def serialize_tool_input(arguments: dict[str, Any] | None) -> str | None:
    """Render tool arguments deterministically for correlation purposes.

    Open Island correlates `PermissionRequest` against the preceding
    `PreToolUse` using `sessionID|toolName|serializedToolInput`. Both events
    must serialise identically or the correlation silently fails.
    """
    if arguments is None:
        return None
    try:
        normalized = normalize_tool_input(arguments)
        return json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
