from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Sequence
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


def has_renderable_preview(normalized: dict[str, Any] | None) -> bool:
    """Return True when Open Island can render a preview from this input.

    Upstream returns the first *string* value among `PREVIEW_KEY_PRIORITY`. If
    none qualifies it falls back to serialising the entire object
    (`ClaudeHooks.swift:1126-1150`), which is how raw JSON such as
    ``{limit: 10}`` reached the UI.

    Non-string recognised keys do not count: upstream's `stringValue` only
    yields text for `.string`, and `toolInputPreview` skips empty values.
    """
    if not isinstance(normalized, dict):
        return False

    for key in PREVIEW_KEY_PRIORITY:
        value = normalized.get(key)
        if isinstance(value, str) and value:
            return True
    return False


def normalize_tool_input(arguments: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rename iTE argument keys to the names Open Island can render.

    Applied uniformly to every event that carries tool input so that the
    ``PermissionRequest`` correlation key (which hashes the serialised input)
    stays stable across ``PreToolUse`` and the permission round trip.

    Deliberately conservative: if the payload already contains a key upstream
    recognises, aliases are left untouched. Otherwise ``grep {pattern, path}``
    would promote ``path`` to ``file_path``, which outranks ``pattern`` in
    upstream's list and would hide the search term the user wants to see.

    Returns ``None`` when nothing is renderable, which makes the caller omit
    ``tool_input`` entirely. That is the important behaviour: omitting it leaves
    the island showing just the humanised tool name, whereas sending an
    unrenderable object makes the island dump raw JSON into the UI
    (e.g. ``$ {limit: 10}`` for ``git_log``). Never leak internals to users.
    """
    if not arguments:
        return None

    normalized = dict(_stringify(arguments))

    if has_renderable_preview(normalized):
        return normalized

    for preferred in _PROMOTION_PREFERENCE:
        for alias, canonical in _ARG_KEY_ALIASES.items():
            if canonical != preferred or alias not in normalized:
                continue
            value = normalized.pop(alias)
            normalized[canonical] = value
            if has_renderable_preview(normalized):
                return normalized
            # Promotion did not yield text (e.g. a non-string value); put it
            # back and keep looking rather than shipping a half-rename.
            normalized.pop(canonical, None)
            normalized[alias] = value

    return None


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

    # Only send input the island can actually render. Anything else makes it
    # dump raw JSON into the UI; omitting it leaves the humanised tool name.
    normalized = normalize_tool_input(tool_input)
    if normalized is not None:
        payload["tool_input"] = normalized

    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    return payload


def post_tool_use(
    session_id: str,
    cwd: str,
    tool_name: str,
    tool_use_id: str | None,
    *,
    output: str | None,
    success: bool,
    error: str | None = None,
    terminal: TerminalContext | None = None,
) -> dict[str, Any]:
    """Build the completion payload.

    Deliberately carries **no** ``tool_input``. Upstream clears its
    ``currentToolInputPreview`` only when an update omits it
    (`BridgeServer.swift:2888-2903`), so omitting it here is what stops the
    finished tool's preview bleeding into the next reasoning label — otherwise
    a rotated gerund would render as ``Mulling config/loader.py``.
    """
    failed = not success
    event_name = "PostToolUseFailure" if failed else "PostToolUse"
    payload = _base(event_name, session_id, cwd, terminal)
    payload["tool_name"] = tool_name
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


# ---------------------------------------------------------------------------
# Activity wording
#
# iTE names each phase of a turn ("Brewing", "Reading file", "Searching code")
# and shows that wording in its own TUI. The island has no free-text activity
# field: its running-status line is derived *solely* from the session's
# `currentTool` (see `island_status_text` below and plan §3.8).
#
# So the only way to surface iTE's wording is to carry it on `tool_name` of a
# `PreToolUse` payload. The helpers in this section build and verify that.
# ---------------------------------------------------------------------------

_ACRONYMS = frozenset({"API", "CI", "ID", "PR", "URL"})


def humanized_tool_name(tool_name: str) -> str:
    """Mirror upstream `currentToolDisplayName`'s fallback humanisation.

    `open-vibe-island/Sources/OpenIslandApp/AgentSession+Presentation.swift:415-430`
    """
    trimmed = tool_name.strip()
    pieces = [piece for piece in trimmed.lstrip("_").split("_") if piece]

    rendered: list[str] = []
    for piece in pieces:
        upper = piece.upper()
        if upper in _ACRONYMS:
            rendered.append(upper)
        else:
            rendered.append(piece[:1].upper() + piece[1:].lower())

    label = " ".join(rendered)
    return label or tool_name


def island_status_text(hook_payload: dict[str, Any]) -> str:
    """Render the island's running-status line for a hook payload.

    Mirrors `spotlightActivityText` / `spotlightRunningActivityText`
    (`AgentSession+Presentation.swift:263-268`, `:361-374`): the humanised tool
    name plus its input preview when one is renderable, otherwise the generic
    fallback.

    This is a verification aid — it is never sent over the wire. It exists so
    the exact user-visible string can be asserted in tests and printed by
    `scripts/open_island_demo.py` instead of requiring a screenshot.
    """
    tool_name = hook_payload.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        return "Running"

    label = humanized_tool_name(tool_name)

    tool_input = hook_payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in PREVIEW_KEY_PRIORITY:
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                return f"{label} {value}"

    return label


def activity_status(
    session_id: str,
    cwd: str,
    label: str,
    terminal: TerminalContext | None = None,
) -> dict[str, Any]:
    """Report iTE's own activity wording to the island.

    The island's running-status line comes only from `currentTool`
    (`spotlightRunningActivityText`), so without this a reasoning turn falls
    back to the generic "Thinking". Carrying the label on `tool_name` is what
    makes the island show iTE's wording instead.

    Deliberately sends no `tool_input` and no `tool_use_id`: the status line
    then has no preview appended, and permission correlation is untouched.
    Upstream drops the associated pending context at `Stop` / `StopFailure` /
    `SessionEnd` (`BridgeServer.swift:2700-2714`), so entries do not accumulate.
    """
    payload = _base("PreToolUse", session_id, cwd, terminal)
    payload["tool_name"] = label
    return payload


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


# ---------------------------------------------------------------------------
# User-attention round trip (approvals + questions)
#
# See `docs/design/open-island-attention-plan.md`. These builders are the only
# place that knows the attention wire shape; the bridge and UI consume them.
# ---------------------------------------------------------------------------

# The `AskUserQuestion` tool name is load-bearing, not cosmetic: upstream's
# `questionPrompt` parser returns nil unless it matches exactly
# (`ClaudeHooks.swift:822-879`), and a nil question prompt falls through to the
# approval card, which would render Deny / Allow Once for a question.
ASK_USER_QUESTION_TOOL = "AskUserQuestion"


# ---------------------------------------------------------------------------
# Human-readable approval text
#
# The notch card reads as: "Tool permission requested" / "<preview>" / "<path>".
# The preview is the only line that explains *what* is about to happen, and the
# tool name is jargon to a user ("write_file", "apply_patch"). So: describe the
# action, and fall back to a humanised tool name only when nothing describes it.
# ---------------------------------------------------------------------------

_SHELL_ACTION_VERBS = {
    "rm": "Delete",
    "rmdir": "Delete folder",
    "unlink": "Delete",
    "mv": "Move",
    "cp": "Copy",
    "mkdir": "Create folder",
    "touch": "Create file",
    "ln": "Link",
    "chmod": "Change permissions on",
    "chown": "Change owner of",
    "curl": "Download",
    "wget": "Download",
    "kill": "Stop process",
    "pkill": "Stop process",
}

# These read as a complete action on their own; no object is appended.
_GIT_ACTION_VERBS = {
    "commit": "Commit changes",
    "push": "Push changes",
    "pull": "Pull changes",
    "fetch": "Fetch changes",
    "checkout": "Switch branch",
    "switch": "Switch branch",
    "merge": "Merge branch",
    "rebase": "Rebase branch",
    "reset": "Reset changes",
    "restore": "Restore files",
    "stash": "Stash changes",
    "add": "Stage changes",
    "tag": "Tag release",
    "clone": "Clone repository",
    "init": "Create repository",
}

_COMMAND_SEPARATORS = {"&&", "||", ";", "|", "&"}


def _first_command_segment(command: str) -> list[str]:
    """Tokens of the first command in a compound shell line.

    ``A && B`` reports ``A``: that is the action the user is being asked to
    authorise first, and a preview of the whole line would be unreadable.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    segment: list[str] = []
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            break
        segment.append(token)
    return segment


def _command_operand(tokens: list[str]) -> str | None:
    """The file a command acts on: its last non-flag argument, as a basename."""
    for token in reversed(tokens):
        if token and not token.startswith("-"):
            return os.path.basename(token) or token
    return None


def shell_action_preview(command: str) -> str | None:
    """Turn a shell command into a short human phrase, or ``None``."""
    segment = _first_command_segment(command)
    if not segment:
        return None

    program = os.path.basename(segment[0]).lower()
    args = segment[1:]

    if program == "git":
        subcommand = next((arg for arg in args if not arg.startswith("-")), "")
        return _GIT_ACTION_VERBS.get(subcommand) or command.strip() or None

    verb = _SHELL_ACTION_VERBS.get(program)
    if verb:
        operand = _command_operand(args)
        return f"{verb} {operand}" if operand else verb

    if program == "sudo" and args:
        return shell_action_preview(" ".join(args))

    # Unrecognised program: the command itself is the most honest preview.
    return command.strip() or None


def humanize_tool_name(tool_name: str) -> str:
    """Last-resort label: ``write_file`` -> ``Write file``.

    MCP tools arrive as ``mcp__server__tool``; the protocol prefix is noise the
    user does not need, so it is dropped.
    """
    words = [word for word in re.split(r"[^0-9A-Za-z]+", tool_name) if word]
    if words and words[0].lower() == "mcp":
        words = words[1:]
    if not words:
        return "Tool action"
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def _description_preview(
    description: str, affected_paths: Sequence[str]
) -> str | None:
    """Shorten a tool's own description for the card.

    Tool descriptions already read naturally ("Create file: /abs/path",
    "Edit file: /abs/path"). The only problems are the absolute path and the
    redundant word "file" — the card is already titled a permission request.
    """
    text = description.strip()
    if not text:
        return None

    for path in affected_paths:
        path_text = str(path)
        text = text.replace(path_text, os.path.basename(path_text))

    text = text.replace(" new file: ", " ").replace(" file: ", " ")
    return text.strip() or None


def approval_preview(
    *,
    tool_name: str,
    description: str | None = None,
    command: str | None = None,
    affected_paths: Sequence[str] = (),
) -> str:
    """Compose the notch card's main line for an approval.

    Order of preference:

    1. A verb for a shell command (``Delete report.txt``).
    2. The tool's own description, path-shortened (``Create report.txt``).
    3. The humanised tool name (``Write file``) — only when nothing above
       describes the action.
    """
    if command and command.strip():
        shell_preview = shell_action_preview(command)
        if shell_preview:
            return shell_preview

    if description:
        described = _description_preview(description, affected_paths)
        if described:
            return described

    return humanize_tool_name(tool_name)


def permission_request(
    session_id: str,
    cwd: str,
    *,
    preview: str | None = None,
    affected_path: str | None = None,
    tool_use_id: str | None = None,
    terminal: TerminalContext | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Build a blocking ``PermissionRequest`` for the notch.

    Deliberately carries **no ``tool_name``**: upstream renders its
    "Always Allow" button only when a tool name is present
    (`IslandPanelView.swift:1748`), and there is no persistent-rule engine
    behind it today. ``tool_use_id`` is still sent so the tool-use badge
    resolves (`BridgeServer.swift:3056-3058`).

    **Card text is driven by ``tool_input.command``, not ``message``.** Upstream
    renders the main line from `currentCommandPreviewText`
    (`IslandPanelView.swift:1890-1896`), which short-circuits on the first
    present key of `PREVIEW_KEY_PRIORITY`; ``command`` outranks ``file_path``.
    ``message`` is only reached when that whole chain is empty, so sending it
    alone shows a raw file path instead of the intended description. Build the
    text with :func:`approval_preview`.
    """
    payload = _base("PermissionRequest", session_id, cwd, terminal)
    if title:
        payload["title"] = _truncate(title)
    if preview:
        payload["message"] = _truncate(preview)

    tool_input: dict[str, Any] = {}
    if preview:
        tool_input["command"] = _truncate(preview)
    # The dim second line is `permissionAffectedPath`, derived from path keys;
    # there is no dedicated field.
    if affected_path:
        tool_input["file_path"] = str(affected_path)

    if tool_input:
        payload["tool_input"] = tool_input

    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    return payload


def question_request(
    session_id: str,
    cwd: str,
    *,
    question: str,
    options: list[str],
    recommended_index: int | None = None,
    tool_use_id: str | None = None,
    terminal: TerminalContext | None = None,
    header: str = "Plan question",
) -> dict[str, Any]:
    """Build an ``AskUserQuestion`` payload that renders as a question card.

    ``tool_name`` and ``header`` are both mandatory: upstream drops any
    question missing either. ``recommended_index`` is carried on that option's
    ``description`` (verified rendered at `IslandPanelView.swift:2230`).

    Free text is always available upstream — it appends an ``Other`` option
    regardless — so this payload does not encode ``allow_free_text``. The caller
    reconciles an unexpected free-text answer.
    """
    option_payloads: list[dict[str, Any]] = []
    for index, label in enumerate(options):
        entry: dict[str, Any] = {"label": str(label)}
        if recommended_index == index:
            entry["description"] = "Recommended"
        option_payloads.append(entry)

    payload = _base("PermissionRequest", session_id, cwd, terminal)
    payload["tool_name"] = ASK_USER_QUESTION_TOOL
    payload["tool_input"] = {
        "questions": [
            {
                "question": question,
                "header": header,
                "options": option_payloads,
                "multiSelect": False,
            }
        ]
    }
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    return payload


def _permission_decision(response: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract the inner decision from a ``claudeHookDirective`` response.

    The wire path is ``response.directive.directive`` — a
    `BridgeResponse.claudeHookDirective` wrapping a `ClaudeHookDirective` whose
    `permissionRequest` case wraps the decision (`ClaudeHooks.swift:560-593`).
    A question answer arrives through the *same* case with `updatedInput`
    populated, so callers branch on what they asked for, not the shape.
    """
    if not isinstance(response, dict):
        return None
    if response.get("type") != "claudeHookDirective":
        return None

    directive = response.get("directive")
    if not isinstance(directive, dict):
        return None
    if directive.get("type") != "permissionRequest":
        return None

    decision = directive.get("directive")
    return decision if isinstance(decision, dict) else None


def parse_permission_directive(response: dict[str, Any] | None) -> str | None:
    """Map a parked permission exchange to ``"approved"`` / ``"denied"``.

    Returns ``None`` when the response is not a recognisable decision, which
    the caller treats as "the island did not answer" — never as a denial.
    """
    decision = _permission_decision(response)
    if decision is None:
        return None

    behavior = decision.get("behavior")
    if behavior == "allow":
        return "approved"
    if behavior == "deny":
        return "denied"
    return None


def parse_question_directive(
    response: dict[str, Any] | None,
    *,
    question: str,
    options: list[str],
) -> dict[str, Any] | None:
    """Map a question answer back into the local card's result shape.

    Upstream merges the reply into the *original* tool input and returns it as
    ``updatedInput.answers`` keyed by the exact question text we sent
    (`BridgeServer.swift:3060-3107`). A value matching one of our option labels
    is a selection; anything else is free text typed through ``Other``.
    """
    decision = _permission_decision(response)
    if decision is None or decision.get("behavior") != "allow":
        return None

    updated = decision.get("updatedInput")
    if not isinstance(updated, dict):
        return None

    answers = updated.get("answers")
    value: Any = None
    if isinstance(answers, dict):
        value = answers.get(question)
    if value is None:
        raw = updated.get("rawAnswer")
        if isinstance(raw, str) and raw:
            value = raw
    if not isinstance(value, str) or not value.strip():
        return {"selected_option": "", "free_text": "", "selected_index": None}

    if value in options:
        return {
            "selected_option": value,
            "free_text": "",
            "selected_index": options.index(value),
        }
    return {"selected_option": "", "free_text": value, "selected_index": None}
