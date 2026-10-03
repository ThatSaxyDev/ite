"""Attachment commands for TUI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rich.panel import Panel
from rich.text import Text
from rich import box

from ite.attachments import MAX_ATTACHMENTS, queue_attachment_paths
from ite.commands import Command, CommandContext, CommandRegistry


def _queue_paths(ctx: CommandContext, paths: list[str]) -> int:
    if not ctx.agent or not ctx.agent.session:
        return 0
    queue = ctx.agent.session.pending_attachment_paths
    pending, _accepted, errors = queue_attachment_paths(queue, paths)
    added = len(pending) - len(queue)
    ctx.agent.session.pending_attachment_paths = pending
    for error in errors:
        ctx.console.print(Text(error, style="red"))
    return added


def _render_queue(ctx: CommandContext) -> None:
    if not ctx.agent or not ctx.agent.session:
        return
    queue = ctx.agent.session.pending_attachment_paths
    if not queue:
        ctx.console.print("[dim]No queued attachments.[/dim]")
        return

    lines = []
    for idx, p in enumerate(queue, start=1):
        lines.append(f"{idx}. {Path(p).name}  [dim]{p}[/dim]")
    ctx.console.print(
        Panel(
            "\n".join(lines),
            title=Text("Queued Attachments", style="bold cyan"),
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def _pick_files_with_curses(cwd: Path) -> list[str]:
    import curses

    files: list[Path] = []
    for p in cwd.rglob("*"):
        if len(files) >= 700:
            break
        if not p.is_file():
            continue
        s = str(p)
        if "/.git/" in s or "/.ite/tmp_attachments/" in s:
            continue
        files.append(p)

    if not files:
        return []

    selected: set[int] = set()

    def _run(stdscr):
        idx = 0
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
            stdscr.addnstr(0, 0, "Select attachments (Space toggle, Enter confirm, Esc cancel)", w - 1, curses.A_BOLD)

            for row, i in enumerate(range(top, min(len(files), top + visible)), start=1):
                marker = "[x]" if i in selected else "[ ]"
                rel = str(files[i].relative_to(cwd))
                line = f"{marker} {rel}"
                attr = curses.A_REVERSE if i == idx else curses.A_NORMAL
                stdscr.addnstr(row, 0, line, w - 1, attr)

            footer = f"Selected: {len(selected)} / {MAX_ATTACHMENTS}"
            stdscr.addnstr(h - 1, 0, footer, w - 1, curses.A_DIM)
            stdscr.refresh()

            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k"), ord("K")):
                idx = (idx - 1) % len(files)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                idx = (idx + 1) % len(files)
            elif key == 32:
                if idx in selected:
                    selected.remove(idx)
                elif len(selected) < MAX_ATTACHMENTS:
                    selected.add(idx)
            elif key in (10, 13):
                return
            elif key in (27, ord("q"), ord("Q")):
                selected.clear()
                return

    curses.wrapper(_run)
    return [str(files[i]) for i in sorted(selected)]


async def cmd_attach(ctx: CommandContext, args: list[str]) -> None:
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]Session not ready.[/error]")
        return

    queue = ctx.agent.session.pending_attachment_paths

    if args and args[0] in {"--list", "list"}:
        _render_queue(ctx)
        return

    if args and args[0] in {"--clear", "clear"}:
        queue.clear()
        ctx.console.print("[dim]Cleared queued attachments.[/dim]")
        return

    if args and args[0] in {"--remove", "remove"}:
        if len(args) < 2:
            ctx.console.print("[error]Usage: /attach --remove <index>[/error]")
            return
        try:
            idx = int(args[1]) - 1
        except Exception:
            ctx.console.print("[error]Index must be a number.[/error]")
            return
        if idx < 0 or idx >= len(queue):
            ctx.console.print("[error]Invalid attachment index.[/error]")
            return
        removed = Path(queue.pop(idx)).name
        ctx.console.print(f"[dim]Removed attachment: {removed}[/dim]")
        return

    if not args:
        if not (sys.stdin.isatty() and sys.stdout.isatty()) or os.name == "nt":
            ctx.console.print("[dim]Interactive picker unavailable here. Use /attach <path>[/dim]")
            return
        picked = _pick_files_with_curses(ctx.config.cwd)
        if not picked:
            ctx.console.print("[dim]No files selected.[/dim]")
            return
        added = _queue_paths(ctx, picked)
        ctx.console.print(f"[dim]Queued {added} attachment(s).[/dim]")
        _render_queue(ctx)
        return

    added = _queue_paths(ctx, args)
    if added <= 0:
        ctx.console.print("[dim]No new files queued.[/dim]")
    else:
        ctx.console.print(f"[dim]Queued {added} attachment(s).[/dim]")
    _render_queue(ctx)


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/attach",
            description="Queue/list/remove attachments for next message",
            handler=cmd_attach,
        )
    )
