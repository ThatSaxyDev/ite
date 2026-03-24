from __future__ import annotations

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ite.commands import Command
from ite.commands import CommandContext
from ite.commands import CommandRegistry


def _render_skills_table(ctx: CommandContext) -> None:
    session = ctx.agent.session
    available = session.list_available_skills()
    active = {skill.identifier for skill in session.get_active_skills()}

    if not available:
        ctx.console.print(
            "[dim]No skills discovered. Put shared skills in .agents/skills and use .ite/skills only for local overrides.[/dim]"
        )
        return

    table = Table(
        title="Skills",
        title_style="bold bright_white",
        border_style="cyan",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
    )
    table.add_column("Identifier", style="bold")
    table.add_column("Status", style="cyan")
    table.add_column("Source", style="dim")
    table.add_column("Description")

    for skill in available:
        identifier = skill["identifier"]
        table.add_row(
            identifier,
            "active" if identifier in active else "available",
            skill["source"],
            skill["description"],
        )

    ctx.console.print()
    ctx.console.print(table)


async def cmd_skills(ctx: CommandContext, args: list[str]) -> None:
    session = ctx.agent.session
    session.refresh_skills()

    if not args or args[0] in {"list", "ls"}:
        _render_skills_table(ctx)
        return

    action = args[0].lower()
    reference = " ".join(args[1:]).strip()

    if action in {"show", "inspect"}:
        if not reference:
            ctx.console.print("[error]Usage: /skills show <name>[/error]")
            return
        skill = session.resolve_skill(reference)
        if skill is None:
            ctx.console.print(f"[error]Skill not found:[/error] {reference}")
            return
        body = f"{skill.description}\n\n{skill.instructions}"
        ctx.console.print()
        ctx.console.print(
            Panel(
                body,
                title=Text.assemble(("Skill ", "dim"), (skill.name, "bold bright_white")),
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        return

    if action in {"use", "activate"}:
        if not reference:
            ctx.console.print("[error]Usage: /skills use <name>[/error]")
            return
        skill = session.activate_skill(reference)
        if skill is None:
            ctx.console.print(f"[error]Skill not found:[/error] {reference}")
            return
        ctx.console.print(
            f"[success]Activated skill:[/success] [bold]{skill.identifier}[/bold] [dim]({skill.name})[/dim]"
        )
        return

    if action in {"drop", "deactivate"}:
        if not reference:
            ctx.console.print("[error]Usage: /skills drop <name>[/error]")
            return
        skill = session.deactivate_skill(reference)
        if skill is None:
            ctx.console.print(f"[error]Skill not active or not found:[/error] {reference}")
            return
        ctx.console.print(f"[dim]Deactivated skill {skill.identifier}.[/dim]")
        return

    if action == "clear":
        session.clear_active_skills()
        ctx.console.print("[dim]Cleared all active skills.[/dim]")
        return

    ctx.console.print(
        "[error]Usage:[/error] [green]/skills[/green], [green]/skills show <name>[/green], [green]/skills use <name>[/green], [green]/skills drop <name>[/green], [green]/skills clear[/green]"
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/skills",
            description="List, inspect, and activate Agent Skills",
            handler=cmd_skills,
        )
    )
