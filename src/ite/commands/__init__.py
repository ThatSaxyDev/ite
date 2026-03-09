"""Command registry framework for the CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ite.config.config import Config
    from ite.agent.agent import Agent
    from ite.ui.tui import TUI

from rich.console import Console


@dataclass
class CommandContext:
    """Everything a command handler needs."""

    config: Config
    agent: Agent | None
    tui: TUI
    console: Console


@dataclass
class Command:
    """A registered CLI command."""

    name: str
    description: str
    handler: Any  # async callable(ctx, args) -> bool
    aliases: list[str] = field(default_factory=list)


class CommandRegistry:
    """Maps command names to handlers and dispatches them."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, command: Command) -> None:
        self._commands[command.name] = command
        for alias in command.aliases:
            self._alias_map[alias] = command.name

    def get(self, name: str) -> Command | None:
        if name in self._commands:
            return self._commands[name]
        canonical = self._alias_map.get(name)
        if canonical:
            return self._commands.get(canonical)
        return None

    def all_commands(self) -> list[Command]:
        return list(self._commands.values())

    async def dispatch(self, command_name: str, args: list[str], ctx: CommandContext) -> bool:
        """Dispatch a command. Returns True if handled."""
        cmd = self.get(command_name)
        if cmd is None:
            ctx.console.print(
                f"[error]Unknown command:[/error] [bold]{command_name}[/bold]  "
                f"[dim]— type [green]/help[/green] for a list of commands[/dim]"
            )
            return True

        await cmd.handler(ctx, args)
        return True


def build_registry() -> CommandRegistry:
    """Build and return the full command registry with all commands."""
    from ite.commands.general import register as register_general
    from ite.commands.branch import register as register_branch
    from ite.commands.model import register as register_model
    from ite.commands.plan import register as register_plan
    from ite.commands.info import register as register_info
    from ite.commands.session import register as register_session
    from ite.commands.subagent import register as register_subagent
    from ite.commands.sandbox import register as register_sandbox
    from ite.commands.attach import register as register_attach

    registry = CommandRegistry()
    register_general(registry)
    register_branch(registry)
    register_model(registry)
    register_plan(registry)
    register_info(registry)
    register_session(registry)
    register_subagent(registry)
    register_sandbox(registry)
    register_attach(registry)
    return registry
