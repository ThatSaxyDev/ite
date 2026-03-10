from __future__ import annotations

from rich.console import Console

from ite.commands import CommandContext


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
