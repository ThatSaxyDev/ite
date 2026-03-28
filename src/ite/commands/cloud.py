"""Cloud auth/config commands."""

from __future__ import annotations

from ite.commands import Command, CommandContext, CommandRegistry
from ite.cloud import CloudAuthError, clear_cloud_auth, ensure_cloud_auth
from ite.config.loader import save_cloud_settings
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box


def _normalized_api_url(value: str) -> str:
    return value.strip().rstrip("/")


def _cloud_status_panel(ctx: CommandContext) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="muted", justify="right", min_width=12)
    table.add_column(style="bold white")
    table.add_row(
        Text("Enabled", style="muted"),
        Text("true" if ctx.config.cloud_auth_enabled else "false", style="info"),
    )
    table.add_row(
        Text("API URL", style="muted"),
        Text(ctx.config.cloud_api_url or "not set", style="info"),
    )
    table.add_row(
        Text("Client ID", style="muted"),
        Text(ctx.config.cloud_client_id or "ite-cli", style="info"),
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
    tail = args[1:]

    if subcommand in {"status", "show"}:
        ctx.console.print()
        ctx.console.print(_cloud_status_panel(ctx))
        return

    if subcommand in {"enable", "on"}:
        api_url = _normalized_api_url(tail[0]) if tail else _normalized_api_url(ctx.config.cloud_api_url or "")
        if not api_url:
            ctx.console.print("[error]Usage:[/error] [bold]/cloud enable <api-url>[/bold]")
            return
        save_cloud_settings(enabled=True, api_url=api_url, client_id=ctx.config.cloud_client_id)
        ctx.config.cloud_auth_enabled = True
        ctx.config.cloud_api_url = api_url
        ctx.console.print(f"[bold green]iTE Cloud enabled.[/bold green] [dim]{api_url}[/dim]")
        return

    if subcommand in {"disable", "off"}:
        save_cloud_settings(enabled=False)
        ctx.config.cloud_auth_enabled = False
        ctx.console.print("[bold green]iTE Cloud disabled.[/bold green]")
        return

    if subcommand == "api":
        if not tail:
            current = ctx.config.cloud_api_url or "not set"
            ctx.console.print(f"[dim]Current API URL:[/dim] {current}")
            return
        api_url = _normalized_api_url(tail[0])
        save_cloud_settings(api_url=api_url)
        ctx.config.cloud_api_url = api_url
        ctx.console.print(f"[bold green]Cloud API URL updated.[/bold green] [dim]{api_url}[/dim]")
        return

    if subcommand == "client":
        if not tail:
            ctx.console.print(f"[dim]Current client ID:[/dim] {ctx.config.cloud_client_id}")
            return
        client_id = tail[0].strip()
        if not client_id:
            ctx.console.print("[error]Client ID cannot be empty.[/error]")
            return
        save_cloud_settings(client_id=client_id)
        ctx.config.cloud_client_id = client_id
        ctx.console.print(f"[bold green]Cloud client ID updated.[/bold green] [dim]{client_id}[/dim]")
        return

    if subcommand == "login":
        if tail:
            api_url = _normalized_api_url(tail[0])
            save_cloud_settings(enabled=True, api_url=api_url, client_id=ctx.config.cloud_client_id)
            ctx.config.cloud_api_url = api_url
            ctx.config.cloud_auth_enabled = True
        if not ctx.config.cloud_auth_enabled:
            ctx.config.cloud_auth_enabled = True
            save_cloud_settings(enabled=True)
        if not ctx.config.cloud_api_url:
            ctx.console.print("[error]Set an API URL first:[/error] [bold]/cloud enable <api-url>[/bold]")
            return
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
        "[dim]Use /cloud status, /cloud enable <api-url>, /cloud login, /cloud logout, /cloud disable[/dim]"
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/cloud",
            description="Manage iTE Cloud auth and API settings",
            handler=cmd_cloud,
        )
    )
