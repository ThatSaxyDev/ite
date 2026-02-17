from config.config import Config
from pathlib import Path
from config.loader import load_config
import sys
from ui.tui import TUI, get_console
from agent.events import AgentEventType
from agent.agent import Agent
import click
import asyncio

console = get_console()


class CLI:
    def __init__(self, config: Config):
        self.config = config
        self.agent: Agent | None = None
        self.tui = TUI(config=config, console=console)

    async def run_single(self, message: str) -> str | None:
        async with Agent(config=self.config) as agent:
            self.agent = agent
            return await self._process_message(message)

    async def run_interactive(self) -> str | None:
        self.tui.print_welcome(
            model=self.config.model_name,
            cwd=self.config.cwd,
            commands=["/help", "/subagent", "/config", "/model", "/exit"],
        )
        async with Agent(
            config=self.config,
            confirmation_callback=self.tui.handle_confirmation,
        ) as agent:
            self.agent = agent

            while True:
                try:
                    user_input = console.input("\n[user]>[/user] ").strip()
                    if not user_input:
                        continue

                    if await self._handle_command(user_input):
                        continue

                    await self._process_message(user_input)
                except KeyboardInterrupt:
                    console.print("\n[dim]Use /exit or /quit to quit[/dim]")
                except EOFError:
                    break

        console.print("\n[dim]Bye![/dim]")

    async def _handle_command(self, user_input: str) -> bool:
        """Handle CLI commands. Returns True if handled, False if it should be sent to agent."""
        if not user_input.startswith("/"):
            return False

        parts = user_input.split()
        command = parts[0].lower()
        args = parts[1:]

        from commands import build_registry, CommandContext

        registry = build_registry()
        ctx = CommandContext(
            config=self.config,
            agent=self.agent,
            tui=self.tui,
            console=console,
        )
        return await registry.dispatch(command, args, ctx)

    def _get_tool_kind(self, tool_name: str) -> str | None:
        tool = self.agent.session.tool_registry.get(tool_name)
        if not tool:
            return None
        return tool.kind.value

    async def _process_message(self, message: str) -> str | None:
        if not self.agent:
            return None

        assistant_streaming = False
        final_response: str | None = None

        # Start spinner while waiting for LLM
        self.tui.start_spinner("Running...")

        async for event in self.agent.run(message):
            # print(event)
            if event.type == AgentEventType.TEXT_DELTA:
                content = event.data.get("content", "")
                if not assistant_streaming:
                    self.tui.stop_spinner()
                    self.tui.begin_assistant()
                    assistant_streaming = True
                self.tui.stream_assistant_delta(content)

            elif event.type == AgentEventType.TEXT_COMPLETE:
                final_response = event.data.get("content")
                if assistant_streaming:
                    self.tui.end_assistant()
                    assistant_streaming = False

            elif event.type == AgentEventType.AGENT_ERROR:
                self.tui.stop_spinner()
                error = event.data.get("error", "Unknown error")
                console.print(f"\n[error]Error: {error}[/error]")

            elif event.type == AgentEventType.TOOL_CALL_START:
                self.tui.stop_spinner()
                tool_name = event.data.get("name", "Unknown tool")
                tool_kind = self._get_tool_kind(tool_name)
                self.tui.tool_call_start(
                    event.data.get("call_id", ""),
                    tool_name,
                    tool_kind,
                    event.data.get("arguments", {}),
                )
                self.tui.start_spinner("Running")

            elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
                self.tui.stop_spinner()
                tool_name = event.data.get("name", "Unknown tool")
                tool_kind = self._get_tool_kind(tool_name)
                self.tui.tool_call_complete(
                    call_id=event.data.get("call_id", ""),
                    name=tool_name,
                    tool_kind=tool_kind,
                    success=event.data.get("success", False),
                    output=event.data.get("output", ""),
                    error=event.data.get("error"),
                    metadata=event.data.get("metadata"),
                    diff=event.data.get("diff"),
                    truncated=event.data.get("truncated", False),
                    exit_code=event.data.get("exit_code"),
                )
                # Restart spinner while LLM processes tool results
                self.tui.start_spinner("Running...")

            elif event.type == AgentEventType.LOOP_DETECTED:
                self.tui.stop_spinner()
                message = event.data.get("message", "Repetitive pattern detected")
                console.print(
                    f"\n[bold yellow]⚠ Loop detected:[/bold yellow] [yellow]{message}[/yellow]"
                )
                self.tui.start_spinner("Recovering...")

        self.tui.stop_spinner()
        return final_response


@click.command()
@click.argument("prompt", required=False)
@click.option(
    "--cwd",
    "-c",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Current working directory",
)
def main(
    prompt: str | None,
    cwd: Path | None,
):

    try:
        config = load_config(cwd=cwd)
    except Exception as e:
        console.print(f"[error]Configuration error: {e}[/error]")
        sys.exit(1)

    errors = config.validate()
    if errors:
        for error in errors:
            console.print(f"[error]{error}[/error]")
        sys.exit(1)

    cli = CLI(config)

    if prompt:
        result = asyncio.run(cli.run_single(prompt))
        if result is None:
            sys.exit(1)
    else:
        asyncio.run(cli.run_interactive())


main()
