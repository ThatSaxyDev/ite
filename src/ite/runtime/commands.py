"""Headless slash-command dispatch for the runtime host.

Item 2 of the Phase 6 follow-up. Before this module, a prompt beginning with ``/``
sent over the relay reached the model as literal text, because
:class:`~ite.runtime.host.RuntimeHost` called ``run_turn`` directly and never routed
through the command registry the way the TUI's ``ReupApp._dispatch_payload`` did
(``ite/src/ite/ui/reup/_composer.py:1804``).

This module restores that behaviour headlessly: the same guard (a dropped file path is
an attachment, never a command), the same registry, the same ``CommandContext`` — only
the ``tui`` surface is swapped for a no-Textual adapter.

``StreamingCommandOutput`` and ``build_command_context`` live here now so the TUI and
the daemon share one implementation; ``ite/ui/reup/adapters/registry.py`` re-exports
them.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from ite.attachment_refs import parse_dropped_file_paths
from ite.commands import CommandContext, CommandRegistry, build_registry


class StreamingCommandOutput(io.StringIO):
    def __init__(self, on_line=None) -> None:
        super().__init__()
        self._on_line = on_line
        self._pending = ""
        self.had_live_output = False

    def write(self, text: str) -> int:
        written = super().write(text)
        if not text or self._on_line is None:
            return written
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            stripped = line.strip()
            if stripped:
                self.had_live_output = True
                self._on_line(stripped)
        return written

    def flush_pending(self) -> None:
        if self._on_line is None:
            return
        stripped = self._pending.strip()
        if stripped:
            self.had_live_output = True
            self._on_line(stripped)
        self._pending = ""


def build_command_context(
    config: Any,
    agent: Any,
    tui: Any,
    output_stream: Any,
) -> CommandContext:
    command_console = Console(
        file=output_stream,
        force_terminal=False,
        color_system=None,
        width=110,
    )
    return CommandContext(
        config=config,
        agent=agent,
        tui=tui,
        console=command_console,
    )


def is_slash_command_line(message: str) -> bool:
    """True if ``message`` should be treated as a command, not a prompt.

    Mirrors ``_composer.py:1795-1804``: a line that parses as dropped file path(s) is
    an attachment regardless of leading slash.
    """

    text = str(message or "")
    if not text.startswith("/"):
        return False
    drop = parse_dropped_file_paths(text)
    is_drop_payload = bool(drop.paths) and drop.prose_count == 0
    return not is_drop_payload


class HeadlessTUIAdapter:
    """Stand-in for ``ReupTUIAdapter`` with no Textual dependency.

    Provides every ``ctx.tui`` member that command handlers access directly. Methods
    that only exist to paint (spinners, cards) collect text instead, which the caller
    can forward to remote clients. Handlers that use ``getattr(ctx.tui, ...)`` for
    optional richer flows either find a working implementation here (``/new``,
    ``/close``) or fall through to their headless fallback.
    """

    def __init__(self, host: Any, session_id: str) -> None:
        self._host = host
        self._session_id = session_id
        self._spinner_handle: str | None = None
        self.output_lines: list[str] = []

    # -- workspace ---------------------------------------------------------

    @property
    def cwd(self) -> Path:
        return Path(self._host.config.cwd)

    @cwd.setter
    def cwd(self, value: Path) -> None:
        self._host.config.cwd = Path(value)

    # -- informational -----------------------------------------------------

    def print_welcome(
        self,
        model: str = "",
        cwd: str = "",
        commands: list[str] | None = None,
        version: str = "",
    ) -> None:
        from ite.update_check import current_runtime_version

        self.output_lines.append(
            f"iTE ready\nModel: {model or 'not set'}\n"
            f"Workspace: {Path(cwd).name or cwd}\n"
            f"Version: {version or current_runtime_version()}"
        )

    def post_success_card(self, title: str, message: str, details: str = "") -> None:
        text = f"{title}: {message}"
        if details:
            text += f"\n{details}"
        self.output_lines.append(text)

    def append_line(self, command: str, message: str) -> None:
        self.output_lines.append(message)

    # -- spinners (text-only) ---------------------------------------------

    def start_spinner(self, command: str, message: str = "Thinking") -> None:
        self._spinner_handle = command
        if message:
            self.output_lines.append(message)

    def change_spinner(self, message: str) -> None:
        if self._spinner_handle and message:
            self.output_lines.append(message)

    def step_spinner(self, message: str) -> None:
        if message:
            self.output_lines.append(message)

    def stream_content(self, chunk: str) -> None:
        return None

    def stop_spinner(self) -> None:
        self._spinner_handle = None

    # -- tool cards (already published as events by RuntimeSession) --------

    def tool_call_start(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        arguments: dict[str, Any],
    ) -> None:
        return None

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
        return None

    # -- lifecycle delegations --------------------------------------------

    async def _start_new_thread(self) -> None:
        await self._host.open_session(self.cwd)

    async def _close_current_thread(self) -> None:
        await self._host.close_session(self._session_id)

    def _apply_hooks_panel_state(self) -> None:
        return None


HEADLESS_INPUT_ERROR = (
    "This command needs interactive input, which the headless runtime cannot provide. "
    "Run it from the iTE terminal UI instead."
)


class _NonInteractiveStdin(io.TextIOBase):
    """stdin stand-in that fails fast instead of blocking a headless daemon.

    ``cmd_plan`` (``ite/commands/plan.py:92``) and ``cmd_subagent``
    (``ite/commands/subagent.py:54``) prompt on stdin. Under a daemon, a real read can
    block forever, wedging the runtime. Raising ``EOFError`` turns that into a clean,
    visible failure.
    """

    def read(self, *args: Any, **kwargs: Any) -> str:
        raise EOFError(HEADLESS_INPUT_ERROR)

    def readline(self, *args: Any, **kwargs: Any) -> str:
        raise EOFError(HEADLESS_INPUT_ERROR)

    def isatty(self) -> bool:
        return False


class RuntimeCommandRunner:
    """Parses and dispatches ``/`` commands against the shared registry."""

    def __init__(self, host: Any, registry: CommandRegistry | None = None) -> None:
        self._host = host
        self._registry = registry
        self._unavailable: set[str] = set()

    @property
    def registry(self) -> CommandRegistry:
        if self._registry is None:
            self._registry = build_registry()
        return self._registry

    def is_available(self, command: str) -> bool:
        return self.registry.get(command) is not None

    async def run(self, command_line: str, session_id: str) -> str:
        """Dispatch one command line. Returns the rendered text output."""

        parts = str(command_line or "").split()
        if not parts:
            return ""
        command = parts[0].lower()
        args = parts[1:]

        runtime_session = self._host.get_session(session_id)
        if runtime_session is None:
            return f"Unknown session: {session_id}"
        agent = runtime_session.agent

        adapter = HeadlessTUIAdapter(self._host, session_id)
        output = StreamingCommandOutput(
            on_line=lambda line: adapter.output_lines.append(line)
        )
        ctx = build_command_context(
            config=self._host.config,
            agent=agent,
            tui=adapter,
            output_stream=output,
        )

        if not self.is_available(command):
            rendered = (
                f"Unknown command: {command} — type /help for a list of commands"
            )
            self._host.append_command_feed(
                {"command": command, "status": "failed", "output": rendered}
            )
            return rendered

        feed_id = self._host.start_command_feed_entry(command_line)
        original_stdin = sys.stdin
        try:
            # Fail fast instead of blocking on a prompt the daemon cannot answer.
            sys.stdin = _NonInteractiveStdin()
            await self.registry.dispatch(command, args, ctx)
        except SystemExit:
            # `/exit` is meaningless for a long-running daemon: save state, stay up.
            self._host.finish_command_feed_entry(
                feed_id, status="completed", output="/exit ignored (daemon stays running)"
            )
            return "/exit ignored (daemon stays running)"
        except EOFError:
            self._host.finish_command_feed_entry(
                feed_id, status="failed", output=HEADLESS_INPUT_ERROR
            )
            await self._host.publish_state()
            return HEADLESS_INPUT_ERROR
        except Exception as exc:  # noqa: BLE001 - surfaced to the client, not raised
            self._host.finish_command_feed_entry(
                feed_id, status="failed", output=str(exc)
            )
            await self._host.publish_state()
            return f"Command failed: {exc}"
        finally:
            sys.stdin = original_stdin

        output.flush_pending()
        rendered_parts = [*adapter.output_lines, output.getvalue().strip()]
        rendered = "\n".join(part for part in rendered_parts if part)
        self._host.finish_command_feed_entry(
            feed_id, status="completed", output=rendered
        )
        await self._host.publish_state()
        return rendered
