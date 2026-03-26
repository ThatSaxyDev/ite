from __future__ import annotations

import json
import re
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ite.skills import build_skills_tool_renderable
from ite.ui.tool_narrative import describe_tool_activity


def ordered_args(tool_name: str, args: dict[str, Any]) -> list[tuple[str, Any]]:
    preferred_order = {
        "read_file": ["path", "offset", "limit"],
        "write_file": ["path", "create_directories", "content"],
        "edit": ["path", "replace_all", "old_string", "new_string"],
        "shell": ["command", "timeout", "cwd"],
        "shell_start": ["command", "cwd"],
        "shell_poll": ["session_id", "cursor", "max_bytes"],
        "shell_send": ["session_id", "input", "append_newline"],
        "shell_stop": ["session_id"],
        "http_request": ["method", "url", "params", "headers", "json_body", "body", "timeout"],
        "list_archive": ["path", "limit"],
        "read_pdf": ["path", "pages", "max_pages"],
        "read_image": ["path", "ocr"],
        "list_dir": ["path", "include_hidden"],
        "grep": ["path", "case_insensitive", "pattern"],
        "glob": ["path", "pattern"],
        "read_toml": ["path", "key_path"],
        "write_toml": ["path", "key_path", "operation", "value", "create_missing"],
        "read_yaml": ["path", "key_path"],
        "write_yaml": ["path", "key_path", "operation", "value", "create_missing"],
        "read_env": ["path", "key"],
        "write_env": ["path", "key", "operation", "value"],
    }

    preferred = preferred_order.get(tool_name, [])
    ordered: list[tuple[str, Any]] = []
    seen: set[str] = set()

    for key in preferred:
        if key in args:
            ordered.append((key, args[key]))
            seen.add(key)

    for key, value in args.items():
        if key not in seen:
            ordered.append((key, value))

    return ordered


def display_path(path: str, *, cwd: Path) -> str:
    try:
        base = cwd.resolve()
        target = Path(path).expanduser().resolve()
        return str(target.relative_to(base))
    except Exception:
        return path


def summarize_subagent_goal(goal: str, *, max_chars: int = 22) -> str:
    text = " ".join(str(goal or "").strip().split())
    if not text:
        return ""
    for prefix in (
        "investigate ",
        "inspect ",
        "review ",
        "analyze ",
        "audit ",
        "check ",
        "research ",
        "look at ",
        "explore ",
    ):
        lowered = text.lower()
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    for separator in (". ", ": ", " - ", "; ", ", then ", ", and "):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
            break
    if len(text) <= max_chars:
        return text
    words = text.split()
    compact = ""
    for word in words:
        candidate = f"{compact} {word}".strip()
        if len(candidate) > max_chars:
            break
        compact = candidate
    compact = compact or text[: max_chars - 3].rstrip()
    if compact != text:
        compact = compact.rstrip() + "..."
    return compact


def todo_start_hint(arguments: dict[str, Any]) -> str:
    scope = str(arguments.get("scope", "execution")).strip().lower()
    action = str(arguments.get("action", "update")).strip().lower()
    label = "planning checklist" if scope == "planning" else "task checklist"

    if action == "add":
        count = 0
        items = arguments.get("items")
        if isinstance(items, list):
            count = len(items)
        elif isinstance(arguments.get("content"), str) and arguments.get("content"):
            count = 1
        return f"Creating {label}" + (f" ({count} items)" if count else "")
    if action == "complete":
        return f"Marking item complete in {label}"
    if action == "reopen":
        return f"Reopening item in {label}"
    if action == "remove":
        return f"Removing item from {label}"
    if action == "update":
        return f"Updating item in {label}"
    if action == "list":
        return f"Refreshing {label}"
    if action == "clear":
        return f"Clearing {label}"
    return "Updating checklist"


def truncate_for_tool(name: str, text: str) -> tuple[str, bool]:
    if not text:
        return "", False

    max_lines_by_tool = {
        "read_file": 10,
        "write_file": 10,
        "edit": 10,
        "list_dir": 7,
        "glob": 7,
        "grep": 14,
        "shell": 12,
        "shell_start": 8,
        "shell_poll": 8,
        "shell_send": 8,
        "shell_stop": 8,
        "http_request": 14,
        "list_archive": 14,
        "read_pdf": 14,
        "read_image": 14,
        "web_fetch": 14,
        "web_search": 12,
        "todos": 8,
        "memory": 8,
        "read_json": 14,
        "edit_json": 14,
        "read_toml": 14,
        "write_toml": 14,
        "read_yaml": 14,
        "write_yaml": 14,
        "read_env": 14,
        "write_env": 14,
        "run_tests": 18,
        "run_linter": 18,
        "run_typecheck": 18,
    }
    max_chars_by_tool = {
        "read_file": 1500,
        "write_file": 1400,
        "edit": 1400,
        "list_dir": 600,
        "glob": 600,
        "grep": 1700,
        "shell": 1400,
        "shell_start": 1000,
        "shell_poll": 1000,
        "shell_send": 1000,
        "shell_stop": 1000,
        "http_request": 1800,
        "list_archive": 1600,
        "read_pdf": 2200,
        "read_image": 1800,
        "web_fetch": 1800,
        "web_search": 1400,
        "todos": 900,
        "memory": 800,
        "read_json": 1800,
        "edit_json": 1800,
        "read_toml": 1800,
        "write_toml": 1800,
        "read_yaml": 1800,
        "write_yaml": 1800,
        "read_env": 1600,
        "write_env": 1600,
        "run_tests": 2200,
        "run_linter": 2200,
        "run_typecheck": 2200,
    }

    max_lines = max_lines_by_tool.get(name, 16)
    max_chars = max_chars_by_tool.get(name, 1800)

    clipped = text
    was_truncated = False

    lines = clipped.splitlines()
    if len(lines) > max_lines:
        clipped = "\n".join(lines[:max_lines])
        was_truncated = True

    if len(clipped) > max_chars:
        clipped = clipped[:max_chars]
        was_truncated = True

    return clipped, was_truncated


def extract_read_file_code(text: str) -> tuple[int, str] | None:
    body = text
    header_match = re.match(r"Showing lines (\d+)-(\d+) of (\d+)\n\n", text)
    if header_match:
        body = text[header_match.end() :]

    code_lines: list[str] = []
    start_line: int | None = None
    for line in body.splitlines():
        match = re.match(r"^\s*(\d+)\|(.*)$", line)
        if not match:
            return None
        line_no = int(match.group(1))
        if start_line is None:
            start_line = line_no
        code_lines.append(match.group(2))

    if start_line is None:
        return None
    return start_line, "\n".join(code_lines)


def extract_diff_hunk_headers(diff_text: str) -> list[str]:
    headers: list[str] = []
    for line in (diff_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("@@"):
            headers.append(stripped)
    return headers


def summarize_diff_hunk_ranges(diff_text: str) -> list[str]:
    summaries: list[str] = []
    pattern = re.compile(
        r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@"
    )
    for header in extract_diff_hunk_headers(diff_text):
        match = pattern.match(header)
        if not match:
            continue
        old_start = int(match.group("old_start"))
        old_count = int(match.group("old_count") or "1")
        new_start = int(match.group("new_start"))
        new_count = int(match.group("new_count") or "1")
        old_end = old_start + max(old_count - 1, 0)
        new_end = new_start + max(new_count - 1, 0)
        summaries.append(f"old {old_start}-{old_end} -> new {new_start}-{new_end}")
    return summaries


def render_numbered_unified_diff(diff_text: str) -> Text:
    hunk_re = re.compile(
        r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? \+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@"
    )
    rendered = Text(no_wrap=True)
    old_lineno = 0
    new_lineno = 0
    gutter_style = "#7d8591"
    context_style = "#edf1f7"
    add_style = "#8fb7a1"
    del_style = "#d8ab74"
    hunk_style = "#b7c8e1"

    def append_line(
        old_label: str,
        new_label: str,
        marker: str,
        content: str,
        *,
        marker_style: str,
        content_style: str,
    ) -> None:
        rendered.append(f"{old_label:>5} ", style=gutter_style)
        rendered.append(f"{new_label:>5} ", style=gutter_style)
        rendered.append(marker, style=marker_style)
        rendered.append(" ")
        rendered.append(content, style=content_style)
        rendered.append("\n")

    for line in (diff_text or "").splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            style = del_style if line.startswith("--- ") else add_style
            rendered.append(line, style=style)
            rendered.append("\n")
            continue

        match = hunk_re.match(line)
        if match:
            old_lineno = int(match.group("old"))
            new_lineno = int(match.group("new"))
            rendered.append("  old   new    \n", style=gutter_style)
            rendered.append(line, style=hunk_style)
            rendered.append("\n")
            continue

        if line.startswith("-") and not line.startswith("--- "):
            append_line(
                str(old_lineno),
                "",
                "-",
                line[1:],
                marker_style=del_style,
                content_style=del_style,
            )
            old_lineno += 1
            continue

        if line.startswith("+") and not line.startswith("+++ "):
            append_line(
                "",
                str(new_lineno),
                "+",
                line[1:],
                marker_style=add_style,
                content_style=add_style,
            )
            new_lineno += 1
            continue

        if line.startswith(" "):
            append_line(
                str(old_lineno),
                str(new_lineno),
                " ",
                line[1:],
                marker_style=gutter_style,
                content_style=context_style,
            )
            old_lineno += 1
            new_lineno += 1
            continue

        rendered.append(line, style=context_style)
        rendered.append("\n")

    return rendered


def normalize_unified_diff_paths(diff_text: str, *, cwd: Path) -> str:
    normalized_lines: list[str] = []
    for line in (diff_text or "").splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            prefix, raw_path = line[:4], line[4:].strip()
            if raw_path != "/dev/null":
                raw_path = display_path(raw_path, cwd=cwd)
            normalized_lines.append(f"{prefix}{raw_path}")
            continue
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


def guess_language(path: str | None) -> str:
    if not path:
        return "text"
    ext = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "jsx",
        ".json": "json",
        ".md": "markdown",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".toml": "toml",
        ".css": "css",
        ".html": "html",
        ".sh": "bash",
        ".diff": "diff",
        ".patch": "diff",
    }.get(ext, "text")


def looks_like_markdown(text: str) -> bool:
    if "```" in text:
        return True
    return bool(re.search(r"(?m)^(#{1,6}\s|\* |\d+\.\s|>\s)", text))


def looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )


def render_todo_payload(
    *,
    output: str,
    metadata: dict[str, Any] | None,
) -> tuple[list[Any], bool]:
    md = metadata if isinstance(metadata, dict) else {}
    completed = md.get("completed", 0)
    total = md.get("total", 0)
    action = md.get("action", "")
    scope = md.get("scope", "execution")
    message = md.get("message", "")
    output_display, was_truncated = truncate_for_tool("todos", output)

    blocks: list[Any] = []

    if total > 0:
        bar_width = 10
        filled = int((completed / total) * bar_width) if total else 0
        bar = "█" * filled + "░" * (bar_width - filled)
        header = Text()
        header.append(
            f"{str(scope).capitalize()} tasks: {completed}/{total} completed ",
            style="#8c97ab",
        )
        header.append(bar, style="green" if completed == total else "yellow")
        blocks.append(header)
    elif isinstance(scope, str):
        blocks.append(Text(f"Scope: {scope}", style="#8c97ab"))

    for line in output_display.splitlines():
        stripped = line.strip()
        if stripped.startswith("☑"):
            styled = Text()
            styled.append("  ☑ ", style="bold green")
            styled.append(stripped[1:].strip(), style="dim strike")
            blocks.append(styled)
        elif stripped.startswith("☐"):
            styled = Text()
            styled.append("  ☐ ", style="bold yellow")
            styled.append(stripped[1:].strip(), style="white")
            blocks.append(styled)

    if action == "clear":
        blocks.append(Text("  All todos cleared", style="#8c97ab"))
    elif message:
        blocks.append(Text(f"  {message}", style="#8c97ab"))

    return blocks, was_truncated


def render_args_table(tool_name: str, args: dict[str, Any], *, cwd: Path) -> Table:
    table = Table.grid(padding=(0, 1))
    table.add_column(style="#8c93a1", justify="right", no_wrap=True)
    table.add_column(style="#dfe4ea", overflow="fold")

    for key, value in ordered_args(tool_name, args):
        if key in {"raw", "raw_arguments"}:
            key = "arguments"
        if key in {"path", "cwd"} and isinstance(value, str):
            value = display_path(value, cwd=cwd)
        elif isinstance(value, str) and key in {"content", "old_string", "new_string"}:
            line_count = len(value.splitlines())
            byte_count = len(value.encode("utf-8", errors="replace"))
            value = f"<{line_count} lines, {byte_count} bytes>"
        elif not isinstance(value, str):
            value = str(value)
        table.add_row(key, value)

    return table


def render_list_dir_output(output: str) -> Text:
    def strip_existing_icon(text: str) -> str:
        cleaned = text.lstrip()
        while cleaned and cleaned[0] in {
            "📁",
            "📂",
            "📄",
            "🗀",
            "🗁",
            "🗂",
            "🗃",
            "🗄",
            "🗋",
            "🗎",
        }:
            cleaned = cleaned[1:].lstrip()
        return cleaned

    result = Text()
    for raw_line in output.splitlines():
        line = strip_existing_icon(raw_line.rstrip())
        if not line:
            result.append("\n")
            continue
        if line.endswith("/"):
            result.append("📁 ", style="#b7c8e1")
            result.append(line, style="#edf1f7")
        else:
            result.append("📄 ", style="#8c93a1")
            result.append(line, style="#dfe4ea")
        result.append("\n")
    return result


def render_grep_output(output: str, *, cwd: Path) -> Any:
    groups: list[tuple[str, list[str]]] = []
    current_file: str | None = None
    current_lines: list[str] = []

    for raw in output.splitlines():
        line = raw.rstrip()
        if line.startswith("=== ") and line.endswith(" ==="):
            if current_file is not None:
                groups.append((current_file, current_lines))
            current_file = line[4:-4].strip()
            current_lines = []
            continue
        if current_file is not None and line:
            current_lines.append(line)
    if current_file is not None:
        groups.append((current_file, current_lines))

    if not groups:
        return Syntax(output, "text", theme="monokai", word_wrap=True)

    table = Table.grid(padding=(0, 1))
    table.add_column(style="#8c93a1", justify="right", no_wrap=True)
    table.add_column(style="#dfe4ea")

    for file_path, lines in groups:
        table.add_row("", Text(display_path(file_path, cwd=cwd), style="bold #b7c8e1"))
        for line in lines:
            match = re.match(r"^\s*(\d+):(.*)$", line)
            if match:
                table.add_row(match.group(1), Text(match.group(2).lstrip(), style="#dfe4ea"))
            else:
                table.add_row("", Text(line, style="#dfe4ea"))
        table.add_row("", Text(""))

    return table


def render_git_log_output(metadata: dict[str, Any] | None) -> Any:
    md = metadata if isinstance(metadata, dict) else {}
    commits = md.get("commits")
    if not isinstance(commits, list) or not commits:
        return Text("No commits found.", style="#8c93a1")

    table = Table.grid(padding=(0, 1))
    table.add_column(style="#b7c8e1", no_wrap=True)
    table.add_column(style="#8c93a1", no_wrap=True)
    table.add_column(style="#c6c6cd")
    table.add_column(style="#edf1f7")

    for commit in commits:
        if not isinstance(commit, dict):
            continue
        short_sha = str(commit.get("short_sha", "")).strip()
        date = str(commit.get("date", "")).strip()
        author = str(commit.get("author", "")).strip()
        subject = str(commit.get("subject", "")).strip()
        table.add_row(short_sha, date, author, subject)

    return table


def render_text_payload(text: str, *, success: bool, language: str = "text") -> Any:
    if not text.strip():
        return Text("No output", style="#8c93a1")
    if "\x1b" in text:
        return Text.from_ansi(text)
    if success and looks_like_markdown(text):
        return RichMarkdown(text)
    if success and looks_like_json(text):
        try:
            payload = json.loads(text)
        except Exception:
            pass
        else:
            return Syntax(
                json.dumps(payload, indent=2, ensure_ascii=False),
                "json",
                theme="monokai",
                word_wrap=True,
            )
    if language != "text":
        return Syntax(text, language, theme="monokai", word_wrap=True)
    return Text(text, style="#dfe4ea")


def render_skills_payload(
    *,
    output: str,
    success: bool,
) -> Any:
    if not output.strip():
        return Text("No output", style="#8c93a1")
    if not success:
        clipped, _ = truncate_for_tool("skills", output)
        return render_text_payload(clipped, success=False)
    try:
        payload = json.loads(output)
    except Exception:
        clipped, _ = truncate_for_tool("skills", output)
        return render_text_payload(clipped, success=True)
    if not isinstance(payload, dict):
        clipped, _ = truncate_for_tool("skills", output)
        return render_text_payload(clipped, success=True)
    rendered = build_skills_tool_renderable(payload)
    if rendered is None:
        clipped, _ = truncate_for_tool("skills", output)
        return render_text_payload(clipped, success=True)
    return rendered


def render_subagent_payload(
    *,
    output: str,
    metadata: dict[str, Any] | None,
    success: bool,
    error: str | None,
) -> tuple[list[Any], bool]:
    md = metadata if isinstance(metadata, dict) else {}
    result = md.get("subagent_result")
    trace = md.get("subagent_trace")
    payload: dict[str, Any] = {}
    if isinstance(result, dict):
        payload = result
    elif output.strip():
        try:
            parsed = json.loads(output)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed

    summary = str(payload.get("summary") or "").strip()
    termination = str(payload.get("termination") or "").strip()
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    tools_used = payload.get("tools_used") if isinstance(payload.get("tools_used"), list) else []

    blocks: list[Any] = []
    was_truncated = False

    trace_parts: list[str] = []
    if isinstance(trace, dict):
        child_session_id = str(trace.get("child_session_id") or "").strip()
        if child_session_id:
            trace_parts.append(child_session_id)
        duration_ms = trace.get("duration_ms")
        if isinstance(duration_ms, int):
            trace_parts.append(f"{duration_ms} ms")
        child_turn_count = trace.get("child_turn_count")
        if isinstance(child_turn_count, int):
            trace_parts.append(f"{child_turn_count} turns")
        attempt_count = trace.get("attempt_count")
        if isinstance(attempt_count, int) and attempt_count > 1:
            trace_parts.append(f"{attempt_count} attempts")
        retries_used = trace.get("retries_used")
        if isinstance(retries_used, int) and retries_used > 0:
            trace_parts.append(f"{retries_used} retries")
    if termination:
        trace_parts.append(f"termination={termination}")
    if isinstance(tools_used, list):
        trace_parts.append(f"tools={len(tools_used)}")
    if trace_parts:
        blocks.append(Text(" • ".join(trace_parts), style="#8c97ab"))

    recovered_after_retry = False
    if isinstance(payload.get("recovered_after_retry"), bool):
        recovered_after_retry = payload.get("recovered_after_retry") is True
    elif isinstance(trace, dict):
        recovered_after_retry = trace.get("recovered_after_retry") is True
    if recovered_after_retry:
        blocks.append(Text("Recovered after retry.", style="#7cc7ff"))

    if summary:
        summary_display, truncated = truncate_for_tool("subagent", summary)
        was_truncated = was_truncated or truncated
        blocks.append(render_text_payload(summary_display, success=True))

    if findings:
        blocks.append(Text("Findings", style="bold #7cc7ff"))
        for item in findings[:4]:
            text = str(item).strip()
            if not text:
                continue
            blocks.append(Text(f"• {text}", style="#dfe4ea"))
        if len(findings) > 4:
            blocks.append(Text(f"... {len(findings) - 4} more findings", style="#8c97ab"))

    if actions:
        blocks.append(Text("Actions", style="bold #f5b54f"))
        for item in actions[:4]:
            text = str(item).strip()
            if not text:
                continue
            blocks.append(Text(f"• {text}", style="#dfe4ea"))
        if len(actions) > 4:
            blocks.append(Text(f"... {len(actions) - 4} more actions", style="#8c97ab"))

    failure_text = ""
    if not success:
        failure_text = str(error or "").strip()
        if not failure_text and output.strip():
            failure_text = output.strip()
        if failure_text and failure_text != summary:
            failure_display, truncated = truncate_for_tool("subagent", failure_text)
            was_truncated = was_truncated or truncated
            blocks.append(Text("Failure", style="bold #d8ab74"))
            blocks.append(render_text_payload(failure_display, success=False))

    if not blocks:
        fallback = output.strip() or str(error or "").strip()
        if fallback:
            fallback_display, truncated = truncate_for_tool("subagent", fallback)
            was_truncated = was_truncated or truncated
            blocks.append(render_text_payload(fallback_display, success=success))
        else:
            blocks.append(Text("No output", style="#8c97ab"))

    return blocks, was_truncated


def render_subagent_runtime_payload(
    *,
    metadata: dict[str, Any] | None,
    output: str = "",
    error: str | None = None,
    success: bool = True,
    collapse_completed: bool = False,
) -> list[Any]:
    def age_label(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            return ""
        try:
            updated_at = datetime.fromisoformat(value)
            now = datetime.now(updated_at.tzinfo or timezone.utc)
            seconds = max(0, int((now - updated_at).total_seconds()))
        except Exception:
            return ""
        if seconds < 2:
            return "updated just now"
        if seconds < 60:
            return f"updated {seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"updated {minutes}m ago"
        hours = minutes // 60
        return f"updated {hours}h ago"

    md = metadata if isinstance(metadata, dict) else {}
    blocks: list[Any] = []

    requested_subagent = str(md.get("requested_subagent") or "").strip()
    selected_subagent = str(md.get("selected_subagent") or "").strip()
    if md.get("reused_existing") is True:
        blocks.append(Text("Reused matching active specialist run.", style="#8c97ab"))
    if requested_subagent and selected_subagent:
        blocks.append(
            Text(
                f"Used `{selected_subagent}` for requested specialist `{requested_subagent}`.",
                style="#8c97ab",
            )
        )

    available_subagents = md.get("available_subagents")
    if isinstance(available_subagents, list) and available_subagents:
        blocks.append(
            Text(
                "Available specialists: " + ", ".join(str(item) for item in available_subagents if str(item).strip()),
                style="#8c97ab",
            )
        )
    if md.get("circuit_open") is True:
        reopen_at = str(md.get("circuit_reopen_at") or "").strip()
        failure_count = md.get("failure_count")
        parts = ["Specialist circuit breaker is open."]
        if isinstance(failure_count, int) and failure_count > 0:
            parts.append(f"{failure_count} recent failures/timeouts.")
        if reopen_at:
            parts.append(f"Retry after {reopen_at}.")
        blocks.append(Text(" ".join(parts), style="#d8ab74"))

    runs = md.get("runs")
    if not isinstance(runs, list) or not runs:
        run = md.get("run")
        runs = [run] if isinstance(run, dict) else []

    if not runs:
        failure_text = str(error or output or "").strip()
        if failure_text and not success:
            blocks.append(Text("Failure", style="bold #d8ab74"))
            blocks.append(render_text_payload(failure_text, success=False))
        else:
            blocks.append(Text("No specialist runs.", style="#8c97ab"))
        return blocks

    table = Table.grid(padding=(0, 1))
    table.add_column(style="#b7c8e1", no_wrap=True)
    table.add_column(style="#8c97ab", no_wrap=True)
    table.add_column(style="#dfe4ea")

    for run in runs[:12]:
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("run_id") or "").strip()
        goal_label = summarize_subagent_goal(str(run.get("goal") or "").strip())
        status = str(run.get("status") or "").strip()
        if collapse_completed and status in {"completed", "failed", "timeout", "cancelled"}:
            detail = ""
        else:
            detail = str(
                run.get("current_activity")
                or run.get("summary")
                or run.get("goal")
                or ""
            ).strip()
            freshness = age_label(run.get("last_update_at"))
            if freshness:
                detail = f"{freshness}  •  {detail}" if detail else freshness
        if len(detail) > 120:
            detail = detail[:117].rstrip() + "..."
        run_label = Text(run_id, style="#b7c8e1")
        if goal_label:
            run_label.append(" · ", style="#667084")
            run_label.append(goal_label, style="#8c97ab")
        table.add_row(run_label, status or "unknown", detail or " ")

    blocks.append(table)

    first_run = runs[0] if runs and isinstance(runs[0], dict) else None
    history = first_run.get("activity_history") if isinstance(first_run, dict) else None
    if not collapse_completed and isinstance(history, list) and history:
        blocks.append(Text("Recent activity", style="bold #d8ab74"))
        for entry in history[-3:]:
            if not isinstance(entry, dict):
                continue
            message = str(entry.get("message") or "").strip()
            freshness = age_label(entry.get("at"))
            line = "  •  ".join(part for part in [freshness, message] if part)
            if line:
                blocks.append(Text(f"• {line}", style="#8c97ab"))

    completed = md.get("completed_run_ids")
    pending = md.get("pending_run_ids")
    cancelled = md.get("cancelled_run_ids")
    notes: list[str] = []
    if isinstance(completed, list):
        notes.append(f"completed={len(completed)}")
    if isinstance(pending, list):
        notes.append(f"pending={len(pending)}")
    if isinstance(cancelled, list):
        notes.append(f"cancelled={len(cancelled)}")
    if notes:
        blocks.append(Text(" • ".join(notes), style="#8c97ab"))
    return blocks


def render_subagent_metrics_payload(
    *,
    metadata: dict[str, Any] | None,
    output: str = "",
    error: str | None = None,
    success: bool = True,
) -> list[Any]:
    md = metadata if isinstance(metadata, dict) else {}
    blocks: list[Any] = []

    if not success:
        failure_text = str(error or output or "").strip()
        if failure_text:
            blocks.append(Text("Failure", style="bold #d8ab74"))
            blocks.append(render_text_payload(failure_text, success=False))
        else:
            blocks.append(Text("No metrics available.", style="#8c97ab"))
        return blocks

    totals = md.get("totals")
    if not isinstance(totals, dict):
        blocks.append(Text("No metrics available.", style="#8c97ab"))
        return blocks

    restored = bool(md.get("restored_from_snapshot"))

    historical = Table.grid(padding=(0, 1))
    historical.add_column(style="#d8ab74", no_wrap=True)
    historical.add_column(style="#edf1f7")
    historical.add_row("Historical session totals", "restored from saved session" if restored else "live session history")
    historical.add_row("Spawned runs", str(int(totals.get("spawned_runs") or 0)))
    historical.add_row("Completed", str(int(totals.get("completed") or 0)))
    historical.add_row("Failed", str(int(totals.get("failed") or 0)))
    historical.add_row("Timeout", str(int(totals.get("timeout") or 0)))
    historical.add_row("Cancelled", str(int(totals.get("cancelled") or 0)))
    historical.add_row("Retries used", str(int(totals.get("retries_used") or 0)))
    historical.add_row("Recovered after retry", str(int(totals.get("recovered_after_retry") or 0)))
    blocks.append(historical)

    live = Table.grid(padding=(0, 1))
    live.add_column(style="#b7c8e1", no_wrap=True)
    live.add_column(style="#edf1f7")
    live.add_row("Live runtime state", "current process")
    live.add_row("Active runs", str(int(totals.get("active_runs") or 0)))
    live.add_row("Retained runs", str(int(totals.get("retained_runs") or 0)))
    live.add_row("Circuit breaker blocks", str(int(totals.get("circuit_breaker_blocks") or 0)))
    live.add_row("Circuit breaker trips", str(int(totals.get("circuit_breaker_trips") or 0)))
    blocks.append(live)

    open_circuits = md.get("open_circuits")
    if isinstance(open_circuits, dict) and open_circuits:
        blocks.append(Text("Open circuits", style="bold #d8ab74"))
        for subagent, reopen_at in open_circuits.items():
            blocks.append(Text(f"{subagent}: retry after {reopen_at}", style="#8c97ab"))

    return blocks


_SHELL_STDERR_MARKER_RE = re.compile(r"(?:^|\n)\s*--- STDERR ---\s*\n", re.MULTILINE)
_TERMINAL_CLEAR_RE = re.compile(r"\x1b\[(?:2K|K)")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_PROGRESS_LINE_RE = re.compile(r"^\s*\d{1,3}%\s")


def split_shell_payload(payload: str) -> tuple[str, str]:
    if not payload.strip():
        return "", ""
    parts = _SHELL_STDERR_MARKER_RE.split(payload)
    if len(parts) == 1:
        return payload.strip(), ""
    stdout = parts[0].strip()
    stderr = "\n".join(part.strip() for part in parts[1:] if part.strip())
    return stdout, stderr


def collapse_terminal_rewrites(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n")
    lines: list[list[str]] = [[]]
    row = 0
    col = 0

    def ensure_line(index: int) -> list[str]:
        while len(lines) <= index:
            lines.append([])
        return lines[index]

    def write_char(ch: str) -> None:
        nonlocal col
        line = ensure_line(row)
        while len(line) < col:
            line.append(" ")
        if col < len(line):
            line[col] = ch
        else:
            line.append(ch)
        col += 1

    index = 0
    text_len = len(normalized)
    while index < text_len:
        ch = normalized[index]
        if ch == "\x1b" and index + 1 < text_len and normalized[index + 1] == "[":
            match = re.match(r"\x1b\[([0-9;?]*)([A-Za-z])", normalized[index:])
            if match:
                params_text, command = match.groups()
                params = [int(part) for part in params_text.split(";") if part.isdigit()]
                amount = params[0] if params else 1
                if command == "A":
                    row = max(0, row - amount)
                elif command == "B":
                    row += amount
                    ensure_line(row)
                elif command == "C":
                    col += amount
                elif command == "D":
                    col = max(0, col - amount)
                elif command == "K":
                    line = ensure_line(row)
                    mode = params[0] if params else 0
                    if mode == 2:
                        line.clear()
                        col = 0
                    elif mode == 1:
                        del line[:col]
                        col = 0
                    else:
                        del line[col:]
                index += match.end()
                continue
        if ch == "\n":
            row += 1
            col = 0
            ensure_line(row)
            index += 1
            continue
        if ch == "\r":
            col = 0
            index += 1
            continue
        if ch == "\b":
            col = max(0, col - 1)
            index += 1
            continue
        if ch == "\x1b":
            index += 1
            continue
        write_char(ch)
        index += 1

    lines_plain = ["".join(line).rstrip() for line in lines]
    compacted_lines: list[str] = []
    pending_progress: str | None = None
    for line in lines_plain:
        plain = line.strip()
        is_progress = bool(_PROGRESS_LINE_RE.match(plain))
        if is_progress:
            pending_progress = line
            continue
        if pending_progress is not None:
            compacted_lines.append(pending_progress)
            pending_progress = None
        compacted_lines.append(line)
    if pending_progress is not None:
        compacted_lines.append(pending_progress)
    return "\n".join(compacted_lines).strip()


def render_terminal_payload(text: str, *, tone: str = "stdout") -> Any:
    collapsed = collapse_terminal_rewrites(text)
    if not collapsed:
        return Text("No output", style="#8c97ab")
    if "\x1b" in collapsed:
        return Text.from_ansi(collapsed)
    style = "#dfe4ea" if tone == "stdout" else "#f0c48d"
    return Text(collapsed, style=style)


def render_terminal_snapshot_payload(
    text: str,
    *,
    tone: str = "stdout",
    max_lines: int | None = None,
    max_chars: int = 16000,
) -> Any:
    if not text:
        return Text("No output", style="#8c97ab")
    window = text[-max_chars:] if len(text) > max_chars else text
    collapsed = collapse_terminal_rewrites(window)
    if not collapsed:
        return Text("No output", style="#8c97ab")
    if max_lines is not None:
        lines = collapsed.splitlines()
        if len(lines) > max_lines:
            collapsed = "\n".join(lines[-max_lines:])
    if "\x1b" in collapsed:
        return Text.from_ansi(collapsed)
    style = "#dfe4ea" if tone == "stdout" else "#f0c48d"
    return Text(collapsed, style=style)


def shell_session_state(metadata: dict[str, Any] | None) -> str:
    md = metadata if isinstance(metadata, dict) else {}
    status = str(md.get("status") or "").strip().lower()
    if status:
        return status
    if md.get("running") is False:
        return "exited"
    if md.get("running") is True:
        if bool(md.get("has_new_output")):
            return "command_running"
        return "idle"
    return "unknown"


def shell_session_status_label(metadata: dict[str, Any] | None, *, running_suffix: str = "") -> tuple[str, str]:
    state = shell_session_state(metadata)
    if state == "command_running":
        return "command running" + running_suffix, "#b7c8e1"
    if state == "idle":
        return "idle", "#8c97ab"
    if state == "stopped":
        return "stopped", "#8c97ab"
    if state == "exited":
        return "exited", "#8c97ab"
    return state.replace("_", " "), "#8c97ab"


def shell_spinner_frame(index: int) -> str:
    frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    return frames[index % len(frames)]


def render_shell_command_line(command: str, *, cwd: Path, shell_cwd: str | None = None) -> Table:
    table = Table.grid(expand=True)
    table.add_column(width=2)
    table.add_column(ratio=1)
    table.add_row(
        Text("$", style="bold #7cc7ff"),
        Text(command.strip() or "(no command)", style="#dbe4f2"),
    )
    if isinstance(shell_cwd, str) and shell_cwd.strip():
        table.add_row(
            Text(""),
            Text(f"in {display_path(shell_cwd.strip(), cwd=cwd)}", style="#8c93a1"),
        )
    return table


def render_shell_running_card(
    arguments: dict[str, Any],
    *,
    cwd: Path,
    spinner_index: int,
) -> Group:
    command = str(arguments.get("command", "")).strip()
    shell_cwd = arguments.get("cwd") if isinstance(arguments.get("cwd"), str) else None
    header = Text()
    header.append(f"{shell_spinner_frame(spinner_index)} ", style="bold #b7c8e1")
    header.append("Running in shell", style="bold #edf1f7")
    header.append("  live", style="#8c93a1")
    return Group(
        header,
        Text(describe_tool_activity("shell", arguments, stage="start"), style="#8c93a1"),
        render_shell_command_line(command, cwd=cwd, shell_cwd=shell_cwd),
    )


def render_shell_result_payload(
    *,
    payload: str,
    metadata: dict[str, Any] | None,
    exit_code: int | None,
    running_suffix: str = "",
) -> list[Any]:
    md = metadata if isinstance(metadata, dict) else {}
    session_id = str(md.get("session_id") or "").strip()
    has_new_output = bool(md.get("has_new_output"))
    running = md.get("running")
    stdout_text, stderr_text = split_shell_payload(payload)
    blocks: list[Any] = []

    summary = Text()
    if session_id:
        summary.append(session_id, style="#8c97ab")
    if isinstance(running, bool) or md.get("status"):
        if summary.plain:
            summary.append("  •  ", style="#667084")
        status_label, status_style = shell_session_status_label(
            md,
            running_suffix=running_suffix,
        )
        summary.append(status_label, style=status_style)
    if exit_code is not None:
        if summary.plain:
            summary.append("  •  ", style="#667084")
        summary.append(f"exit {exit_code}", style="#8c97ab")
    if md.get("timed_out"):
        if summary.plain:
            summary.append("  •  ", style="#667084")
        summary.append("timed out", style="#f5b54f")
    if summary.plain:
        blocks.append(summary)

    if not has_new_output and session_id:
        if isinstance(running, bool) and not running:
            blocks.append(Text("No new output.", style="#8c97ab"))
        else:
            blocks.append(Text("No new output yet.", style="#8c97ab"))
        return blocks

    if not stdout_text and not stderr_text:
        blocks.append(Text("No output", style="#8c97ab"))
        return blocks

    if stdout_text and stderr_text:
        blocks.append(render_terminal_payload(stdout_text, tone="stdout"))
        blocks.append(Text("stderr", style="bold #d8ab74"))
        blocks.append(render_terminal_payload(stderr_text, tone="stderr"))
    elif stdout_text:
        blocks.append(render_terminal_payload(stdout_text, tone="stdout"))
    else:
        blocks.append(render_terminal_payload(stderr_text, tone="stderr"))
    return blocks
