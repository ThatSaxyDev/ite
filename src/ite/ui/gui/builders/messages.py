from __future__ import annotations
import json
import re
import flet as ft
from typing import Any
from pathlib import Path
from ite.ui.tool_narrative import activity_title
from ite.ui.tool_narrative import describe_tool_activity
from ..tokens import *


class MessageBuilderMixin:
    def _build_chat_markdown(self, content: str) -> ft.Markdown:
        return ft.Markdown(
            content,
            selectable=True,
            extension_set="gitHubFlavored",
        )

    def _build_user_message_content(self, content: str) -> ft.Control:
        simple_text = content.strip()
        looks_like_markdown = bool(
            re.search(r"(?m)^(#{1,6}\s|\* |\d+\.\s|>\s|```)", simple_text)
        )
        if "\n" not in simple_text and not looks_like_markdown:
            return ft.Text(
                simple_text,
                size=TYPE_BODY + 1,
                color=TEXT_PRIMARY,
                weight=WEIGHT_MEDIUM,
                selectable=True,
            )
        return self._build_chat_markdown(content)

    def _wrap_in_lane(self, content: ft.Control) -> ft.Control:
        return ft.Row(
            [
                ft.Container(
                    width=CONTENT_LANE_WIDTH,
                    content=content,
                )
            ],
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def _build_status_chip(self, text: str, color: str, border: str, bg: str) -> ft.Container:
        return ft.Container(
            content=ft.Text(text, size=TYPE_SM, color=color, weight=WEIGHT_SEMIBOLD),
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            border=ft.Border.all(1, border),
            border_radius=RADIUS_LG,
            bgcolor=bg,
        )

    def _tool_status_icon(self, state: str) -> str:
        if state == "running":
            return ft.Icons.PLAY_CIRCLE_ROUNDED
        if state == "done":
            return ft.Icons.CHECK_CIRCLE_ROUNDED
        return ft.Icons.CANCEL_ROUNDED

    def _shell_state_icon(self, state: str, color: str) -> ft.Control:
        if state == "running":
            return ft.ProgressRing(width=16, height=16, stroke_width=2.2, color=color)
        icon = ft.Icons.CHECK_CIRCLE_ROUNDED if state == "done" else ft.Icons.ERROR_OUTLINE_ROUNDED
        return ft.Icon(icon, size=16, color=color)

    def _split_shell_output(self, payload: str) -> tuple[str, str]:
        marker = "\n\n--- STDERR ---\n"
        if marker in payload:
            stdout, stderr = payload.split(marker, 1)
            return stdout.strip(), stderr.strip()
        if payload.startswith("--- STDERR ---\n"):
            return "", payload.replace("--- STDERR ---\n", "", 1).strip()
        return payload.strip(), ""

    def _build_shell_command_surface(
        self,
        command: str,
        *,
        cwd: str | None = None,
        prefix: str = "$",
    ) -> ft.Control:
        meta_bits: list[ft.Control] = []
        if isinstance(cwd, str) and cwd.strip():
            meta_bits.append(
                ft.Text(
                    cwd.strip(),
                    size=TYPE_SM,
                    color=TEXT_MUTED,
                    selectable=True,
                )
            )

        return ft.Container(
            bgcolor=SURFACE_1,
            border=ft.Border.all(1, BORDER),
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                prefix,
                                style=ft.TextStyle(
                                    font_family=FONT_MONO,
                                    size=TYPE_BODY,
                                    color=ACCENT,
                                    weight=WEIGHT_BOLD,
                                ),
                            ),
                            ft.Text(
                                command or "(no command)",
                                style=ft.TextStyle(
                                    font_family=FONT_MONO,
                                    size=TYPE_BODY,
                                    color=TEXT_PRIMARY,
                                ),
                                selectable=True,
                                expand=True,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    ft.Row(meta_bits, spacing=8, wrap=True) if meta_bits else ft.Container(),
                ],
                spacing=8 if meta_bits else 0,
                tight=True,
            ),
        )

    def _build_shell_stream_section(
        self,
        title: str,
        content: str,
        *,
        tone: str,
        max_height: int = 210,
    ) -> ft.Control:
        accent = SUCCESS if tone == "stdout" else ft.Colors.with_opacity(0.92, ft.Colors.AMBER_200)
        subtitle = "Output" if tone == "stdout" else "Warnings / errors"
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(title, size=TYPE_SM, color=accent, weight=WEIGHT_BOLD),
                            ft.Text(subtitle, size=TYPE_SM, color=TEXT_MUTED),
                        ],
                        spacing=8,
                    ),
                    self._build_tool_payload_surface(
                        self._build_scrollable_text_block(
                            content,
                            max_height=max_height,
                            line_limit=520,
                            markdown=False,
                        ),
                        code_mode=True,
                    ),
                ],
                spacing=SPACE_XS,
                tight=True,
            )
        )

    def _build_shell_result_view(
        self,
        payload: str,
        metadata: dict[str, Any] | None,
        exit_code: int | None,
    ) -> ft.Control:
        md = metadata if isinstance(metadata, dict) else {}
        stdout_text, stderr_text = self._split_shell_output(payload)
        sections: list[ft.Control] = []

        if stdout_text:
            sections.append(self._build_shell_stream_section("stdout", stdout_text, tone="stdout"))
        if stderr_text:
            sections.append(self._build_shell_stream_section("stderr", stderr_text, tone="stderr"))
        if not sections:
            sections.append(self._build_empty_output_hint())

        footer_bits: list[ft.Control] = []
        if isinstance(exit_code, int):
            footer_bits.append(
                ft.Text(
                    f"exit code {exit_code}",
                    size=TYPE_SM,
                    color=TEXT_MUTED,
                )
            )
        if md.get("timed_out"):
            footer_bits.append(
                ft.Text(
                    "timed out",
                    size=TYPE_SM,
                    color=ft.Colors.with_opacity(0.92, ft.Colors.AMBER_200),
                    weight=WEIGHT_SEMIBOLD,
                )
            )

        return ft.Column(
            sections + ([ft.Row(footer_bits, spacing=12, wrap=True)] if footer_bits else []),
            spacing=SPACE_SM,
            tight=True,
        )

    def _build_tool_payload_surface(self, inner: ft.Control, *, code_mode: bool = False) -> ft.Container:
        return ft.Container(
            content=inner,
            bgcolor=SURFACE_1 if not code_mode else SURFACE_2,
            border=ft.Border.all(1, BORDER_STRONG if code_mode else BORDER),
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=10, vertical=10),
        )

    def _build_scrollable_text_block(
        self,
        content: str,
        *,
        max_height: int = 220,
        line_limit: int = 500,
        markdown: bool = False,
    ) -> ft.Control:
        lines = content.splitlines()
        clipped = lines[:line_limit]
        clipped_text = "\n".join(clipped)
        if len(lines) > line_limit:
            clipped_text += f"\n\n... [{len(lines) - line_limit} more lines not shown]"

        line_count = max(1, len(clipped))
        estimated_height = min(max(42, line_count * 22 + 12), max_height)
        body: ft.Control
        if markdown:
            body = ft.Markdown(
                clipped_text,
                selectable=True,
                extension_set="gitHubFlavored",
            )
        else:
            body = ft.Text(
                clipped_text,
                style=MONO_STYLE,
                selectable=True,
            )
        return ft.Container(
            height=estimated_height,
            content=ft.Column(
                [body],
                scroll=ft.ScrollMode.AUTO,
                tight=True,
                spacing=0,
            ),
        )

    def _build_empty_output_hint(self) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, size=14, color=TEXT_MUTED),
                    ft.Text("No output", size=TYPE_SM, color=TEXT_MUTED),
                ],
                spacing=8,
            ),
            padding=ft.Padding.symmetric(horizontal=6, vertical=4),
        )

    def _looks_like_source_excerpt(self, text: str) -> bool:
        lines = text.splitlines()
        if len(lines) < 4:
            return False
        numbered = 0
        for line in lines[:20]:
            if re.match(r"^\s*\d+\|", line):
                numbered += 1
        return numbered >= 4

    def _to_code_block(self, text: str, language: str = "text") -> str:
        cleaned_lines = []
        for line in text.splitlines():
            cleaned_lines.append(re.sub(r"^\s*\d+\|", "", line))
        return f"```{language}\n" + "\n".join(cleaned_lines).strip("\n") + "\n```"

    def _guess_language(self, path: str | None) -> str:
        if not path:
            return "text"
        suffix = Path(path).suffix.lower()
        return {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "jsx",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".json": "json",
            ".toml": "toml",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
            ".sh": "bash",
            ".zsh": "bash",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".kt": "kotlin",
            ".swift": "swift",
            ".c": "c",
            ".h": "c",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".css": "css",
            ".html": "html",
            ".xml": "xml",
            ".sql": "sql",
            ".dart": "dart",
        }.get(suffix, "text")

    def _highlight_code_line(self, line: str, language: str) -> ft.Text:
        keyword_set = {
            "python": {
                "def", "class", "import", "from", "return", "if", "elif", "else",
                "for", "while", "try", "except", "with", "as", "async", "await",
                "True", "False", "None", "in", "and", "or", "not", "lambda", "pass",
            },
            "javascript": {
                "function", "const", "let", "var", "return", "if", "else", "for",
                "while", "try", "catch", "class", "import", "from", "export", "async",
                "await", "true", "false", "null",
            },
            "typescript": {
                "function", "const", "let", "var", "return", "if", "else", "for",
                "while", "try", "catch", "class", "import", "from", "export", "async",
                "await", "true", "false", "null", "interface", "type",
            },
        }
        language_key = language if language in keyword_set else "python"
        keywords = keyword_set[language_key]
        token_pattern = re.compile(
            r"(#.*$|//.*$|\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|\b\d+(?:\.\d+)?\b|\b[A-Za-z_]\w*\b)"
        )

        spans: list[ft.TextSpan] = []
        cursor = 0
        for match in token_pattern.finditer(line):
            start, end = match.span()
            if start > cursor:
                spans.append(ft.TextSpan(line[cursor:start], style=ft.TextStyle(font_family=FONT_MONO, color=TEXT_PRIMARY, size=TYPE_BODY)))
            token = match.group(0)
            color = TEXT_PRIMARY
            if token.startswith("#") or token.startswith("//"):
                color = ft.Colors.with_opacity(0.65, ft.Colors.GREEN_300)
            elif token.startswith('"') or token.startswith("'"):
                color = ft.Colors.with_opacity(0.95, ft.Colors.AMBER_200)
            elif token in keywords:
                color = ft.Colors.with_opacity(0.95, ft.Colors.CYAN_200)
            elif token.replace(".", "", 1).isdigit():
                color = ft.Colors.with_opacity(0.95, ft.Colors.PINK_200)
            spans.append(ft.TextSpan(token, style=ft.TextStyle(font_family=FONT_MONO, color=color, size=TYPE_BODY)))
            cursor = end
        if cursor < len(line):
            spans.append(ft.TextSpan(line[cursor:], style=ft.TextStyle(font_family=FONT_MONO, color=TEXT_PRIMARY, size=TYPE_BODY)))
        return ft.Text(spans=spans, selectable=True)

    def _build_colored_code_view(
        self,
        content: str,
        language: str,
        *,
        start_line: int = 1,
        max_height: int = 360,
        line_limit: int = 700,
    ) -> ft.Control:
        rows: list[ft.Control] = []
        lines = content.splitlines()
        clipped = lines[:line_limit]
        for idx, line in enumerate(clipped, start=start_line):
            rows.append(
                ft.Row(
                    [
                        ft.Text(f"{idx:>4}", style=ft.TextStyle(font_family=FONT_MONO, color=TEXT_MUTED, size=TYPE_BODY)),
                        ft.Container(width=10),
                        self._highlight_code_line(line, language),
                    ],
                    spacing=0,
                )
            )
        if len(lines) > len(clipped):
            rows.append(
                ft.Text(
                    f"... {len(lines) - len(clipped)} more lines",
                    size=TYPE_SM,
                    color=TEXT_MUTED,
                )
            )
        estimated_height = min(max(110, len(clipped) * 23 + 20), max_height)
        return ft.Container(
            height=estimated_height,
            content=ft.Column(rows, spacing=2, tight=True, scroll=ft.ScrollMode.AUTO),
        )

    def _build_diff_view(self, diff_text: str, *, max_height: int = 340, line_limit: int = 800) -> ft.Control:
        rows: list[ft.Control] = []
        lines = diff_text.splitlines()
        clipped = lines[:line_limit]
        for line in clipped:
            color = TEXT_PRIMARY
            if line.startswith("+"):
                color = ft.Colors.with_opacity(0.95, ft.Colors.GREEN_300)
            elif line.startswith("-"):
                color = ft.Colors.with_opacity(0.95, ft.Colors.RED_300)
            elif line.startswith("@@"):
                color = ft.Colors.with_opacity(0.95, ft.Colors.CYAN_200)
            elif line.startswith(("---", "+++")):
                color = ft.Colors.with_opacity(0.9, ft.Colors.AMBER_200)
            rows.append(
                ft.Text(
                    line,
                    style=ft.TextStyle(font_family=FONT_MONO, color=color, size=TYPE_BODY),
                    selectable=True,
                )
            )
        if len(lines) > len(clipped):
            rows.append(
                ft.Text(
                    f"... {len(lines) - len(clipped)} more lines",
                    size=TYPE_SM,
                    color=TEXT_MUTED,
                )
            )
        estimated_height = min(max(110, len(clipped) * 22 + 20), max_height)
        return ft.Container(
            height=estimated_height,
            content=ft.Column(rows, spacing=2, tight=True, scroll=ft.ScrollMode.AUTO),
        )

    def _build_file_list_view(
        self,
        paths: list[str],
        *,
        max_height: int = 210,
        line_limit: int = 240,
    ) -> ft.Control:
        clipped = paths[:line_limit]
        rows: list[ft.Control] = []
        for p in clipped:
            rows.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.INSERT_DRIVE_FILE_ROUNDED, size=14, color=TEXT_MUTED),
                        ft.Text(
                            p,
                            style=ft.TextStyle(font_family=FONT_MONO, size=TYPE_BODY, color=TEXT_PRIMARY),
                            selectable=True,
                        ),
                    ],
                    spacing=8,
                )
            )
        if len(paths) > len(clipped):
            rows.append(ft.Text(f"... {len(paths)-len(clipped)} more entries", size=TYPE_SM, color=TEXT_MUTED))
        estimated_height = min(max(90, len(clipped) * 24 + 16), max_height)
        return ft.Container(
            height=estimated_height,
            content=ft.Column(rows, spacing=4, tight=True, scroll=ft.ScrollMode.AUTO),
        )

    def _build_grep_view(
        self,
        payload: str,
        *,
        max_height: int = 260,
        line_limit: int = 420,
    ) -> ft.Control:
        groups: list[tuple[str, list[str]]] = []
        current_file: str | None = None
        current_lines: list[str] = []
        for raw in payload.splitlines():
            line = raw.rstrip()
            if line.startswith("=== ") and line.endswith(" ==="):
                if current_file is not None:
                    groups.append((current_file, current_lines))
                current_file = line[4:-4].strip()
                current_lines = []
                continue
            if current_file is not None:
                if line:
                    current_lines.append(line)
        if current_file is not None:
            groups.append((current_file, current_lines))

        if not groups:
            return self._build_scrollable_text_block(
                payload,
                max_height=max_height,
                line_limit=line_limit,
                markdown=False,
            )

        rows: list[ft.Control] = []
        max_line_digits = 2
        for _, match_lines in groups:
            for line in match_lines:
                m = re.match(r"^\s*(\d+):(.*)$", line)
                if m:
                    max_line_digits = max(max_line_digits, len(m.group(1)))

        shown = 0
        for file_path, match_lines in groups:
            if shown >= line_limit:
                break
            rows.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.FOLDER_OPEN_ROUNDED, size=14, color=TEXT_MUTED),
                        ft.Text(file_path, size=TYPE_SM, color=TEXT_SECONDARY, selectable=True),
                    ],
                    spacing=8,
                )
            )
            for line in match_lines:
                if shown >= line_limit:
                    break
                color = TEXT_PRIMARY
                m = re.match(r"^\s*(\d+):(.*)$", line)
                if m:
                    line_no = m.group(1)
                    text = m.group(2).lstrip()
                    rows.append(
                        ft.Row(
                            [
                                ft.Container(
                                    width=max(28, max_line_digits * 9 + 8),
                                    content=ft.Text(
                                        line_no,
                                        style=ft.TextStyle(font_family=FONT_MONO, size=TYPE_SM, color=TEXT_MUTED),
                                        text_align=ft.TextAlign.RIGHT,
                                    ),
                                ),
                                ft.Container(width=8),
                                ft.Text(
                                    text,
                                    style=ft.TextStyle(font_family=FONT_MONO, size=TYPE_BODY, color=color),
                                    selectable=True,
                                ),
                            ],
                            spacing=0,
                        )
                    )
                else:
                    rows.append(
                        ft.Text(
                            line,
                            style=ft.TextStyle(font_family=FONT_MONO, size=TYPE_BODY, color=color),
                            selectable=True,
                        )
                    )
                shown += 1
            rows.append(ft.Container(height=4))

        estimated_height = min(max(110, min(shown, 28) * 22 + 24), max_height)
        return ft.Container(
            height=estimated_height,
            content=ft.Column(rows, spacing=2, tight=True, scroll=ft.ScrollMode.AUTO),
        )

    def _looks_like_json(self, value: str) -> bool:
        text = value.strip()
        if not text:
            return False
        if (text.startswith("{") and text.endswith("}")) or (
            text.startswith("[") and text.endswith("]")
        ):
            return True
        return False

    def _normalize_path_lines(self, payload: str) -> list[str]:
        lines = []
        for raw in payload.splitlines():
            line = raw.strip()
            if not line:
                continue
            line = line.lstrip("📄").lstrip("🗂️").strip()
            if line.endswith("/"):
                line = line[:-1]
            lines.append(line)
        return lines

    def _build_meta_summary(self, name: str, metadata: dict[str, Any] | None, exit_code: int | None) -> ft.Control | None:
        if not isinstance(metadata, dict):
            metadata = {}
        chips: list[ft.Control] = []

        def chip(label: str) -> ft.Control:
            return ft.Container(
                content=ft.Text(label, size=TYPE_SM, color=TEXT_SECONDARY),
                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                border=ft.Border.all(1, BORDER),
                border_radius=RADIUS_SM,
                bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.WHITE),
            )

        if name == "glob":
            matches = metadata.get("matches")
            if isinstance(matches, int):
                chips.append(chip(f"{matches} files found"))
        elif name == "list_dir":
            entries = metadata.get("entries")
            if isinstance(entries, int):
                chips.append(chip(f"{entries} entries"))
        elif name == "grep":
            matches = metadata.get("matches")
            files = metadata.get("files_searched")
            if isinstance(matches, int):
                if isinstance(files, int):
                    chips.append(chip(f"{matches} matches in {files} files"))
                else:
                    chips.append(chip(f"{matches} matches"))
        elif name == "read_file":
            shown_start = metadata.get("shown_start")
            shown_end = metadata.get("shown_end")
            total = metadata.get("total_lines")
            if all(isinstance(x, int) for x in [shown_start, shown_end, total]):
                chips.append(chip(f"lines {shown_start}-{shown_end} of {total}"))
        elif name == "write_file":
            if isinstance(metadata.get("path"), str):
                chips.append(chip(str(metadata["path"])))
            if isinstance(metadata.get("lines_added"), int):
                chips.append(chip(f"{metadata['lines_added']} lines written"))
        elif name == "edit":
            if isinstance(metadata.get("path"), str):
                chips.append(chip(str(metadata["path"])))
            if isinstance(metadata.get("replace_count"), int):
                chips.append(chip(f"{metadata['replace_count']} replacements"))
            if isinstance(metadata.get("line_diff"), int):
                sign = "+" if metadata["line_diff"] > 0 else ""
                chips.append(chip(f"{sign}{metadata['line_diff']} line delta"))
        elif name == "apply_patch":
            actions = metadata.get("actions")
            if isinstance(actions, list):
                chips.append(chip(f"{len(actions)} files changed"))
        elif name == "shell":
            safety = metadata.get("safety_classification")
            if isinstance(safety, str):
                chips.append(chip(f"{safety} command"))
            if isinstance(exit_code, int):
                chips.append(chip(f"exit code {exit_code}"))
            if metadata.get("has_stderr"):
                chips.append(chip("stderr captured"))
        elif name == "web_search":
            query = metadata.get("query")
            provider = metadata.get("provider")
            results = metadata.get("results")
            if isinstance(query, str) and query.strip():
                chips.append(chip(query.strip()))
            if isinstance(results, int):
                chips.append(chip(f"{results} result{'s' if results != 1 else ''}"))
            if isinstance(provider, str) and provider.strip():
                chips.append(chip(provider))
        elif name == "web_fetch":
            status_code = metadata.get("status_code")
            content_type = metadata.get("content_type")
            url = metadata.get("url")
            if isinstance(status_code, int):
                chips.append(chip(str(status_code)))
            if isinstance(content_type, str) and content_type.strip():
                chips.append(chip(content_type.strip()))
            if isinstance(url, str) and url.strip():
                chips.append(chip(url.strip()))

        if not chips:
            return None
        return ft.Row(chips, spacing=8, wrap=True)

    def _build_patch_actions_view(self, actions: list[dict[str, Any]]) -> ft.Control:
        rows: list[ft.Control] = []
        for action in actions[:300]:
            op = str(action.get("action", "update")).lower()
            path = str(action.get("path", ""))
            color = TEXT_SECONDARY
            icon = ft.Icons.EDIT_ROUNDED
            if op == "add":
                color = ft.Colors.with_opacity(0.9, ft.Colors.GREEN_300)
                icon = ft.Icons.ADD_CIRCLE_OUTLINE_ROUNDED
            elif op == "delete":
                color = ft.Colors.with_opacity(0.9, ft.Colors.RED_300)
                icon = ft.Icons.REMOVE_CIRCLE_OUTLINE_ROUNDED
            rows.append(
                ft.Row(
                    [
                        ft.Icon(icon, size=14, color=color),
                        ft.Text(op.upper(), size=TYPE_SM, color=color, weight=WEIGHT_SEMIBOLD),
                        ft.Text(path, style=ft.TextStyle(font_family=FONT_MONO, size=TYPE_BODY, color=TEXT_PRIMARY), selectable=True),
                    ],
                    spacing=8,
                )
            )
        return ft.Container(
            height=min(max(90, len(rows) * 24 + 16), 220),
            content=ft.Column(rows, spacing=4, tight=True, scroll=ft.ScrollMode.AUTO),
        )

    def _truncate_content(
        self,
        content: str,
        *,
        max_chars: int = 700,
        max_lines: int = 8,
    ) -> tuple[str, bool]:
        lines = content.splitlines()
        clipped_lines = lines[:max_lines]
        clipped = "\n".join(clipped_lines)
        if len(clipped) > max_chars:
            clipped = clipped[:max_chars]
        is_truncated = len(lines) > max_lines or len(content) > max_chars
        return clipped, is_truncated

    def _build_expandable_block(
        self,
        content: str,
        *,
        as_markdown: bool = False,
        max_chars: int = 700,
        max_lines: int = 8,
    ) -> ft.Control:
        preview, is_truncated = self._truncate_content(
            content,
            max_chars=max_chars,
            max_lines=max_lines,
        )

        if as_markdown:
            body: ft.Control = ft.Markdown(
                preview if is_truncated else content,
                selectable=True,
                extension_set="gitHubFlavored",
            )
        else:
            body = ft.Text(
                preview if is_truncated else content,
                style=MONO_STYLE,
                selectable=True,
            )

        if not is_truncated:
            return body

        expanded = {"value": False}
        state_label = ft.Text("", size=TYPE_SM, color=TEXT_MUTED)
        toggle = ft.IconButton(
            icon=ft.Icons.KEYBOARD_ARROW_DOWN,
            icon_size=18,
            tooltip="Expand",
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.07, ft.Colors.WHITE)},
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )

        def on_toggle(e):
            expanded["value"] = not expanded["value"]
            new_text = content if expanded["value"] else preview
            if isinstance(body, ft.Markdown):
                body.value = new_text
            else:
                body.value = new_text
            toggle.icon = (
                ft.Icons.KEYBOARD_ARROW_UP
                if expanded["value"]
                else ft.Icons.KEYBOARD_ARROW_DOWN
            )
            toggle.tooltip = "Collapse" if expanded["value"] else "Expand"
            state_label.value = "" if expanded["value"] else ""
            if self.page:
                self._safe_page_update()
                self._scroll_chat_to_bottom(animate=False)

        toggle.on_click = on_toggle

        return ft.Column(
            [
                ft.Row(
                    [state_label, ft.Container(expand=True), toggle],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                body,
            ],
            tight=True,
            spacing=SPACE_XS,
        )

    def build_chat_message(self, role: str, content: str, is_error: bool = False) -> ft.Control:
        if role == "assistant" and not is_error:
            bubble = ft.Container(
                content=self._build_chat_markdown(content),
                border_radius=RADIUS_SM,
                padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                width=ASSISTANT_MESSAGE_WIDTH - 20,
            )
        else:
            bg = SURFACE_2 if role == "user" else SURFACE_1
            border_color = BORDER if not is_error else ft.Colors.with_opacity(0.28, ft.Colors.RED_300)
            bubble = ft.Container(
                content=ft.Container(
                    content=self._build_user_message_content(content) if role == "user" else self._build_chat_markdown(content),
                    alignment=ft.Alignment(-1, 0),
                ),
                bgcolor=bg,
                border_radius=RADIUS_MD,
                padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                border=ft.Border.all(1, border_color),
                shadow=SHADOW_SUBTLE if is_error else None,
                width=USER_MESSAGE_WIDTH if role == "user" else ASSISTANT_MESSAGE_WIDTH,
            )

        align = ft.MainAxisAlignment.END if role == "user" else ft.MainAxisAlignment.START
        return self._wrap_in_lane(ft.Row([bubble], alignment=align))

    def build_system_log_message(self, title: str, content: str, level: str = "info") -> ft.Control:
        color = TEXT_SECONDARY
        border = BORDER
        if level == "error":
            color = ft.Colors.with_opacity(0.85, ft.Colors.RED_200)
            border = ft.Colors.with_opacity(0.25, ft.Colors.RED_300)

        card = ft.Container(
            bgcolor=SURFACE_ELEVATED,
            border_radius=RADIUS_SM,
            border=ft.Border.all(1, border if level == "error" else HAIRLINE),
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            width=SPECIAL_CARD_WIDTH,
            content=ft.Column(
                [
                    ft.Text(title, size=10, color=TEXT_MUTED, weight=ft.FontWeight.W_600),
                    ft.Text(content, style=MONO_STYLE, selectable=True, color=color),
                ],
                tight=True,
                spacing=CHAT_BLOCK_GAP,
            ),
        )
        return self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))

    def _add_message(
        self,
        role: str,
        content: str,
        is_error: bool = False,
        force_scroll: bool = True,
    ):
        if not self.messages_column or not self.page:
            return
        self._append_chat_control(self.build_chat_message(role, content, is_error=is_error))
        self._safe_page_update()
        self._scroll_chat_to_bottom(force=force_scroll)

    def _add_assistant_card(self, title: str, content: ft.Control):
        if not self.messages_column or not self.page:
            return

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Text(title, size=TYPE_SM, color=TEXT_MUTED, weight=WEIGHT_SEMIBOLD),
                    ft.Divider(height=1, color=HAIRLINE),
                    content,
                ],
                spacing=CHAT_BLOCK_GAP,
                tight=True,
            ),
            bgcolor=SURFACE_ELEVATED,
            border=ft.Border.all(1, HAIRLINE),
            border_radius=RADIUS_MD,
            padding=ft.Padding.symmetric(horizontal=CARD_PAD_X + 2, vertical=CARD_PAD_Y + 1),
            width=SPECIAL_CARD_WIDTH,
        )
        self._append_chat_control(
            self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        )
        self._safe_page_update()
        self._scroll_chat_to_bottom(force=True)

    def _add_aside_card(self, question: str, answer: str):
        if not self.messages_column or not self.page:
            return

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("/aside", size=TYPE_SM, color="#93F2E8", weight=WEIGHT_BOLD),
                            ft.Container(expand=True),
                            ft.Text("side thread  •  no tools", size=TYPE_XS, color="#78B8B2", weight=WEIGHT_SEMIBOLD),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=1, color=ft.Colors.with_opacity(0.12, "#4ECDC4")),
                    ft.Text(
                        question,
                        size=TYPE_MD,
                        color="#D7F5F0",
                        italic=True,
                        selectable=True,
                    ),
                    self._build_chat_markdown(answer),
                ],
                spacing=CHAT_BLOCK_GAP,
                tight=True,
            ),
            bgcolor="#122024",
            border=ft.Border(
                left=ft.BorderSide(3, "#4ECDC4"),
                top=ft.BorderSide(1, ft.Colors.with_opacity(0.08, "#4ECDC4")),
                right=ft.BorderSide(1, ft.Colors.with_opacity(0.08, "#4ECDC4")),
                bottom=ft.BorderSide(1, ft.Colors.with_opacity(0.08, "#4ECDC4")),
            ),
            border_radius=RADIUS_MD,
            padding=ft.Padding.symmetric(horizontal=CARD_PAD_X + 2, vertical=CARD_PAD_Y + 1),
            width=SPECIAL_CARD_WIDTH,
        )
        self._append_chat_control(
            self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        )
        self._safe_page_update()
        self._scroll_chat_to_bottom(force=True)

    def _add_plan_card(self, plan_text: str):
        if not self.messages_column or not self.page:
            return
        if hasattr(self, "_set_workboard_plan_text"):
            self._set_workboard_plan_text(plan_text)
        self._add_assistant_card(
            "Plan Updated",
            ft.Text(
                "Implementation plan added to Workboard.",
                color=TEXT_SECONDARY,
            ),
        )

    def _add_todo_compact_notice(self, metadata: dict[str, Any] | None, success: bool):
        if not self.messages_column or not self.page:
            return
        md = metadata if isinstance(metadata, dict) else {}
        if not success:
            self._add_assistant_card(
                "Checklist",
                ft.Text("Could not update checklist.", color=ft.Colors.with_opacity(0.88, ft.Colors.RED_300)),
            )
            return

        action = str(md.get("action", "list")).strip().lower()
        scope = str(md.get("scope", "execution")).strip().lower()
        completed = int(md.get("completed", 0) or 0)
        total = int(md.get("total", 0) or 0)
        scope_label = "Planning" if scope == "planning" else "Execution"
        prefix = {
            "add": "Checklist created",
            "complete": "Checklist updated",
            "reopen": "Checklist updated",
            "remove": "Checklist updated",
            "update": "Checklist updated",
            "clear": "Checklist cleared",
            "list": "Checklist refreshed",
        }.get(action, "Checklist updated")
        self._add_assistant_card(
            "Checklist",
            ft.Text(
                f"{prefix} ({scope_label}: {completed}/{total} completed). See Workboard for details.",
                color=TEXT_SECONDARY,
            ),
        )

    def _sanitize_cli_output(self, text: str) -> str:
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", text)
        cleaned = re.sub(r"[│┌┐└┘├┤┬┴┼─]+", "", cleaned)
        cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines())
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _stream_assistant_delta(self, content: str):
        if not self.messages_column or not self.page:
            return

        if self.streaming_markdown is None or self.streaming_container is None:
            self.streaming_text = ""
            self.streaming_markdown = self._build_chat_markdown("")
            self.streaming_container = ft.Container(
                content=self.streaming_markdown,
                border_radius=RADIUS_SM,
                padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                width=ASSISTANT_MESSAGE_WIDTH - 20,
            )
            self._append_chat_control(
                self._wrap_in_lane(
                    ft.Row([self.streaming_container], alignment=ft.MainAxisAlignment.START)
                )
            )

        self.streaming_text += content
        self.streaming_markdown.value = self.streaming_text
        self._safe_page_update()
        self._scroll_chat_to_bottom(animate=True, force=True)

    def _finalize_streaming_message(self):
        self.streaming_markdown = None
        self.streaming_container = None
        self.streaming_text = ""

    def _add_tool_call(
        self,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        tool_kind: str | None,
    ):
        if not self.messages_column or not self.page:
            return
        if not hasattr(self, "_tool_args_by_call_id"):
            self._tool_args_by_call_id = {}
        self._tool_args_by_call_id[call_id] = arguments

        if name == "todos":
            args_text = self._todo_start_hint(arguments)
        else:
            args_text = "\n".join(f"{k}={v}" for k, v in arguments.items()) or "(no args)"
        narrative = describe_tool_activity(
            name,
            arguments,
            stage="start",
        )
        title_text = activity_title(name, stage="start")
        state = "running"
        state_color = ACCENT
        border_color = ACCENT_SOFT
        status_bg = ft.Colors.with_opacity(0.1, ACCENT)
        if name == "shell":
            command = str(arguments.get("command", "")).strip()
            cwd = arguments.get("cwd")
            card = ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                self._shell_state_icon(state, state_color),
                                ft.Text("Running in shell", size=TYPE_BODY, weight=WEIGHT_BOLD, color=TEXT_PRIMARY),
                                ft.Container(expand=True),
                                self._build_status_chip("live", state_color, border_color, status_bg),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(narrative, size=TYPE_SM, color=TEXT_SECONDARY),
                        self._build_shell_command_surface(command, cwd=str(cwd) if isinstance(cwd, str) else None),
                    ],
                    spacing=SPACE_MD,
                    tight=True,
                ),
                border=ft.Border.all(1, border_color),
                border_radius=RADIUS_SM,
                padding=ft.Padding.symmetric(horizontal=CARD_PAD_X, vertical=CARD_PAD_Y),
                width=SPECIAL_CARD_WIDTH,
                bgcolor=SURFACE_ELEVATED,
            )
        else:
            icon_name = self._tool_status_icon(state)
            card = ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(icon_name, size=16, color=state_color),
                                ft.Text(title_text, size=TYPE_BODY, weight=WEIGHT_BOLD, color=TEXT_PRIMARY),
                                ft.Container(expand=True),
                                ft.Text(
                                    f"{name} #{call_id[:8]}" if getattr(self.config, "debug", False) else "",
                                    size=TYPE_SM,
                                    color=TEXT_MUTED,
                                ),
                                self._build_status_chip(
                                    state,
                                    state_color,
                                    border_color,
                                    status_bg,
                                ),
                            ]
                        ),
                        ft.Divider(height=1, color=HAIRLINE),
                        ft.Text(narrative, size=TYPE_SM, color=TEXT_SECONDARY),
                        self._build_tool_payload_surface(
                            self._build_scrollable_text_block(
                                args_text,
                                max_height=140,
                                line_limit=180,
                                markdown=False,
                            )
                        ),
                    ],
                    spacing=SPACE_MD,
                    tight=True,
                ),
                border=ft.Border.all(1, border_color),
                border_radius=RADIUS_SM,
                padding=ft.Padding.symmetric(horizontal=CARD_PAD_X, vertical=CARD_PAD_Y),
                width=SPECIAL_CARD_WIDTH,
                bgcolor=SURFACE_ELEVATED,
            )
        row = self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        row_index = self._append_chat_control(row)
        if row_index is not None:
            self._tool_call_row_indices[call_id] = row_index
        self._safe_page_update()
        self._scroll_chat_to_bottom(force=True)

    def _update_tool_call(
        self,
        call_id: str,
        name: str,
        success: bool,
        output: str,
        error: str | None,
        metadata: dict[str, Any] | None,
        diff: str | None,
        exit_code: int | None,
    ):
        if not self.messages_column or not self.page:
            return

        index = self._tool_call_row_indices.get(call_id)
        if index is None or index >= len(self.messages_column.controls):
            return

        md = metadata if isinstance(metadata, dict) else {}
        policy_redirect = bool(md.get("policy_blocked") and md.get("redirect_to"))
        state_text = "done" if success else ("redirected" if policy_redirect else "failed")
        state_color = SUCCESS if success else (WARNING if policy_redirect else DANGER)
        payload = (output or error or "No output").strip() or "No output"
        args = {}
        if hasattr(self, "_tool_args_by_call_id"):
            args = self._tool_args_by_call_id.get(call_id, {})
        narrative = describe_tool_activity(
            name,
            args,
            md,
            stage="complete",
            success=success,
        )
        if name == "todos":
            narrative = self._todo_completion_narrative(
                success=success,
                metadata=metadata if isinstance(metadata, dict) else {},
            )

        code_mode = False
        language = self._guess_language(
            metadata.get("path") if isinstance(metadata, dict) else None
        )
        start_line = 1
        if isinstance(metadata, dict) and isinstance(metadata.get("shown_start"), int):
            start_line = int(metadata.get("shown_start"))
        code_content = payload
        if self._looks_like_source_excerpt(payload):
            code_content = "\n".join(
                re.sub(r"^\s*\d+\|", "", line) for line in payload.splitlines()
            )
            code_mode = True

        if payload == "No output":
            payload_block = self._build_empty_output_hint()
        elif diff:
            payload_block: ft.Control = self._build_diff_view(diff)
            code_mode = True
        elif name == "todos":
            payload_block = self._build_todo_payload(
                payload=payload,
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        elif code_mode:
            payload_block = self._build_colored_code_view(
                content=code_content,
                language=language,
                start_line=start_line,
            )
            code_mode = True
        elif name in {"glob", "list_dir"} and success:
            paths = self._normalize_path_lines(payload)
            payload_block = self._build_file_list_view(paths)
        elif name == "grep" and success:
            payload_block = self._build_grep_view(payload)
        elif name == "apply_patch" and success and isinstance(metadata, dict) and isinstance(metadata.get("actions"), list):
            payload_block = self._build_patch_actions_view(metadata.get("actions") or [])
        elif name == "shell":
            payload_block = self._build_shell_result_view(
                payload,
                metadata if isinstance(metadata, dict) else {},
                exit_code,
            )
        elif name == "web_search":
            payload_block = self._build_scrollable_text_block(
                payload,
                max_height=240,
                line_limit=420,
                markdown=False,
            )
        elif name == "web_fetch":
            content_type = metadata.get("content_type") if isinstance(metadata, dict) else ""
            payload_block = self._build_scrollable_text_block(
                payload,
                max_height=260,
                line_limit=520,
                markdown=not (isinstance(content_type, str) and "json" in content_type),
            )
        elif self._looks_like_json(payload):
            try:
                normalized = json.dumps(json.loads(payload), indent=2)
            except Exception:
                normalized = payload
            payload_block = self._build_colored_code_view(
                content=normalized,
                language="json",
                start_line=1,
                max_height=280,
                line_limit=500,
            )
            code_mode = True
        else:
            payload_block = self._build_scrollable_text_block(
                payload,
                max_height=220,
                line_limit=500,
                markdown=False,
            )
        recoverable = bool(md.get("recoverable")) or policy_redirect
        title_text = activity_title(name, stage="complete", success=success, metadata=md)
        summary_row = self._build_meta_summary(name, metadata if isinstance(metadata, dict) else None, exit_code)
        if policy_redirect:
            payload = "No output"
            payload_block = self._build_scrollable_text_block(
                f"Continuing with `{md.get('redirect_to')}`.",
                max_height=100,
                line_limit=4,
                markdown=False,
            )

        if name == "shell":
            content_items = [
                ft.Row(
                    [
                        self._shell_state_icon(state_text, state_color),
                        ft.Text(
                            "Command finished" if success else ("Command needs retry" if recoverable else "Command failed"),
                            size=TYPE_BODY,
                            weight=WEIGHT_BOLD,
                            color=TEXT_PRIMARY,
                        ),
                        ft.Container(expand=True),
                        self._build_status_chip(
                            "done" if success else ("redirected" if policy_redirect else ("retry" if recoverable else "failed")),
                            state_color,
                            SUCCESS_SOFT if success else (WARNING_SOFT if recoverable else DANGER_SOFT),
                            ft.Colors.with_opacity(
                                0.1,
                                ft.Colors.GREEN_300 if success else (ft.Colors.AMBER_300 if recoverable else ft.Colors.RED_300),
                            ),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text(narrative, size=TYPE_SM, color=TEXT_SECONDARY),
                self._build_shell_command_surface(
                    str(args.get("command", "")).strip(),
                    cwd=str(metadata.get("cwd")) if isinstance(metadata, dict) and isinstance(metadata.get("cwd"), str) else None,
                ),
            ]
        else:
            icon_name = self._tool_status_icon(state_text)
            content_items = [
                ft.Row(
                    [
                        ft.Icon(icon_name, size=16, color=state_color),
                        ft.Text(title_text, size=TYPE_BODY, weight=WEIGHT_BOLD, color=TEXT_PRIMARY),
                        ft.Container(expand=True),
                        ft.Text(
                            f"{name} #{call_id[:8]}" if getattr(self.config, "debug", False) else "",
                            size=TYPE_SM,
                            color=TEXT_MUTED,
                        ),
                        self._build_status_chip(
                            state_text,
                            state_color,
                            SUCCESS_SOFT if success else (WARNING_SOFT if recoverable else DANGER_SOFT),
                            ft.Colors.with_opacity(
                                0.1,
                                ft.Colors.GREEN_300 if success else (ft.Colors.AMBER_300 if recoverable else ft.Colors.RED_300),
                            ),
                        ),
                    ]
                ),
                ft.Divider(height=1, color=HAIRLINE),
                ft.Text(narrative, size=TYPE_SM, color=TEXT_SECONDARY),
            ]
        if summary_row is not None:
            content_items.append(summary_row)
        if name == "shell":
            content_items.append(payload_block)
        else:
            content_items.append(self._build_tool_payload_surface(payload_block, code_mode=code_mode))

        card = ft.Container(
            content=ft.Column(
                content_items,
                spacing=SPACE_MD,
                tight=True,
            ),
            border=ft.Border.all(1, SUCCESS_SOFT if success else DANGER_SOFT),
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=CARD_PAD_X, vertical=CARD_PAD_Y),
            width=SPECIAL_CARD_WIDTH,
            bgcolor=SURFACE_ELEVATED,
        )
        self.messages_column.controls[index] = self._wrap_in_lane(
            ft.Row([card], alignment=ft.MainAxisAlignment.START)
        )
        self._safe_page_update()
        self._scroll_chat_to_bottom(animate=False, force=True)

    def _todo_start_hint(self, arguments: dict[str, Any]) -> str:
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
            return f"Creating your {label}" + (f" with {count} task(s)." if count else ".")
        if action == "complete":
            return f"Marking a task complete in your {label}."
        if action == "reopen":
            return f"Reopening a task in your {label}."
        if action == "remove":
            return f"Removing a task from your {label}."
        if action == "update":
            return f"Updating a task in your {label}."
        if action == "list":
            return f"Refreshing your {label}."
        if action == "clear":
            return f"Clearing your {label}."
        return f"Updating your {label}."

    def _todo_completion_narrative(self, *, success: bool, metadata: dict[str, Any]) -> str:
        if not success:
            return "Could not update the checklist."
        scope = str(metadata.get("scope", "execution")).strip().lower()
        action = str(metadata.get("action", "list")).strip().lower()
        label = "planning checklist" if scope == "planning" else "execution checklist"
        if action == "add":
            return f"Added tasks to your {label}."
        if action == "complete":
            return f"Marked a task complete in your {label}."
        if action == "reopen":
            return f"Reopened a task in your {label}."
        if action == "remove":
            return f"Removed a task from your {label}."
        if action == "update":
            return f"Updated a task in your {label}."
        if action == "clear":
            return f"Cleared your {label}."
        return f"Refreshed your {label}."

    def _build_todo_payload(self, payload: str, metadata: dict[str, Any]) -> ft.Control:
        scope = str(metadata.get("scope", "execution")).strip().lower()
        action = str(metadata.get("action", "list")).strip().lower()
        pending = int(metadata.get("pending", 0) or 0)
        completed = int(metadata.get("completed", 0) or 0)
        total = int(metadata.get("total", 0) or 0)
        message = str(metadata.get("message", "") or "").strip()
        scope_label = "Planning" if scope == "planning" else "Execution"
        title = f"{scope_label} checklist"
        ratio = (completed / total) if total > 0 else 0.0

        pending_items: list[str] = []
        completed_items: list[str] = []
        for raw in payload.splitlines():
            stripped = raw.strip()
            if stripped.startswith("☐"):
                task_text = re.sub(r"^\[([^\]]+)\]\s*", "", stripped[1:].strip())
                pending_items.append(task_text)
            elif stripped.startswith("☑"):
                task_text = re.sub(r"^\[([^\]]+)\]\s*", "", stripped[1:].strip())
                completed_items.append(task_text)

        chips = ft.Row(
            [
                ft.Container(
                    content=ft.Text(
                        f"{completed}/{total} completed",
                        size=TYPE_SM,
                        color=SUCCESS,
                        weight=WEIGHT_SEMIBOLD,
                    ),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    border=ft.Border.all(1, SUCCESS_SOFT),
                    border_radius=RADIUS_LG,
                    bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.GREEN_300),
                ),
                ft.Container(
                    content=ft.Text(
                        f"{pending} pending",
                        size=TYPE_SM,
                        color=WARNING,
                        weight=WEIGHT_SEMIBOLD,
                    ),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    border=ft.Border.all(1, WARNING_SOFT),
                    border_radius=RADIUS_LG,
                    bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.AMBER_300),
                ),
            ],
            spacing=8,
            wrap=True,
        )

        progress_bar = ft.ProgressBar(
            value=ratio,
            color=SUCCESS,
            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.WHITE),
            bar_height=7,
        )

        lines: list[ft.Control] = [
            ft.Text(title, size=TYPE_TITLE, color=TEXT_PRIMARY, weight=WEIGHT_BOLD),
            chips,
            progress_bar,
        ]
        if action == "add":
            lines.append(ft.Text("Checklist initialized", size=TYPE_SM, color=TEXT_SECONDARY))
        elif action == "complete":
            lines.append(ft.Text("Progress updated", size=TYPE_SM, color=TEXT_SECONDARY))
        elif action == "clear":
            lines.append(ft.Text("Checklist cleared", size=TYPE_SM, color=TEXT_SECONDARY))

        if pending_items:
            lines.append(ft.Text("Up next", size=TYPE_SM, color=TEXT_MUTED, weight=WEIGHT_SEMIBOLD))
            for task_text in pending_items[:6]:
                lines.append(ft.Text(f"□ {task_text}", size=TYPE_BODY, color=TEXT_PRIMARY))
            if len(pending_items) > 6:
                lines.append(ft.Text(f"+{len(pending_items) - 6} more pending", size=TYPE_SM, color=TEXT_MUTED))

        if completed_items:
            lines.append(ft.Text("Done", size=TYPE_SM, color=TEXT_MUTED, weight=WEIGHT_SEMIBOLD))
            for task_text in completed_items[:4]:
                lines.append(ft.Text(f"✓ {task_text}", size=TYPE_BODY, color=TEXT_SECONDARY))
            if len(completed_items) > 4:
                lines.append(ft.Text(f"+{len(completed_items) - 4} more completed", size=TYPE_SM, color=TEXT_MUTED))

        if message:
            lines.append(ft.Text(message, size=TYPE_SM, color=TEXT_MUTED))

        return ft.Container(
            content=ft.Column(lines, spacing=7, tight=True),
            padding=ft.Padding.symmetric(horizontal=10, vertical=10),
            border=ft.Border.all(1, BORDER),
            border_radius=RADIUS_MD,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
        )
