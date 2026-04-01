"""Cloud auth/config commands."""

from __future__ import annotations

from ite.commands import Command, CommandContext, CommandRegistry
from ite.cloud import CloudAuthError, clear_cloud_auth, ensure_cloud_auth, get_usage_summary, get_activity
from ite.config.loader import save_cloud_settings
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.console import Group
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


async def cmd_usage(ctx: CommandContext, args: list[str]) -> None:
    """Show usage summary from iTE Cloud."""
    summary = get_usage_summary(ctx.config)
    if not summary:
        ctx.console.print("[error]Usage is not available right now.[/error]")
        return

    quotas = summary.get("quotas") or {}
    five_hour = quotas.get("fiveHour") or {}
    used = int(five_hour.get("usedUsdCents") or 0)
    cap = max(1, int(five_hour.get("capUsdCents") or 1))
    remaining = max(0, min(100, round(((cap - used) / cap) * 100)))

    table = Table.grid(padding=(0, 2))
    table.add_column(style="muted", justify="right", min_width=12)
    table.add_column(style="bold white")
    table.add_row(Text("5-Hour Cap", style="muted"), Text(f"{cap / 100:.2f} USD", style="bold cyan"))
    table.add_row(Text("Used", style="muted"), Text(f"{used / 100:.2f} USD", style="bold yellow"))
    table.add_row(Text("Remaining", style="muted"), Text(f"{remaining}%", style="bold green"))

    ctx.console.print()
    ctx.console.print(
        Panel(
            table,
            title=Text.assemble(("📊 ", ""), ("Usage Summary", "bold bright_white")),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_activity(ctx: CommandContext, args: list[str]) -> None:
    """Show recent activity from iTE Cloud."""
    payload = get_activity(ctx.config)
    if not payload:
        ctx.console.print("[error]Usage analytics are not available right now.[/error]")
        return

    data = payload.get("data") or {}
    recent = data.get("recent") or []

    lines: list[Text] = []
    for item in recent[:10]:
        timestamp = str(item.get("timestamp", ""))[:16].replace("T", " ")
        model = item.get("model", "unknown")
        tokens = item.get("tokens", 0)
        lines.append(
            Text.assemble(
                (timestamp, "code"),
                ("  ", ""),
                (model, "bold cyan"),
                (f"  {tokens} tokens", "dim"),
            )
        )

    if not lines:
        lines.append(Text("No recent activity.", style="dim"))

    ctx.console.print()
    ctx.console.print(
        Panel(
            Group(*lines),
            title=Text.assemble(("📈 ", ""), ("Recent Activity", "bold bright_white")),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/cloud",
            description="Manage iTE Cloud auth and API settings",
            handler=cmd_cloud,
        )
    )
    registry.register(
        Command(
            name="/usage",
            description="Show usage summary from iTE Cloud",
            handler=cmd_usage,
        )
    )
    registry.register(
        Command(
            name="/activity",
            description="Show recent activity from iTE Cloud",
            handler=cmd_activity,
        )
    )
