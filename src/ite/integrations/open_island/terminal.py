from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# TERM_PROGRAM values mapped to the terminal names Open Island's jump-back
# resolves. Upstream probes via AppleScript; we read the environment instead,
# which is cheap and never prompts for automation permission.
_TERM_PROGRAM_NAMES = {
    "Apple_Terminal": "Terminal",
    "iTerm.app": "iTerm",
    "iTerm2": "iTerm",
    "WarpTerminal": "Warp",
    "ghostty": "Ghostty",
    "vscode": "VS Code",
    "Hyper": "Hyper",
    "kitty": "kitty",
    "Alacritty": "Alacritty",
    "WezTerm": "WezTerm",
    "Tabby": "Tabby",
    "rio": "Rio",
}

# Session-id variables exposed by specific terminals.
_SESSION_ID_ENV_VARS = (
    "ITERM_SESSION_ID",
    "TERM_SESSION_ID",
    "WEZTERM_PANE",
    "KITTY_WINDOW_ID",
)


@dataclass(frozen=True)
class TerminalContext:
    """Best-effort terminal identification used for Open Island jump-back."""

    app: str | None = None
    tty: str | None = None
    session_id: str | None = None
    title: str | None = None

    def as_payload_fields(self) -> dict[str, str]:
        """Return only the non-empty fields, keyed for the hook payload.

        Omitted keys deliberately fall through to upstream's own fallbacks;
        sending an explicit ``"Unknown"`` would defeat them.
        """
        fields: dict[str, str] = {}
        if self.app:
            fields["terminal_app"] = self.app
        if self.tty:
            fields["terminal_tty"] = self.tty
        if self.session_id:
            fields["terminal_session_id"] = self.session_id
        if self.title:
            fields["terminal_title"] = self.title
        return fields


def detect_terminal_app(env: dict[str, str] | None = None) -> str | None:
    """Resolve a terminal application name from the environment."""
    source = os.environ if env is None else env

    program = source.get("TERM_PROGRAM", "").strip()
    if program:
        mapped = _TERM_PROGRAM_NAMES.get(program)
        if mapped:
            return mapped
        return program

    # Fall back to the TERM family, which at least distinguishes the common
    # cases without claiming precision we do not have.
    term = source.get("TERM", "").strip()
    if "ghostty" in term:
        return "Ghostty"
    return None


def detect_terminal_session_id(env: dict[str, str] | None = None) -> str | None:
    """Resolve a terminal session identifier, if the terminal exposes one."""
    source = os.environ if env is None else env
    for name in _SESSION_ID_ENV_VARS:
        value = source.get(name, "").strip()
        if value:
            return value
    return None


def _tty_from_fd(fd: int) -> str | None:
    try:
        return os.ttyname(fd)
    except (OSError, ValueError):
        return None


def detect_tty() -> str | None:
    """Resolve the controlling TTY for the current process.

    Tries the standard descriptors first, then falls back to ``ps`` for the
    parent process, which covers hosts where stdin is redirected.
    """
    for fd in (0, 1, 2):
        tty = _tty_from_fd(fd)
        if tty:
            return tty

    try:
        result = subprocess.run(
            ["ps", "-o", "tty=", "-p", str(os.getppid())],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    name = result.stdout.strip()
    if not name or name in {"??", "-"}:
        return None
    return name if name.startswith("/") else f"/dev/{name}"


def detect_terminal(
    env: dict[str, str] | None = None,
    *,
    include_tty: bool = True,
) -> TerminalContext:
    """Detect terminal context for jump-back. Never raises.

    Detection is best-effort: any failure yields ``None`` for that field, and
    an entirely failed detection yields an empty context rather than an error.
    """
    try:
        app = detect_terminal_app(env)
    except Exception:  # noqa: BLE001 - detection is best-effort by design
        logger.debug("Open Island terminal app detection failed")
        app = None

    try:
        session_id = detect_terminal_session_id(env)
    except Exception:  # noqa: BLE001 - detection is best-effort by design
        logger.debug("Open Island terminal session id detection failed")
        session_id = None

    tty = None
    if include_tty and sys.platform == "darwin":
        try:
            tty = detect_tty()
        except Exception:  # noqa: BLE001 - detection is best-effort by design
            logger.debug("Open Island tty detection failed")
            tty = None

    return TerminalContext(app=app, tty=tty, session_id=session_id)


def workspace_name(cwd: Path | str) -> str:
    """Return the workspace label Open Island renders as the session headline."""
    path = Path(cwd)
    name = path.name
    return name or str(path)
