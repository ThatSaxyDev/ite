"""Sandbox commands: /sandbox — manage filesystem and git sandboxing."""

from pathlib import Path
from commands import Command, CommandContext, CommandRegistry
from rich.panel import Panel
from rich.text import Text
from rich import box


# Module-level git sandbox instance (persists across command invocations)
_git_sandbox = None


def _get_git_sandbox(ctx: CommandContext):
    """Lazily create and return the GitSandbox instance."""
    global _git_sandbox
    if _git_sandbox is None:
        from safety.git_sandbox import GitSandbox
        _git_sandbox = GitSandbox(ctx.config.cwd)
    return _git_sandbox


async def cmd_sandbox(ctx: CommandContext, args: list[str]) -> None:
    if not args:
        _show_status(ctx)
        return

    sub_cmd = args[0].lower()

    if sub_cmd in ("on", "off"):
        # Toggle filesystem sandbox
        ctx.config.sandbox.enabled = sub_cmd == "on"
        state = "enabled" if ctx.config.sandbox.enabled else "disabled"
        _print_panel(ctx, "🔒", "Filesystem Sandbox", f"Sandbox {state}", "green" if sub_cmd == "on" else "yellow")

    elif sub_cmd == "fs":
        if len(args) > 1 and args[1].lower() in ("on", "off"):
            ctx.config.sandbox.enabled = args[1].lower() == "on"
            state = "enabled" if ctx.config.sandbox.enabled else "disabled"
            _print_panel(ctx, "🔒", "Filesystem Sandbox", f"Sandbox {state}", "green" if ctx.config.sandbox.enabled else "yellow")
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

    elif sub_cmd == "git":
        if len(args) > 1 and args[1].lower() == "on":
            gs = _get_git_sandbox(ctx)
            try:
                branch = gs.start()
                ctx.config.sandbox.git_sandbox = True
                _print_panel(ctx, "🌿", "Git Sandbox Started", f"Branch: {branch}", "green")
            except Exception as e:
                ctx.console.print(f"[error]{e}[/error]")
        elif len(args) > 1 and args[1].lower() == "off":
            ctx.config.sandbox.git_sandbox = False
            _print_panel(ctx, "🌿", "Git Sandbox", "Git sandbox disabled", "yellow")
        else:
            gs = _get_git_sandbox(ctx)
            status = gs.status()
            info = f"Active: {status['active']}"
            if status['sandbox_branch']:
                info += f"\nBranch: {status['sandbox_branch']}"
            if status['original_branch']:
                info += f"\nOriginal: {status['original_branch']}"
            _print_panel(ctx, "🌿", "Git Sandbox", info, "cyan")

    elif sub_cmd == "diff":
        gs = _get_git_sandbox(ctx)
        try:
            diff = gs.diff()
            if diff:
                ctx.console.print()
                ctx.console.print(Panel(
                    diff, title="🌿 Sandbox Diff",
                    title_align="left", border_style="cyan",
                    box=box.ROUNDED, padding=(1, 2),
                ))
            else:
                ctx.console.print("[dim]No changes in sandbox.[/dim]")
        except Exception as e:
            ctx.console.print(f"[error]{e}[/error]")

    elif sub_cmd == "accept":
        gs = _get_git_sandbox(ctx)
        try:
            result = gs.accept()
            _print_panel(ctx, "✅", "Sandbox Accepted", result, "green")
        except Exception as e:
            ctx.console.print(f"[error]{e}[/error]")

    elif sub_cmd == "reject":
        gs = _get_git_sandbox(ctx)
        try:
            result = gs.reject()
            _print_panel(ctx, "❌", "Sandbox Rejected", result, "yellow")
        except Exception as e:
            ctx.console.print(f"[error]{e}[/error]")

    else:
        ctx.console.print(
            "[error]Usage: /sandbox [on|off|fs|git|allow|diff|accept|reject][/error]"
        )


def _show_status(ctx: CommandContext) -> None:
    fs_state = "enabled" if ctx.config.sandbox.enabled else "disabled"
    git_state = "enabled" if ctx.config.sandbox.git_sandbox else "disabled"
    allowed = [str(p) for p in ctx.config.sandbox.allowed_paths]

    info = Text()
    info.append("Filesystem: ", style="code")
    info.append(fs_state, style="green bold" if ctx.config.sandbox.enabled else "yellow bold")
    info.append("\n")
    info.append("Git Sandbox: ", style="code")
    info.append(git_state, style="green bold" if ctx.config.sandbox.git_sandbox else "yellow bold")
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
    info.append("  /sandbox git on|off   ", style="green")
    info.append("Toggle git sandbox\n", style="dim")
    info.append("  /sandbox diff         ", style="green")
    info.append("Show sandbox changes\n", style="dim")
    info.append("  /sandbox accept       ", style="green")
    info.append("Merge sandbox changes\n", style="dim")
    info.append("  /sandbox reject       ", style="green")
    info.append("Discard sandbox changes", style="dim")

    _print_panel(ctx, "🔒", "Sandbox Status", info, "cyan")


def _print_panel(ctx: CommandContext, icon: str, title_text: str, content, border: str) -> None:
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
    registry.register(Command(
        name="/sandbox",
        description="Manage filesystem and git sandboxing",
        handler=cmd_sandbox,
    ))
