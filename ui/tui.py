from config.config import Config
from utils.text import truncate_text
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich import box
from utils.paths import display_path_relative_to_cwd
from pathlib import Path
from typing import Any
from rich.text import Text
from rich.rule import Rule
from rich.theme import Theme
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from typing import Tuple
import re

AGENT_THEME = Theme(
    {
        # General
        "info": "cyan",
        "warning": "yellow",
        "error": "bright_red bold",
        "success": "green",
        "dim": "dim",
        "muted": "grey50",
        "border": "grey35",
        "highlight": "bold cyan",
        # Roles
        "user": "bright_blue bold",
        "assistant": "bright_white",
        # Tools
        "tool": "bright_magenta bold",
        "tool.read": "cyan",
        "tool.write": "yellow",
        "tool.shell": "magenta",
        "tool.network": "bright_blue",
        "tool.memory": "green",
        "tool.mcp": "bright_cyan",
        # Code / blocks
        "code": "white",
    }
)

_console: Console | None = None


def get_console() -> Console:
    global _console
    if _console is None:
        _console = Console(theme=AGENT_THEME, highlight=False)

    return _console


class TUI:
    def __init__(
        self,
        config: Config,
        console: Console | None = None,
    ) -> None:
        self.console = console or get_console()
        self._assistant_stream_open = False
        self._tool_args_by_call_id: dict[str, dict[str, Any]] = {}
        self.config = config
        self.cwd = self.config.cwd
        self._max_block_tokens = 2500

    def begin_assistant(self) -> None:
        self.console.print()
        self.console.print(
            Rule(
                Text("Assistant", style="assistant"),
            )
        )
        self._assistant_stream_open = True

    def end_assistant(self) -> None:
        if self._assistant_stream_open:
            self.console.print()
        self._assistant_stream_open = False

    def stream_assistant_delta(self, content: str) -> None:
        self.console.print(content, end="", markup=False)

    def _ordered_args(self, tool_name: str, args: dict[str, Any]) -> list[Tuple]:
        _PREFERRED_ORDER = {
            "read_file": ["path", "offset", "limit"],
            "write_file": ["path", "create_directories", "content"],
            "edit": ["path", "replace_all", "old_string", "new_string"],
            "shell": ["command", "timeout", "cwd"],
            "list_dir": ["path", "include_hidden"],
            "grep": ["path", "case_insensitive", "pattern"],
            "glob": ["path", "pattern"],
            "web_search": ["query", "max_results"],
            "todos": ["action", "task", "due_date"],
            "memory": ["action", "key", "value"],
        }

        preferred = _PREFERRED_ORDER.get(tool_name, [])
        ordered: list[tuple[str, Any]] = []
        seen = set()

        for key in preferred:
            if key in args:
                ordered.append((key, args[key]))
                seen.add(key)

        remaining_keys = set(args.keys() - seen)

        ordered.extend((key, args[key]) for key in remaining_keys)

        return ordered

    def _render_args_table(self, tool_name: str, args: dict[str, Any]) -> Table:
        table = Table.grid(padding=(0, 1))
        table.add_column(style="muted", justify="right", no_wrap=True)
        table.add_column(style="code", overflow="fold")

        for key, value in self._ordered_args(tool_name, args):
            if isinstance(value, str):
                if key in {"content", "old_string", "new_string"}:
                    line_count = len(value.splitlines()) or 0
                    byte_count = len(value.encode("utf-8", errors="replace"))
                    value = f" <-- {line_count} lines | {byte_count} bytes -->"

            if isinstance(value, bool):
                value = str(value)
            elif not isinstance(value, str):
                value = str(value)

            table.add_row(key, value)

        return table

    def tool_call_start(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        arguments: dict[str, Any],
    ) -> None:
        self._tool_args_by_call_id[call_id] = arguments

        border_style = f"tool.{tool_kind}" if tool_kind else "tool"

        title = Text.assemble(
            ("⏺ ", "muted"),
            (name, border_style),
            (" ", "muted"),
            (f"#{call_id[:8]}", "muted"),
        )

        display_args = dict(arguments)
        for key in ("path", "cwd"):
            val = display_args.get(key)
            if isinstance(val, str) and self.cwd:
                display_args[key] = str(display_path_relative_to_cwd(val, self.cwd))

        panel = Panel(
            self._render_args_table(name, display_args)
            if display_args
            else Text("(no args)", style="muted"),
            title=title,
            title_align="left",
            subtitle=Text("running...", style="muted"),
            subtitle_align="right",
            border_style=border_style,
            box=box.ROUNDED,
            padding=(1, 2),
        )

        self.console.print()
        self.console.print(panel)

    def _extract_read_file_code(self, text: str) -> tuple[int, str] | None:
        body = text
        header_match = re.match(r"Showing lines (\d+)-(\d+) of (\d+)\n\n", text)
        if header_match:
            body = text[header_match.end() :]

        code_lines: list[str] = []
        start_line: int | None = None
        for line in body.splitlines():
            m = re.match(r"^\s*(\d+)\|(.*)$", line)
            if not m:
                return None

            line_no = int(m.group(1))

            if start_line is None:
                start_line = line_no

            code_lines.append(m.group(2))

        if start_line is None:
            return None

        return start_line, "\n".join(code_lines)

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
            ".bash": "bash",
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
            ".kts": "kotlin",
        }.get(suffix, "text")

    def _gradient_text(self, text: str) -> Text:
        start_r, start_g, start_b = 0, 200, 255
        end_r, end_g, end_b = 180, 80, 255

        rich_text = Text()
        total = max(len(text) - 1, 1)

        for i, char in enumerate(text):
            t = i / total
            r = int(start_r + (end_r - start_r) * t)
            g = int(start_g + (end_g - start_g) * t)
            b = int(start_b + (end_b - start_b) * t)
            rich_text.append(char, style=f"bold #{r:02x}{g:02x}{b:02x}")

        return rich_text

    def print_welcome(
        self,
        model: str = "",
        cwd: str = "",
        commands: list[str] | None = None,
        version: str = "0.1.0",
    ) -> None:
        import pyfiglet

        ascii_art = pyfiglet.figlet_format("ite", font="slant")
        logo = self._gradient_text(ascii_art.rstrip())

        info_table = Table.grid(padding=(0, 2))
        info_table.add_column(style="muted", justify="right", min_width=8)
        info_table.add_column(style="code")

        cwd_display = str(cwd).replace(str(Path.home()), "~")
        info_table.add_row("model", Text(model or "not set", style="cyan"))
        info_table.add_row("cwd", Text(cwd_display, style="info"))
        if commands:
            info_table.add_row("commands", Text("  ".join(commands), style="success"))

        footer = Text(f"v{version} · type /help for commands", style="dim")

        content = Group(
            Text(),
            logo,
            Text(),
            Rule(style="grey35"),
            Text(),
            info_table,
            Text(),
            footer,
        )

        self.console.print(
            Panel(
                content,
                border_style="grey35",
                box=box.DOUBLE,
                padding=(0, 3),
            )
        )
        self.console.print()

    def tool_call_complete(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        success: bool,
        output: str,
        error: str | None,
        metadata: dict[str, Any] | None,
        diff: str | None,
        truncated: bool,
        exit_code: int | None,
    ) -> None:

        border_style = f"tool.{tool_kind}" if tool_kind else "tool"
        status_icon = "✅" if success else "❌"
        status_style = "success" if success else "error"

        title = Text.assemble(
            (f"{status_icon} ", status_style),
            (name, border_style),
            (" ", "muted"),
            (f"#{call_id[:8]}", "muted"),
        )

        args = self._tool_args_by_call_id.get(call_id, {})

        primary_path = None
        blocks = []

        if isinstance(metadata, dict) and isinstance(metadata.get("path"), str):
            primary_path = metadata.get("path")

        if name == "read_file" and success:
            if primary_path:
                start_line, code = self._extract_read_file_code(output)
                shown_start = metadata.get("shown_start")
                shown_end = metadata.get("shown_end")
                total_lines = metadata.get("total_lines")

                language = self._guess_language(primary_path)

                header_parts = [display_path_relative_to_cwd(primary_path, self.cwd)]
                header_parts.append(" ⏺ ")

                if shown_start and shown_end and total_lines:
                    header_parts.append(
                        f"lines {shown_start}-{shown_end} of {total_lines}"
                    )

                header = "".join(header_parts)

                blocks.append(Text(header, style="muted"))
                blocks.append(Text())
                blocks.append(
                    Syntax(
                        code,
                        language,
                        theme="monokai",
                        line_numbers=True,
                        start_line=start_line,
                        word_wrap=False,
                    )
                )
            else:
                output_display = truncate_text(
                    output,
                    "",
                    self._max_block_tokens,
                )
                blocks.append(
                    Syntax(
                        output_display,
                        "text",
                        theme="monokai",
                        word_wrap=False,
                    )
                )

        elif name in {"write_file", "edit"} and success and diff:
            output_line = output.strip() if output.strip() else "Completed"
            blocks.append(Text(output_line, style="muted"))
            diff_text = diff
            diff_display = truncate_text(
                diff_text,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(Syntax(diff_display, "diff", theme="monokai", word_wrap=True))

        elif name == "shell" and success:
            command = args.get("command")
            if isinstance(command, str) and command.strip():
                blocks.append(Text(f"$ {command.strip()}", style="muted"))

            if exit_code is not None:
                blocks.append(Text(f"exit_code={exit_code}", style="muted"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(output_display, "text", theme="monokai", word_wrap=True)
            )

        elif name == "list_dir" and success:
            entries = metadata.get("entries")
            path = metadata.get("path")
            summary = []

            if isinstance(path, str):
                summary.append(path)

            if isinstance(entries, int):
                summary.append(f"{entries} entries")

            if summary:
                blocks.append(Text(" • ".join(summary), style="muted"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(output_display, "text", theme="monokai", word_wrap=True)
            )

        elif name == "grep" and success:
            matches = metadata.get("matches")
            files_searched = metadata.get("files_searched")
            summary = []

            if isinstance(matches, int):
                if matches == 1:
                    summary.append("1 match was found")
                else:
                    summary.append(f"{matches} matches were found")

            if isinstance(files_searched, int):
                file_word = "file" if files_searched == 1 else "files"
                summary.append(f"searched {files_searched} {file_word}")

            if summary:
                blocks.append(Text(" • ".join(summary), style="muted"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(output_display, "text", theme="monokai", word_wrap=True)
            )

        elif name == "glob" and success:
            matches = metadata.get("matches")

            if isinstance(matches, int):
                if matches == 1:
                    blocks.append(Text("1 match was found", style="muted"))
                else:
                    blocks.append(Text(f"{matches} matches were found", style="muted"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )
            blocks.append(
                Syntax(output_display, "text", theme="monokai", word_wrap=True)
            )

        elif name == "web_search" and success:
            results_count = metadata.get("results")
            query = args.get("query")

            summary = []

            if isinstance(query, str):
                summary.append(f'"{query}"')

            if isinstance(results_count, int):
                if results_count == 1:
                    summary.append("1 result")
                else:
                    summary.append(f"{results_count} results")

            if summary:
                blocks.append(Text(" • ".join(summary), style="muted"))
                blocks.append(Text())

            # Parse results into structured data
            results = []
            current = {}
            for line in output.splitlines():
                line = line.strip()
                if not line or line.startswith("Search results for:"):
                    if current:
                        results.append(current)
                        current = {}
                    continue
                if line and line[0].isdigit() and ". Title: " in line:
                    if current:
                        results.append(current)
                    current = {"title": line.split(". Title: ", 1)[1]}
                elif line.startswith("URL: "):
                    current["url"] = line[5:]
                elif line.startswith("Snippet: "):
                    current["snippet"] = line[9:]
            if current:
                results.append(current)

            result_table = Table.grid(padding=(0, 1))
            result_table.add_column(style="muted", justify="right", width=3)
            result_table.add_column()

            for i, r in enumerate(results, start=1):
                title_text = Text()
                title_text.append(r.get("title", ""), style="highlight")
                result_table.add_row(f"{i}.", title_text)

                if r.get("url"):
                    result_table.add_row("", Text(r["url"], style="dim"))

                if r.get("snippet"):
                    result_table.add_row("", Text(r["snippet"], style="muted"))

                # spacer between results
                if i < len(results):
                    result_table.add_row("", Text())

            blocks.append(result_table)

        elif name == "web_fetch" and success:
            status_code = metadata.get("status_code")
            content_type = metadata.get("content_type")
            content_length = metadata.get("content_length")

            url = args.get("url")

            summary = []

            if isinstance(status_code, int):
                summary.append(str(status_code))

            if isinstance(content_length, int):
                summary.append(f"{content_length} bytes")

            if isinstance(content_type, str):
                summary.append(content_type)

            if isinstance(url, str):
                summary.append(url)

            if summary:
                blocks.append(Text(" • ".join(summary), style="muted"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )

            if isinstance(content_type, str) and "json" in content_type:
                blocks.append(
                    Syntax(output_display, "json", theme="monokai", word_wrap=True)
                )
            else:
                blocks.append(Markdown(output_display))

        elif name == "todos" and success:
            completed = metadata.get("completed", 0) if metadata else 0
            total = metadata.get("total", 0) if metadata else 0
            action = metadata.get("action", "") if metadata else ""

            # Progress header
            if total > 0:
                bar_width = 20
                filled = int((completed / total) * bar_width) if total else 0
                bar = "█" * filled + "░" * (bar_width - filled)
                header = Text()
                header.append(f"Tasks: {completed}/{total} completed ", style="muted")
                header.append(bar, style="green" if completed == total else "yellow")
                blocks.append(header)
                blocks.append(Text())

            # Render each line with styled checkboxes
            for line in output.splitlines():
                styled = Text()
                stripped = line.strip()
                if stripped.startswith("☑"):
                    styled.append("  ☑ ", style="bold green")
                    styled.append(
                        stripped[1:].strip(),
                        style="dim strikethrough",
                    )
                elif stripped.startswith("☐"):
                    styled.append("  ☐ ", style="bold yellow")
                    styled.append(stripped[1:].strip(), style="white")
                else:
                    continue

                blocks.append(styled)

            if action == "clear":
                blocks.append(Text("  All todos cleared", style="muted"))

        elif name == "memory" and success:
            action = args.get("action", "")
            key = args.get("key", "")

            if action == "set":
                styled = Text()
                styled.append("  ✓ ", style="bold green")
                styled.append("Saved ", style="muted")
                styled.append(key, style="bold cyan")
                blocks.append(styled)

            elif action == "get":
                found = metadata.get("found", False) if metadata else False
                styled = Text()
                if found:
                    styled.append("  🔑 ", style="bold cyan")
                    styled.append(f"{key}", style="bold cyan")
                    styled.append(" → ", style="muted")
                    # Extract value from output after "key: "
                    val = output.split(f"{key}: ", 1)[-1] if key else output
                    styled.append(val, style="white")
                else:
                    styled.append("  ○ ", style="dim")
                    styled.append(f"{key} ", style="dim")
                    styled.append("not found", style="dim italic")
                blocks.append(styled)

            elif action == "delete":
                styled = Text()
                styled.append("  ✗ ", style="bold red")
                styled.append("Deleted ", style="muted")
                styled.append(key, style="bold cyan")
                blocks.append(styled)

            elif action == "list":
                found = metadata.get("found", False) if metadata else False
                if not found:
                    blocks.append(Text("  No memories stored", style="muted"))
                else:
                    mem_table = Table(
                        show_header=True,
                        header_style="bold cyan",
                        box=None,
                        padding=(0, 2),
                    )
                    mem_table.add_column("Key", style="cyan")
                    mem_table.add_column("Value", style="white")

                    for line in output.splitlines():
                        stripped = line.strip()
                        if ":" in stripped and not stripped.startswith("Stored"):
                            k, v = stripped.split(":", 1)
                            mem_table.add_row(k.strip(), v.strip())

                    blocks.append(mem_table)

            elif action == "clear":
                blocks.append(Text(f"  ✓ {output}", style="muted"))

        if error and not success:
            blocks.append(Text(error, style="error"))

            output_display = truncate_text(
                output,
                self.config.model_name,
                self._max_block_tokens,
            )

            if output_display.strip():
                blocks.append(
                    Syntax(output_display, "text", theme="monokai", word_wrap=True)
                )
            else:
                blocks.append(Text("No output", style="muted"))

        if truncated:
            blocks.append(Text("... [truncated]", style="warning"))

        panel = Panel(
            Group(*blocks),
            title=title,
            title_align="left",
            subtitle=Text("done" if success else "failed", style=status_style),
            subtitle_align="right",
            border_style=border_style,
            box=box.HEAVY,
            padding=(1, 2),
        )

        self.console.print()
        self.console.print(panel)
