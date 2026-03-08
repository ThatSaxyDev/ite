from __future__ import annotations

from typing import Any


def activity_title(
    name: str,
    *,
    stage: str = "start",
    success: bool | None = None,
) -> str:
    running = stage == "start"
    done = bool(success)
    if name == "read_file":
        return "Reading file" if running else ("Read file" if done else "Read failed")
    if name == "write_file":
        return "Writing file" if running else ("Wrote file" if done else "Write failed")
    if name == "edit":
        return "Editing file" if running else ("Edited file" if done else "Edit failed")
    if name == "apply_patch":
        return "Applying multi-file patch" if running else ("Applied patch" if done else "Patch failed")
    if name == "list_dir":
        return "Listing directory" if running else ("Listed directory" if done else "List failed")
    if name == "grep":
        return "Searching code" if running else ("Searched code" if done else "Search failed")
    if name == "glob":
        return "Finding files" if running else ("Found files" if done else "File search failed")
    if name == "shell":
        return "Running command" if running else ("Command completed" if done else "Command failed")
    if name.startswith("subagent_"):
        return "Delegating to specialist" if running else ("Specialist completed" if done else "Specialist failed")
    if name == "web_search":
        return "Searching web" if running else ("Web search completed" if done else "Web search failed")
    if name == "web_fetch":
        return "Fetching page" if running else ("Fetch completed" if done else "Fetch failed")
    if name == "todos":
        return "Updating task list" if running else ("Task list updated" if done else "Task list update failed")
    if name == "memory":
        return "Updating memory" if running else ("Memory updated" if done else "Memory update failed")
    return "Running tool" if running else ("Tool completed" if done else "Tool failed")


def describe_tool_activity(
    name: str,
    args: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    stage: str = "start",
    success: bool | None = None,
) -> str:
    args = args or {}
    metadata = metadata or {}
    verb = "Running" if stage == "start" else ("Completed" if success else "Failed")

    if name == "read_file":
        path = _path(args, metadata)
        if stage != "start":
            shown_start = metadata.get("shown_start")
            shown_end = metadata.get("shown_end")
            total = metadata.get("total_lines")
            if all(isinstance(x, int) for x in [shown_start, shown_end, total]):
                return f"{verb} reading {path} (lines {shown_start}-{shown_end} of {total})."
        offset = args.get("offset", 1)
        limit = args.get("limit")
        if isinstance(limit, int):
            end_line = int(offset) + limit - 1
            return f"{verb} read of {path} from line {offset} to {end_line}."
        return f"{verb} read of {path}."

    if name == "write_file":
        return f"{verb} write to {_path(args, metadata)}."

    if name == "edit":
        return f"{verb} edit on {_path(args, metadata)}."

    if name == "apply_patch":
        actions = metadata.get("actions")
        if isinstance(actions, list):
            return f"{verb} patch across {len(actions)} file(s)."
        return f"{verb} multi-file patch operation."

    if name == "shell":
        command = str(args.get("command", "")).strip()
        if command:
            return f"{verb} shell command: `{_trim(command, 100)}`."
        return f"{verb} shell command."

    if name == "grep":
        pattern = str(args.get("pattern", "")).strip()
        target = _path(args, metadata)
        if pattern:
            return f"{verb} search for `{_trim(pattern, 60)}` in {target}."
        return f"{verb} code search in {target}."

    if name == "glob":
        pattern = str(args.get("pattern", "")).strip()
        target = _path(args, metadata)
        if pattern:
            return f"{verb} file pattern search `{_trim(pattern, 60)}` in {target}."
        return f"{verb} file pattern search in {target}."

    if name == "list_dir":
        return f"{verb} directory listing for {_path(args, metadata)}."

    if name.startswith("subagent_"):
        subagent = name.replace("subagent_", "", 1)
        goal = str(args.get("goal", "")).strip()
        if goal:
            return f"{verb} subagent `{subagent}` for: {_trim(goal, 110)}"
        return f"{verb} subagent `{subagent}`."

    if name == "web_search":
        query = str(args.get("query", "")).strip()
        if query:
            return f"{verb} web search for: {_trim(query, 90)}"
        return f"{verb} web search."

    if name == "web_fetch":
        url = str(args.get("url", "")).strip()
        if url:
            return f"{verb} fetch of {_trim(url, 90)}."
        return f"{verb} web fetch."

    if name == "todos":
        action = str(args.get("action", "")).strip() or "update"
        return f"{verb} todo list action: {action}."

    if name == "memory":
        action = str(args.get("action", "")).strip() or "update"
        key = str(args.get("key", "")).strip()
        if key:
            return f"{verb} memory action `{action}` for key `{_trim(key, 40)}`."
        return f"{verb} memory action `{action}`."

    return f"{verb} tool `{name}`."


def _path(args: dict[str, Any], metadata: dict[str, Any]) -> str:
    value = args.get("path")
    if isinstance(value, str) and value.strip():
        return value
    value = metadata.get("path")
    if isinstance(value, str) and value.strip():
        return value
    return "the workspace"


def _trim(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
