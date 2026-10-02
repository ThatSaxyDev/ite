"""Command registry framework for the CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ite.config.config import Config
    from ite.agent.agent import Agent

from rich.console import Console


@dataclass
class CommandContext:
    """Everything a command handler needs."""

    config: Config
    agent: Agent | None
    tui: Any
    console: Console
    outcome: str = "completed"
    result: str = ""
    evidence_files: list[str] = field(default_factory=list)
    followup_prompt: str | None = None
    assistant_message: str | None = None


@dataclass
class Command:
    """A registered CLI command."""

    name: str
    description: str
    handler: Any  # async callable(ctx, args) -> bool
    aliases: list[str] = field(default_factory=list)
    variants: tuple[tuple[str, str], ...] = ()


class CommandRegistry:
    """Maps command names to handlers and dispatches them."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, command: Command) -> None:
        from ite.commands.help_catalog import COMMAND_VARIANTS

        if not command.variants:
            command.variants = COMMAND_VARIANTS.get(command.name, ())
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
        from ite.agent.learning import learning_command_error

        error = learning_command_error(ctx.agent.session if ctx.agent else None, command_name)
        if error:
            ctx.outcome = "failed"
            ctx.result = error
            ctx.console.print(error, markup=False)
            return True
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
    from ite.commands.publish import register as register_publish
    from ite.commands.model import register as register_model
    from ite.commands.plan import register as register_plan
    from ite.commands.learn import register as register_learn
    from ite.commands.info import register as register_info
    from ite.commands.history import register as register_history
    from ite.commands.todos import register as register_todos
    from ite.commands.aside import register as register_aside
    from ite.commands.session import register as register_session
    from ite.commands.subagent import register as register_subagent
    from ite.commands.sandbox import register as register_sandbox
    from ite.commands.attach import register as register_attach
    from ite.commands.cloud import register as register_cloud
    from ite.commands.skills import register as register_skills
    from ite.commands.remote import register as register_remote
    from ite.commands.hooks import register as register_hooks
    from ite.commands.flow import register as register_flow
    from ite.commands.goal import register as register_goal
    from ite.commands.open_island import register as register_open_island

    from ite.commands.init import register as register_init
    from ite.commands.remind import register as register_remind

    registry = CommandRegistry()
    register_general(registry)
    register_init(registry)  # /init command
    register_remind(registry)  # /remind command
    register_branch(registry)
    register_publish(registry)
    register_model(registry)
    register_plan(registry)
    register_learn(registry)
    register_info(registry)
    register_history(registry)
    register_todos(registry)
    register_aside(registry)
    register_session(registry)
    register_subagent(registry)
    register_sandbox(registry)
    register_attach(registry)
    register_cloud(registry)
    register_skills(registry)
    register_remote(registry)
    register_hooks(registry)
    register_flow(registry)
    register_goal(registry)
    register_open_island(registry)
    return registry
