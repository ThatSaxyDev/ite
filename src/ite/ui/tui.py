import json
import re
from pathlib import Path
from typing import Any, Tuple

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from ite.agent.change_history import change_entries_with_stats
from ite.config.config import Config
from ite.tools.base import ToolConfirmation
from ite.ui.tool_narrative import activity_title, describe_tool_activity
from ite.utils.paths import display_path_relative_to_cwd
from ite.utils.text import truncate_text

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
        self._assistant_buffer: str = ""
        self._assistant_live: Live | None = None
        self._assistant_stream_frame: int = 0
        self._tool_args_by_call_id: dict[str, dict[str, Any]] = {}
        self.config = config
        self.cwd = self.config.cwd
        self._max_block_tokens = 2500
        self._assistant_live_max_preview_lines = 12
        # Spinner state
        self._spinner_live: Live | None = None
        self._spinner_running = False

    def start_spinner(self, command: str, message: str = "Thinking") -> None:
        """Show an animated spinner with a message."""
        if self._spinner_running:
            return
        spinner = Spinner(
            "dots2",
            text=Text.assemble(
                (" ", "assistant"),
                (f"{message}...", "assistant"),
            ),
            style="assistant",
        )
        self._spinner_live = Live(
            spinner,
            console=self.console,
            refresh_per_second=10,
            transient=True,  # Erase spinner when stopped
        )
        self._spinner_live.start()
        self._spinner_running = True

    def stop_spinner(self) -> None:
        """Stop and remove the spinner."""
        if self._spinner_live and self._spinner_running:
            self._spinner_live.stop()
        self._spinner_live = None
        self._spinner_running = False

    def begin_assistant(self) -> None:
        self._assistant_buffer = ""
        self._assistant_stream_open = True
        self._assistant_stream_frame = 0
        if self._assistant_live is not None:
            self._assistant_live.stop()
        self._assistant_live = Live(
            self._render_assistant_panel("", streaming=True),
            console=self.console,
            refresh_per_second=12,
            transient=True,
        )
        self._assistant_live.start()

    def _render_assistant_panel(
        self, content: str, *, streaming: bool = False
    ) -> Panel:
        if streaming:
            body = self._render_assistant_stream_preview(content)
        else:
            body = (
                Markdown(content) if content.strip() else Text(" ", style="assistant")
            )
        return Panel(
            body,
            border_style="bright_white",
            box=box.HEAVY,
            padding=(0, 1),
        )

    def _render_assistant_stream_preview(self, content: str):
        if not content.strip():
            return Text(" ", style="assistant")

        preview, was_truncated = self._truncate_stream_preview(
            content,
            max_lines=self._assistant_live_max_preview_lines,
        )
        blocks: list[Any] = [
            Markdown(preview),
        ]
        spinner_frames = ["|", "/", "-", "\\"]
        spinner = spinner_frames[self._assistant_stream_frame % len(spinner_frames)]
        if was_truncated:
            blocks.append(
                Padding(
                    Text(f"{spinner}", style="muted"),
                    (1, 0, 0, 0),
                )
            )
        else:
            blocks.append(
                Padding(
                    Text(f"{spinner}", style="muted"),
                    (1, 0, 0, 0),
                )
            )
        return Group(*blocks)

    def _truncate_stream_preview(
        self, text: str, *, max_lines: int
    ) -> tuple[str, bool]:
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text, False
        clipped = "\n".join(lines[-max_lines:]).rstrip()
        if clipped:
            clipped = "...\n\n" + clipped
        else:
            clipped = "..."
        return clipped, True

    def end_assistant(self, final_content: str | None = None) -> None:
        render_content = (
            final_content if final_content is not None else self._assistant_buffer
        ).strip()
        if self._assistant_live is not None:
            if render_content:
                self._assistant_live.update(
                    self._render_assistant_panel(render_content, streaming=True)
                )
            self._assistant_live.stop()
            self._assistant_live = None
        if self._assistant_stream_open and render_content:
            self.console.print(
                self._render_assistant_panel(render_content, streaming=False)
            )
        self._assistant_stream_open = False
        self._assistant_buffer = ""

    def render_change_summary(self, change_set: object | None, cwd: Path) -> None:
        entries, extra = change_entries_with_stats(change_set, cwd=cwd, max_items=3)
        if not entries:
            return
        count = len(getattr(change_set, "changes", []) or [])
        files_text = f"{count} file" if count == 1 else f"{count} files"
        lines = []
        for name, additions, deletions in entries:
            line = f"[dim]• {name}[/dim]"
            if additions:
                line += f"  [green]+{additions}[/green]"
            if deletions:
                line += f"  [red]-{deletions}[/red]"
            lines.append(line)
        if extra:
            lines.append(f"[dim]• +{extra} more[/dim]")
        lines.append("")
        lines.append(f"[dim]Changed {files_text} in this turn.[/dim]")
        lines.append("[dim]Run /undo to revert these edits.[/dim]")
        self.console.print(
            Panel(
                "\n".join(lines),
                title=Text("Changed", style="bold cyan"),
                border_style="cyan",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )

    def stream_assistant_delta(self, content: str) -> None:
        self._assistant_buffer += content
        self._assistant_stream_frame += 1
        if self._assistant_live is not None:
            self._assistant_live.update(
                self._render_assistant_panel(self._assistant_buffer, streaming=True)
            )

    def _ordered_args(self, tool_name: str, args: dict[str, Any]) -> list[Tuple]:
        _PREFERRED_ORDER = {
            "read_file": ["path", "offset", "limit"],
            "write_file": ["path", "create_directories", "content"],
            "edit": ["path", "replace_all", "old_string", "new_string"],
            "read_toml": ["path", "key_path"],
            "write_toml": ["path", "key_path", "operation", "value", "create_missing"],
            "read_yaml": ["path", "key_path"],
            "write_yaml": ["path", "key_path", "operation", "value", "create_missing"],
            "read_env": ["path", "key"],
            "write_env": ["path", "key", "operation", "value"],
            "http_request": ["method", "url", "params", "headers", "json_body", "body", "timeout"],
            "list_archive": ["path", "limit"],
            "read_pdf": ["path", "pages", "max_pages"],
            "read_image": ["path", "ocr"],
            "shell": ["command", "timeout", "cwd"],
            "list_dir": ["path", "include_hidden"],
            "grep": ["path", "case_insensitive", "pattern"],
            "glob": ["path", "pattern"],
            "web_search": ["query", "max_results"],
            "todos": ["action", "scope", "id", "content", "items", "new_content"],
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

    def _render_subagent_start_summary(
        self, name: str, args: dict[str, Any]
    ) -> list[Any]:
        blocks: list[Any] = []
        specialist = name.removeprefix("subagent_").strip() or "specialist"
        goal = str(args.get("goal", "")).strip()

        blocks.append(Text(f"Specialist: {specialist}", style="muted"))
        if goal:
            first_line = next(
                (line.strip() for line in goal.splitlines() if line.strip()), ""
            )
            if len(first_line) > 120:
                first_line = first_line[:117].rstrip() + "..."
            if first_line:
                blocks.append(Text(f"Focus: {first_line}", style="code"))

        return blocks

    def tool_call_start(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        arguments: dict[str, Any],
    ) -> None:
        if name == "memory":
            return
        self._tool_args_by_call_id[call_id] = arguments
        narrative = describe_tool_activity(
            name,
            arguments,
            stage="start",
        )
        title_text = activity_title(name, stage="start")

        border_style = f"tool.{tool_kind}" if tool_kind else "tool"

        title = Text.assemble(
            ("⏺ ", "muted"),
            (title_text, border_style),
        )
        if self.config.debug:
            title.append(f"  {name} #{call_id[:8]}", "muted")

        display_args = dict(arguments)
        for key in ("path", "cwd"):
            val = display_args.get(key)
            if isinstance(val, str) and self.cwd:
                display_args[key] = str(display_path_relative_to_cwd(val, self.cwd))

        if name == "todos":
            scope = str(display_args.get("scope", "execution")).strip().lower()
            action = str(display_args.get("action", "update")).strip().lower()
            label = "planning checklist" if scope == "planning" else "task checklist"
            hint = "Updating checklist"
            if action == "add":
                count = 0
                items = display_args.get("items")
                if isinstance(items, list):
                    count = len(items)
                elif isinstance(display_args.get("content"), str) and display_args.get(
                    "content"
                ):
                    count = 1
                hint = f"Creating {label}" + (f" ({count} items)" if count else "")
            elif action == "complete":
                hint = f"Marking item complete in {label}"
            elif action == "reopen":
                hint = f"Reopening item in {label}"
            elif action == "remove":
                hint = f"Removing item from {label}"
            elif action == "update":
                hint = f"Updating item in {label}"
            elif action == "list":
                hint = f"Refreshing {label}"
            elif action == "clear":
                hint = f"Clearing {label}"

            panel = Panel(
                Group(
                    Text(narrative, style="muted"),
                    Text(hint, style="code"),
                ),
                title=title,
                title_align="left",
                subtitle=Text("running...", style="muted"),
                subtitle_align="right",
                border_style=border_style,
                box=box.ROUNDED,
                padding=(0, 1),
            )
            self.console.print()
            self.console.print(panel)
            return

        if name.startswith("subagent_"):
            panel = Panel(
                Group(
                    Text(narrative, style="muted"),
                    *self._render_subagent_start_summary(name, display_args),
                ),
                title=title,
                title_align="left",
                subtitle=Text("running...", style="muted"),
                subtitle_align="right",
                border_style=border_style,
                box=box.ROUNDED,
                padding=(0, 1),
            )
            self.console.print()
            self.console.print(panel)
            return

        panel = Panel(
            Group(
                Text(narrative, style="muted"),
                self._render_args_table(name, display_args)
                if display_args
                else Text("(no args)", style="muted"),
            ),
            title=title,
            title_align="left",
            subtitle=Text("running...", style="muted"),
            subtitle_align="right",
            border_style=border_style,
            box=box.ROUNDED,
            padding=(0, 1),
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

    def _summary_line(self, *parts: str) -> Text:
        clean = [p for p in parts if p]
        return Text(" • ".join(clean), style="muted")

    def _truncate_for_tool(
        self,
        name: str,
        text: str,
        *,
        preserve_lines: bool = True,
    ) -> tuple[str, bool]:
        if not text:
            return text, False

        max_lines_by_tool = {
            "read_file": 16,
            "write_file": 18,
            "edit": 18,
            "list_dir": 10,
            "glob": 10,
            "grep": 24,
            "shell": 18,
            "web_fetch": 24,
            "web_search": 18,
            "todos": 14,
            "memory": 12,
            "read_toml": 18,
            "write_toml": 18,
            "read_yaml": 18,
            "write_yaml": 18,
            "read_env": 16,
            "write_env": 16,
            "http_request": 18,
            "list_archive": 16,
            "read_pdf": 18,
            "read_image": 16,
        }
        max_chars_by_tool = {
            "read_file": 2600,
            "write_file": 2400,
            "edit": 2400,
            "list_dir": 900,
            "glob": 900,
            "grep": 2800,
            "shell": 2200,
            "web_fetch": 3200,
            "web_search": 2200,
            "todos": 1600,
            "memory": 1200,
            "read_toml": 2200,
            "write_toml": 2200,
            "read_yaml": 2200,
            "write_yaml": 2200,
            "read_env": 1800,
            "write_env": 1800,
            "http_request": 2200,
            "list_archive": 1800,
            "read_pdf": 2600,
            "read_image": 1800,
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

        token_truncated = truncate_text(
            clipped,
            self.config.model_name,
            self._max_block_tokens,
            preserve_lines=preserve_lines,
        )
        if token_truncated != clipped:
            was_truncated = True

        return token_truncated, was_truncated

    def _render_grep_block(self, output: str) -> Table | None:
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
            return None

        max_digits = 2
        for _, lines in groups:
            for line in lines:
                m = re.match(r"^\s*(\d+):(.*)$", line)
                if m:
                    max_digits = max(max_digits, len(m.group(1)))

        table = Table.grid(padding=(0, 1))
        table.add_column(
            style="muted", justify="right", no_wrap=True, width=max_digits + 1
        )
        table.add_column(style="code")

        for file_path, lines in groups:
            table.add_row("", Text(file_path, style="highlight"))
            for line in lines:
                m = re.match(r"^\s*(\d+):(.*)$", line)
                if m:
                    table.add_row(m.group(1), Text(m.group(2).lstrip(), style="code"))
                else:
                    table.add_row("", Text(line, style="code"))
            table.add_row("", Text(""))
        return table

    def _render_subagent_payload(self, output: str) -> list[Any] | None:
        try:
            payload = json.loads(output)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None

        blocks: list[Any] = []
        summary = str(payload.get("summary", "")).strip()
        termination = str(payload.get("termination", "")).strip()
        tools_used = payload.get("tools_used", [])
        findings = payload.get("findings", [])
        actions = payload.get("actions", [])

        if summary:
            summary_text = summary
            if len(summary_text) > 220:
                summary_text = summary_text[:217].rstrip() + "..."
            blocks.append(Text(summary_text, style="muted"))
            blocks.append(Text())

        meta_parts = []
        if termination:
            meta_parts.append(f"termination={termination}")
        if isinstance(tools_used, list):
            meta_parts.append(f"tools={len(tools_used)}")
        if meta_parts:
            blocks.append(self._summary_line(*meta_parts))
            blocks.append(Text())

        if isinstance(findings, list) and findings:
            blocks.append(Text("Findings", style="bold cyan"))
            for item in findings[:4]:
                text = str(item)
                if len(text) > 140:
                    text = text[:137].rstrip() + "..."
                blocks.append(Text(f"- {text}", style="code"))
            if len(findings) > 4:
                blocks.append(
                    Text(f"... {len(findings) - 4} more findings", style="muted")
                )
            blocks.append(Text())

        if isinstance(actions, list) and actions:
            blocks.append(Text("Actions", style="bold yellow"))
            for item in actions[:4]:
                text = str(item)
                if len(text) > 140:
                    text = text[:137].rstrip() + "..."
                blocks.append(Text(f"- {text}", style="code"))
            if len(actions) > 4:
                blocks.append(
                    Text(f"... {len(actions) - 4} more actions", style="muted")
                )

        if not blocks:
            return None
        return blocks

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
        end_r, end_g, end_b = 30, 80, 48

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
        version: str = "0.0.31",
    ) -> None:
        # Hand-crafted large block art — no pyfiglet needed
        logo_lines = [
            "  ██╗ ██████╗ ███████╗",
            "  ╚═╝ ╚═██╔═╝ ██╔═══╝",
            "  ██╗   ██║   ████╗  ",
            "  ██║   ██║   ██╔═╝  ",
            "  ██║   ██║   ███████╗",
            "  ╚═╝   ╚═╝   ╚══════╝",
        ]
        logo = self._gradient_text("\n".join(logo_lines))

        # tagline = Text("  your intelligent terminal engine", style="dim italic")

        # Info section with icons
        info_table = Table.grid(padding=(0, 2))
        info_table.add_column(style="muted", justify="right", min_width=10)
        info_table.add_column(style="code")

        cwd_display = str(cwd).replace(str(Path.home()), "~")
        info_table.add_row(
            Text("Model", style="muted"),
            Text(model or "not set", style="cyan bold"),
        )
        info_table.add_row(
            Text("Workspace", style="muted"),
            Text(cwd_display, style="info"),
        )

        footer = Text(
            f"  v{version} · type /help for commands",
            style="code",
        )

        content = Group(
            Text(),
            logo,
            # tagline,
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
                box=box.HEAVY,
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
        if name == "memory":
            return

        border_style = f"tool.{tool_kind}" if tool_kind else "tool"
        md = metadata if isinstance(metadata, dict) else {}
        policy_redirect = bool(md.get("policy_blocked") and md.get("redirect_to"))
        recoverable = bool(md.get("recoverable")) or policy_redirect
        status_icon = "✅" if success else ("↪" if policy_redirect else ("↺" if recoverable else "❌"))
        status_style = "success" if success else ("warning" if recoverable else "error")
        title_text = activity_title(
            name,
            stage="complete",
            success=success,
            metadata=md,
        )

        title = Text.assemble(
            (f"{status_icon} ", status_style),
            (title_text, border_style),
        )
        if self.config.debug:
            title.append(f"  {name} #{call_id[:8]}", "muted")

        args = self._tool_args_by_call_id.get(call_id, {})
        narrative = describe_tool_activity(
            name,
            args,
            md,
            stage="complete",
            success=success,
        )

        primary_path = None
        local_truncated = False
        blocks = []

        if isinstance(metadata, dict) and isinstance(metadata.get("path"), str):
            primary_path = metadata.get("path")

        if name == "read_file" and success:
            extracted = self._extract_read_file_code(output) if primary_path else None
            if primary_path and extracted is not None:
                start_line, code = extracted
                code_display, was_truncated = self._truncate_for_tool(
                    name,
                    code,
                    preserve_lines=True,
                )
                local_truncated = local_truncated or was_truncated
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
                blocks.append(
                    Syntax(
                        code_display,
                        language,
                        theme="monokai",
                        line_numbers=True,
                        start_line=start_line,
                        word_wrap=False,
                    )
                )
            else:
                blocks.append(Text(narrative, style="muted"))
                output_display, was_truncated = self._truncate_for_tool(
                    name,
                    output,
                    preserve_lines=True,
                )
                local_truncated = local_truncated or was_truncated
                blocks.append(
                    Syntax(
                        output_display,
                        "text",
                        theme="monokai",
                        word_wrap=False,
                    )
                )

        elif name in {"write_file", "edit", "write_toml", "write_yaml", "write_env"} and success and diff:
            blocks.append(Text(narrative, style="muted"))
            output_line = output.strip() if output.strip() else "Completed"
            blocks.append(Text(output_line, style="muted"))
            if isinstance(metadata, dict):
                parts = []
                if isinstance(metadata.get("path"), str):
                    parts.append(str(metadata["path"]))
                if isinstance(metadata.get("replace_count"), int):
                    parts.append(f"{metadata['replace_count']} replacements")
                if isinstance(metadata.get("lines_added"), int):
                    parts.append(f"{metadata['lines_added']} lines")
                if isinstance(metadata.get("line_diff"), int):
                    sign = "+" if metadata["line_diff"] > 0 else ""
                    parts.append(f"{sign}{metadata['line_diff']} line delta")
                if name == "write_env":
                    key = metadata.get("key")
                    if isinstance(key, str) and key:
                        parts.append(key)
                elif name in {"write_toml", "write_yaml"}:
                    key_path = metadata.get("key_path")
                    if isinstance(key_path, str) and key_path:
                        parts.append(key_path)
                if isinstance(metadata.get("operation"), str) and metadata.get("operation"):
                    parts.append(str(metadata["operation"]))
            if parts:
                blocks.append(self._summary_line(*parts))
            diff_text = diff
            diff_display, was_truncated = self._truncate_for_tool(
                name,
                diff_text,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated
            blocks.append(Syntax(diff_display, "diff", theme="monokai", word_wrap=True))

        elif name in {"read_json", "read_toml", "read_yaml", "read_env"} and success:
            blocks.append(Text(narrative, style="muted"))
            target_parts = []
            if primary_path:
                target_parts.append(str(display_path_relative_to_cwd(primary_path, self.cwd)))
            if name == "read_json":
                scoped = md.get("json_path")
            elif name in {"read_toml", "read_yaml"}:
                scoped = md.get("key_path")
            else:
                scoped = md.get("key")
            if isinstance(scoped, str) and scoped.strip():
                target_parts.append(scoped.strip())
            if target_parts:
                blocks.append(self._summary_line(*target_parts))

            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated
            language = "json"
            if name == "read_toml":
                language = "toml"
            elif name == "read_yaml":
                language = "yaml"
            blocks.append(Syntax(output_display, language, theme="monokai", word_wrap=True))

        elif name == "http_request" and success:
            blocks.append(Text(narrative, style="muted"))
            summary = []
            method = md.get("method") or args.get("method")
            url = md.get("url") or args.get("url")
            if isinstance(method, str):
                summary.append(method.upper())
            if isinstance(md.get("status_code"), int):
                summary.append(str(md["status_code"]))
            if isinstance(md.get("content_type"), str) and md.get("content_type"):
                summary.append(str(md["content_type"]))
            if isinstance(url, str):
                summary.append(url)
            if summary:
                blocks.append(self._summary_line(*summary))

            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated
            blocks.append(Syntax(output_display, "text", theme="monokai", word_wrap=True))

        elif name == "list_archive" and success:
            blocks.append(Text(narrative, style="muted"))
            summary = []
            if isinstance(primary_path, str):
                summary.append(str(display_path_relative_to_cwd(primary_path, self.cwd)))
            if isinstance(md.get("archive_format"), str):
                summary.append(str(md["archive_format"]))
            if isinstance(md.get("entry_count"), int):
                summary.append(f"{md['entry_count']} entries")
            if summary:
                blocks.append(self._summary_line(*summary))

            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated
            blocks.append(Syntax(output_display, "text", theme="monokai", word_wrap=True))

        elif name == "read_pdf" and success:
            blocks.append(Text(narrative, style="muted"))
            summary = []
            if isinstance(primary_path, str):
                summary.append(str(display_path_relative_to_cwd(primary_path, self.cwd)))
            if isinstance(md.get("page_count"), int):
                summary.append(f"{md['page_count']} pages")
            if isinstance(md.get("text_extraction_quality"), str) and md.get("text_extraction_quality"):
                summary.append(str(md["text_extraction_quality"]))
            if summary:
                blocks.append(self._summary_line(*summary))

            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated
            blocks.append(Syntax(output_display, "text", theme="monokai", word_wrap=True))

        elif name == "read_image" and success:
            blocks.append(Text(narrative, style="muted"))
            summary = []
            if isinstance(primary_path, str):
                summary.append(str(display_path_relative_to_cwd(primary_path, self.cwd)))
            if isinstance(md.get("width"), int) and isinstance(md.get("height"), int):
                summary.append(f"{md['width']}x{md['height']}")
            if isinstance(md.get("format"), str) and md.get("format"):
                summary.append(str(md["format"]))
            if md.get("ocr_requested"):
                summary.append("ocr")
            if summary:
                blocks.append(self._summary_line(*summary))

            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated
            blocks.append(Syntax(output_display, "json", theme="monokai", word_wrap=True))

        elif name == "shell" and success:
            blocks.append(Text(narrative, style="muted"))
            command = args.get("command")
            if isinstance(command, str) and command.strip():
                blocks.append(Text(f"$ {command.strip()}", style="muted"))

            summary_parts = []
            safety = metadata.get("safety_classification")
            if isinstance(safety, str):
                summary_parts.append(f"{safety} command")
            if exit_code is not None:
                summary_parts.append(f"exit code {exit_code}")
            if metadata.get("has_stderr"):
                summary_parts.append("stderr captured")
            if summary_parts:
                blocks.append(self._summary_line(*summary_parts))

            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated
            if output_display.strip():
                blocks.append(
                    Syntax(output_display, "text", theme="monokai", word_wrap=True)
                )
            else:
                blocks.append(Text("No output", style="muted"))

        elif name == "list_dir" and success:
            blocks.append(Text(narrative, style="muted"))
            entries = metadata.get("entries")
            path = metadata.get("path")
            summary = []

            if isinstance(path, str):
                summary.append(path)

            if isinstance(entries, int):
                summary.append(f"{entries} entries")

            if summary:
                blocks.append(self._summary_line(*summary))

            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated
            if output_display.strip():
                blocks.append(
                    Syntax(output_display, "text", theme="monokai", word_wrap=True)
                )
            else:
                blocks.append(Text("No output", style="muted"))

        elif name == "grep" and success:
            blocks.append(Text(narrative, style="muted"))
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
                blocks.append(self._summary_line(*summary))

            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated
            grep_block = self._render_grep_block(output_display)
            if grep_block is not None:
                blocks.append(grep_block)
            elif output_display.strip():
                blocks.append(
                    Syntax(output_display, "text", theme="monokai", word_wrap=True)
                )
            else:
                blocks.append(Text("No output", style="muted"))

        elif name == "glob" and success:
            blocks.append(Text(narrative, style="muted"))
            matches = metadata.get("matches")

            if isinstance(matches, int):
                if matches == 1:
                    blocks.append(self._summary_line("1 file found"))
                else:
                    blocks.append(self._summary_line(f"{matches} files found"))

            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated
            if output_display.strip():
                blocks.append(
                    Syntax(output_display, "text", theme="monokai", word_wrap=True)
                )
            else:
                blocks.append(Text("No output", style="muted"))

        elif name == "web_search" and success:
            blocks.append(Text(narrative, style="muted"))
            results_count = metadata.get("results")
            query = args.get("query")
            provider = metadata.get("provider")
            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated

            summary = []

            if isinstance(query, str):
                summary.append(f'"{query}"')

            if isinstance(results_count, int):
                if results_count == 1:
                    summary.append("1 result")
                else:
                    summary.append(f"{results_count} results")
            if isinstance(provider, str):
                summary.append(provider)

            if summary:
                blocks.append(Text(" • ".join(summary), style="muted"))
                blocks.append(Text())

            # Parse results into structured data
            results = []
            current = {}
            for line in output_display.splitlines():
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

            max_results_rows = 8
            for i, r in enumerate(results[:max_results_rows], start=1):
                title_text = Text()
                title_text.append(r.get("title", ""), style="highlight")
                result_table.add_row(f"{i}.", title_text)

                if r.get("url"):
                    result_table.add_row("", Text(r["url"], style="dim"))

                if r.get("snippet"):
                    result_table.add_row("", Text(r["snippet"], style="muted"))

                # spacer between results
                if i < min(len(results), max_results_rows):
                    result_table.add_row("", Text())

            if len(results) > max_results_rows:
                result_table.add_row(
                    "",
                    Text(
                        f"... {len(results) - max_results_rows} more results",
                        style="muted",
                    ),
                )

            blocks.append(result_table)

        elif name == "web_fetch" and success:
            blocks.append(Text(narrative, style="muted"))
            status_code = metadata.get("status_code")
            content_type = metadata.get("content_type")
            content_length = metadata.get("content_length")
            url = metadata.get("url") or args.get("url")

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

            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated

            if isinstance(content_type, str) and "json" in content_type:
                blocks.append(
                    Syntax(output_display, "json", theme="monokai", word_wrap=True)
                )
            else:
                blocks.append(Markdown(output_display))

        elif name == "todos" and success:
            blocks.append(Text(narrative, style="muted"))
            completed = metadata.get("completed", 0) if metadata else 0
            total = metadata.get("total", 0) if metadata else 0
            action = metadata.get("action", "") if metadata else ""
            scope = metadata.get("scope", "execution") if metadata else "execution"
            message = metadata.get("message", "") if metadata else ""
            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated

            # Progress header
            if total > 0:
                bar_width = 20
                filled = int((completed / total) * bar_width) if total else 0
                bar = "█" * filled + "░" * (bar_width - filled)
                header = Text()
                header.append(
                    f"{scope.capitalize()} tasks: {completed}/{total} completed ",
                    style="muted",
                )
                header.append(bar, style="green" if completed == total else "yellow")
                blocks.append(header)
                blocks.append(Text())
            elif isinstance(scope, str):
                blocks.append(Text(f"Scope: {scope}", style="muted"))
                blocks.append(Text())

            # Render each line with styled checkboxes
            for line in output_display.splitlines():
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
            elif message:
                blocks.append(Text(f"  {message}", style="muted"))

        elif name == "memory" and success:
            blocks.append(Text(narrative, style="muted"))
            action = args.get("action", "")
            key = args.get("key", "")
            output_display, was_truncated = self._truncate_for_tool(
                name,
                output,
                preserve_lines=True,
            )
            local_truncated = local_truncated or was_truncated

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
                    val = (
                        output_display.split(f"{key}: ", 1)[-1]
                        if key
                        else output_display
                    )
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

                    for line in output_display.splitlines():
                        stripped = line.strip()
                        if ":" in stripped and not stripped.startswith("Stored"):
                            k, v = stripped.split(":", 1)
                            mem_table.add_row(k.strip(), v.strip())

                    blocks.append(mem_table)

            elif action == "clear":
                blocks.append(Text(f"  ✓ {output}", style="muted"))

        elif name.startswith("subagent_"):
            rendered = self._render_subagent_payload(output)
            if rendered is not None:
                blocks.append(Text(narrative, style="muted"))
                blocks.extend(rendered)
            elif output.strip():
                blocks.append(Text(narrative, style="muted"))
                output_display, was_truncated = self._truncate_for_tool(
                    name,
                    output,
                    preserve_lines=True,
                )
                local_truncated = local_truncated or was_truncated
                blocks.append(
                    Syntax(output_display, "json", theme="monokai", word_wrap=True)
                )
            else:
                blocks.append(Text("No output", style="muted"))

        else:
            blocks.append(Text(narrative, style="muted"))
            if policy_redirect:
                redirect_to = str(md.get("redirect_to") or "").strip()
                if redirect_to:
                    blocks.append(Text(f"Continuing with `{redirect_to}`.", style="muted"))
            elif error and not success:
                blocks.append(Text(error, style="error"))

            output_display = ""
            if not policy_redirect:
                output_display, was_truncated = self._truncate_for_tool(
                    name,
                    output,
                    preserve_lines=True,
                )
                local_truncated = local_truncated or was_truncated

            if output_display.strip():
                if success:
                    blocks.append(Markdown(output_display))
                else:
                    blocks.append(
                        Syntax(output_display, "text", theme="monokai", word_wrap=True)
                    )
            elif not policy_redirect:
                blocks.append(Text("No output", style="muted"))

        if local_truncated:
            blocks.append(Text("... [truncated]", style="warning"))
        elif truncated:
            blocks.append(Text("... [truncated]", style="warning"))

        panel = Panel(
            Group(*blocks),
            title=title,
            title_align="left",
            subtitle=Text("done" if success else "failed", style=status_style),
            subtitle_align="right",
            border_style=border_style,
            box=box.HEAVY,
            padding=(0, 1),
        )

        self.console.print()
        self.console.print(panel)

    def handle_confirmation(self, confirmation: ToolConfirmation) -> bool:
        if self._spinner_running:
            self.stop_spinner()
        output = [
            Text(confirmation.tool_name, style="tool"),
            Text(confirmation.description, style="code"),
        ]

        if confirmation.command:
            output.append(Text(f"$ {confirmation.command}", style="warning"))

        if confirmation.diff:
            diff_text = confirmation.diff.to_diff()
            output.append(
                Syntax(
                    diff_text,
                    "diff",
                    theme="monokai",
                    word_wrap=True,
                )
            )

        self.console.print()
        self.console.print(
            Panel(
                Group(*output),
                title=Text("Approval required", style="warning"),
                title_align="left",
                border_style="warning",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

        response = Prompt.ask(
            "\nApprove?", choices=["y", "n", "yes", "no"], default="n"
        )

        return response.lower() in {"y", "yes"}

    def recoverable_sandbox_note(self, tool_name: str, error: str) -> None:
        path_text = ""
        match = re.search(
            r"Access denied: (.+?) is outside the project sandbox", error or ""
        )
        if match:
            path_text = match.group(1)

        body = [
            Text(
                "Blocked exploratory read outside the workspace sandbox.",
                style="muted",
            ),
            Text(),
        ]
        if path_text:
            body.append(Text(path_text, style="warning"))
            body.append(Text())
        body.append(
            Text(
                "Continuing with allowed files inside the current workspace.",
                style="code",
            )
        )

        self.console.print()
        self.console.print(
            Panel(
                Group(*body),
                title=Text(f"{tool_name} blocked, recovered", style="warning"),
                title_align="left",
                border_style="warning",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    def prompt_plan_question(
        self,
        *,
        question: str,
        options: list[str],
        question_number: int | None = None,
        recommended_index: int | None = None,
        allow_free_text: bool = True,
    ) -> dict[str, Any]:
        if self._spinner_running:
            self.stop_spinner()

        lines = []
        for idx, option in enumerate(options, start=1):
            marker = " (recommended)" if recommended_index == idx - 1 else ""
            lines.append(f"{idx}. {option}{marker}")
        if allow_free_text:
            lines.append("0. Enter custom answer")

        self.console.print()
        self.console.print(
            Panel(
                Group(
                    Text(question, style="bold white"),
                    Text(),
                    Text("\n".join(lines), style="code"),
                ),
                title=Text(
                    (
                        f"Asking question {question_number}"
                        if isinstance(question_number, int) and question_number > 0
                        else "Planning question"
                    ),
                    style="bold cyan",
                ),
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

        valid_choices = [str(i) for i in range(1, len(options) + 1)]
        if allow_free_text:
            valid_choices = ["0", *valid_choices]
        default_choice = (
            str(recommended_index + 1)
            if recommended_index is not None and 0 <= recommended_index < len(options)
            else (valid_choices[0] if valid_choices else "1")
        )
        choice_label = "/".join(valid_choices)
        while True:
            raw = self.console.input(
                f"Select option [{choice_label}] ({default_choice}): "
            )
            picked = (raw or "").strip()
            if not picked:
                picked = default_choice
            if picked in valid_choices:
                break
            if allow_free_text and picked and not picked.isdigit():
                # If the user pasted free text at the option prompt, accept it directly.
                return {
                    "selected_option": "",
                    "free_text": picked,
                    "selected_index": None,
                }
            self.console.print(
                "[error]Please select one of the available options[/error]"
            )

        if picked == "0" and allow_free_text:
            text = self.console.input("Your answer: ").strip()
            return {"selected_option": "", "free_text": text, "selected_index": None}

        selected_index = int(picked) - 1
        selected_option = options[selected_index]
        return {
            "selected_option": selected_option,
            "free_text": "",
            "selected_index": selected_index,
        }

    def prompt_plan_implementation(self, asked_questions: int = 0) -> bool:
        self.console.print()
        self.console.print(
            Panel(
                Text(
                    (
                        "Implement this plan now?"
                        if asked_questions <= 0
                        else f"Implement this plan now? (asked {asked_questions} questions)"
                    ),
                    style="bold white",
                ),
                title=Text("Plan Ready", style="bold cyan"),
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        response = Prompt.ask(
            "Implement plan",
            choices=["y", "n", "yes", "no"],
            default="n",
        )
        return response.lower() in {"y", "yes"}

    def show_help(self) -> None:
        help_text = """
## Commands

- `/help` - Show this help
- `/exit` or `/quit` - Exit the agent
- `/clear` - Clear conversation history
- `/config` - Show current configuration
- `/model <name>` - Change the model
- `/approval <mode>` - Change approval mode
- `/stats` - Show session statistics
- `/tools` - List available tools
- `/mcp` - Show MCP server status
- `/sessions` - List saved sessions
- `/sessions <session_id>` - Resume a saved session directly

## Tips

- Just type your message to chat with the agent
- The agent can read, write, and execute code
- Some operations require approval (can be configured)
"""
        self.console.print(Markdown(help_text))
