from __future__ import annotations

import io

from rich.console import Console

from ite.commands import CommandContext


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


def build_command_context(config, agent, tui, output_stream) -> CommandContext:
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
