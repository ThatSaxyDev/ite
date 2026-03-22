from __future__ import annotations

from typing import Any


def is_policy_redirect(metadata: dict[str, Any] | None) -> bool:
    metadata = metadata or {}
    return bool(metadata.get("policy_blocked") and metadata.get("redirect_to"))


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
    redirect = is_policy_redirect(metadata)
    recoverable = bool(metadata.get("recoverable")) or redirect
    if redirect and not running and not done:
        return "Switching tools"
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
    if name == "shell_start":
        return "Starting shell session" if running else ("Shell session started" if done else "Shell session start failed")
    if name == "shell_poll":
        if running:
            return "Checking shell session"
        if done:
            if metadata.get("running") is False and not metadata.get("has_new_output"):
                return "Shell session finished"
            return "Shell session updated"
        return "Shell session check failed"
    if name == "shell_send":
        return "Sending shell input" if running else ("Shell input sent" if done else "Shell input failed")
    if name == "shell_stop":
        return "Stopping shell session" if running else ("Shell session stopped" if done else "Shell session stop failed")
    if name == "spawn_subagent":
        return "Spawning specialist" if running else ("Specialist started" if done else "Specialist spawn failed")
    if name == "spawn_subagents":
        return "Spawning specialists" if running else ("Specialists started" if done else "Specialist batch failed")
    if name == "wait_subagent":
        return "Waiting on specialists" if running else ("Specialist wait finished" if done else "Specialist wait failed")
    if name == "list_subagents":
        return "Checking specialists" if running else ("Specialist status ready" if done else "Specialist status failed")
    if name == "cancel_subagent":
        return "Cancelling specialists" if running else ("Specialist cancel complete" if done else "Specialist cancel failed")
    if name.startswith("subagent_"):
        return "Asking specialist" if running else ("Specialist finished" if done else "Specialist failed")
    if name == "web_search":
        return "Searching web" if running else ("Web search finished" if done else "Web search failed")
    if name == "web_fetch":
        return "Fetching page" if running else ("Fetched page" if done else "Fetch failed")
    if name == "http_request":
        return "Sending HTTP request" if running else ("HTTP response ready" if done else "HTTP request failed")
    if name == "list_archive":
        return "Inspecting archive" if running else ("Archive contents ready" if done else "Archive inspection failed")
    if name == "read_pdf":
        return "Reading PDF" if running else ("PDF loaded" if done else "PDF read failed")
    if name == "read_image":
        return "Reading image" if running else ("Image loaded" if done else "Image read failed")
    if name == "todos":
        return "Updating checklist" if running else ("Checklist updated" if done else "Checklist update failed")
    if name == "memory":
        return "Updating memory" if running else ("Memory updated" if done else ("Memory retry needed" if recoverable else "Memory update failed"))
    if name == "read_json":
        return "Reading JSON" if running else ("JSON loaded" if done else "JSON read failed")
    if name == "edit_json":
        return "Updating JSON" if running else ("JSON updated" if done else "JSON edit failed")
    if name == "read_toml":
        return "Reading TOML" if running else ("TOML loaded" if done else "TOML read failed")
    if name == "write_toml":
        return "Updating TOML" if running else ("TOML updated" if done else "TOML update failed")
    if name == "read_yaml":
        return "Reading YAML" if running else ("YAML loaded" if done else "YAML read failed")
    if name == "write_yaml":
        return "Updating YAML" if running else ("YAML updated" if done else "YAML update failed")
    if name == "read_env":
        return "Reading env file" if running else ("Env loaded" if done else "Env read failed")
    if name == "write_env":
        return "Updating env file" if running else ("Env updated" if done else "Env update failed")
    if name == "run_tests":
        return "Running tests" if running else ("Test results ready" if done else "Tests failed")
    if name == "run_linter":
        return "Running linter" if running else ("Lint results ready" if done else "Lint failed")
    if name == "run_typecheck":
        return "Running typecheck" if running else ("Typecheck results ready" if done else "Typecheck failed")
    if name == "git_status":
        return "Checking git status" if running else ("Git status updated" if done else "Git status failed")
    if name == "git_diff":
        return "Inspecting git diff" if running else ("Git diff ready" if done else "Git diff failed")
    if name == "git_log":
        return "Reading git history" if running else ("Git history ready" if done else "Git history failed")
    if name == "git_branch":
        return "Managing branch" if running else ("Branch updated" if done else "Branch action failed")
    if name == "git_remote":
        return "Managing remotes" if running else ("Remote updated" if done else "Remote action failed")
    if name == "git_commit":
        return "Creating commit" if running else ("Commit created" if done else "Commit failed")
    if name == "git_push":
        return "Publishing branch" if running else ("Publish complete" if done else "Publish failed")
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
    redirect = is_policy_redirect(metadata)
    redirect_to = str(metadata.get("redirect_to") or "").strip()
    if redirect and stage != "start" and not success:
        if redirect_to:
            return f"`{redirect_to}` fits this step better, so continuing there."
        return f"This step is being continued with a more suitable tool."

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

    if name == "shell_start":
        command = str(args.get("command", "")).strip()
        shell_cwd = str(args.get("cwd") or metadata.get("cwd") or "").strip()
        target = f" in {shell_cwd}" if shell_cwd else ""
        if command:
            if stage == "start":
                return f"Starting shell session for `{_trim(command, 100)}`{target}."
            if success:
                return f"Started shell session for `{_trim(command, 100)}`{target}."
            return f"Failed to start shell session for `{_trim(command, 100)}`{target}."
        if stage == "start":
            return f"Starting interactive shell session{target}."
        if success:
            return f"Started interactive shell session{target}."
        return f"Failed to start interactive shell session{target}."

    if name == "shell_poll":
        session_id = str(args.get("session_id") or metadata.get("session_id") or "").strip()
        status = str(metadata.get("status") or "").strip()
        has_new_output = metadata.get("has_new_output")
        if stage == "start":
            return f"Checking shell session `{session_id}`." if session_id else "Checking shell session."
        if success:
            if has_new_output is False and status == "exited":
                return (
                    f"No new output from shell session `{session_id}`. It has already finished."
                    if session_id
                    else "No new output. The shell session has already finished."
                )
            if has_new_output is False:
                return (
                    f"No new output from shell session `{session_id}` yet."
                    if session_id
                    else "No new output from the shell session yet."
                )
            if session_id and status:
                return f"Updated shell session `{session_id}` ({status})."
            if session_id:
                return f"Updated shell session `{session_id}`."
            return "Updated shell session."
        return f"Failed to check shell session `{session_id}`." if session_id else "Failed to check shell session."

    if name == "shell_send":
        session_id = str(args.get("session_id") or metadata.get("session_id") or "").strip()
        shell_input = str(args.get("input") or "").strip()
        if shell_input:
            if stage == "start":
                return (
                    f"Sending `{_trim(shell_input, 80)}` to shell session `{session_id}`."
                    if session_id
                    else f"Sending `{_trim(shell_input, 80)}` to shell session."
                )
            if success:
                return (
                    f"Sent `{_trim(shell_input, 80)}` to shell session `{session_id}`."
                    if session_id
                    else f"Sent `{_trim(shell_input, 80)}` to shell session."
                )
            return (
                f"Failed to send `{_trim(shell_input, 80)}` to shell session `{session_id}`."
                if session_id
                else f"Failed to send `{_trim(shell_input, 80)}` to shell session."
            )
        if stage == "start":
            return f"Sending input to shell session `{session_id}`." if session_id else "Sending input to shell session."
        if success:
            return f"Sent input to shell session `{session_id}`." if session_id else "Sent input to shell session."
        return f"Failed to send input to shell session `{session_id}`." if session_id else "Failed to send input to shell session."

    if name == "shell_stop":
        session_id = str(args.get("session_id") or metadata.get("session_id") or "").strip()
        if stage == "start":
            return f"Stopping shell session `{session_id}`." if session_id else "Stopping shell session."
        if success:
            return f"Stopped shell session `{session_id}`." if session_id else "Stopped shell session."
        return f"Failed to stop shell session `{session_id}`." if session_id else "Failed to stop shell session."

    if name == "spawn_subagent":
        subagent = str(args.get("subagent", "")).strip()
        goal = str(args.get("goal", "")).strip()
        if stage == "start":
            if subagent and goal:
                return f"Starting specialist `{subagent}` for: {_trim(goal, 110)}."
            if subagent:
                return f"Starting specialist `{subagent}`."
            return "Starting specialist."
        if success:
            runs = metadata.get("run") if isinstance(metadata.get("run"), dict) else {}
            run_id = str(runs.get("run_id") or "").strip()
            suffix = f" (`{run_id}`)" if run_id else ""
            if metadata.get("reused_existing") is True:
                if subagent:
                    return f"Reused active specialist `{subagent}`{suffix}."
                return f"Reused active specialist{suffix}."
            if subagent:
                return f"Started specialist `{subagent}`{suffix}."
            return f"Started specialist{suffix}."
        if subagent:
            return f"Failed to start specialist `{subagent}`."
        return "Failed to start specialist."

    if name == "spawn_subagents":
        requests = args.get("requests")
        count = len(requests) if isinstance(requests, list) else 0
        if stage == "start":
            if count:
                return f"Starting {count} specialist run{'s' if count != 1 else ''}."
            return "Starting specialist batch."
        if success:
            actual_count = metadata.get("count")
            reused_count = metadata.get("reused_existing_count")
            count_text = actual_count if isinstance(actual_count, int) else count
            reused_text = (
                f" Reused {reused_count} existing run{'s' if reused_count != 1 else ''}."
                if isinstance(reused_count, int) and reused_count > 0
                else ""
            )
            if count_text:
                return f"Started {count_text} specialist run{'s' if count_text != 1 else ''}.{reused_text}"
            return f"Started specialist batch.{reused_text}"
        return "Failed to start specialist batch."

    if name == "wait_subagent":
        if stage == "start":
            return "Waiting for specialist runs to finish."
        if success:
            completed = metadata.get("completed_run_ids")
            pending = metadata.get("pending_run_ids")
            completed_count = len(completed) if isinstance(completed, list) else 0
            pending_count = len(pending) if isinstance(pending, list) else 0
            return f"Wait finished: {completed_count} completed, {pending_count} still pending."
        return "Failed while waiting for specialist runs."

    if name == "list_subagents":
        if stage == "start":
            return "Checking specialist runs."
        if success:
            count = metadata.get("count")
            if isinstance(count, int):
                return f"Listed {count} specialist run{'s' if count != 1 else ''}."
            return "Listed specialist runs."
        return "Failed to list specialist runs."

    if name == "cancel_subagent":
        if stage == "start":
            return "Cancelling specialist runs."
        if success:
            cancelled = metadata.get("cancelled_run_ids")
            count = len(cancelled) if isinstance(cancelled, list) else 0
            return f"Cancelled {count} specialist run{'s' if count != 1 else ''}."
        return "Failed to cancel specialist runs."

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

    if name == "http_request":
        method = str(args.get("method") or metadata.get("method") or "GET").strip().upper()
        url = str(args.get("url") or metadata.get("url") or "").strip()
        if url:
            if stage == "start":
                return f"Sending {method} request to {_trim(url, 90)}."
            if success:
                return f"Completed {method} request to {_trim(url, 90)}."
            return f"{method} request failed for {_trim(url, 90)}."
        if stage == "start":
            return "Sending HTTP request."
        if success:
            return "Completed HTTP request."
        return "HTTP request failed."

    if name == "list_archive":
        path = _path(args, metadata)
        if stage == "start":
            return f"Inspecting archive {path}."
        if success:
            return f"Loaded archive contents for {path}."
        return f"Failed to inspect archive {path}."

    if name == "read_pdf":
        path = _path(args, metadata)
        pages = metadata.get("selected_pages") or args.get("pages")
        if stage == "start":
            return f"Reading PDF {path}."
        if success and isinstance(pages, list) and pages:
            preview = ", ".join(str(page) for page in pages[:5])
            suffix = ", ..." if len(pages) > 5 else ""
            return f"Processed selected PDF pages ({preview}{suffix})."
        if success:
            return "Processed PDF successfully."
        return f"Failed to read PDF {path}."

    if name == "read_image":
        path = _path(args, metadata)
        if stage == "start":
            return f"Reading image {path}."
        if success and metadata.get("ocr_requested"):
            return "Processed image successfully with OCR."
        if success:
            return "Processed image successfully."
        return f"Failed to read image {path}."

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

    if name == "read_json":
        path = _path(args, metadata)
        json_path = str(args.get("json_path") or metadata.get("json_path") or "").strip()
        target = f"{path} :: {json_path}" if json_path else path
        if stage == "start":
            return f"Reading JSON from {target}."
        if success:
            return f"Loaded JSON from {target}."
        return f"Failed to read JSON from {target}."

    if name == "edit_json":
        path = _path(args, metadata)
        operation = str(args.get("operation") or metadata.get("operation") or "set").strip()
        json_path = str(args.get("json_path") or metadata.get("json_path") or "").strip()
        target = f"{path} :: {json_path}" if json_path else path
        if stage == "start":
            return f"Applying JSON `{operation}` at {target}."
        if success:
            return f"Applied JSON `{operation}` at {target}."
        return f"Failed JSON `{operation}` at {target}."

    if name in {"read_toml", "read_yaml"}:
        path = _path(args, metadata)
        key_path = str(args.get("key_path") or metadata.get("key_path") or "").strip()
        target = f"{path} :: {key_path}" if key_path else path
        kind = "TOML" if name == "read_toml" else "YAML"
        if stage == "start":
            return f"Reading {kind} from {target}."
        if success:
            return f"Loaded {kind} from {target}."
        return f"Failed to read {kind} from {target}."

    if name in {"write_toml", "write_yaml"}:
        path = _path(args, metadata)
        operation = str(args.get("operation") or metadata.get("operation") or "set").strip()
        key_path = str(args.get("key_path") or metadata.get("key_path") or "").strip()
        target = f"{path} :: {key_path}" if key_path else path
        kind = "TOML" if name == "write_toml" else "YAML"
        if stage == "start":
            return f"Applying {kind} `{operation}` at {target}."
        if success:
            return f"Applied {kind} `{operation}` at {target}."
        return f"Failed {kind} `{operation}` at {target}."

    if name == "read_env":
        path = _path(args, metadata)
        key = str(args.get("key") or metadata.get("key") or "").strip()
        target = f"{path} :: {key}" if key else path
        if stage == "start":
            return f"Reading env values from {target}."
        if success:
            return f"Loaded env values from {target}."
        return f"Failed to read env values from {target}."

    if name == "write_env":
        path = _path(args, metadata)
        key = str(args.get("key") or metadata.get("key") or "").strip()
        operation = str(args.get("operation") or metadata.get("operation") or "set").strip()
        target = f"{path} :: {key}" if key else path
        if stage == "start":
            return f"Applying env `{operation}` at {target}."
        if success:
            return f"Applied env `{operation}` at {target}."
        return f"Failed env `{operation}` at {target}."

    if name in {"run_tests", "run_linter", "run_typecheck"}:
        command = str(args.get("command") or metadata.get("command") or "").strip()
        label = {
            "run_tests": "tests",
            "run_linter": "linter",
            "run_typecheck": "typecheck",
        }[name]
        if command:
            if stage == "start":
                return f"Running {label}: `{_trim(command, 100)}`."
            if success:
                return f"Finished {label}: `{_trim(command, 100)}`."
            return f"{label.capitalize()} failed: `{_trim(command, 100)}`."
        if stage == "start":
            return f"Running {label}."
        if success:
            return f"Finished {label}."
        return f"{label.capitalize()} failed."

    if name == "git_status":
        branch = str(metadata.get("branch") or "").strip()
        if stage == "start":
            return f"Checking git status for {branch}." if branch else "Checking git status."
        if success:
            return f"Updated git status for {branch}." if branch else "Updated git status."
        return f"Failed to check git status for {branch}." if branch else "Failed to check git status."

    if name == "git_diff":
        selection = str(metadata.get("selection") or "").strip() or "working tree"
        path = str(args.get("path", "")).strip()
        if stage == "start":
            return f"Inspecting {selection} diff for {path}." if path else f"Inspecting {selection} diff."
        if success:
            return f"Loaded {selection} diff for {path}." if path else f"Loaded {selection} diff."
        return f"Failed to load {selection} diff for {path}." if path else f"Failed to load {selection} diff."

    if name == "git_log":
        ref = str(args.get("ref") or metadata.get("ref") or "HEAD").strip()
        limit = args.get("limit") or metadata.get("count")
        if stage == "start":
            return f"Reading recent commits from {ref}."
        if success and isinstance(limit, int):
            return f"Loaded {limit} recent commit{'s' if limit != 1 else ''} from {ref}."
        if success:
            return f"Loaded recent commits from {ref}."
        return f"Failed to read commit history from {ref}."

    if name == "git_branch":
        action = str(args.get("action", "")).strip().lower() or str(metadata.get("action", "")).strip().lower() or "list"
        branch = str(args.get("branch") or metadata.get("branch") or "").strip()
        if stage == "start":
            return f"Running branch action `{action}` for {branch}." if branch else f"Running branch action `{action}`."
        if success:
            return f"Completed branch action `{action}` for {branch}." if branch else f"Completed branch action `{action}`."
        return f"Failed branch action `{action}` for {branch}." if branch else f"Failed branch action `{action}`."

    if name == "git_remote":
        action = str(args.get("action", "")).strip().lower() or str(metadata.get("action", "")).strip().lower() or "list"
        remote = str(args.get("name") or metadata.get("name") or "").strip()
        if stage == "start":
            return f"Running remote action `{action}` for {remote}." if remote else f"Running remote action `{action}`."
        if success:
            return f"Completed remote action `{action}` for {remote}." if remote else f"Completed remote action `{action}`."
        return f"Failed remote action `{action}` for {remote}." if remote else f"Failed remote action `{action}`."

    if name == "git_commit":
        message = str(args.get("message") or metadata.get("message") or "").strip()
        if stage == "start":
            return f"Creating commit: {_trim(message, 72)}" if message else "Creating git commit."
        if success:
            return f"Created commit: {_trim(message, 72)}" if message else "Created git commit."
        return f"Failed to create commit: {_trim(message, 72)}" if message else "Failed to create git commit."

    if name == "git_push":
        target = str(metadata.get("upstream") or metadata.get("remote_name") or "").strip()
        if stage == "start":
            return f"Publishing current branch to {target}." if target else "Publishing current branch."
        if success:
            return f"Published current branch to {target}." if target else "Published current branch."
        return f"Failed to publish current branch to {target}." if target else "Failed to publish current branch."

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
    elif name == "shell_start":
        label = "Starting shell session"
    elif name == "shell_poll":
        label = "Checking shell session"
    elif name == "shell_send":
        label = "Sending shell input"
    elif name == "shell_stop":
        label = "Stopping shell session"
    elif name == "spawn_subagent":
        label = "Starting specialist"
    elif name == "wait_subagent":
        label = "Waiting on specialists"
    elif name == "list_subagents":
        label = "Checking specialists"
    elif name == "cancel_subagent":
        label = "Cancelling specialists"
    elif name == "web_search":
        label = "Researching web"
    elif name == "web_fetch":
        label = "Reading source"
    elif name == "http_request":
        label = "Sending HTTP request"
    elif name == "list_archive":
        label = "Inspecting archive"
    elif name == "read_pdf":
        label = "Reading PDF"
    elif name == "read_image":
        label = "Reading image"
    elif name == "todos":
        scope = str(args.get("scope", "")).strip() or str(md.get("scope", "")).strip()
        label = "Updating planning checklist" if scope == "planning" else "Updating checklist"
    elif name == "memory":
        label = "Updating memory"
    elif name == "read_json":
        label = "Reading JSON"
    elif name == "edit_json":
        label = "Updating JSON"
    elif name == "read_toml":
        label = "Reading TOML"
    elif name == "write_toml":
        label = "Updating TOML"
    elif name == "read_yaml":
        label = "Reading YAML"
    elif name == "write_yaml":
        label = "Updating YAML"
    elif name == "read_env":
        label = "Reading env file"
    elif name == "write_env":
        label = "Updating env file"
    elif name == "run_tests":
        label = "Running tests"
    elif name == "run_linter":
        label = "Running linter"
    elif name == "run_typecheck":
        label = "Running typecheck"
    elif name == "git_status":
        label = "Checking git status"
    elif name == "git_diff":
        label = "Inspecting diff"
    elif name == "git_log":
        label = "Reading git history"
    elif name == "git_branch":
        label = "Managing branches"
    elif name == "git_remote":
        label = "Managing remotes"
    elif name == "git_commit":
        label = "Creating commit"
    elif name == "git_push":
        label = "Publishing branch"
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
