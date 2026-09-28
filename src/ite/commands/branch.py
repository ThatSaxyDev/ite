"""Branch commands: /branch for list/switch/create."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence
from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ite.commands import Command, CommandContext, CommandRegistry
from ite.git.branches import (
    BranchInfo,
    checkout_branch,
    create_and_checkout,
    current_branch,
    is_git_repo,
    list_local_branches,
)


def _branch_rows(branches: Sequence[BranchInfo]) -> Table:
    table = Table(title="Branches", box=box.SIMPLE)
    table.add_column("Branch", style="bold cyan")
    table.add_column("Current", style="bold white", justify="center")
    for branch in branches:
        table.add_row(branch.name, "✓" if branch.is_current else "")
    return table


def _pick_branch_with_curses(branches: list[BranchInfo]) -> str | None:
    import curses

    selected: str | None = None

    def _run(stdscr):
        nonlocal selected
        idx = next((i for i, b in enumerate(branches) if b.is_current), 0)
        top = 0
        curses.curs_set(0)
        stdscr.keypad(True)
        while True:
            h, w = stdscr.getmaxyx()
            visible = max(h - 4, 1)
            if idx < top:
                top = idx
            elif idx >= top + visible:
                top = idx - visible + 1

            stdscr.erase()
            stdscr.addnstr(0, 0, "Branches", w - 1, curses.A_BOLD)
            for row, i in enumerate(range(top, min(len(branches), top + visible)), start=1):
                marker = "▶ " if i == idx else "  "
                current = " ✓" if branches[i].is_current else ""
                line = f"{marker}{branches[i].name}{current}"
                attr = curses.A_REVERSE if i == idx else curses.A_NORMAL
                stdscr.addnstr(row, 0, line, w - 1, attr)

            help_text = "↑/↓ or j/k to move, Enter/Space switch, Esc/q cancel"
            stdscr.addnstr(h - 1, 0, help_text, w - 1, curses.A_DIM)
            stdscr.refresh()

            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k"), ord("K")):
                idx = (idx - 1) % len(branches)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                idx = (idx + 1) % len(branches)
            elif key in (10, 13, 32):
                selected = branches[idx].name
                return
            elif key in (27, ord("q"), ord("Q")):
                selected = None
                return

    curses.wrapper(_run)
    return selected


def _try_pick_branch(branches: list[BranchInfo]) -> str | None:
    if not branches:
        return None
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    if os.name == "nt":
        return None
    try:
        return _pick_branch_with_curses(branches)
    except Exception:
        return None


async def cmd_branch(ctx: CommandContext, args: list[str]) -> None:
    cwd = Path(ctx.config.cwd).resolve()
    if not is_git_repo(cwd):
        ctx.console.print("[error]Not a git repository in current workspace.[/error]")
        return

    branches = list_local_branches(cwd)
    if not branches:
        ctx.console.print("[warning]No local branches found.[/warning]")
        return

    if "--list" in args:
        ctx.console.print(_branch_rows(branches))
        return

    if "--create" in args or (args and args[0] == "create"):
        if "--create" in args:
            create_idx = args.index("--create")
            branch_name = args[create_idx + 1] if create_idx + 1 < len(args) else ""
        else:
            branch_name = args[1] if len(args) > 1 else ""
        if not branch_name.strip():
            ctx.console.print("[error]Usage: /branch --create <name>[/error]")
            return
        result = create_and_checkout(cwd, branch_name)
        if result.ok:
            title = Text.assemble(("🌿 ", ""), ("Branch Created", "bold bright_white"))
            ctx.console.print()
            ctx.console.print(
                Panel(
                    Text.assemble((result.message, "bold cyan")),
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return
        ctx.console.print(f"[error]{result.message}[/error]")
        return

    if args:
        target = args[0]
        result = checkout_branch(cwd, target)
        if result.ok:
            title = Text.assemble(("🌿 ", ""), ("Branch Switched", "bold bright_white"))
            ctx.console.print()
            ctx.console.print(
                Panel(
                    Text.assemble((result.message, "bold cyan")),
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return
        ctx.console.print(f"[error]{result.message}[/error]")
        return

    selected = _try_pick_branch(branches)
    if selected:
        result = checkout_branch(cwd, selected)
        if result.ok:
            title = Text.assemble(("🌿 ", ""), ("Branch Switched", "bold bright_white"))
            ctx.console.print()
            ctx.console.print(
                Panel(
                    Text.assemble((result.message, "bold cyan")),
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return
        ctx.console.print(f"[error]{result.message}[/error]")
        return

    ctx.console.print(_branch_rows(branches))
    ctx.console.print(
        f"[dim]Current: {current_branch(cwd)} • Use /branch <name> or /branch --create <name>[/dim]"
    )


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/branch",
            description="List, switch, or create git branches",
            handler=cmd_branch,
        )
    )

