"""Model/config commands: /model, /config, /approval."""

import os
import sys
from pathlib import Path
from ite.commands import Command, CommandContext, CommandRegistry
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box


def _pick_approval_with_curses(
    modes: list[str],
    descriptions: dict[str, str],
    current_mode: str,
) -> str | None:
    import curses

    selected: str | None = None

    def _run(stdscr):
        nonlocal selected
        idx = modes.index(current_mode) if current_mode in modes else 0

        curses.curs_set(0)
        stdscr.keypad(True)

        while True:
            h, w = stdscr.getmaxyx()
            stdscr.erase()
            stdscr.addnstr(0, 0, "Approval Modes", w - 1, curses.A_BOLD)

            row = 2
            for i, mode in enumerate(modes):
                marker = "● " if mode == current_mode else "  "
                prefix = "▶ " if i == idx else "  "
                line = f"{prefix}{marker}{mode}"
                attr = curses.A_REVERSE if i == idx else curses.A_NORMAL
                stdscr.addnstr(row, 0, line, w - 1, attr)
                row += 1
                desc = descriptions.get(mode, "")
                stdscr.addnstr(row, 4, desc, w - 5, curses.A_DIM)
                row += 1

            help_text = "↑/↓ or j/k to move, Enter/Space to select, Esc/q to cancel"
            stdscr.addnstr(h - 1, 0, help_text, w - 1, curses.A_DIM)
            stdscr.refresh()

            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k"), ord("K")):
                idx = (idx - 1) % len(modes)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                idx = (idx + 1) % len(modes)
            elif key in (10, 13, 32):
                selected = modes[idx]
                return
            elif key in (27, ord("q"), ord("Q")):
                selected = None
                return

    curses.wrapper(_run)
    return selected


def _pick_approval_mode(
    modes: list[str],
    descriptions: dict[str, str],
    current_mode: str,
) -> str | None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    if os.name == "nt":
        return None
    try:
        return _pick_approval_with_curses(modes, descriptions, current_mode)
    except Exception:
        return None


async def cmd_model(ctx: CommandContext, args: list[str]) -> None:
    if args:
        old_model = ctx.config.model_name
        new_model = args[0]
        ctx.config.model_name = new_model
        title = Text.assemble(("🤖 ", ""), ("Model Changed", "bold bright_white"))
        ctx.console.print()
        ctx.console.print(
            Panel(
                Text.assemble(
                    (old_model, "dim strikethrough"),
                    (" → ", "muted"),
                    (new_model, "bold cyan"),
                    "\n\n",
                    ("Model changed successfully", "green"),
                ),
                title=title,
                title_align="left",
                border_style="green",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    else:
        title = Text.assemble(("🤖 ", ""), ("Model", "bold bright_white"))
        ctx.console.print()
        ctx.console.print(
            Panel(
                Text.assemble(
                    ("Active model: ", "code"),
                    (ctx.config.model_name, "bold cyan"),
                    "\n\n",
                    ("Use ", "code"),
                    ("/model <name>", "green bold"),
                    (" to change the model", "code"),
                ),
                title=title,
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )


async def cmd_config(ctx: CommandContext, args: list[str]) -> None:
    title = Text.assemble(("⚙ ", ""), ("Current Configuration", "bold bright_white"))
    config_table = Table.grid(padding=(0, 2))
    config_table.add_column(style="code", justify="right", min_width=8)
    config_table.add_column(style="bold white")
    cwd_display = str(ctx.config.cwd).replace(str(Path.home()), "~")
    config_table.add_row(
        Text("Model", style="muted"),
        Text(ctx.config.model_name, style="cyan bold"),
    )
    config_table.add_row(
        Text("Current Dir", style="muted"),
        Text(cwd_display, style="info"),
    )
    config_table.add_row(
        Text("Approval", style="muted"),
        Text(ctx.config.approval.value, style="info"),
    )
    config_table.add_row(
        Text("Max Turns", style="muted"),
        Text(str(ctx.config.max_turns), style="info"),
    )
    config_table.add_row(
        Text("Hooks Enabled", style="muted"),
        Text(str(ctx.config.hooks_enabled), style="info"),
    )

    ctx.console.print()
    ctx.console.print(
        Panel(
            config_table,
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


async def cmd_approval(ctx: CommandContext, args: list[str]) -> None:
    from ite.config.config import ApprovalPolicy
    from ite.config.loader import save_global_approval_mode

    valid_modes = [p.value for p in ApprovalPolicy]
    mode_descriptions = {
        "on_request": "Ask before every mutating action",
        "on_failure": "Auto-approve, ask only on failure",
        "auto": "Auto-approve all safe operations",
        "auto_edit": "Auto-approve edits, confirm commands",
        "never": "Only allow safe commands, reject all else",
        "yolo": "Approve everything — no guardrails",
    }

    if args and args[0].lower() == "help":
        lines = Text()
        for mode in ApprovalPolicy:
            marker = " ← current" if mode == ctx.config.approval else ""
            lines.append(
                f"  {mode.value}",
                style="bold cyan" if mode == ctx.config.approval else "green bold",
            )
            lines.append(f"  {mode_descriptions[mode.value]}", style="dim")
            if marker:
                lines.append(marker, style="yellow")
            lines.append("\n")

        title = Text.assemble(("🛡 ", ""), ("Approval Modes", "bold bright_white"))
        ctx.console.print()
        ctx.console.print(
            Panel(
                lines,
                title=title,
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    elif args:
        new_approval = args[0].lower()
        if new_approval not in valid_modes:
            ctx.console.print(
                f"[error]Invalid approval mode:[/error] [bold]{args[0]}[/bold]\n"
                f"[dim]Valid modes: [green]{', '.join(valid_modes)}[/green] — try [green]/approval help[/green][/dim]"
            )
            return

        old_approval = ctx.config.approval.value
        selected_policy = ApprovalPolicy(new_approval)
        ctx.config.approval = selected_policy
        if ctx.agent and ctx.agent.session:
            ctx.agent.session.approval_manager.approval_policy = selected_policy
        save_global_approval_mode(selected_policy)
        title = Text.assemble(("🛡 ", ""), ("Approval Changed", "bold bright_white"))
        ctx.console.print()
        ctx.console.print(
            Panel(
                Text.assemble(
                    (old_approval, "dim strikethrough"),
                    (" → ", "muted"),
                    (new_approval, "bold cyan"),
                    "\n\n",
                    ("Approval changed successfully", "green"),
                ),
                title=title,
                title_align="left",
                border_style="green",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    else:
        selected = _pick_approval_mode(
            modes=valid_modes,
            descriptions=mode_descriptions,
            current_mode=ctx.config.approval.value,
        )
        if selected and selected != ctx.config.approval.value:
            old_approval = ctx.config.approval.value
            selected_policy = ApprovalPolicy(selected)
            ctx.config.approval = selected_policy
            if ctx.agent and ctx.agent.session:
                ctx.agent.session.approval_manager.approval_policy = selected_policy
            save_global_approval_mode(selected_policy)
            title = Text.assemble(("🛡 ", ""), ("Approval Changed", "bold bright_white"))
            ctx.console.print()
            ctx.console.print(
                Panel(
                    Text.assemble(
                        (old_approval, "dim strikethrough"),
                        (" → ", "muted"),
                        (selected, "bold cyan"),
                        ("\n\nApproval changed successfully", "green"),
                    ),
                    title=title,
                    title_align="left",
                    border_style="green",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return

        title = Text.assemble(("🛡 ", ""), ("Approval", "bold bright_white"))
        ctx.console.print()
        ctx.console.print(
            Panel(
                Text.assemble(
                    ("Active approval: ", "code"),
                    (ctx.config.approval.value, "bold cyan"),
                    "\n\n",
                    ("Use ", "code"),
                    ("/approval <mode>", "green bold"),
                    (" to change  •  ", "code"),
                    ("/approval help", "green bold"),
                    (" to see all modes", "code"),
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
        name="/model", description="Show or change the model",
        handler=cmd_model,
    ))
    registry.register(Command(
        name="/config", description="Show current configuration",
        handler=cmd_config,
    ))
    registry.register(Command(
        name="/approval", description="Show or change approval mode",
        handler=cmd_approval,
    ))
