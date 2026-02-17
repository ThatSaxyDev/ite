"""Session commands: /save, /sessions, /resume, /checkpoint, /checkpoints, /restore."""

from datetime import datetime
from ite.commands import Command, CommandContext, CommandRegistry
from ite.agent.session import Session
from ite.agent.session_manager import SessionSnapshot, SessionManager
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box


async def cmd_save(ctx: CommandContext, args: list[str]) -> None:
    session_manager = SessionManager()
    session_snapshot = SessionSnapshot(
        session_id=ctx.agent.session.session_id,
        created_at=ctx.agent.session.created_at,
        updated_at=ctx.agent.session.updated_at,
        turn_count=ctx.agent.session.turn_count,
        messages=ctx.agent.session.context_manager.get_messages(),
        total_usage=ctx.agent.session.context_manager.total_usage,
    )
    session_manager.save_session(session_snapshot)

    from ite.tools.builtin.memory import MemoryTool

    MemoryTool.append_episodic_entry(
        summary=f"Session saved ({ctx.agent.session.turn_count} turns)",
        cwd=str(ctx.config.cwd),
        key=ctx.agent.session.session_id,
    )
    title = Text.assemble(("💾  ", ""), ("Session saved", "bold bright_white"))
    ctx.console.print()
    ctx.console.print(
        Panel(
            Text.assemble(
                (f"Session: {ctx.agent.session.session_id}", "bold cyan"),
            ),
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_sessions(ctx: CommandContext, args: list[str]) -> None:
    session_manager = SessionManager()
    sessions = session_manager.list_sessions()
    # Filter out empty sessions (0 turns)
    sessions = [s for s in sessions if s["turn_count"] > 0]
    if not sessions:
        ctx.console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(title="Available Sessions", box=box.SIMPLE)
    table.add_column("Session ID", style="bold cyan")
    table.add_column("Name", style="bold white")
    table.add_column("Updated At")
    table.add_column("Turns", justify="right")

    for session in sessions:
        updated = datetime.fromisoformat(session["updated_at"])
        name = session.get("name") or "[dim]—[/dim]"
        table.add_row(
            session["session_id"],
            name,
            updated.strftime("%b %d · %I:%M %p"),
            str(session["turn_count"]),
        )

    ctx.console.print(table)


async def cmd_resume(ctx: CommandContext, args: list[str]) -> None:
    if not args:
        ctx.console.print(
            "[error]Missing session ID.[/error]  [dim]Run [green]/sessions[/green] to list saved sessions, then use [green]/resume <session_id>[/green][/dim]"
        )
        return

    session_id = args[0]
    session_manager = SessionManager()
    snapshot = session_manager.load_session(session_id)

    if snapshot is None:
        ctx.console.print(
            f"[error]Session not found:[/error] [bold]{session_id}[/bold]. [dim]Run [green]/sessions[/green] to list saved sessions.[/dim]"
        )
        return

    # Auto-checkpoint current session before overwriting
    if (
        ctx.agent.session.context_manager
        and ctx.agent.session.context_manager.message_count > 0
    ):
        current_snapshot = SessionSnapshot(
            session_id=ctx.agent.session.session_id,
            created_at=ctx.agent.session.created_at,
            updated_at=ctx.agent.session.updated_at,
            turn_count=ctx.agent.session.turn_count,
            messages=ctx.agent.session.context_manager.get_messages(),
            total_usage=ctx.agent.session.context_manager.total_usage,
        )
        session_manager.save_checkpoint(current_snapshot)

    session = Session(config=ctx.config)
    session.session_id = snapshot.session_id
    session.created_at = snapshot.created_at
    session.updated_at = snapshot.updated_at
    session.turn_count = snapshot.turn_count

    await ctx.agent.session.client.close()
    await ctx.agent.session.mcp_manager.shutdown()
    await session.initialize()

    session.context_manager.set_messages(snapshot.messages)
    session.context_manager.total_usage = snapshot.total_usage
    ctx.agent.session = session

    title = Text.assemble(("💾  ", ""), ("Resumed", "bold bright_white"))
    ctx.console.print()
    ctx.console.print(
        Panel(
            Text.assemble(
                (f"Session loaded: {session_id}", "bold cyan"),
                (f"  {snapshot.name}" if snapshot.name else "", "dim"),
            ),
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_checkpoint(ctx: CommandContext, args: list[str]) -> None:
    session_manager = SessionManager()
    session_snapshot = SessionSnapshot(
        session_id=ctx.agent.session.session_id,
        created_at=ctx.agent.session.created_at,
        updated_at=ctx.agent.session.updated_at,
        turn_count=ctx.agent.session.turn_count,
        messages=ctx.agent.session.context_manager.get_messages(),
        total_usage=ctx.agent.session.context_manager.total_usage,
    )
    checkpoint_id = session_manager.save_checkpoint(session_snapshot)
    title = Text.assemble(("💾  ", ""), ("Checkpoint created", "bold bright_white"))
    ctx.console.print()
    ctx.console.print(
        Panel(
            Text.assemble((f"Checkpoint: {checkpoint_id}", "bold cyan")),
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_checkpoints(ctx: CommandContext, args: list[str]) -> None:
    session_manager = SessionManager()
    target_id = args[0] if args else ctx.agent.session.session_id
    checkpoints = session_manager.list_checkpoints(target_id)

    if not checkpoints:
        ctx.console.print(
            f"[dim]No checkpoints found for session [bold]{target_id[:8]}…[/bold][/dim]"
        )
        return

    table = Table(
        title=f"Checkpoints for {target_id[:8]}…",
        title_style="bold bright_white",
        border_style="cyan",
        box=box.SIMPLE_HEAVY,
        padding=(0, 2),
    )
    table.add_column("Checkpoint ID", style="bold")
    table.add_column("Created At", style="cyan")
    table.add_column("Turn Count", style="dim", justify="right")

    for cp in checkpoints:
        created = datetime.fromisoformat(cp["created_at"])
        table.add_row(
            cp["checkpoint_id"],
            created.strftime("%b %d, %Y · %I:%M %p"),
            str(cp["turn_count"]),
        )

    ctx.console.print()
    ctx.console.print(table)


async def cmd_restore(ctx: CommandContext, args: list[str]) -> None:
    if not args:
        ctx.console.print(
            "[error]Missing checkpoint ID.[/error]  [dim]Use [green]/checkpoints[/green] to list checkpoints, then [green]/restore <checkpoint_id>[/green][/dim]"
        )
        return

    checkpoint_id = args[0]
    session_manager = SessionManager()
    snapshot = session_manager.load_checkpoint(checkpoint_id)

    if snapshot is None:
        ctx.console.print(
            f"[error]Checkpoint not found:[/error] [bold]{checkpoint_id}[/bold]. [dim]Use [green]/checkpoints[/green] to list available checkpoints.[/dim]"
        )
        return

    session = Session(config=ctx.config)
    session.session_id = snapshot.session_id
    session.created_at = snapshot.created_at
    session.updated_at = snapshot.updated_at
    session.turn_count = snapshot.turn_count

    await ctx.agent.session.client.close()
    await ctx.agent.session.mcp_manager.shutdown()
    await session.initialize()

    session.context_manager.set_messages(snapshot.messages)
    session.context_manager.total_usage = snapshot.total_usage
    ctx.agent.session = session

    title = Text.assemble(("💾  ", ""), ("Checkpoint Restored", "bold bright_white"))
    ctx.console.print()
    ctx.console.print(
        Panel(
            Text.assemble((f"Checkpoint: {checkpoint_id}", "bold cyan")),
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def register(registry: CommandRegistry) -> None:
    # /save and /checkpoint disabled — auto-save handles persistence now.
    # Handler code preserved above for future use.
    # registry.register(Command(
    #     name="/save", description="Save current session",
    #     handler=cmd_save,
    # ))
    registry.register(Command(
        name="/sessions", description="List saved sessions",
        handler=cmd_sessions,
    ))
    registry.register(Command(
        name="/resume", description="Resume a saved session",
        handler=cmd_resume,
    ))
    # registry.register(Command(
    #     name="/checkpoint", description="Create a checkpoint",
    #     handler=cmd_checkpoint,
    # ))
    registry.register(Command(
        name="/checkpoints", description="List available checkpoints",
        handler=cmd_checkpoints,
    ))
    registry.register(Command(
        name="/restore", description="Restore a checkpoint",
        handler=cmd_restore,
    ))
