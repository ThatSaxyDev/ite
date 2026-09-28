"""Hook commands: /hooks for configured runtime automation."""

from __future__ import annotations

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ite.commands import Command, CommandContext, CommandRegistry
from ite.config.loader import save_workspace_hooks_enabled


async def cmd_hooks(ctx: CommandContext, args: list[str]) -> None:
    if args and args[0].lower() in {"on", "off"}:
        enable = args[0].lower() == "on"
        old_state = ctx.config.hooks_enabled
        ctx.config.hooks_enabled = enable

        # Persist to workspace config
        saved_path = save_workspace_hooks_enabled(ctx.config.cwd, enable)

        # Update session hook system
        if ctx.agent and ctx.agent.session:
            ctx.agent.session.hook_system.hooks = (
                [hook for hook in ctx.config.hooks if hook.enabled]
                if enable
                else []
            )

        # Trigger immediate UI refresh for the toggle button
        try:
            ctx.tui._apply_hooks_panel_state()
        except Exception:
            pass

        title = Text.assemble(("🪝 ", ""), ("Hooks " + ("Enabled" if enable else "Disabled"), "bold bright_white"))
        state_change = "enabled" if enable else "disabled"
        ctx.console.print()
        ctx.console.print(
            Panel(
                Text.assemble(
                    (str(old_state).lower(), "dim strikethrough"),
                    (" → ", "muted"),
                    (state_change, "bold cyan"),
                    "\n\n",
                    (f"Hooks {state_change} and saved to {saved_path.name}", "green"),
                ),
                title=title,
                title_align="left",
                border_style="green",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        return

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
            description="Show configured hooks, or use /hooks on|off to enable/disable hooks",
            handler=cmd_hooks,
        )
    )
