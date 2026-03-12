"""Todo visibility and inspection commands."""

from __future__ import annotations

from ite.commands import Command, CommandContext, CommandRegistry
from ite.tools.base import ToolInvocation
from rich.panel import Panel
from rich.text import Text
from rich import box


def _render_status(ctx: CommandContext) -> None:
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session[/error]")
        return

    session = ctx.agent.session
    state = session.export_todos_state()
    planning = state.get("planning", []) if isinstance(state, dict) else []
    execution = state.get("execution", []) if isinstance(state, dict) else []
    title = Text.assemble(("✓ ", "green"), ("Todos", "bold bright_white"))
    body = Text.assemble(
        ("Planning visibility: ", "code"),
        (
            "shown",
            "bold cyan",
        )
        if session.show_planning_todos
        else ("hidden", "dim"),
        ("\nPlanning scope count: ", "code"),
        (str(len(planning)), "bold cyan"),
        ("\nExecution scope count: ", "code"),
        (str(len(execution)), "bold green"),
        ("\n\nUse ", "code"),
        ("/todos planning on", "green"),
        (" or ", "code"),
        ("/todos planning off", "green"),
        (" to toggle planning internals.", "code"),
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


async def cmd_todos(ctx: CommandContext, args: list[str]) -> None:
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session[/error]")
        return

    session = ctx.agent.session
    if not args:
        _render_status(ctx)
        return

    if len(args) >= 2 and args[0].lower() == "planning" and args[1].lower() in {"on", "off"}:
        session.show_planning_todos = args[1].lower() == "on"
        state = "shown" if session.show_planning_todos else "hidden"
        ctx.console.print(f"[dim]Planning todos are now {state}.[/dim]")
        if session.show_planning_todos:
            tool = session.tool_registry.get("todos")
            if tool is not None:
                result = await tool.execute(
                    ToolInvocation(
                        params={"action": "list", "scope": "planning"},
                        cwd=ctx.config.cwd,
                    )
                )
                if result.success:
                    ctx.console.print(result.output)
        return

    if args[0].lower() == "list":
        scope = "execution"
        if len(args) >= 2 and args[1].lower() in {"planning", "execution"}:
            scope = args[1].lower()
        tool = session.tool_registry.get("todos")
        if tool is None:
            ctx.console.print("[error]Todos tool is unavailable[/error]")
            return
        result = await tool.execute(
            ToolInvocation(
                params={"action": "list", "scope": scope},
                cwd=ctx.config.cwd,
            )
        )
        if result.success:
            ctx.console.print(result.output)
        else:
            ctx.console.print(f"[error]{result.error}[/error]")
        return

    ctx.console.print(
        "[error]Invalid usage.[/error] [dim]Use /todos, /todos planning on|off, or /todos list [planning|execution][/dim]"
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/todos",
            description="Show todo status, list todos, or toggle planning todo visibility",
            handler=cmd_todos,
        )
    )
