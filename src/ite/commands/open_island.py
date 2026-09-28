"""Open Island notification controls."""

from __future__ import annotations

import sys

from ite.commands import Command, CommandContext, CommandRegistry
from ite.config.loader import save_open_island_settings


def _status_line(ctx: CommandContext) -> str:
    enabled = bool(ctx.config.integrations.open_island.enabled)
    if not enabled:
        return "Open Island notifications are off. Use `/oi on` to enable them."
    if sys.platform != "darwin":
        return "Open Island notifications are on, but they are available on macOS only."
    bridge = getattr(ctx.agent, "open_island_bridge", None)
    if bridge is not None and bridge.enabled:
        return "Open Island notifications are on and connected to this session."
    return "Open Island notifications are on and will connect when a session starts."


async def handle_open_island(ctx: CommandContext, args: list[str]) -> bool:
    """Show or change the local Open Island notification preference."""
    action = (args[0] if args else "status").strip().lower()
    if action in {"status", "info"}:
        ctx.console.print(f"[bold]{_status_line(ctx)}[/bold]")
        return True

    if action not in {"on", "off"}:
        ctx.console.print("[red]Usage:[/red] /oi | /oi on | /oi off")
        return True

    enabled = action == "on"
    save_open_island_settings(enabled=enabled)
    ctx.config.integrations.open_island.enabled = enabled

    agent = ctx.agent
    if agent is not None:
        await agent.set_open_island_enabled(enabled)

    if enabled:
        ctx.console.print("[green]Open Island notifications are enabled.[/green]")
    else:
        ctx.console.print("[yellow]Open Island notifications are disabled.[/yellow]")
    return True


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/oi",
            description="Show or toggle Open Island notifications",
            handler=handle_open_island,
        )
    )
