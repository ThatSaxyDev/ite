"""/remind command - Re-inject AGENTS.md content into the conversation."""

from ite.commands import Command, CommandContext, CommandRegistry
from ite.config.loader import (
    AGENTS_MD_FILE,
    _get_agents_md_files,
    _merge_agents_md_instructions,
)


async def cmd_remind(ctx: CommandContext, args: list[str]) -> None:
    """
    Re-inject AGENTS.md content as a reminder in the conversation.
    
    Usage: /remind
    
    Useful when the LLM seems to be drifting from project conventions.
    Reloads AGENTS.md files fresh and adds a system reminder.
    """
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session.[/error]")
        return
    
    cwd = ctx.config.cwd
    
    # Reload AGENTS.md files fresh
    files = _get_agents_md_files(cwd)
    
    if not files:
        ctx.console.print(
            f"[warning]No {AGENTS_MD_FILE} found.[/warning]\n"
            f"[dim]Create one with [bold]/init[/bold] or manually.[/dim]"
        )
        return
    
    # Full content re-injection
    merged = _merge_agents_md_instructions(files)
    if merged:
        full_reminder = f"""[AGENTS.md Reference - Refreshed]

{merged}

---
Follow the above instructions carefully in subsequent responses."""
        
        ctx.agent.session.context_manager.add_system_message(full_reminder)
        ctx.console.print(
            f"[success]AGENTS.md content re-injected[/success] [dim]({len(files)} file(s))[/dim]"
        )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/remind",
            description="Re-inject AGENTS.md content as a system reminder",
            handler=cmd_remind,
        )
    )
