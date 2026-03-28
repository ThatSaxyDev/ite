"""Cloud auth/config commands."""

from __future__ import annotations

from ite.commands import Command, CommandContext, CommandRegistry
from ite.cloud import CloudAuthError, clear_cloud_auth, ensure_cloud_auth
from ite.config.loader import save_cloud_settings
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box


def _cloud_status_panel(ctx: CommandContext) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="muted", justify="right", min_width=12)
    table.add_column(style="bold white")
    table.add_row(
        Text("Enabled", style="muted"),
        Text("true" if ctx.config.cloud_auth_enabled else "false", style="info"),
    )
    return Panel(
        table,
        title=Text.assemble(("☁ ", ""), ("iTE Cloud", "bold bright_white")),
        title_align="left",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )


async def cmd_cloud(ctx: CommandContext, args: list[str]) -> None:
    subcommand = args[0].lower() if args else "status"

    if subcommand in {"status", "show"}:
        ctx.console.print()
        ctx.console.print(_cloud_status_panel(ctx))
        return

    if subcommand == "login":
        if not ctx.config.cloud_auth_enabled:
            ctx.config.cloud_auth_enabled = True
            save_cloud_settings(enabled=True)
        clear_cloud_auth()
        try:
            ensure_cloud_auth(ctx.console, ctx.config)
        except CloudAuthError as exc:
            ctx.console.print(f"[error]Cloud login failed:[/error] {exc}")
            return
        ctx.console.print("[bold green]iTE Cloud session is active.[/bold green]")
        return

    if subcommand == "logout":
        cleared = clear_cloud_auth()
        if cleared:
            ctx.console.print("[bold green]Cloud session cleared.[/bold green]")
        else:
            ctx.console.print("[dim]No local cloud session was present.[/dim]")
        return

    ctx.console.print(
        "[error]Unknown /cloud command.[/error] "
        "[dim]Use /cloud status, /cloud login, or /cloud logout[/dim]"
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/cloud",
            description="Manage iTE Cloud auth and API settings",
            handler=cmd_cloud,
        )
    )
