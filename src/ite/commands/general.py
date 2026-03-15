"""General commands: /ite, /exit, /quit, /help, /clear, /new."""

import sys
from ite.commands import Command, CommandContext, CommandRegistry
from ite.memory import MemoryManager
from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown
from rich import box


async def cmd_ite(ctx: CommandContext, args: list[str]) -> None:
    ctx.tui.print_welcome(
        model=ctx.config.model_name,
        cwd=ctx.config.cwd,
    )


async def cmd_exit(ctx: CommandContext, args: list[str]) -> None:
    # Auto-save session before exiting (skip empty sessions)
    try:
        from ite.agent.session_manager import SessionSnapshot, SessionManager

        session = ctx.agent.session
        if session.turn_count > 0:
            session_manager = SessionManager()
            snapshot = SessionSnapshot(
                session_id=session.session_id,
                name=session.name,
                workspace_path=str(ctx.config.cwd.resolve()),
                created_at=session.created_at,
                updated_at=session.updated_at,
                turn_count=session.turn_count,
                messages=session.context_manager.get_messages(),
                total_usage=session.context_manager.total_usage,
                plan_mode_enabled=session.plan_mode_enabled,
                plan_phase=session.plan_phase,
                plan_questions_asked=session.plan_questions_asked,
                plan_target_questions=session.plan_target_questions,
                pending_plan_text=session.pending_plan_text,
                active_plan_text=session.active_plan_text,
                todos_state=session.export_todos_state(),
                show_planning_todos=session.show_planning_todos,
            )
            session_manager.save_session(snapshot)
    except Exception:
        pass

    try:
        MemoryManager(ctx.config.cwd, session_id=ctx.agent.session.session_id).clear_session_short_term()
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
    from ite.agent.session_manager import SessionSnapshot, SessionManager

    previous = ctx.agent.session

    # Save current session before switching if it has real turns.
    if previous.turn_count > 0:
        session_manager = SessionManager()
        snapshot = SessionSnapshot(
            session_id=previous.session_id,
            name=previous.name,
            workspace_path=str(ctx.config.cwd.resolve()),
            created_at=previous.created_at,
            updated_at=previous.updated_at,
            turn_count=previous.turn_count,
            messages=previous.context_manager.get_messages(),
            total_usage=previous.context_manager.total_usage,
            plan_mode_enabled=previous.plan_mode_enabled,
            plan_phase=previous.plan_phase,
            plan_questions_asked=previous.plan_questions_asked,
            plan_target_questions=previous.plan_target_questions,
            pending_plan_text=previous.pending_plan_text,
            active_plan_text=previous.active_plan_text,
            todos_state=previous.export_todos_state(),
            show_planning_todos=previous.show_planning_todos,
        )
        session_manager.save_session(snapshot)

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


def register(registry: CommandRegistry) -> None:
    registry.register(Command(
        name="/ite", description="Show welcome screen", handler=cmd_ite,
    ))
    registry.register(Command(
        name="/exit", description="Exit the agent",
        handler=cmd_exit, aliases=["/quit"],
    ))
    registry.register(Command(
        name="/help", description="Show this help", handler=cmd_help,
    ))
    registry.register(Command(
        name="/clear", description="Clear conversation history",
        handler=cmd_clear,
    ))
    registry.register(Command(
        name="/new", description="Start a new thread/session",
        handler=cmd_new,
    ))
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
