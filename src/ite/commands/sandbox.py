"""Sandbox commands: /sandbox — manage filesystem sandboxing."""

from pathlib import Path
from ite.commands import Command, CommandContext, CommandRegistry
from rich.panel import Panel
from rich.text import Text
from rich import box


async def cmd_sandbox(ctx: CommandContext, args: list[str]) -> None:
    if not args:
        _show_status(ctx)
        return

    sub_cmd = args[0].lower()
    if sub_cmd in {"on", "off"} or (sub_cmd == "fs" and len(args) > 1 and args[1].lower() in {"on", "off"}):
        from ite.config.loader import save_global_permission_mode

        ctx.config.permissions = None
        save_global_permission_mode(None)

    if sub_cmd in ("on", "off"):
        # Toggle filesystem sandbox
        ctx.config.sandbox.enabled = sub_cmd == "on"
        state = "enabled" if ctx.config.sandbox.enabled else "disabled"
        _print_panel(
            ctx,
            "🔒",
            "Filesystem Sandbox",
            f"Sandbox {state}",
            "green" if sub_cmd == "on" else "yellow",
        )

    elif sub_cmd == "fs":
        if len(args) > 1 and args[1].lower() in ("on", "off"):
            ctx.config.sandbox.enabled = args[1].lower() == "on"
            state = "enabled" if ctx.config.sandbox.enabled else "disabled"
            _print_panel(
                ctx,
                "🔒",
                "Filesystem Sandbox",
                f"Sandbox {state}",
                "green" if ctx.config.sandbox.enabled else "yellow",
            )
        else:
            state = "enabled" if ctx.config.sandbox.enabled else "disabled"
            allowed = [str(p) for p in ctx.config.sandbox.allowed_paths]
            info = f"Status: {state}\nAllowed paths: {', '.join(allowed) if allowed else 'project cwd only'}"
            _print_panel(ctx, "🔒", "Filesystem Sandbox", info, "cyan")

    elif sub_cmd == "allow":
        if len(args) < 2:
            ctx.console.print("[error]Usage: /sandbox allow <path>[/error]")
            return
        new_path = Path(args[1]).expanduser().resolve()
        if new_path not in ctx.config.sandbox.allowed_paths:
            ctx.config.sandbox.allowed_paths.append(new_path)
        _print_panel(ctx, "🔒", "Path Allowed", f"Added: {new_path}", "green")

    elif sub_cmd == "remove":
        if len(args) < 2:
            ctx.console.print("[error]Usage: /sandbox remove <path>[/error]")
            return
        rm_path = Path(args[1]).expanduser().resolve()
        if rm_path in ctx.config.sandbox.allowed_paths:
            ctx.config.sandbox.allowed_paths.remove(rm_path)
            _print_panel(ctx, "🔒", "Path Removed", f"Removed: {rm_path}", "yellow")
        else:
            ctx.console.print(f"[dim]{rm_path} was not in the allowed list.[/dim]")

    elif sub_cmd == "clear":
        count = len(ctx.config.sandbox.allowed_paths)
        ctx.config.sandbox.allowed_paths.clear()
        _print_panel(
            ctx,
            "🔒",
            "Paths Cleared",
            f"Removed {count} allowed path(s). Only project cwd remains.",
            "yellow",
        )

    elif sub_cmd == "list":
        allowed = [str(p) for p in ctx.config.sandbox.allowed_paths]
        info = Text()
        info.append("Project cwd: ", style="code")
        info.append(str(ctx.config.cwd), style="bold cyan")
        info.append("\n\nAllowed paths:\n", style="code")
        if allowed:
            for idx, path in enumerate(allowed, start=1):
                info.append(f"  {idx}. ", style="dim")
                info.append(path, style="bold cyan")
                info.append("\n")
        else:
            info.append("  (none)\n", style="dim")
        _print_panel(ctx, "🔒", "Allowed Sandbox Paths", info, "cyan")

    elif sub_cmd in ("git", "diff", "accept", "reject"):
        ctx.console.print(
            "[error]Git sandbox commands are no longer supported.[/error]\n"
            "[dim]Available: /sandbox on|off|fs|allow|remove|clear|list[/dim]"
        )

    else:
        ctx.console.print(
            "[error]Usage: /sandbox [on|off|fs|allow|remove|clear|list][/error]"
        )


def _show_status(ctx: CommandContext) -> None:
    fs_state = "enabled" if ctx.config.sandbox.enabled else "disabled"
    allowed = [str(p) for p in ctx.config.sandbox.allowed_paths]

    info = Text()
    info.append("Filesystem: ", style="code")
    info.append(
        fs_state, style="green bold" if ctx.config.sandbox.enabled else "yellow bold"
    )
    info.append("\n")
    if allowed:
        info.append("\n")
        info.append("Allowed Paths: ", style="code")
        info.append(", ".join(allowed), style="dim")

    info.append("\n\n")
    info.append("Commands:\n", style="bold")
    info.append("  /sandbox on|off       ", style="green")
    info.append("Toggle filesystem sandbox\n", style="dim")
    info.append("  /sandbox allow <path> ", style="green")
    info.append("Allow an extra path\n", style="dim")
    info.append("  /sandbox remove <path>", style="green")
    info.append("Remove an allowed path\n", style="dim")
    info.append("  /sandbox clear        ", style="green")
    info.append("Clear all allowed paths\n", style="dim")
    info.append("  /sandbox list         ", style="green")
    info.append("List allowed paths", style="dim")

    _print_panel(ctx, "🔒", "Sandbox Status", info, "cyan")


def _print_panel(
    ctx: CommandContext, icon: str, title_text: str, content, border: str
) -> None:
    title = Text.assemble((f"{icon} ", ""), (title_text, "bold bright_white"))
    body = content if isinstance(content, Text) else Text(content, style="bold cyan")
    ctx.console.print()
    ctx.console.print(
        Panel(
            body,
            title=title,
            title_align="left",
            border_style=border,
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/sandbox",
            description="Manage filesystem sandboxing",
            handler=cmd_sandbox,
        )
    )
