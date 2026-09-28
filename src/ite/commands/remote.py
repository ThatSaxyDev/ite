"""Remote commands: /remote for the Reup mobile bridge."""

from __future__ import annotations

from ite.commands import Command, CommandContext, CommandRegistry


async def cmd_remote(ctx: CommandContext, args: list[str]) -> None:
    handler = getattr(ctx.tui, "_run_remote_command_from_registry", None)
    if callable(handler):
        await handler(args)
        return
    ctx.console.print("[error]/remote is currently available in the Reup interface.[/error]")


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/remote",
            description="Start or inspect the mobile remote bridge",
            handler=cmd_remote,
        )
    )
