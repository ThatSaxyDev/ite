from __future__ import annotations

from typing import Any


def activity_title(
    name: str,
    *,
    stage: str = "start",
    success: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    metadata = metadata or {}
    running = stage == "start"
    done = bool(success)
    recoverable = bool(metadata.get("recoverable"))
    if name == "read_file":
        return "Reading file" if running else ("Completed reading" if done else ("Read needs retry" if recoverable else "Read failed"))
    if name == "write_file":
        return "Writing file" if running else ("Saved file" if done else "Write failed")
    if name == "edit":
        return "Editing file" if running else ("Updated file" if done else ("Edit needs refinement" if recoverable else "Edit failed"))
    if name == "apply_patch":
        return "Applying patch" if running else ("Applied patch" if done else ("Patch needs retry" if recoverable else "Patch failed"))
    if name == "list_dir":
        return "Checking folder" if running else ("Checked folder" if done else "List failed")
    if name == "grep":
        return "Searching code" if running else ("Finished searching code" if done else ("Search needs retry" if recoverable else "Search failed"))
    if name == "glob":
        return "Finding files" if running else ("Found matching files" if done else "File search failed")
    if name == "shell":
        return "Running command" if running else ("Command finished" if done else ("Command needs retry" if recoverable else "Command failed"))
    if name.startswith("subagent_"):
        return "Asking specialist" if running else ("Specialist finished" if done else "Specialist failed")
    if name == "web_search":
        return "Searching web" if running else ("Web search finished" if done else "Web search failed")
    if name == "web_fetch":
        return "Fetching page" if running else ("Fetched page" if done else "Fetch failed")
    if name == "todos":
        return "Updating checklist" if running else ("Checklist updated" if done else "Checklist update failed")
    if name == "memory":
        return "Updating memory" if running else ("Memory updated" if done else ("Memory retry needed" if recoverable else "Memory update failed"))
    return "Running tool" if running else ("Tool completed" if done else ("Tool needs retry" if recoverable else "Tool failed"))


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

    if name == "read_file":
        path = _path(args, metadata)
        if stage != "start":
            shown_start = metadata.get("shown_start")
            shown_end = metadata.get("shown_end")
            total = metadata.get("total_lines")
            if all(isinstance(x, int) for x in [shown_start, shown_end, total]):
                prefix = "Completed reading" if success else "Failed to read"
                return f"{prefix} {path} (lines {shown_start}-{shown_end} of {total})."
        offset = args.get("offset", 1)
        limit = args.get("limit")
        if isinstance(limit, int):
            end_line = int(offset) + limit - 1
            if stage == "start":
                return f"Reading {path} from line {offset} to {end_line}."
            if success:
                return f"Completed reading {path} from line {offset} to {end_line}."
            return f"Failed to read {path} from line {offset} to {end_line}."
        if stage == "start":
            return f"Reading {path}."
        if success:
            return f"Completed reading {path}."
        return f"Failed to read {path}."

    if name == "write_file":
        path = _path(args, metadata)
        if stage == "start":
            return f"Writing {path}."
        if success:
            return f"Saved {path}."
        return f"Failed to write {path}."

    if name == "edit":
        path = _path(args, metadata)
        if stage == "start":
            return f"Editing {path}."
        if success:
            return f"Updated {path}."
        if metadata.get("recoverable"):
            return f"Edit needs refinement for {path}."
        return f"Failed to edit {path}."

    if name == "apply_patch":
        actions = metadata.get("actions")
        if isinstance(actions, list):
            if stage == "start":
                return f"Applying changes across {len(actions)} file(s)."
            if success:
                return f"Applied changes across {len(actions)} file(s)."
            return f"Failed to apply changes across {len(actions)} file(s)."
        if stage == "start":
            return "Applying patch."
        if success:
            return "Applied patch."
        if metadata.get("recoverable"):
            return "Patch needs retry."
        return "Failed to apply patch."

    if name == "shell":
        command = str(args.get("command", "")).strip()
        if command:
            if stage == "start":
                return f"Running command: `{_trim(command, 100)}`."
            if success:
                return f"Finished command: `{_trim(command, 100)}`."
            return f"Command failed: `{_trim(command, 100)}`."
        if stage == "start":
            return "Running command."
        if success:
            return "Finished command."
        return "Command failed."

    if name == "grep":
        pattern = str(args.get("pattern", "")).strip()
        target = _path(args, metadata)
        if pattern:
            if stage == "start":
                return f"Searching {target} for `{_trim(pattern, 60)}`."
            if success:
                return f"Finished searching {target} for `{_trim(pattern, 60)}`."
            return f"Search failed for `{_trim(pattern, 60)}` in {target}."
        if stage == "start":
            return f"Searching code in {target}."
        if success:
            return f"Finished searching code in {target}."
        return f"Search failed in {target}."

    if name == "glob":
        pattern = str(args.get("pattern", "")).strip()
        target = _path(args, metadata)
        if pattern:
            if stage == "start":
                return f"Looking for `{_trim(pattern, 60)}` in {target}."
            if success:
                return f"Found matches for `{_trim(pattern, 60)}` in {target}."
            return f"File search failed for `{_trim(pattern, 60)}` in {target}."
        if stage == "start":
            return f"Looking for files in {target}."
        if success:
            return f"Finished looking for files in {target}."
        return f"File search failed in {target}."

    if name == "list_dir":
        path = _path(args, metadata)
        if stage == "start":
            return f"Checking {path}."
        if success:
            return f"Checked {path}."
        return f"Failed to check {path}."

    if name.startswith("subagent_"):
        subagent = name.replace("subagent_", "", 1)
        goal = str(args.get("goal", "")).strip()
        if goal:
            if stage == "start":
                return f"Asking specialist `{subagent}` to help with: {_trim(goal, 110)}"
            if success:
                return f"Specialist `{subagent}` finished: {_trim(goal, 110)}"
            return f"Specialist `{subagent}` failed: {_trim(goal, 110)}"
        if stage == "start":
            return f"Asking specialist `{subagent}`."
        if success:
            return f"Specialist `{subagent}` finished."
        return f"Specialist `{subagent}` failed."

    if name == "web_search":
        query = str(args.get("query", "")).strip()
        if query:
            if stage == "start":
                return f"Searching the web for: {_trim(query, 90)}"
            if success:
                return f"Finished web search for: {_trim(query, 90)}"
            return f"Web search failed for: {_trim(query, 90)}"
        if stage == "start":
            return "Searching the web."
        if success:
            return "Finished web search."
        return "Web search failed."

    if name == "web_fetch":
        url = str(args.get("url", "")).strip()
        if url:
            if stage == "start":
                return f"Fetching {_trim(url, 90)}."
            if success:
                return f"Fetched {_trim(url, 90)}."
            return f"Failed to fetch {_trim(url, 90)}."
        if stage == "start":
            return "Fetching page."
        if success:
            return "Fetched page."
        return "Fetch failed."

    if name == "todos":
        action = str(args.get("action", "")).strip() or str(metadata.get("action", "")).strip() or "update"
        scope = str(args.get("scope", "")).strip() or str(metadata.get("scope", "")).strip() or "execution"
        label = "planning checklist" if scope == "planning" else "checklist"
        if action == "add":
            if stage == "start":
                return f"Setting up {label}."
            if success:
                return f"Set up {label}."
            return f"Failed to set up {label}."
        if action == "complete":
            if stage == "start":
                return f"Updating {label} progress."
            if success:
                return f"Updated {label} progress."
            return f"Failed to update {label} progress."
        if action == "reopen":
            if stage == "start":
                return f"Reopening an item in {label}."
            if success:
                return f"Reopened an item in {label}."
            return f"Failed to reopen an item in {label}."
        if action == "remove":
            if stage == "start":
                return f"Removing an item from {label}."
            if success:
                return f"Removed an item from {label}."
            return f"Failed to remove an item from {label}."
        if action == "update":
            if stage == "start":
                return f"Updating an item in {label}."
            if success:
                return f"Updated an item in {label}."
            return f"Failed to update an item in {label}."
        if action == "clear":
            if stage == "start":
                return f"Clearing {label}."
            if success:
                return f"Cleared {label}."
            return f"Failed to clear {label}."
        if action == "list":
            if stage == "start":
                return f"Refreshing {label}."
            if success:
                return f"Refreshed {label}."
            return f"Failed to refresh {label}."
        if stage == "start":
            return f"Updating {label}."
        if success:
            return f"Updated {label}."
        return f"Failed to update {label}."

    if name == "memory":
        action = str(args.get("action", "")).strip() or "update"
        key = str(args.get("key", "")).strip()
        if key:
            if stage == "start":
                return f"Updating memory `{_trim(key, 40)}`."
            if success:
                return f"Updated memory `{_trim(key, 40)}`."
            if metadata.get("recoverable"):
                return f"Memory retry needed for `{_trim(key, 40)}`."
            return f"Failed to update memory `{_trim(key, 40)}`."
        if stage == "start":
            return f"Running memory action `{action}`."
        if success:
            return f"Completed memory action `{action}`."
        if metadata.get("recoverable"):
            return f"Memory action `{action}` needs retry."
        return f"Failed memory action `{action}`."

    if name == "plan_question":
        question = str(args.get("question", "")).strip()
        if question:
            trimmed = _trim(question, 90)
            if stage == "start":
                return f"Asking a planning question: {trimmed}"
            if success:
                return f"Captured planning answer for: {trimmed}"
            return f"Planning question failed: {trimmed}"
        if stage == "start":
            return "Asking a planning question."
        if success:
            return "Captured a planning answer."
        return "Planning question failed."

    if stage == "start":
        return f"Running tool `{name}`."
    if success:
        return f"Completed tool `{name}`."
    return f"Tool `{name}` failed."


def progress_label(
    *,
    tool_name: str | None = None,
    arguments: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    phase: str = "reasoning",
    plan_mode: bool = False,
) -> str:
    args = arguments or {}
    md = metadata or {}
    if not tool_name:
        return "Planning" if plan_mode else "Thinking"

    name = tool_name
    label = "Working"
    if name == "list_dir":
        label = "Exploring workspace"
    elif name == "grep":
        label = "Searching code"
    elif name == "glob":
        label = "Finding files"
    elif name == "read_file":
        path = _path(args, md)
        label = "Reading file" if path != "the workspace" else "Reading workspace files"
    elif name == "shell":
        label = "Running command"
    elif name == "web_search":
        label = "Researching web"
    elif name == "web_fetch":
        label = "Reading source"
    elif name == "todos":
        scope = str(args.get("scope", "")).strip() or str(md.get("scope", "")).strip()
        label = "Updating planning checklist" if scope == "planning" else "Updating checklist"
    elif name == "memory":
        label = "Updating memory"
    elif name.startswith("subagent_"):
        label = "Delegating to specialist"

    if phase == "post_tool":
        if name in {"list_dir", "grep", "glob", "read_file", "web_search", "web_fetch"}:
            return label
        return "Planning next step" if plan_mode else "Reviewing results"

    return label


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
