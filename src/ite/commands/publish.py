"""Publish commands: /publish for configuring a remote and pushing the current branch."""

from __future__ import annotations

from pathlib import Path

from ite.commands import Command, CommandContext, CommandRegistry
from ite.git.branches import is_git_repo
from ite.git.remotes import upsert_remote
from ite.git.working_tree import git_outbound_state, push_current_branch


def _publish_usage() -> str:
    return (
        "Usage: /publish\n"
        "       /publish <remote-url>\n"
        "       /publish <remote-name> <remote-url>"
    )


def _parse_publish_args(args: list[str]) -> tuple[str | None, str | None] | None:
    if not args:
        return None, None
    if len(args) == 1:
        return "origin", args[0]
    if len(args) == 2:
        return args[0], args[1]
    return None


async def cmd_publish(ctx: CommandContext, args: list[str]) -> None:
    cwd = Path(ctx.config.cwd).resolve()
    if not is_git_repo(cwd):
        ctx.console.print("[error]Not a git repository in current workspace.[/error]")
        return

    parsed = _parse_publish_args(args)
    if parsed is None:
        ctx.console.print(f"[error]{_publish_usage()}[/error]")
        return

    remote_name, remote_url = parsed
    if remote_url:
        configured = upsert_remote(cwd, remote_name or "origin", remote_url)
        if not configured.ok:
            ctx.console.print(f"[error]{configured.message}[/error]")
            return
        ctx.console.print(f"[success]{configured.message}[/success]")

    outbound = git_outbound_state(cwd)
    if outbound is None:
        ctx.console.print("[error]Cannot publish from a detached HEAD.[/error]")
        return
    if not outbound.has_remote:
        ctx.console.print("[error]No remote configured for this repository.[/error]")
        ctx.console.print(f"[dim]{_publish_usage()}[/dim]")
        return

    result = push_current_branch(cwd)
    if not result.ok:
        ctx.console.print(f"[error]{result.message}[/error]")
        return
    ctx.console.print(f"[success]{result.message}[/success]")


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/publish",
            description="Publish the current branch, optionally configuring a remote first",
            handler=cmd_publish,
        )
    )
