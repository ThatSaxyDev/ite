"""History commands: /undo, /redo, /history."""

from __future__ import annotations

from ite.agent.change_history import ChangeConflictError
from ite.commands import Command, CommandContext, CommandRegistry
from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def _require_session(ctx: CommandContext):
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session.[/error]")
        return None
    return ctx.agent.session


def _render_history_table(entries) -> Table:
    table = Table(title="Change History", box=box.SIMPLE)
    table.add_column("ID", style="bold cyan")
    table.add_column("Summary", style="white")
    table.add_column("Files", justify="right", style="bold white")
    for change_set in entries:
        table.add_row(change_set.id, change_set.label, str(len(change_set.changes)))
    return table


async def cmd_history(ctx: CommandContext, args: list[str]) -> None:
    session = _require_session(ctx)
    if session is None:
        return

    entries = session.change_history.history()
    if not entries:
        ctx.console.print("[dim]No recorded file changes in this session.[/dim]")
        return

    ctx.console.print(_render_history_table(entries))


async def cmd_undo(ctx: CommandContext, args: list[str]) -> None:
    session = _require_session(ctx)
    if session is None:
        return

    force = "--force" in args
    try:
        change_set = session.change_history.undo(force=force)
    except ChangeConflictError as exc:
        ctx.console.print(f"[error]{exc}[/error]")
        return

    title = Text.assemble(("↶ ", ""), ("Undid changes", "bold bright_white"))
    body = Text.assemble(
        (change_set.label, "bold cyan"),
        ("  ", ""),
        (f"{len(change_set.changes)} file(s)", "dim"),
    )
    ctx.console.print()
    ctx.console.print(
        Panel(
            body,
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_redo(ctx: CommandContext, args: list[str]) -> None:
    session = _require_session(ctx)
    if session is None:
        return

    force = "--force" in args
    try:
        change_set = session.change_history.redo(force=force)
    except ChangeConflictError as exc:
        ctx.console.print(f"[error]{exc}[/error]")
        return

    title = Text.assemble(("↷ ", ""), ("Reapplied changes", "bold bright_white"))
    body = Text.assemble(
        (change_set.label, "bold cyan"),
        ("  ", ""),
        (f"{len(change_set.changes)} file(s)", "dim"),
    )
    ctx.console.print()
    ctx.console.print(
        Panel(
            body,
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/undo",
            description="Undo the most recent recorded file change set",
            handler=cmd_undo,
        )
    )
    registry.register(
        Command(
            name="/redo",
            description="Reapply the most recently undone file change set",
            handler=cmd_redo,
        )
    )
    registry.register(
        Command(
            name="/history",
            description="Show recorded file change sets for this session",
            handler=cmd_history,
        )
    )
