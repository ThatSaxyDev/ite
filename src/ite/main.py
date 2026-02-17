from config.config import Config
from pathlib import Path
from config.loader import load_config
import logging
import sys
from ui.tui import TUI, get_console
from agent.events import AgentEventType
from agent.agent import Agent
from agent.session_manager import SessionSnapshot, SessionManager
import click
import asyncio
import signal

logger = logging.getLogger(__name__)
console = get_console()


class CLI:
    def __init__(self, config: Config):
        self.config = config
        self.agent: Agent | None = None
        self.tui = TUI(config=config, console=console)


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

            try:
                while True:
                    try:
                        user_input = console.input("\n[user]>[/user] ").strip()
                        if not user_input:
                            continue

                        if await self._handle_command(user_input):
                            continue

                        # Run agent in a cancellable task with SIGINT → cancel
                        response_task = asyncio.create_task(
                            self._process_message(user_input)
                        )

                        loop = asyncio.get_running_loop()
                        loop.add_signal_handler(signal.SIGINT, response_task.cancel)

                        was_interrupted = False
                        try:
                            await response_task
                        except asyncio.CancelledError:
                            was_interrupted = True
                            self.tui.stop_spinner()
                            self.tui.end_assistant()
                            console.print("\n[grey50]⏹ Response interrupted[/grey50]")
                        finally:
                            # Restore default so Ctrl+C works at the prompt
                            loop.remove_signal_handler(signal.SIGINT)

                        # ── Flight recorder: auto-save after every exchange ──
                        if not was_interrupted:
                            await self._auto_save()

                    except KeyboardInterrupt:
                        console.print()  # clean line after ^C at prompt
                    except EOFError:
                        break
            finally:
                # Crash safety: save on any unexpected exit
                self._auto_save_sync()

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

    async def _auto_save(self) -> None:
        """Flight recorder: silently save session state after every exchange."""
        if not self.agent or not self.agent.session:
            return
        if self.agent.session.turn_count == 0:
            return  # Don't save empty sessions

        try:
            session = self.agent.session
            session_manager = SessionManager()

            # Generate smart name on first exchange
            if session.name is None and session.turn_count > 0:
                session.name = await self._generate_session_name(session)

            snapshot = SessionSnapshot(
                session_id=session.session_id,
                name=session.name,
                created_at=session.created_at,
                updated_at=session.updated_at,
                turn_count=session.turn_count,
                messages=session.context_manager.get_messages(),
                total_usage=session.context_manager.total_usage,
            )
            session_manager.save_session(snapshot)
            # console.print(
            #     f"[dim]  💾 Session auto-saved · {session.turn_count} turns · {session.name or session.session_id[:8]}[/dim]"
            # )

            # Auto-checkpoint every 5 turns
            if session.turn_count > 0 and session.turn_count % 5 == 0:
                cp_id = session_manager.save_checkpoint(snapshot)
                console.print(f"[dim]  📌 Auto-checkpoint · {cp_id[:20]}…[/dim]")

        except Exception as e:
            logger.warning("Auto-save failed: %s", e)

    def _auto_save_sync(self) -> None:
        """Synchronous fallback for auto-save in finally blocks."""
        if not self.agent or not self.agent.session:
            return
        if self.agent.session.turn_count == 0:
            return  # Don't save empty sessions

        try:
            session = self.agent.session
            session_manager = SessionManager()
            snapshot = SessionSnapshot(
                session_id=session.session_id,
                name=session.name,
                created_at=session.created_at,
                updated_at=session.updated_at,
                turn_count=session.turn_count,
                messages=session.context_manager.get_messages(),
                total_usage=session.context_manager.total_usage,
            )
            session_manager.save_session(snapshot)
        except Exception:
            pass

    async def _generate_session_name(self, session) -> str:
        """Use the LLM to generate a concise session title from the first exchange."""
        first_user = ""
        try:
            # Get the first user message and assistant response
            messages = session.context_manager.get_messages()
            first_user = ""
            first_assistant = ""
            for msg in messages:
                if msg.get("role") == "user" and not first_user:
                    first_user = msg.get("content", "")[:200]
                elif (
                    msg.get("role") == "assistant"
                    and first_user
                    and not first_assistant
                ):
                    first_assistant = msg.get("content", "")[:200]
                    break

            if not first_user:
                return "New Session"

            naming_messages = [
                {
                    "role": "user",
                    "content": (
                        "Generate a concise 3-6 word title for this conversation. "
                        "Reply with ONLY the title text, nothing else. No quotes, no punctuation at the end.\n\n"
                        f"User: {first_user}\n"
                        + (f"Assistant: {first_assistant}" if first_assistant else "")
                    ),
                }
            ]

            title = ""
            async for event in session.client.chat_completion(
                naming_messages, tools=None, stream=True
            ):
                if event.text_delta and event.text_delta.content:
                    title += event.text_delta.content

            title = title.strip()[:60]
            if title:
                return title

        except Exception as e:
            logger.warning("Session naming failed: %s", e)

        # Fallback: first sentence of user message, max 60 chars
        first_sentence = first_user.split(".")[0].split("?")[0].split("!")[0][:60]
        return first_sentence.strip() or "New Session"

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
@click.option(
    "--cwd",
    "-c",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Current working directory",
)
@click.option("--model", "-m", help="Model name to use")
@click.option("--api-key", "-k", help="API key for the LLM provider")
@click.option("--base-url", "-u", help="Base URL for the OpenAI-compatible API")
def main(
    cwd: Path | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
):

    try:
        config = load_config(cwd=cwd)
    except Exception as e:
        console.print(f"[error]Configuration error: {e}[/error]")
        sys.exit(1)

    # CLI flags override everything
    if api_key:
        config.api_key = api_key
    if base_url:
        config.base_url = base_url
    if model:
        config.model.name = model

    # If credentials are still missing, run the setup wizard
    if config.needs_setup:
        from config.setup import run_setup_wizard

        config = run_setup_wizard(console, config)

    errors = config.validate()
    if errors:
        # Filter out the api_key error since wizard should have handled it
        real_errors = [e for e in errors if e != "missing_api_key"]
        if real_errors:
            for error in real_errors:
                console.print(f"[error]{error}[/error]")
            sys.exit(1)

    cli = CLI(config)
    asyncio.run(cli.run_interactive())


main()
