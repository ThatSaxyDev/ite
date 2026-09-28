"""Subagent commands: /subagent list|create|delete."""

from ite.commands import Command, CommandContext, CommandRegistry
from rich.panel import Panel
from rich.table import Table
from rich import box


async def cmd_subagent(ctx: CommandContext, args: list[str]) -> None:
    if not args:
        ctx.console.print("[error]Usage: /subagent <list|create|delete>[/error]")
        return

    sub_cmd = args[0].lower()

    if sub_cmd == "list":
        _list_subagents(ctx)
    elif sub_cmd == "create":
        _create_subagent_interactive(ctx)
    elif sub_cmd == "delete":
        if len(args) < 2:
            ctx.console.print("[error]Usage: /subagent delete <name>[/error]")
        else:
            _delete_subagent(ctx, args[1])
    else:
        ctx.console.print(f"[error]Unknown subagent command: {sub_cmd}[/error]")


def _list_subagents(ctx: CommandContext) -> None:
    from ite.tools.subagent import SubagentTool

    tools = ctx.agent.session.tool_registry.get_tools()
    subagents = [t for t in tools if isinstance(t, SubagentTool)]

    if not subagents:
        ctx.console.print("[dim]No subagents found.[/dim]")
        return

    table = Table(title="Available Subagents", box=box.SIMPLE)
    table.add_column("Name", style="bold cyan")
    table.add_column("Description")
    table.add_column("Source", style="dim")

    for sa in subagents:
        table.add_row(sa.definition.name, sa.definition.description, "Active")

    ctx.console.print(table)


def _create_subagent_interactive(ctx: CommandContext) -> None:
    ctx.console.print(Panel("Create a new Subagent", style="bold green"))

    while True:
        name = ctx.console.input("[bold]Name (no spaces):[/bold] ").strip()
        if " " in name:
            ctx.console.print("[error]Name cannot contain spaces[/error]")
            continue
        if name:
            break

    description = ctx.console.input("[bold]Description:[/bold] ").strip()

    ctx.console.print("[bold]Goal/System Prompt (press Enter twice to finish):[/bold]")
    lines = []
    while True:
        line = ctx.console.input()
        if not line and (not lines or not lines[-1]):
            break
        lines.append(line)
    goal_prompt = "\n".join(lines).strip()

    # Tools
    ctx.console.print(
        "[bold]Allowed Tools (comma separated, leave empty for all):[/bold]"
    )
    all_tools = [t.name for t in ctx.agent.session.tool_registry.get_tools()]
    ctx.console.print(f"[dim]Available: {', '.join(all_tools)}[/dim]")

    tools_input = ctx.console.input("> ").strip()
    allowed_tools = (
        [t.strip() for t in tools_input.split(",")] if tools_input else None
    )

    # Confirm
    ctx.console.print(
        Panel(
            f"[bold]Name:[/bold] {name}\n"
            f"[bold]Description:[/bold] {description}\n"
            f"[bold]Goal Prompt:[/bold]\n{goal_prompt}\n\n"
            f"[bold]Tools:[/bold] {allowed_tools or 'All'}",
            title="Preview",
        )
    )
    if ctx.console.input("Save? [Y/n] ").lower() == "n":
        ctx.console.print("[dim]Cancelled[/dim]")
        return

    # Save to .ite/subagents/
    subagents_dir = ctx.config.cwd / ".ite" / "subagents"
    subagents_dir.mkdir(parents=True, exist_ok=True)
    file_path = subagents_dir / f"{name}.toml"

    tools_list_str = str(allowed_tools).replace("'", '"') if allowed_tools else "[]"
    if not allowed_tools:
        pass

    toml_content = f"""name = "{name}"
description = "{description}"
allowed_tools = {tools_list_str}

goal_prompt = \"\"\"
{goal_prompt}
\"\"\"
"""

    try:
        file_path.write_text(toml_content, encoding="utf-8")
        ctx.console.print(f"[success]Subagent saved to {file_path}[/success]")
        ctx.console.print(
            "[dim info]Restart the agent to load the new subagent.[/dim info]"
        )
    except Exception as e:
        ctx.console.print(f"[error]Failed to save subagent: {e}[/error]")


def _delete_subagent(ctx: CommandContext, name: str) -> None:
    subagents_dir = ctx.config.cwd / ".ite" / "subagents"
    file_path = subagents_dir / f"{name}.toml"

    if file_path.exists():
        try:
            file_path.unlink()
            ctx.console.print(f"[success]Deleted subagent {name}[/success]")
            ctx.console.print(
                "[dim info]Restart the agent to apply changes.[/dim info]"
            )
        except Exception as e:
            ctx.console.print(f"[error]Failed to delete: {e}[/error]")
    else:
        ctx.console.print(
            f"[error]Subagent configuration not found at {file_path}[/error]"
        )


def register(registry: CommandRegistry) -> None:
    registry.register(Command(
        name="/subagent",
        description="Manage subagents (list, create, delete)",
        handler=cmd_subagent,
        aliases=["/subagents"],
    ))
