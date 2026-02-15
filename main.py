from config.config import Config
from pathlib import Path
from config.loader import load_config
import sys
from ui.tui import TUI, get_console
from rich.panel import Panel
from rich.table import Table
from rich import box
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
        async with Agent(config=self.config) as agent:
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
                    console.print("\n[dim]Use /exit to quit[/dim]")
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

        if command == "/exit":
            sys.exit(0)

        elif command == "/help":
            console.print(
                Panel(
                    """[bold]Commands:[/bold]
  /subagent list   List available subagents
  /subagent create Create a new subagent
  /subagent delete Delete a subagent
  /model           Show current model
  /config          Show current configuration
  /exit            Exit the application""",
                    title="Help",
                    border_style="cyan",
                )
            )
            return True

        elif command == "/model":
            console.print(
                f"[bold cyan]Current model:[/bold cyan] {self.config.model_name}"
            )
            return True

        elif command == "/config":
            console.print(f"[bold]CWD:[/bold] {self.config.cwd}")
            console.print(f"[bold]Model:[/bold] {self.config.model_name}")
            return True

        elif command == "/subagent" or command == "/subagents":
            if not args:
                console.print("[error]Usage: /subagent <list|create|delete>[/error]")
                return True

            sub_cmd = args[0].lower()

            if sub_cmd == "list":
                self._list_subagents()
            elif sub_cmd == "create":
                self._create_subagent_interactive()
            elif sub_cmd == "delete":
                if len(args) < 2:
                    console.print("[error]Usage: /subagent delete <name>[/error]")
                else:
                    self._delete_subagent(args[1])
            else:
                console.print(f"[error]Unknown subagent command: {sub_cmd}[/error]")

            return True

        return False

    def _list_subagents(self):
        from tools.subagent import SubagentTool

        tools = self.agent.session.tool_registry.get_tools()
        subagents = [t for t in tools if isinstance(t, SubagentTool)]

        if not subagents:
            console.print("[dim]No subagents found.[/dim]")
            return

        table = Table(title="Available Subagents", box=box.SIMPLE)
        table.add_column("Name", style="bold cyan")
        table.add_column("Description")
        table.add_column("Source", style="dim")

        for sa in subagents:
            # Check if it's user-defined (dynamically loaded) vs built-in
            # We can infer this by checking if it overrides a default or is extra
            # For now just list them
            table.add_row(sa.definition.name, sa.definition.description, "Active")

        console.print(table)

    def _create_subagent_interactive(self):
        console.print(Panel("Create a new Subagent", style="bold green"))

        while True:
            name = console.input("[bold]Name (no spaces):[/bold] ").strip()
            if " " in name:
                console.print("[error]Name cannot contain spaces[/error]")
                continue
            if name:
                break

        description = console.input("[bold]Description:[/bold] ").strip()

        console.print("[bold]Goal/System Prompt (press Enter twice to finish):[/bold]")
        lines = []
        while True:
            line = console.input()
            if not line and (not lines or not lines[-1]):
                break
            lines.append(line)
        goal_prompt = "\n".join(lines).strip()

        # Tools
        console.print(
            "[bold]Allowed Tools (comma separated, leave empty for all):[/bold]"
        )
        all_tools = [t.name for t in self.agent.session.tool_registry.get_tools()]
        console.print(f"[dim]Available: {', '.join(all_tools)}[/dim]")

        tools_input = console.input("> ").strip()
        allowed_tools = (
            [t.strip() for t in tools_input.split(",")] if tools_input else None
        )

        # Confirm
        console.print(
            Panel(
                f"[bold]Name:[/bold] {name}\n"
                f"[bold]Description:[/bold] {description}\n"
                f"[bold]Goal Prompt:[/bold]\n{goal_prompt}\n\n"
                f"[bold]Tools:[/bold] {allowed_tools or 'All'}",
                title="Preview",
            )
        )
        if console.input("Save? [Y/n] ").lower() == "n":
            console.print("[dim]Cancelled[/dim]")
            return

        # Save to .ite/subagents/
        subagents_dir = self.config.cwd / ".ite" / "subagents"
        subagents_dir.mkdir(parents=True, exist_ok=True)
        file_path = subagents_dir / f"{name}.toml"

        # Generate TOML content
        tools_list_str = str(allowed_tools).replace("'", '"') if allowed_tools else "[]"
        if not allowed_tools:
            # If allow list is empty/None in our object, we might want to default to something safe
            # or just comment it out. For now let's write what they requested.
            pass

        toml_content = f"""name = "{name}"
description = "{description}"
allowed_tools = {tools_list_str}

goal_prompt = \"\"\"
{goal_prompt}
\"\"\"
"""

        try:
            file_path.write_text(toml_content, encoding="utf-8")
            console.print(f"[success]Subagent saved to {file_path}[/success]")
            console.print(
                "[dim info]Restart the agent to load the new subagent.[/dim info]"
            )
        except Exception as e:
            console.print(f"[error]Failed to save subagent: {e}[/error]")

    def _delete_subagent(self, name: str):
        # Look in .ite/subagents
        subagents_dir = self.config.cwd / ".ite" / "subagents"
        file_path = subagents_dir / f"{name}.toml"

        if file_path.exists():
            try:
                file_path.unlink()
                console.print(f"[success]Deleted subagent {name}[/success]")
                console.print(
                    "[dim info]Restart the agent to apply changes.[/dim info]"
                )
            except Exception as e:
                console.print(f"[error]Failed to delete: {e}[/error]")
        else:
            console.print(
                f"[error]Subagent configuration not found at {file_path}[/error]"
            )

    def _get_tool_kind(self, tool_name: str) -> str | None:
        tool_kind = None
        tool = self.agent.session.tool_registry.get(tool_name)
        if not tool:
            tool_kind = None

        tool_kind = tool.kind.value
        return tool_kind

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
