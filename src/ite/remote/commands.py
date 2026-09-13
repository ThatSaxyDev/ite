"""Headless slash-command execution for the cloud runtime.

The interactive TUI intercepts a `/command` line and dispatches it through the
command registry. The headless runtime had no such path: every slash command the
mobile app offered was submitted to the model as ordinary chat text, so `/plan
on`, `/approval yolo` and the rest silently did nothing.

This module gives the runtime the same dispatch, with a minimal stand-in for the
TUI surface so existing command handlers run unchanged. Anything genuinely
interactive is recorded as a UI request rather than silently dropped, so the
remote can open the matching modal.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

from ite.commands import build_registry

logger = logging.getLogger(__name__)

#: Commands whose surface the headless runtime cannot provide at all. Reported
#: as unavailable rather than being sent to the model or requesting a UI the
#: remote cannot fulfil. The cloud runtime is single-session by design, so
#: thread management has no meaning here yet.
UI_ONLY_COMMANDS = {
    "/theme",
    "/new",
    "/close",
}

#: A UI request the remote knows how to satisfy with a modal.
UI_REQUESTS = {
    "new_thread",
    "close_thread",
    "model_picker",
    "theme_picker",
    "settings",
}


@dataclass
class HeadlessCommandResult:
    """Outcome of one ``/command`` execution."""

    command: str
    args: list[str]
    ok: bool
    output: str = ""
    #: Set when the command needs a remote modal, e.g. ``model_picker``.
    ui_request: str = ""
    #: Set when the command could not run; shown to the user.
    error: str = ""

    @property
    def has_output(self) -> bool:
        return bool(self.output.strip())


class HeadlessCommandTui:
    """The slice of the TUI that command handlers touch.

    Handlers reach for spinners, inline writers and a handful of picker
    entrypoints. Headless there is no screen, so the cosmetic calls are no-ops
    and the interactive ones record a request for the remote to satisfy.
    """

    def __init__(self, *, cwd: Path, output: io.StringIO) -> None:
        self.cwd = cwd
        self._output = output
        #: Last interactive surface a handler asked for.
        self.ui_request: str = ""

    # -- text output -----------------------------------------------------

    def append_line(self, text: str = "", *_: Any, **__: Any) -> None:
        value = str(text or "")
        if value:
            self._output.write(f"{value}\n")

    def post_success_card(self, *_: Any, **__: Any) -> None:
        return None

    # -- spinners; there is no screen to animate --------------------------

    def change_spinner(self, *_: Any, **__: Any) -> None:
        return None

    def start_spinner(self, *_: Any, **__: Any) -> None:
        return None

    def stop_spinner(self, *_: Any, **__: Any) -> None:
        return None

    # -- tool rendering; the agent already streams these ------------------

    def tool_call_start(self, *_: Any, **__: Any) -> None:
        return None

    def tool_call_complete(self, *_: Any, **__: Any) -> None:
        return None

    def print_welcome(self, *_: Any, **__: Any) -> None:
        return None

    def _apply_hooks_panel_state(self, *_: Any, **__: Any) -> None:
        return None

    # -- interactive surfaces the remote owns ----------------------------
    # Handlers look these up with getattr(..., None) and skip when absent.
    # Providing them lets a command declare what the user must be shown. Every
    # call site awaits them, so they must be coroutines — a plain `def` here
    # would raise "object NoneType can't be used in 'await' expression".
    #
    # Only surfaces the remote can genuinely satisfy are provided. Thread
    # management is intentionally absent: it falls through to the command's own
    # non-TUI path rather than asking the app for something it cannot do.

    async def _open_model_picker_from_meta(self, *_: Any, **__: Any) -> None:
        self._request("model_picker")

    async def _open_settings_screen(self, *_: Any, **__: Any) -> None:
        self._request("settings")

    def _request(self, name: str) -> None:
        if not self.ui_request:
            self.ui_request = name


@dataclass
class _Capture:
    stream: io.StringIO = field(default_factory=io.StringIO)


def is_slash_command(text: str) -> bool:
    """Whether a submitted message is a command rather than a prompt.

    Mirrors the TUI, which treats any leading ``/`` as a command attempt.
    """
    stripped = str(text or "").strip()
    if not stripped.startswith("/"):
        return False
    # A bare "/" is not a command.
    return len(stripped) > 1 and not stripped.startswith("//")


def parse_command(text: str) -> tuple[str, list[str]]:
    """Split a command line the way the TUI does."""
    parts = str(text or "").strip().split()
    if not parts:
        return "", []
    return parts[0].lower(), parts[1:]


async def run_headless_command(
    *,
    command_line: str,
    config: Any,
    agent: Any,
    cwd: Path,
) -> HeadlessCommandResult:
    """Dispatch one slash command and capture its console output.

    Never raises for an ordinary failure: the caller turns the result into a
    command-feed entry, so a broken command surfaces as a failed entry rather
    than a dead turn.
    """
    command, args = parse_command(command_line)

    if command in UI_ONLY_COMMANDS:
        return HeadlessCommandResult(
            command=command,
            args=args,
            ok=False,
            error=f"{command} isn't available from the mobile app yet.",
        )

    capture = _Capture()
    console = Console(
        file=capture.stream,
        force_terminal=False,
        color_system=None,
        width=110,
    )
    tui = HeadlessCommandTui(cwd=Path(cwd), output=capture.stream)

    registry = build_registry()
    if registry.get(command) is None:
        return HeadlessCommandResult(
            command=command,
            args=args,
            ok=False,
            error=f"Unknown command: {command}",
        )

    from ite.commands import CommandContext

    ctx = CommandContext(config=config, agent=agent, tui=tui, console=console)

    try:
        await registry.dispatch(command, args, ctx)
    except EOFError:
        # A handler asked for interactive input (e.g. `/plan on` with a saved
        # plan). That decision belongs to the user, so hand it back as a UI
        # request instead of failing the command.
        logger.info("Command %s needs interactive input", command)
        return HeadlessCommandResult(
            command=command,
            args=args,
            ok=True,
            output=capture.stream.getvalue().strip(),
            ui_request=tui.ui_request or "input_required",
        )
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        logger.exception("Command %s failed", command)
        return HeadlessCommandResult(
            command=command,
            args=args,
            ok=False,
            output=capture.stream.getvalue().strip(),
            error=str(exc),
        )

    return HeadlessCommandResult(
        command=command,
        args=args,
        ok=True,
        output=capture.stream.getvalue().strip(),
        ui_request=tui.ui_request,
    )


__all__ = [
    "HeadlessCommandResult",
    "HeadlessCommandTui",
    "is_slash_command",
    "parse_command",
    "run_headless_command",
    "UI_ONLY_COMMANDS",
]
