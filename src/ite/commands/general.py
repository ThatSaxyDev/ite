"""General commands: /ite, /exit, /quit, /help, /clear, /new, /close, /refresh."""

import sys

from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from ite.cloud import clear_cloud_auth
from ite.commands import Command, CommandContext, CommandRegistry
from ite.memory import MemoryManager


async def cmd_ite(ctx: CommandContext, args: list[str]) -> None:
    ctx.tui.print_welcome(
        model=ctx.config.model_name,
        cwd=ctx.config.cwd,
    )


async def cmd_exit(ctx: CommandContext, args: list[str]) -> None:
    # Auto-save session before exiting (skip empty sessions)
    try:
        from ite.agent.session_manager import SessionManager, SessionSnapshot

        session = ctx.agent.session
        if session.turn_count > 0:
            session_manager = SessionManager()
            snapshot = SessionSnapshot(
                **session.snapshot_kwargs(workspace_path=str(ctx.config.cwd.resolve()))
            )
            session_manager.save_session(snapshot)
            session.record_lifecycle_episode(
                session.build_lifecycle_summary(
                    f"Session exited ({session.turn_count} turns)"
                ),
                source="session_exit",
            )
    except Exception:
        pass

    try:
        MemoryManager(
            ctx.config.cwd, session_id=ctx.agent.session.session_id
        ).clear_session_short_term()
    except Exception:
        pass

    ctx.console.print()
    ctx.console.print(
        Text.assemble(
            ("👋 ", ""),
            ("Goodbye! ", "bold bright_white"),
            ("See you next time.", "code"),
        )
    )
    ctx.console.print()
    sys.exit(0)


async def cmd_help(ctx: CommandContext, args: list[str]) -> None:
    from ite.commands import build_registry

    registry = build_registry()
    lines = []
    for cmd in registry.all_commands():
        aliases = ""
        if cmd.aliases:
            aliases = " or ".join(f"`{a}`" for a in cmd.aliases)
            aliases = f" ({aliases})"
        lines.append(f"- `{cmd.name}`{aliases} — {cmd.description}")

    help_md = Markdown("\n".join(lines))
    title = Text.assemble(("⌨  ", ""), ("Commands", "bold bright_white"))
    ctx.console.print()
    ctx.console.print(
        Panel(
            help_md,
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_clear(ctx: CommandContext, args: list[str]) -> None:
    ctx.agent.session.context_manager.clear()
    ctx.agent.session.loop_detector.clear()
    title = Text.assemble(("🗑  ", ""), ("Cleared", "bold bright_white"))
    ctx.console.print()
    ctx.console.print(
        Panel(
            Text.assemble(("Conversation cleared", "bold cyan")),
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_new(ctx: CommandContext, args: list[str]) -> None:
    # If the active UI has a richer new-thread flow, delegate to it.
    start_new_thread = getattr(ctx.tui, "_start_new_thread", None)
    if callable(start_new_thread):
        await start_new_thread()
        return

    from ite.agent.session import Session
    from ite.agent.session_manager import SessionManager, SessionSnapshot

    previous = ctx.agent.session

    # Save current session before switching if it has real turns.
    if previous.turn_count > 0:
        session_manager = SessionManager()
        snapshot = SessionSnapshot(
            **previous.snapshot_kwargs(workspace_path=str(ctx.config.cwd.resolve()))
        )
        session_manager.save_session(snapshot)
        previous.record_lifecycle_episode(
            previous.build_lifecycle_summary(
                f"Started new session after {previous.turn_count} turns"
            ),
            source="session_new",
        )

    old_callback = previous.approval_manager.confirmation_callback
    await previous.client.close()
    await previous.mcp_manager.shutdown()

    fresh = Session(config=ctx.config)
    await fresh.initialize()
    fresh.approval_manager.confirmation_callback = old_callback
    ctx.agent.session = fresh

    title = Text.assemble(("✨  ", ""), ("New Session", "bold bright_white"))
    ctx.console.print()
    ctx.console.print(
        Panel(
            Text.assemble(
                ("Started a fresh thread ", "bold cyan"),
                (f"({fresh.session_id[:8]}…)", "dim"),
            ),
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_close(ctx: CommandContext, args: list[str]) -> None:
    close_current_thread = getattr(ctx.tui, "_close_current_thread", None)
    if callable(close_current_thread):
        await close_current_thread()
        return

    ctx.console.print(
        "[error]/close is only available in multi-thread surfaces.[/error]"
    )


async def cmd_logout(ctx: CommandContext, args: list[str]) -> None:
    cleared = clear_cloud_auth()
    if cleared:
        ctx.console.print("[bold green]Cloud session cleared.[/bold green]")
        ctx.console.print(
            "[dim]Run `ite` again or use `/cloud login` to start sign-in from scratch.[/dim]"
        )
        return
    ctx.console.print("[dim]No local cloud session was present.[/dim]")


async def cmd_refresh(ctx: CommandContext, args: list[str]) -> None:
    ctx.console.print(
        "[dim]Use `/refresh` while signed in to refresh Pro status, "
        "bundled models, and entitlements.[/dim]"
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/ite",
            description="Show welcome screen",
            handler=cmd_ite,
        )
    )
    registry.register(
        Command(
            name="/exit",
            description="Exit the agent",
            handler=cmd_exit,
            aliases=["/quit"],
        )
    )
    registry.register(
        Command(
            name="/help",
            description="Show this help",
            handler=cmd_help,
        )
    )
    registry.register(
        Command(
            name="/clear",
            description="Clear conversation history",
            handler=cmd_clear,
        )
    )
    registry.register(
        Command(
            name="/new",
            description="Start a new thread/session",
            handler=cmd_new,
        )
    )
    registry.register(
        Command(
            name="/close",
            description="Close the current thread/session",
            handler=cmd_close,
        )
    )
    registry.register(
        Command(
            name="/logout",
            description="Log out of iTE",
            handler=cmd_logout,
        )
    )
    registry.register(
        Command(
            name="/refresh",
            description="Refresh Pro status, bundled models, and entitlements",
            handler=cmd_refresh,
        )
    )
    registry.register(
        Command(
            name="/setup",
            description="Re-run provider setup wizard",
            handler=cmd_setup,
        )
    )


async def cmd_setup(ctx: CommandContext, args: list[str]) -> None:
    from ite.config.setup import run_setup_wizard

    config = run_setup_wizard(ctx.console, ctx.config)

    # Update live config
    ctx.config.api_key = config.api_key
    ctx.config.base_url = config.base_url
    ctx.config.model.name = config.model.name

    # Update the LLM client with new credentials
    if ctx.agent and ctx.agent.session:
        ctx.agent.session.client._client = None  # force re-init on next call
