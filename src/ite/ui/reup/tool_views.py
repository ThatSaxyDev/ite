from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ite.ui.tool_narrative import describe_tool_activity


def ordered_args(tool_name: str, args: dict[str, Any]) -> list[tuple[str, Any]]:
    preferred_order = {
        "read_file": ["path", "offset", "limit"],
        "write_file": ["path", "create_directories", "content"],
        "edit": ["path", "replace_all", "old_string", "new_string"],
        "shell": ["command", "timeout", "cwd"],
        "list_dir": ["path", "include_hidden"],
        "grep": ["path", "case_insensitive", "pattern"],
        "glob": ["path", "pattern"],
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
        "web_fetch": 14,
        "web_search": 12,
        "todos": 8,
        "memory": 8,
    }
    max_chars_by_tool = {
        "read_file": 1500,
        "write_file": 1400,
        "edit": 1400,
        "list_dir": 600,
        "glob": 600,
        "grep": 1700,
        "shell": 1400,
        "web_fetch": 1800,
        "web_search": 1400,
        "todos": 900,
        "memory": 800,
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
    gutter_style = "#7f8ea3"
    context_style = "#e7edf7"
    add_style = "#a7f36b"
    del_style = "#ff9bb7"
    hunk_style = "#b6b09c"

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
    table.add_column(style="#7d8aa5", justify="right", no_wrap=True)
    table.add_column(style="#d5d9e2", overflow="fold")

    for key, value in ordered_args(tool_name, args):
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
            result.append("📁 ", style="#9bc7ff")
            result.append(line, style="#dce6ff")
        else:
            result.append("📄 ", style="#9da9bd")
            result.append(line, style="#d5d9e2")
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
    table.add_column(style="#8c97ab", justify="right", no_wrap=True)
    table.add_column(style="#d5d9e2")

    for file_path, lines in groups:
        table.add_row("", Text(display_path(file_path, cwd=cwd), style="bold #9bc7ff"))
        for line in lines:
            match = re.match(r"^\s*(\d+):(.*)$", line)
            if match:
                table.add_row(match.group(1), Text(match.group(2).lstrip(), style="#d5d9e2"))
            else:
                table.add_row("", Text(line, style="#d5d9e2"))
        table.add_row("", Text(""))

    return table


def render_git_log_output(metadata: dict[str, Any] | None) -> Any:
    md = metadata if isinstance(metadata, dict) else {}
    commits = md.get("commits")
    if not isinstance(commits, list) or not commits:
        return Text("No commits found.", style="#8c97ab")

    table = Table.grid(padding=(0, 1))
    table.add_column(style="#7cc7ff", no_wrap=True)
    table.add_column(style="#8c97ab", no_wrap=True)
    table.add_column(style="#b9c3d6")
    table.add_column(style="#dfe8f8")

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
        return Text("No output", style="#8c97ab")
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
    return Syntax(text, language, theme="monokai", word_wrap=True)


def split_shell_payload(payload: str) -> tuple[str, str]:
    marker = "\n\n--- STDERR ---\n"
    if marker in payload:
        stdout, stderr = payload.split(marker, 1)
        return stdout.strip(), stderr.strip()
    if payload.startswith("--- STDERR ---\n"):
        return "", payload.replace("--- STDERR ---\n", "", 1).strip()
    return payload.strip(), ""


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
            Text(f"in {display_path(shell_cwd.strip(), cwd=cwd)}", style="#8c97ab"),
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
    header.append(f"{shell_spinner_frame(spinner_index)} ", style="bold #9bc7ff")
    header.append("Running in shell", style="bold #9bc7ff")
    header.append("  live", style="#8c97ab")
    return Group(
        header,
        Text(""),
        Text(describe_tool_activity("shell", arguments, stage="start"), style="#8c97ab"),
        Text(""),
        render_shell_command_line(command, cwd=cwd, shell_cwd=shell_cwd),
    )


def render_shell_result_payload(
    *,
    payload: str,
    metadata: dict[str, Any] | None,
    exit_code: int | None,
) -> list[Any]:
    md = metadata if isinstance(metadata, dict) else {}
    stdout_text, stderr_text = split_shell_payload(payload)
    blocks: list[Any] = []

    summary = Text()
    safety = md.get("safety_classification")
    if isinstance(safety, str) and safety.strip():
        summary.append(f"{safety} command", style="#8c97ab")
    if exit_code is not None:
        if summary.plain:
            summary.append("  •  ", style="#667084")
        summary.append(f"exit {exit_code}", style="#8c97ab")
    if md.get("timed_out"):
        if summary.plain:
            summary.append("  •  ", style="#667084")
        summary.append("timed out", style="#f5b54f")
    if summary.plain:
        blocks.extend([summary, Text("")])

    if stdout_text:
        blocks.append(Text("stdout", style="bold #7ad69f"))
        blocks.append(render_text_payload(stdout_text, success=True))
        blocks.append(Text(""))
    if stderr_text:
        blocks.append(Text("stderr", style="bold #f5b54f"))
        blocks.append(render_text_payload(stderr_text, success=False))
        blocks.append(Text(""))

    if not stdout_text and not stderr_text:
        blocks.append(Text("No output", style="#8c97ab"))
    elif blocks and isinstance(blocks[-1], Text) and blocks[-1].plain == "":
        blocks.pop()

    return blocks
