"""Cloud auth/config commands."""

from __future__ import annotations

from ite.commands import Command, CommandContext, CommandRegistry
from ite.cloud import (
    CloudAuthError,
    CloudConnectionError,
    CloudSessionState,
    clear_cloud_auth,
    ensure_cloud_auth,
    get_activity,
    get_cloud_auth_status,
    get_usage_summary,
)
from ite.config.loader import save_cloud_settings
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.console import Group
from rich import box


def _cloud_status_panel(ctx: CommandContext) -> Panel:
    auth = get_cloud_auth_status(ctx.config)
    table = Table.grid(padding=(0, 2))
    table.add_column(style="muted", justify="right", min_width=12)
    table.add_column(style="bold white")
    table.add_row(
        Text("Enabled", style="muted"),
        Text("true" if ctx.config.cloud_auth_enabled else "false", style="info"),
    )
    table.add_row(Text("Session", style="muted"), Text(auth.state, style="info"))
    if auth.message:
        table.add_row(Text("Detail", style="muted"), Text(auth.message, style="dim"))
    return Panel(
        table,
        title=Text.assemble(("☁ ", ""), ("iTE Cloud", "bold bright_white")),
        title_align="left",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )


async def cmd_status(ctx: CommandContext, args: list[str]) -> None:
    ctx.console.print()
    ctx.console.print(_cloud_status_panel(ctx))


async def cmd_login(ctx: CommandContext, args: list[str]) -> None:
    if not ctx.config.cloud_auth_enabled:
        ctx.config.cloud_auth_enabled = True
        save_cloud_settings(enabled=True)
    auth = get_cloud_auth_status(ctx.config)
    if auth.state == CloudSessionState.VALID:
        ctx.console.print("[bold green]Already signed in to iTE Cloud.[/bold green]")
        return
    if auth.state == CloudSessionState.NETWORK_ERROR:
        ctx.console.print(f"[error]{auth.message}[/error]")
        return
    if auth.state == CloudSessionState.INVALID:
        stored_session = getattr(auth, "session", None)
        if stored_session is not None:
            ctx.console.print(f"[error]{auth.message}[/error]")
            return
        clear_cloud_auth(revoke_remote=False)
    if auth.state == CloudSessionState.SIGNED_OUT and getattr(auth, "session", None) is not None:
        ctx.console.print(f"[error]{auth.message}[/error]")
        return
    try:
        ensure_cloud_auth(ctx.console, ctx.config)
    except CloudConnectionError as exc:
        ctx.console.print(f"[error]Cloud API unreachable:[/error] {exc}")
        return
    except CloudAuthError as exc:
        ctx.console.print(f"[error]Cloud login failed:[/error] {exc}")
        return
    ctx.console.print("[bold green]iTE Cloud session is active.[/bold green]")


async def cmd_usage(ctx: CommandContext, args: list[str]) -> None:
    """Show usage summary from iTE Cloud."""
    summary = get_usage_summary(ctx.config)
    if not summary:
        ctx.console.print("[error]Usage is not available right now.[/error]")
        return

    quotas = summary.get("quotas") or {}
    quota_rows = (
        ("5-Hour", "fiveHour"),
        ("Weekly", "sevenDay"),
        ("Monthly", "thirtyDay"),
    )

    table = Table.grid(padding=(0, 2))
    table.add_column(style="muted", justify="right", min_width=12)
    table.add_column(style="bold white")
    for label, key in quota_rows:
        quota = quotas.get(key) or {}
        used = int(quota.get("usedUsdCents") or 0)
        cap = max(1, int(quota.get("capUsdCents") or 1))
        remaining = max(0, min(100, int(((cap - used) / cap) * 100)))
        table.add_row(
            Text(f"{label} Cap", style="muted"),
            Text(f"{cap / 100:.2f} USD", style="bold cyan"),
        )
        table.add_row(
            Text("Used", style="muted"),
            Text(f"{used / 100:.2f} USD", style="bold yellow"),
        )
        table.add_row(
            Text("Remaining", style="muted"),
            Text(f"{remaining}%", style="bold green"),
        )

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
            name="/status",
            description="Show iTE account connection status",
            handler=cmd_status,
        )
    )
    registry.register(
        Command(
            name="/login",
            description="Sign in to iTE Cloud",
            handler=cmd_login,
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
