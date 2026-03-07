"""Session commands: /save, /sessions, /resume (checkpointing remains internal)."""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
from ite.commands import Command, CommandContext, CommandRegistry
from ite.agent.session import Session
from ite.agent.session_manager import SessionSnapshot, SessionManager
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box


def _tool_kind_for_name(ctx: CommandContext, tool_name: str) -> str | None:
    if not ctx.agent or not ctx.agent.session:
        return None
    tool = ctx.agent.session.tool_registry.get(tool_name)
    if not tool:
        return None
    return tool.kind.value


def _render_resumed_transcript(ctx: CommandContext, messages: list[dict]) -> None:
    if not messages:
        return

    tool_call_names: dict[str, str] = {}

    ctx.console.print()
    ctx.console.print("[dim]Restored conversation:[/dim]")

    for message in messages:
        role = message.get("role")
        content = message.get("content", "")

        if role == "system":
            # Internal system prompt; keep hidden.
            continue

        if role == "user":
            ctx.console.print()
            ctx.console.print(f"[user]>[/user] {content}")
            continue

        if role == "assistant":
            if content:
                title = Text.assemble(("⏺ ", "muted"), ("ite", "bold bright_white"))
                ctx.console.print()
                ctx.console.print(
                    Panel(
                        content,
                        title=title,
                        title_align="left",
                        border_style="bright_white",
                        box=box.HEAVY,
                        padding=(1, 2),
                    )
                )

            for tool_call in message.get("tool_calls") or []:
                call_id = tool_call.get("id", "")
                function = tool_call.get("function", {}) or {}
                tool_name = function.get("name", "tool")
                raw_args = function.get("arguments", "") or ""
                try:
                    parsed_args = json.loads(raw_args) if raw_args else {}
                except Exception:
                    parsed_args = {"raw": raw_args}

                tool_call_names[call_id] = tool_name
                ctx.tui.tool_call_start(
                    call_id=call_id,
                    name=tool_name,
                    tool_kind=_tool_kind_for_name(ctx, tool_name),
                    arguments=parsed_args,
                )
            continue

        if role == "tool":
            call_id = message.get("tool_call_id", "")
            tool_name = tool_call_names.get(call_id, "tool")
            output = content if isinstance(content, str) else str(content)
            success = not output.lstrip().startswith("Error:")
            ctx.tui.tool_call_complete(
                call_id=call_id,
                name=tool_name,
                tool_kind=_tool_kind_for_name(ctx, tool_name),
                success=success,
                output=output,
                error=None if success else output,
                metadata={},
                diff=None,
                truncated=False,
                exit_code=None,
            )


def _format_picker_row(session: dict[str, str | int]) -> str:
    updated = datetime.fromisoformat(str(session["updated_at"])).strftime("%b %d · %I:%M %p")
    sid = str(session["session_id"])
    sid_short = f"{sid[:8]}...{sid[-6:]}" if len(sid) > 18 else sid
    name = str(session.get("name") or "—").strip()
    if len(name) > 38:
        name = name[:35] + "..."
    return f"{sid_short:<18}  {name:<38}  {updated:<18}"


def _pick_session_with_curses(sessions: list[dict]) -> str | None:
    import curses

    selected_id: str | None = None

    def _run(stdscr):
        nonlocal selected_id
        selected_idx = 0
        top_idx = 0

        curses.curs_set(0)
        stdscr.keypad(True)

        while True:
            height, width = stdscr.getmaxyx()
            visible_rows = max(height - 4, 1)
            if selected_idx < top_idx:
                top_idx = selected_idx
            elif selected_idx >= top_idx + visible_rows:
                top_idx = selected_idx - visible_rows + 1

            stdscr.erase()
            header = "Available Sessions"
            stdscr.addnstr(0, 0, header, width - 1, curses.A_BOLD)

            for row, idx in enumerate(range(top_idx, min(len(sessions), top_idx + visible_rows)), start=1):
                marker = "▶ " if idx == selected_idx else "  "
                line = marker + _format_picker_row(sessions[idx])
                attr = curses.A_REVERSE if idx == selected_idx else curses.A_NORMAL
                stdscr.addnstr(row, 0, line, width - 1, attr)

            help_text = "↑/↓ or j/k to move, Enter/Space to resume, Esc/q to cancel"
            stdscr.addnstr(height - 1, 0, help_text, width - 1, curses.A_DIM)
            stdscr.refresh()

            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k"), ord("K")):
                selected_idx = (selected_idx - 1) % len(sessions)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                selected_idx = (selected_idx + 1) % len(sessions)
            elif key in (10, 13, 32):
                selected_id = str(sessions[selected_idx]["session_id"])
                return
            elif key in (27, ord("q"), ord("Q")):
                selected_id = None
                return

    curses.wrapper(_run)
    return selected_id


async def _pick_session_to_resume(
    ctx: CommandContext,
    sessions: list[dict],
) -> str | None:
    if not sessions:
        return None
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None

    selected_idx = 0
    try:
        if os.name == "nt":
            return None
        return _pick_session_with_curses(sessions)
    except (KeyboardInterrupt, EOFError):
        return None
    return None


async def cmd_save(ctx: CommandContext, args: list[str]) -> None:
    session_manager = SessionManager()
    session_snapshot = SessionSnapshot(
        session_id=ctx.agent.session.session_id,
        name=ctx.agent.session.name,
        workspace_path=str(ctx.config.cwd.resolve()),
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
    all_workspaces = "--all" in args
    sessions = session_manager.list_sessions(
        workspace_path=None if all_workspaces else ctx.config.cwd,
        include_legacy_unscoped=all_workspaces,
    )
    # Filter out empty sessions (0 turns)
    sessions = [s for s in sessions if s["turn_count"] > 0]
    if not sessions:
        ctx.console.print("[dim]No sessions found.[/dim]")
        return

    # Non-interactive or explicit list mode: show static table only.
    if "--list" in args:
        table = Table(title="Available Sessions", box=box.SIMPLE)
        table.add_column("Session ID", style="bold cyan")
        table.add_column("Name", style="bold white")
        table.add_column("Updated At")

        for session in sessions:
            updated = datetime.fromisoformat(session["updated_at"])
            name = session.get("name") or "[dim]—[/dim]"
            table.add_row(
                session["session_id"],
                name,
                updated.strftime("%b %d · %I:%M %p"),
            )
        ctx.console.print(table)
        return

    selected_session_id = await _pick_session_to_resume(ctx, sessions)
    if selected_session_id:
        await cmd_resume(ctx, [selected_session_id])
        return

    # Fallback: show static listing and usage hint.
    table = Table(title="Available Sessions", box=box.SIMPLE)
    table.add_column("Session ID", style="bold cyan")
    table.add_column("Name", style="bold white")
    table.add_column("Updated At")

    for session in sessions:
        updated = datetime.fromisoformat(session["updated_at"])
        name = session.get("name") or "[dim]—[/dim]"
        table.add_row(
            session["session_id"],
            name,
            updated.strftime("%b %d · %I:%M %p"),
        )

    ctx.console.print(table)
    if sys.stdin.isatty() and sys.stdout.isatty():
        ctx.console.print(
            "[dim]Tip: press ↑/↓ then Enter in /sessions interactive picker, or run /sessions --list for table only.[/dim]"
        )


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
            name=ctx.agent.session.name,
            workspace_path=str(ctx.config.cwd.resolve()),
            created_at=ctx.agent.session.created_at,
            updated_at=ctx.agent.session.updated_at,
            turn_count=ctx.agent.session.turn_count,
            messages=ctx.agent.session.context_manager.get_messages(),
            total_usage=ctx.agent.session.context_manager.total_usage,
        )
        session_manager.save_checkpoint(current_snapshot)

    if snapshot.workspace_path:
        target_workspace = Path(snapshot.workspace_path).resolve()
        if target_workspace != ctx.config.cwd.resolve():
            ctx.console.print(
                f"[dim]Switching workspace to {target_workspace} for resumed session.[/dim]"
            )
            ctx.config.cwd = target_workspace
            ctx.tui.cwd = target_workspace

    session = Session(config=ctx.config)
    session.session_id = snapshot.session_id
    session.name = snapshot.name
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
    _render_resumed_transcript(ctx, snapshot.messages)


async def cmd_checkpoint(ctx: CommandContext, args: list[str]) -> None:
    session_manager = SessionManager()
    session_snapshot = SessionSnapshot(
        session_id=ctx.agent.session.session_id,
        name=ctx.agent.session.name,
        workspace_path=str(ctx.config.cwd.resolve()),
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

    if snapshot.workspace_path:
        target_workspace = Path(snapshot.workspace_path).resolve()
        if target_workspace != ctx.config.cwd.resolve():
            ctx.console.print(
                f"[dim]Switching workspace to {target_workspace} for restored checkpoint.[/dim]"
            )
            ctx.config.cwd = target_workspace
            ctx.tui.cwd = target_workspace

    session = Session(config=ctx.config)
    session.session_id = snapshot.session_id
    session.name = snapshot.name
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
    # Checkpoint commands intentionally not registered for user-facing CLI.
    # Internal auto-checkpoint flow remains active.
