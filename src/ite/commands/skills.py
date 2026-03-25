from __future__ import annotations

from pathlib import Path

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ite.commands import Command
from ite.commands import CommandContext
from ite.commands import CommandRegistry
from ite.skills import install_skills_from_source


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
    table.add_column("Invoke", style="green")
    table.add_column("Source", style="dim")
    table.add_column("Description")

    for skill in available:
        identifier = skill["identifier"]
        table.add_row(
            identifier,
            (
                "active"
                if identifier in active
                else "blocked"
                if skill.get("trusted") == "false" and skill.get("requires_trust") == "true"
                else "available"
            ),
            "yes" if skill.get("user_invocable") == "true" else "no",
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
    option_args = [item for item in args[1:] if item.startswith("--")]
    value_args = [item for item in args[1:] if not item.startswith("--")]
    reference = " ".join(value_args).strip()

    if action in {"show", "inspect"}:
        if not reference:
            ctx.console.print("[error]Usage: /skills show <name>[/error]")
            return
        skill = session.resolve_skill(reference)
        if skill is None:
            ctx.console.print(f"[error]Skill not found:[/error] {reference}")
            return
        parts = [skill.description]
        if skill.requires_trust and not skill.trusted:
            parts.append("Trust status: blocked until this workspace is trusted with `/skills trust`.")
        if skill.user_invocable:
            parts.append("User-invocable: yes")
        if skill.version:
            parts.append(f"Version: {skill.version}")
        if skill.author:
            parts.append(f"Author: {skill.author}")
        if skill.homepage:
            parts.append(f"Homepage: {skill.homepage}")
        if skill.tags:
            parts.append("Tags: " + ", ".join(skill.tags[:12]))
        if skill.argument_hint:
            parts.append(f"Argument hint: {skill.argument_hint}")
        if skill.reference_files:
            refs = "\n".join(f"- {path}" for path in skill.reference_files[:20])
            parts.append(f"Reference files:\n{refs}")
        parts.append(skill.instructions)
        body = "\n\n".join(parts)
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
        preview = session.resolve_skill(reference)
        if preview is not None and preview.requires_trust and not preview.trusted:
            ctx.console.print(
                "[error]Workspace skills are blocked until trusted.[/error] [dim]Run /skills trust to allow project-provided skills.[/dim]"
            )
            return
        skill = session.activate_skill(reference)
        if skill is None:
            ctx.console.print(f"[error]Skill not found:[/error] {reference}")
            return
        ctx.console.print(
            f"[success]Activated skill:[/success] [bold]{skill.identifier}[/bold] [dim]({skill.name})[/dim]"
        )
        return

    if action == "trust":
        session.trust_skill_workspace()
        ctx.console.print(
            f"[dim]Trusted workspace skills for {ctx.config.cwd}. Project skill roots can now be activated.[/dim]"
        )
        return

    if action == "untrust":
        session.untrust_skill_workspace()
        ctx.console.print(
            f"[dim]Removed trust for workspace skills in {ctx.config.cwd}. Active project skills were cleared.[/dim]"
        )
        return

    if action == "add":
        if not reference:
            ctx.console.print("[error]Usage: /skills add <path> [--global|--local][/error]")
            return
        install_global = "--global" in option_args
        install_local = "--local" in option_args
        if install_global and install_local:
            ctx.console.print("[error]Choose only one destination flag: --global or --local.[/error]")
            return
        if install_global:
            destination = Path.home() / ".agents" / "skills"
        elif install_local:
            destination = ctx.config.cwd / ".ite" / "skills"
        else:
            destination = ctx.config.cwd / ".agents" / "skills"
        try:
            result = install_skills_from_source(Path(reference), destination)
        except Exception as exc:
            ctx.console.print(f"[error]Failed to install skills:[/error] {exc}")
            return
        session.refresh_skills()
        if destination == ctx.config.cwd / ".agents" / "skills":
            session.trust_skill_workspace()
        installed = ", ".join(result.installed_skill_names)
        ctx.console.print(
            f"[success]Installed skills:[/success] {installed}\n[dim]Source root: {result.detected_root} → {result.destination}[/dim]"
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
        "[error]Usage:[/error] [green]/skills[/green], [green]/skills show <name>[/green], [green]/skills use <name>[/green], [green]/skills drop <name>[/green], [green]/skills clear[/green], [green]/skills add <path> [--global|--local][/green], [green]/skills trust[/green], [green]/skills untrust[/green]"
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/skills",
            description="List, inspect, and activate Agent Skills",
            handler=cmd_skills,
        )
    )
