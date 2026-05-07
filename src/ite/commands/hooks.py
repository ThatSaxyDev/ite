"""Hook commands: /hooks for configured runtime automation."""

from __future__ import annotations

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ite.commands import Command, CommandContext, CommandRegistry


async def cmd_hooks(ctx: CommandContext, args: list[str]) -> None:
    session = ctx.agent.session if ctx.agent and ctx.agent.session else None
    snapshot = (
        session.hook_system.snapshot()
        if session is not None
        else {
            "enabled": bool(ctx.config.hooks_enabled),
            "configured": [
                {
                    "name": hook.name,
                    "trigger": hook.trigger.value,
                    "command": hook.command or "<inline script>",
                    "timeout_sec": hook.timeout_sec,
                    "enabled": hook.enabled,
                }
                for hook in ctx.config.hooks
            ],
            "runs": [],
        }
    )

    configured = [
        item for item in snapshot.get("configured", []) if isinstance(item, dict)
    ]
    runs = [item for item in snapshot.get("runs", []) if isinstance(item, dict)]

    table = Table(box=box.SIMPLE, expand=True)
    table.add_column("Trigger", style="muted")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Timeout", justify="right")
    for hook in configured:
        status = "on" if hook.get("enabled", True) else "off"
        timeout = hook.get("timeout_sec")
        table.add_row(
            str(hook.get("trigger") or ""),
            str(hook.get("name") or "hook"),
            status,
            f"{timeout:g}s" if isinstance(timeout, (int, float)) else "",
        )

    if not configured:
        table.add_row("-", "No hooks configured", "-", "-")

    recent = Text()
    for run in reversed(runs[-8:]):
        status = str(run.get("status") or "unknown")
        duration = run.get("duration_ms")
        recent.append(str(run.get("trigger") or ""), style="muted")
        recent.append("  ")
        recent.append(str(run.get("name") or "hook"), style="bold")
        recent.append("  ")
        recent.append(status)
        if isinstance(duration, int):
            recent.append(f"  {duration}ms", style="muted")
        error = str(run.get("error") or "").strip()
        if error:
            recent.append(f"  {error}", style="error")
        recent.append("\n")
    if not recent:
        recent.append("No hook runs recorded for this session.", style="muted")

    enabled = "enabled" if snapshot.get("enabled") else "disabled"
    ctx.console.print()
    ctx.console.print(
        Panel(
            table,
            title=Text(f"Hooks ({enabled})", style="bold bright_white"),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )
    ctx.console.print(
        Panel(
            recent,
            title=Text("Recent runs", style="bold bright_white"),
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/hooks",
            description="Show configured hooks and recent hook runs",
            handler=cmd_hooks,
        )
    )
