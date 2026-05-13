from __future__ import annotations

import json
import os
import re
import subprocess
import platform
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


def detect_host_textual_theme() -> str:
    """Best-effort detection for the host light / dark appearance."""
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=0.5,
                check=False,
            )
        except Exception:
            result = None
        if result is not None:
            if result.returncode == 0 and "dark" in result.stdout.lower():
                return "textual-dark"
            if result.returncode != 0:
                return "textual-light"

    colorfgbg = os.environ.get("COLORFGBG", "").strip()
    if colorfgbg:
        try:
            background = int(colorfgbg.split(";")[-1])
        except ValueError:
            return "textual-dark"
        return "textual-dark" if background in {0, 1, 2, 3, 4, 5, 6, 8} else "textual-light"

    return "textual-dark"


def normalize_syntax_theme(theme: str | None) -> str:
    """Use Textual's theme names for Rich syntax output."""
    value = str(theme or "").strip()
    return value or "textual-dark"


def normalize_style_color(value: str | None, fallback: str) -> str:
    """Return a Rich-compatible color token."""
    resolved = str(value or fallback).strip() or fallback
    if re.fullmatch(r"#[0-9a-fA-F]{8}", resolved):
        return resolved[:7]
    return resolved


def _hex_rgb(value: str) -> tuple[int, int, int] | None:
    resolved = normalize_style_color(value, "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", resolved):
        return (
            int(resolved[1:3], 16),
            int(resolved[3:5], 16),
            int(resolved[5:7], 16),
        )
    return None


def _relative_luminance(color: str) -> float | None:
    rgb = _hex_rgb(color)
    if rgb is None:
        return None

    def _channel(value: int) -> float:
        normalized = value / 255.0
        if normalized <= 0.03928:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    red, green, blue = (_channel(component) for component in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _prefer_darker_text(color: str, fallback: str, *, threshold: float) -> str:
    luminance = _relative_luminance(color)
    if luminance is None:
        return fallback
    return fallback if luminance > threshold else color


def is_light_background(theme_variables: dict[str, str] | None = None) -> bool:
    theme = theme_variables or {}
    background = normalize_style_color(theme.get("background"), "#121212")
    background_luminance = _relative_luminance(background)
    return background_luminance is not None and background_luminance > 0.58


def syntax_background_color(theme_variables: dict[str, str] | None = None) -> str:
    theme = theme_variables or {}
    return normalize_style_color(
        theme.get("surface-darken-1") or theme.get("surface"),
        "#1b1d20",
    )


def render_palette(theme_variables: dict[str, str] | None = None) -> dict[str, str]:
    theme = theme_variables or {}
    background = normalize_style_color(theme.get("background"), "#121212")
    fg = normalize_style_color(theme.get("foreground"), "#e0e0e0")
    secondary = normalize_style_color(
        theme.get("text-secondary") or theme.get("foreground-muted"),
        fg,
    )
    muted = normalize_style_color(theme.get("foreground-muted"), secondary)
    disabled = normalize_style_color(theme.get("foreground-disabled"), muted)
    primary = normalize_style_color(theme.get("text-primary"), "#57A5E2")
    accent = normalize_style_color(theme.get("text-accent"), "#FFC473")
    warning = normalize_style_color(theme.get("text-warning"), "#FFC473")
    error = normalize_style_color(theme.get("text-error"), "#D17E92")
    success = normalize_style_color(theme.get("text-success"), "#8AD4A1")
    border = normalize_style_color(theme.get("border"), "#0178D4")

    if is_light_background(theme):
        fg = _prefer_darker_text(fg, "#253243", threshold=0.32)
        secondary = _prefer_darker_text(secondary, "#38506a", threshold=0.42)
        muted = _prefer_darker_text(muted, "#51657d", threshold=0.5)
        disabled = _prefer_darker_text(disabled, "#6b7b8e", threshold=0.58)
        primary = _prefer_darker_text(primary, "#1f5f99", threshold=0.56)
        accent = _prefer_darker_text(accent, "#9a6415", threshold=0.62)
        warning = _prefer_darker_text(warning, "#9a6415", threshold=0.62)
        error = _prefer_darker_text(error, "#9a3d4f", threshold=0.62)
        success = _prefer_darker_text(success, "#2c7a55", threshold=0.62)
        border = _prefer_darker_text(border, "#5b6d84", threshold=0.72)

    return {
        "background": background,
        "fg": fg,
        "secondary": secondary,
        "muted": muted,
        "disabled": disabled,
        "primary": primary,
        "accent": accent,
        "warning": warning,
        "error": error,
        "success": success,
        "border": border,
    }


def split_mcp_tool_identity(
    tool_name: str,
    *,
    server_name: str | None = None,
    mcp_tool_name: str | None = None,
) -> tuple[str, str]:
    resolved_server = str(server_name or "").strip()
    resolved_tool = str(mcp_tool_name or "").strip()
    raw_name = str(tool_name or "").strip()
    if raw_name and "__" in raw_name:
        inferred_server, inferred_tool = raw_name.split("__", 1)
        if not resolved_server:
            resolved_server = inferred_server.strip()
        if not resolved_tool:
            resolved_tool = inferred_tool.strip()
    elif raw_name and not resolved_tool:
        resolved_tool = raw_name
    return resolved_server, resolved_tool


def humanize_mcp_name(value: str) -> str:
    words = [part for part in re.split(r"[-_]+", str(value or "").strip()) if part]
    if not words:
        return ""
    return " ".join(word.capitalize() for word in words)


def _is_empty_mcp_value(value: Any) -> bool:
    return value is None or value == ""


def format_mcp_identity(tool_name: str, *, server_name: str | None = None, mcp_tool_name: str | None = None) -> str:
    resolved_server, resolved_tool = split_mcp_tool_identity(
        tool_name,
        server_name=server_name,
        mcp_tool_name=mcp_tool_name,
    )
    parts = [part for part in [humanize_mcp_name(resolved_server), humanize_mcp_name(resolved_tool)] if part]
    return " • ".join(parts)


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


def compact_tool_preview_blocks(
    blocks: list[Any],
    *,
    theme_variables: dict[str, str] | None = None,
    max_chars: int = 180,
) -> list[Any]:
    """Return the first useful text line from a completed tool render."""
    palette = render_palette(theme_variables)
    for block in blocks:
        if isinstance(block, Text):
            first_line = next(
                (line.strip() for line in block.plain.splitlines() if line.strip()),
                "",
            )
            if not first_line:
                continue
            preview = Text(style=block.style or palette["muted"])
            if len(first_line) > max_chars:
                first_line = first_line[: max_chars - 3].rstrip() + "..."
            preview.append(first_line)
            return [preview]
        if isinstance(block, str):
            first_line = next(
                (line.strip() for line in block.splitlines() if line.strip()),
                "",
            )
            if not first_line:
                continue
            if len(first_line) > max_chars:
                first_line = first_line[: max_chars - 3].rstrip() + "..."
            return [Text(first_line, style=palette["muted"])]
    return [Text("Details hidden.", style=palette["muted"])]


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


def render_numbered_unified_diff(
    diff_text: str,
    theme_variables: dict[str, str] | None = None,
) -> Text:
    palette = render_palette(theme_variables)
    hunk_re = re.compile(
        r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? \+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@"
    )
    rendered = Text(no_wrap=True)
    old_lineno = 0
    new_lineno = 0
    gutter_style = palette["secondary"]
    context_style = palette["fg"]
    add_style = palette["success"]
    del_style = palette["warning"]
    hunk_style = palette["primary"]

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


def parse_nested_json_payload(text: str) -> Any | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if isinstance(parsed, str):
        nested = parsed.strip()
        if not nested:
            return parsed
        try:
            return json.loads(nested)
        except Exception:
            return parsed
    return parsed


def summarize_mcp_success(
    *,
    server_name: str,
    tool_name: str,
    payload_text: str,
    theme_variables: dict[str, str] | None = None,
) -> tuple[str, list[Any], bool]:
    parsed = parse_nested_json_payload(payload_text)
    label = humanize_mcp_name(server_name) or "MCP"
    blocks: list[Any] = []
    was_truncated = False
    palette = render_palette(theme_variables)

    if isinstance(parsed, list):
        count = len(parsed)
        summary = f"Loaded {count} result{'s' if count != 1 else ''} from {label}."
        table = Table.grid(expand=True)
        table.add_column(style=palette["fg"], ratio=2)
        table.add_column(style=palette["muted"], ratio=3)
        shown = 0
        for item in parsed:
            if not isinstance(item, dict):
                continue
            primary = str(
                item.get("name")
                or item.get("title")
                or item.get("slug")
                or item.get("id")
                or ""
            ).strip()
            if not primary:
                continue
            secondary = str(
                item.get("site_id")
                or item.get("primarySiteUrl")
                or item.get("url")
                or item.get("state")
                or ""
            ).strip()
            table.add_row(primary, secondary)
            shown += 1
            if shown >= 4:
                break
        if shown:
            blocks.append(table)
        return summary, blocks, was_truncated

    if isinstance(parsed, dict):
        primary = str(
            parsed.get("name")
            or parsed.get("title")
            or parsed.get("slug")
            or parsed.get("id")
            or ""
        ).strip()
        summary = f"{label} details loaded."
        if primary:
            summary = f"Loaded {primary} from {label}."
        table = Table.grid(padding=(0, 1))
        table.add_column(style=palette["muted"], no_wrap=True)
        table.add_column(style=palette["fg"], overflow="fold")
        seen_keys: set[str] = set()
        preferred_keys = [
            "id",
            "name",
            "title",
            "slug",
            "state",
            "status",
            "url",
            "site_id",
            "primarySiteUrl",
            "teamId",
        ]
        for key in preferred_keys:
            value = parsed.get(key)
            if _is_empty_mcp_value(value):
                continue
            table.add_row(key, str(value))
            seen_keys.add(key)
            if len(seen_keys) >= 6:
                break
        if len(seen_keys) < 6:
            for key, value in parsed.items():
                if key in seen_keys or _is_empty_mcp_value(value):
                    continue
                table.add_row(str(key), str(value))
                seen_keys.add(str(key))
                if len(seen_keys) >= 6:
                    break
        if seen_keys:
            blocks.append(table)
        return summary, blocks, was_truncated

    output_display, was_truncated = truncate_for_tool(tool_name, payload_text)
    if output_display.strip():
        sections = split_mcp_text_sections(output_display)
        if sections:
            for title, body in sections:
                blocks.append(Text(title, style="bold #b7c8e1"))
                if body.strip():
                    blocks.append(
                        render_text_payload(
                            body,
                            success=True,
                            theme_variables=theme_variables,
                        )
                    )
        else:
            blocks.append(
                render_text_payload(
                    output_display,
                    success=True,
                    theme_variables=theme_variables,
                )
            )
    return f"{label} data loaded.", blocks, was_truncated


def split_mcp_text_sections(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_body: list[str] = []
    index = 0

    def flush() -> None:
        nonlocal current_title, current_body
        if current_title and any(line.strip() for line in current_body):
            sections.append((current_title, "\n".join(current_body).strip()))
        current_title = None
        current_body = []

    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        markdown_match = re.match(r"^#{1,3}\s+(.+)$", stripped)
        heading = markdown_match.group(1).strip() if markdown_match else None
        if heading is None and _looks_like_mcp_heading(lines, index):
            heading = stripped
        if heading is not None:
            flush()
            current_title = heading
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            continue
        if current_title is not None:
            current_body.append(raw_line)
        index += 1

    flush()
    return sections if len(sections) >= 2 else []


def _looks_like_mcp_heading(lines: list[str], index: int) -> bool:
    stripped = lines[index].strip()
    if not stripped or len(stripped) > 48:
        return False
    if any(token in stripped for token in ("http://", "https://", "{", "}", "[", "]", ":", "=")):
        return False
    if not re.match(r"^[A-Za-z][A-Za-z0-9 /_-]*$", stripped):
        return False
    has_blank_before = index == 0 or not lines[index - 1].strip()
    has_blank_after = index + 1 < len(lines) and not lines[index + 1].strip()
    return has_blank_before and has_blank_after


def render_mcp_start_payload(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    cwd: Path,
    theme_variables: dict[str, str] | None = None,
) -> list[Any]:
    identity = format_mcp_identity(tool_name)
    blocks: list[Any] = []
    palette = render_palette(theme_variables)
    if identity:
        blocks.append(Text(identity, style=palette["fg"]))
    if arguments:
        blocks.append(
            render_args_table(
                tool_name,
                arguments,
                cwd=cwd,
                theme_variables=theme_variables,
            )
        )
    else:
        blocks.append(Text("Waiting for MCP response.", style=palette["muted"]))
    return blocks


def render_todo_payload(
    *,
    output: str,
    metadata: dict[str, Any] | None,
    theme_variables: dict[str, str] | None = None,
) -> tuple[list[Any], bool]:
    md = metadata if isinstance(metadata, dict) else {}
    completed = md.get("completed", 0)
    total = md.get("total", 0)
    action = md.get("action", "")
    scope = md.get("scope", "execution")
    message = md.get("message", "")
    output_display, was_truncated = truncate_for_tool("todos", output)

    blocks: list[Any] = []
    palette = render_palette(theme_variables)

    if total > 0:
        bar_width = 10
        filled = int((completed / total) * bar_width) if total else 0
        bar = "█" * filled + "░" * (bar_width - filled)
        header = Text()
        header.append(
            f"{str(scope).capitalize()} tasks: {completed}/{total} completed ",
            style=palette["muted"],
        )
        header.append(bar, style=palette["success"] if completed == total else palette["warning"])
        blocks.append(header)
    elif isinstance(scope, str):
        blocks.append(Text(f"Scope: {scope}", style=palette["muted"]))

    for line in output_display.splitlines():
        stripped = line.strip()
        if stripped.startswith("☑"):
            styled = Text()
            styled.append("  ☑ ", style=f"bold {palette['success']}")
            styled.append(stripped[1:].strip(), style=f"{palette['muted']} strike")
            blocks.append(styled)
        elif stripped.startswith("☐"):
            styled = Text()
            styled.append("  ☐ ", style=f"bold {palette['warning']}")
            styled.append(stripped[1:].strip(), style=palette["fg"])
            blocks.append(styled)

    if action == "clear":
        blocks.append(Text("  All todos cleared", style=palette["muted"]))
    elif message:
        blocks.append(Text(f"  {message}", style=palette["muted"]))

    return blocks, was_truncated


def render_args_table(
    tool_name: str,
    args: dict[str, Any],
    *,
    cwd: Path,
    theme_variables: dict[str, str] | None = None,
) -> Table:
    palette = render_palette(theme_variables)
    table = Table.grid(padding=(0, 1))
    table.add_column(style=palette["muted"], justify="right", no_wrap=True)
    table.add_column(style=palette["fg"], overflow="fold")

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


def render_list_dir_output(
    output: str,
    *,
    theme_variables: dict[str, str] | None = None,
) -> Text:
    palette = render_palette(theme_variables)
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
            result.append("📁 ", style=palette["primary"])
            result.append(line, style=palette["fg"])
        else:
            result.append("📄 ", style=palette["muted"])
            result.append(line, style=palette["fg"])
        result.append("\n")
    return result


def render_grep_output(
    output: str,
    *,
    cwd: Path,
    syntax_theme: str = "textual-dark",
    theme_variables: dict[str, str] | None = None,
) -> Any:
    palette = render_palette(theme_variables)
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
        return Syntax(
            output,
            "text",
            theme=normalize_syntax_theme(syntax_theme),
            word_wrap=True,
        )

    table = Table.grid(padding=(0, 1))
    table.add_column(style=palette["muted"], justify="right", no_wrap=True)
    table.add_column(style=palette["fg"])

    for file_path, lines in groups:
        table.add_row("", Text(display_path(file_path, cwd=cwd), style=f"bold {palette['primary']}"))
        for line in lines:
            match = re.match(r"^\s*(\d+):(.*)$", line)
            if match:
                table.add_row(match.group(1), Text(match.group(2).lstrip(), style=palette["fg"]))
            else:
                table.add_row("", Text(line, style=palette["fg"]))
        table.add_row("", Text(""))

    return table


def render_git_log_output(
    metadata: dict[str, Any] | None,
    *,
    theme_variables: dict[str, str] | None = None,
) -> Any:
    palette = render_palette(theme_variables)
    md = metadata if isinstance(metadata, dict) else {}
    commits = md.get("commits")
    if not isinstance(commits, list) or not commits:
        return Text("No commits found.", style=palette["muted"])

    table = Table.grid(padding=(0, 1))
    table.add_column(style=palette["primary"], no_wrap=True)
    table.add_column(style=palette["muted"], no_wrap=True)
    table.add_column(style=palette["secondary"])
    table.add_column(style=palette["fg"])

    for commit in commits:
        if not isinstance(commit, dict):
            continue
        short_sha = str(commit.get("short_sha", "")).strip()
        date = str(commit.get("date", "")).strip()
        author = str(commit.get("author", "")).strip()
        subject = str(commit.get("subject", "")).strip()
        table.add_row(short_sha, date, author, subject)

    return table


def render_text_payload(
    text: str,
    *,
    success: bool,
    language: str = "text",
    syntax_theme: str = "textual-dark",
    theme_variables: dict[str, str] | None = None,
) -> Any:
    palette = render_palette(theme_variables)
    if not text.strip():
        return Text("No output", style=palette["muted"])
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
                theme=normalize_syntax_theme(syntax_theme),
                word_wrap=True,
                background_color=syntax_background_color(theme_variables),
            )
    if language != "text":
        return Syntax(
            text,
            language,
            theme=normalize_syntax_theme(syntax_theme),
            word_wrap=True,
            background_color=syntax_background_color(theme_variables),
        )
    return Text(text, style=palette["fg"])


def render_line_numbered_text(
    text: str,
    *,
    start_line: int = 1,
    theme_variables: dict[str, str] | None = None,
) -> Text:
    palette = render_palette(theme_variables)
    gutter_style = palette["secondary"]
    body_style = palette["fg"]
    rendered = Text(no_wrap=True)
    lines = (text or "").splitlines()
    if not lines:
        return Text("", style=body_style)
    width = max(len(str(start_line + len(lines) - 1)), 1)
    for index, line in enumerate(lines, start=start_line):
        rendered.append(f"{index:>{width}} ", style=gutter_style)
        rendered.append(line, style=body_style)
        if index < start_line + len(lines) - 1:
            rendered.append("\n")
    if text.endswith("\n"):
        rendered.append("\n")
    return rendered


def render_skills_payload(
    *,
    output: str,
    success: bool,
    theme_variables: dict[str, str] | None = None,
) -> Any:
    if not output.strip():
        return Text("No output", style=render_palette(theme_variables)["muted"])
    if not success:
        clipped, _ = truncate_for_tool("skills", output)
        return render_text_payload(clipped, success=False, theme_variables=theme_variables)
    try:
        payload = json.loads(output)
    except Exception:
        clipped, _ = truncate_for_tool("skills", output)
        return render_text_payload(clipped, success=True, theme_variables=theme_variables)
    if not isinstance(payload, dict):
        clipped, _ = truncate_for_tool("skills", output)
        return render_text_payload(clipped, success=True, theme_variables=theme_variables)
    styles = render_palette(theme_variables)
    rendered = build_skills_tool_renderable(payload, styles=styles)
    if rendered is None:
        clipped, _ = truncate_for_tool("skills", output)
        return render_text_payload(clipped, success=True, theme_variables=theme_variables)
    return rendered


def render_subagent_payload(
    *,
    output: str,
    metadata: dict[str, Any] | None,
    success: bool,
    error: str | None,
    theme_variables: dict[str, str] | None = None,
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
    palette = render_palette(theme_variables)

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
        blocks.append(Text(" • ".join(trace_parts), style=palette["muted"]))

    recovered_after_retry = False
    if isinstance(payload.get("recovered_after_retry"), bool):
        recovered_after_retry = payload.get("recovered_after_retry") is True
    elif isinstance(trace, dict):
        recovered_after_retry = trace.get("recovered_after_retry") is True
    if recovered_after_retry:
        blocks.append(Text("Recovered after retry.", style=palette["primary"]))

    if summary:
        summary_display, truncated = truncate_for_tool("subagent", summary)
        was_truncated = was_truncated or truncated
        blocks.append(render_text_payload(summary_display, success=True, theme_variables=theme_variables))

    if findings:
        blocks.append(Text("Findings", style=f"bold {palette['primary']}"))
        for item in findings[:4]:
            text = str(item).strip()
            if not text:
                continue
            blocks.append(Text(f"• {text}", style=palette["fg"]))
        if len(findings) > 4:
            blocks.append(Text(f"... {len(findings) - 4} more findings", style=palette["muted"]))

    if actions:
        blocks.append(Text("Actions", style=f"bold {palette['warning']}"))
        for item in actions[:4]:
            text = str(item).strip()
            if not text:
                continue
            blocks.append(Text(f"• {text}", style=palette["fg"]))
        if len(actions) > 4:
            blocks.append(Text(f"... {len(actions) - 4} more actions", style=palette["muted"]))

    failure_text = ""
    if not success:
        failure_text = str(error or "").strip()
        if not failure_text and output.strip():
            failure_text = output.strip()
        if failure_text and failure_text != summary:
            failure_display, truncated = truncate_for_tool("subagent", failure_text)
            was_truncated = was_truncated or truncated
            blocks.append(Text("Failure", style=f"bold {palette['warning']}"))
            blocks.append(render_text_payload(failure_display, success=False, theme_variables=theme_variables))

    if not blocks:
        fallback = output.strip() or str(error or "").strip()
        if fallback:
            fallback_display, truncated = truncate_for_tool("subagent", fallback)
            was_truncated = was_truncated or truncated
            blocks.append(render_text_payload(fallback_display, success=success, theme_variables=theme_variables))
        else:
            blocks.append(Text("No output", style=palette["muted"]))

    return blocks, was_truncated


def render_subagent_runtime_payload(
    *,
    metadata: dict[str, Any] | None,
    output: str = "",
    error: str | None = None,
    success: bool = True,
    collapse_completed: bool = False,
    theme_variables: dict[str, str] | None = None,
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
    palette = render_palette(theme_variables)

    requested_subagent = str(md.get("requested_subagent") or "").strip()
    selected_subagent = str(md.get("selected_subagent") or "").strip()
    if md.get("reused_existing") is True:
        blocks.append(Text("Reused matching active specialist run.", style=palette["muted"]))
    if requested_subagent and selected_subagent:
        blocks.append(
            Text(
                f"Used `{selected_subagent}` for requested specialist `{requested_subagent}`.",
                style=palette["muted"],
            )
        )

    available_subagents = md.get("available_subagents")
    if isinstance(available_subagents, list) and available_subagents:
        blocks.append(
            Text(
                "Available specialists: " + ", ".join(str(item) for item in available_subagents if str(item).strip()),
                style=palette["muted"],
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
        blocks.append(Text(" ".join(parts), style=palette["warning"]))

    runs = md.get("runs")
    if not isinstance(runs, list) or not runs:
        run = md.get("run")
        runs = [run] if isinstance(run, dict) else []

    if not runs:
        failure_text = str(error or output or "").strip()
        if failure_text and not success:
            blocks.append(Text("Failure", style=f"bold {palette['warning']}"))
            blocks.append(render_text_payload(failure_text, success=False, theme_variables=theme_variables))
        else:
            blocks.append(Text("No specialist runs.", style=palette["muted"]))
        return blocks

    table = Table.grid(padding=(0, 1))
    table.add_column(style=palette["primary"], no_wrap=True)
    table.add_column(style=palette["muted"], no_wrap=True)
    table.add_column(style=palette["fg"])

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
        run_label = Text(run_id, style=palette["primary"])
        if goal_label:
            run_label.append(" · ", style=palette["disabled"])
            run_label.append(goal_label, style=palette["muted"])
        table.add_row(run_label, status or "unknown", detail or " ")

    blocks.append(table)

    first_run = runs[0] if runs and isinstance(runs[0], dict) else None
    history = first_run.get("activity_history") if isinstance(first_run, dict) else None
    if not collapse_completed and isinstance(history, list) and history:
        blocks.append(Text("Recent activity", style=f"bold {palette['warning']}"))
        for entry in history[-3:]:
            if not isinstance(entry, dict):
                continue
            message = str(entry.get("message") or "").strip()
            freshness = age_label(entry.get("at"))
            line = "  •  ".join(part for part in [freshness, message] if part)
            if line:
                blocks.append(Text(f"• {line}", style=palette["muted"]))

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
        blocks.append(Text(" • ".join(notes), style=palette["muted"]))
    return blocks


def render_subagent_metrics_payload(
    *,
    metadata: dict[str, Any] | None,
    output: str = "",
    error: str | None = None,
    success: bool = True,
    theme_variables: dict[str, str] | None = None,
) -> list[Any]:
    md = metadata if isinstance(metadata, dict) else {}
    blocks: list[Any] = []
    palette = render_palette(theme_variables)

    if not success:
        failure_text = str(error or output or "").strip()
        if failure_text:
            blocks.append(Text("Failure", style=f"bold {palette['warning']}"))
            blocks.append(render_text_payload(failure_text, success=False, theme_variables=theme_variables))
        else:
            blocks.append(Text("No metrics available.", style=palette["muted"]))
        return blocks

    totals = md.get("totals")
    if not isinstance(totals, dict):
        blocks.append(Text("No metrics available.", style=palette["muted"]))
        return blocks

    restored = bool(md.get("restored_from_snapshot"))

    historical = Table.grid(padding=(0, 1))
    historical.add_column(style=palette["warning"], no_wrap=True)
    historical.add_column(style=palette["fg"])
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
    live.add_column(style=palette["primary"], no_wrap=True)
    live.add_column(style=palette["fg"])
    live.add_row("Live runtime state", "current process")
    live.add_row("Active runs", str(int(totals.get("active_runs") or 0)))
    live.add_row("Retained runs", str(int(totals.get("retained_runs") or 0)))
    live.add_row("Circuit breaker blocks", str(int(totals.get("circuit_breaker_blocks") or 0)))
    live.add_row("Circuit breaker trips", str(int(totals.get("circuit_breaker_trips") or 0)))
    blocks.append(live)

    open_circuits = md.get("open_circuits")
    if isinstance(open_circuits, dict) and open_circuits:
        blocks.append(Text("Open circuits", style=f"bold {palette['warning']}"))
        for subagent, reopen_at in open_circuits.items():
            blocks.append(Text(f"{subagent}: retry after {reopen_at}", style=palette["muted"]))

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


def render_terminal_payload(
    text: str,
    *,
    tone: str = "stdout",
    theme_variables: dict[str, str] | None = None,
) -> Any:
    palette = render_palette(theme_variables)
    collapsed = collapse_terminal_rewrites(text)
    if not collapsed:
        return Text("No output", style=palette["muted"])
    if "\x1b" in collapsed:
        return Text.from_ansi(collapsed)
    style = palette["fg"] if tone == "stdout" else palette["warning"]
    return Text(collapsed, style=style)


def render_terminal_snapshot_payload(
    text: str,
    *,
    tone: str = "stdout",
    max_lines: int | None = None,
    max_chars: int = 16000,
    theme_variables: dict[str, str] | None = None,
) -> Any:
    palette = render_palette(theme_variables)
    if not text:
        return Text("No output", style=palette["muted"])
    window = text[-max_chars:] if len(text) > max_chars else text
    collapsed = collapse_terminal_rewrites(window)
    if not collapsed:
        return Text("No output", style=palette["muted"])
    if max_lines is not None:
        lines = collapsed.splitlines()
        if len(lines) > max_lines:
            collapsed = "\n".join(lines[-max_lines:])
    if "\x1b" in collapsed:
        return Text.from_ansi(collapsed)
    style = palette["fg"] if tone == "stdout" else palette["warning"]
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
        return "command running" + running_suffix, "primary"
    if state == "idle":
        return "idle", "muted"
    if state == "stopped":
        return "stopped", "muted"
    if state == "exited":
        return "exited", "muted"
    return state.replace("_", " "), "muted"


def shell_spinner_frame(index: int) -> str:
    frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    return frames[index % len(frames)]


def render_shell_command_line(
    command: str,
    *,
    cwd: Path,
    shell_cwd: str | None = None,
    theme_variables: dict[str, str] | None = None,
) -> Table:
    palette = render_palette(theme_variables)
    table = Table.grid(expand=True)
    table.add_column(width=2)
    table.add_column(ratio=1)
    table.add_row(
        Text("$", style=f"bold {palette['primary']}"),
        Text(command.strip() or "(no command)", style=palette["fg"]),
    )
    if isinstance(shell_cwd, str) and shell_cwd.strip():
        table.add_row(
            Text(""),
            Text(f"in {display_path(shell_cwd.strip(), cwd=cwd)}", style=palette["muted"]),
        )
    return table


def render_shell_running_card(
    arguments: dict[str, Any],
    *,
    cwd: Path,
    spinner_index: int,
    theme_variables: dict[str, str] | None = None,
) -> Group:
    palette = render_palette(theme_variables)
    command = str(arguments.get("command", "")).strip()
    shell_cwd = arguments.get("cwd") if isinstance(arguments.get("cwd"), str) else None
    header = Text()
    header.append(f"{shell_spinner_frame(spinner_index)} ", style=f"bold {palette['primary']}")
    header.append("Running in shell", style=f"bold {palette['fg']}")
    header.append("  live", style=palette["muted"])
    return Group(
        header,
        Text(describe_tool_activity("shell", arguments, stage="start"), style=palette["muted"]),
        render_shell_command_line(command, cwd=cwd, shell_cwd=shell_cwd, theme_variables=theme_variables),
    )


def render_shell_result_payload(
    *,
    payload: str,
    metadata: dict[str, Any] | None,
    exit_code: int | None,
    running_suffix: str = "",
    theme_variables: dict[str, str] | None = None,
) -> list[Any]:
    palette = render_palette(theme_variables)
    md = metadata if isinstance(metadata, dict) else {}
    session_id = str(md.get("session_id") or "").strip()
    has_new_output = bool(md.get("has_new_output"))
    running = md.get("running")
    stdout_text, stderr_text = split_shell_payload(payload)
    blocks: list[Any] = []

    summary = Text()
    if session_id:
        summary.append(session_id, style=palette["muted"])
    if isinstance(running, bool) or md.get("status"):
        if summary.plain:
            summary.append("  •  ", style=palette["disabled"])
        status_label, status_style = shell_session_status_label(
            md,
            running_suffix=running_suffix,
        )
        summary.append(status_label, style=palette.get(status_style, palette["muted"]))
    if exit_code is not None:
        if summary.plain:
            summary.append("  •  ", style=palette["disabled"])
        summary.append(f"exit {exit_code}", style=palette["muted"])
    if md.get("timed_out"):
        if summary.plain:
            summary.append("  •  ", style=palette["disabled"])
        summary.append("timed out", style=palette["warning"])
    if summary.plain:
        blocks.append(summary)

    if not has_new_output and session_id:
        if isinstance(running, bool) and not running:
            blocks.append(Text("No new output.", style=palette["muted"]))
        else:
            blocks.append(Text("No new output yet.", style=palette["muted"]))
        return blocks

    if not stdout_text and not stderr_text:
        blocks.append(Text("No output", style=palette["muted"]))
        return blocks

    if stdout_text and stderr_text:
        blocks.append(render_terminal_payload(stdout_text, tone="stdout", theme_variables=theme_variables))
        blocks.append(Text("stderr", style=f"bold {palette['warning']}"))
        blocks.append(render_terminal_payload(stderr_text, tone="stderr", theme_variables=theme_variables))
    elif stdout_text:
        blocks.append(render_terminal_payload(stdout_text, tone="stdout", theme_variables=theme_variables))
    else:
        blocks.append(render_terminal_payload(stderr_text, tone="stderr", theme_variables=theme_variables))
    return blocks
