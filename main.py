from agent.session import Session
from agent.session_manager import SessionSnapshot
from agent.session_manager import SessionManager
from config.config import Config
from pathlib import Path
from config.loader import load_config
from datetime import datetime
import sys
from ui.tui import TUI, get_console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
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

        if command == "/ite":
            self.tui.print_welcome(
                model=self.config.model_name,
                cwd=self.config.cwd,
            )
            return True

        elif command == "/exit" or command == "/quit":
            console.print()
            console.print(
                Text.assemble(
                    ("👋 ", ""),
                    ("Goodbye! ", "bold bright_white"),
                    ("See you next time.", "code"),
                )
            )
            console.print()
            sys.exit(0)

        elif command == "/help":
            help_md = Markdown(
                "- `/help` — Show this help\n"
                "- `/exit` or `/quit` — Exit the agent\n"
                "- `/clear` — Clear conversation history\n"
                "- `/config` — Show current configuration\n"
                "- `/model` — Show current model\n"
                "- `/model <name>` — Change the model\n"
                "- `/approval <mode>` — Change approval mode\n"
                "- `/stats` — Show session statistics\n"
                "- `/tools` — List available tools\n"
                "- `/mcp` — Show MCP server status\n"
                "- `/save` — Save current session\n"
                "- `/checkpoint [name]` — Create a checkpoint\n"
                "- `/checkpoints` — List available checkpoints\n"
                "- `/restore <checkpoint_id>` — Restore a checkpoint\n"
                "- `/sessions` — List saved sessions\n"
                "- `/resume <session_id>` — Resume a saved session\n\n"
                "- `/subagent list` — List all available subagents\n"
                "- `/subagent create` — Interactively create a new subagent\n"
                "- `/subagent delete <name>` — Delete a subagent by name\n\n"
                # "---\n\n"
                # "### Tips\n\n"
                # "- Just type your message to chat with the agent\n"
                # "- The agent can read, write, and execute code\n"
                # "- Some operations require approval (can be configured)\n"
            )

            title = Text.assemble(
                ("⌨  ", ""),
                ("Commands", "bold bright_white"),
            )

            console.print()
            console.print(
                Panel(
                    help_md,
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return True

        elif command == "/model":
            if args:
                old_model = self.config.model_name
                new_model = args[0]
                self.config.model_name = new_model
                title = Text.assemble(
                    ("🤖 ", ""), ("Model Changed", "bold bright_white")
                )
                console.print()
                console.print(
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
                console.print()
                console.print(
                    Panel(
                        Text.assemble(
                            ("Active model: ", "code"),
                            (self.config.model_name, "bold cyan"),
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
            return True

        elif command == "/config":
            title = Text.assemble(
                ("⚙ ", ""), ("Current Configuration", "bold bright_white")
            )
            config_table = Table.grid(padding=(0, 2))
            config_table.add_column(style="code", justify="right", min_width=8)
            config_table.add_column(style="bold white")
            cwd_display = str(self.config.cwd).replace(str(Path.home()), "~")
            config_table.add_row(
                Text("Model", style="muted"),
                Text(self.config.model_name, style="cyan bold"),
            )
            config_table.add_row(
                Text("Current Dir", style="muted"),
                Text(cwd_display, style="info"),
            )
            config_table.add_row(
                Text("Approval", style="muted"),
                Text(self.config.approval.value, style="info"),
            )
            config_table.add_row(
                Text("Max Turns", style="muted"),
                Text(str(self.config.max_turns), style="info"),
            )
            config_table.add_row(
                Text("Hooks Enabled", style="muted"),
                Text(str(self.config.hooks_enabled), style="info"),
            )

            console.print()
            console.print(
                Panel(
                    config_table,
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return True

        elif command == "/approval":
            from config.config import ApprovalPolicy

            valid_modes = [p.value for p in ApprovalPolicy]

            if args and args[0].lower() == "help":
                mode_descriptions = {
                    "on_request": "Ask before every mutating action",
                    "on_failure": "Auto-approve, ask only on failure",
                    "auto": "Auto-approve all safe operations",
                    "auto_edit": "Auto-approve edits, confirm commands",
                    "never": "Only allow safe commands, reject all else",
                    "yolo": "Approve everything — no guardrails",
                }
                lines = Text()
                for mode in ApprovalPolicy:
                    marker = " ← current" if mode == self.config.approval else ""
                    lines.append(
                        f"  {mode.value}",
                        style="bold cyan"
                        if mode == self.config.approval
                        else "green bold",
                    )
                    lines.append(f"  {mode_descriptions[mode.value]}", style="dim")
                    if marker:
                        lines.append(marker, style="yellow")
                    lines.append("\n")

                title = Text.assemble(
                    ("🛡 ", ""), ("Approval Modes", "bold bright_white")
                )
                console.print()
                console.print(
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
                    console.print(
                        f"[error]Invalid approval mode:[/error] [bold]{args[0]}[/bold]\n"
                        f"[dim]Valid modes: [green]{', '.join(valid_modes)}[/green] — try [green]/approval help[/green][/dim]"
                    )
                    return True

                old_approval = self.config.approval.value
                self.config.approval = ApprovalPolicy(new_approval)
                title = Text.assemble(
                    ("🛡 ", ""), ("Approval Changed", "bold bright_white")
                )
                console.print()
                console.print(
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
                title = Text.assemble(("🛡 ", ""), ("Approval", "bold bright_white"))
                console.print()
                console.print(
                    Panel(
                        Text.assemble(
                            ("Active approval: ", "code"),
                            (self.config.approval.value, "bold cyan"),
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
            return True

        elif command == "/stats":
            stats = self.agent.session.get_stats()
            title = Text.assemble(
                ("📊 ", ""), ("Session Statistics", "bold bright_white")
            )
            console.print()
            console.print(
                Panel(
                    Text.assemble(
                        ("Session ID: ", "code"),
                        (stats["session_id"], "bold cyan"),
                        ("\nTurn Count: ", "code"),
                        (str(stats["turn_count"]), "bold cyan"),
                        ("\nMessage Count: ", "code"),
                        (str(stats["message_count"]), "bold cyan"),
                        ("\nToken Usage: ", "code"),
                        (str(stats["token_usage"]), "bold cyan"),
                        ("\nTools Enabled: ", "code"),
                        (str(stats["tools_enabled"]), "bold cyan"),
                        ("\nMCP Servers: ", "code"),
                        (str(stats["mcp_servers"]), "bold cyan"),
                    ),
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return True

        elif command == "/tools":
            tools = self.agent.session.tool_registry.get_tools()
            title = Text.assemble(
                ("🔧 ", ""), (f"Available Tools ({len(tools)})", "bold bright_white")
            )
            tools_table = Table.grid(padding=(0, 2))
            tools_table.add_column(style="code", justify="right", min_width=4)
            tools_table.add_column(style="green bold", min_width=20)
            tools_table.add_column(style="code")
            for i, tool in enumerate(tools, 1):
                desc = getattr(tool, "description", "")
                if desc and len(desc) > 60:
                    desc = desc[:57] + "..."
                tools_table.add_row(
                    Text(str(i), style="code"),
                    Text(tool.name, style="cyan bold"),
                    Text(desc, style="code"),
                )
            console.print()
            console.print(
                Panel(
                    tools_table,
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return True

        elif command == "/mcp":
            mcp_mgr = self.agent.session.mcp_manager
            servers = mcp_mgr.get_all_servers()
            title = Text.assemble(
                ("🔌 ", ""), (f"MCP Servers ({len(servers)})", "bold bright_white")
            )
            if not servers:
                console.print()
                console.print(
                    Panel(
                        Text.assemble(
                            ("No MCP servers configured", "dim"),
                            ("\n\n", ""),
                            ("Add servers in ", "code"),
                            (".ite/config.toml", "green bold"),
                            (" under ", "code"),
                            ("[mcp_servers]", "green bold"),
                        ),
                        title=title,
                        title_align="left",
                        border_style="cyan",
                        box=box.ROUNDED,
                        padding=(1, 2),
                    )
                )
            else:
                mcp_table = Table.grid(padding=(0, 2))
                mcp_table.add_column(style="cyan bold", min_width=16)
                mcp_table.add_column(min_width=12)
                mcp_table.add_column(style="code")
                for server in servers:
                    is_connected = server["status"] == "connected"
                    status_style = "green bold" if is_connected else "red bold"
                    mcp_table.add_row(
                        Text(server["name"], style="cyan bold"),
                        Text(f"● {server['status']}", style=status_style),
                        Text(f"[{server['tools']} tools]", style="code"),
                    )
                console.print()
                console.print(
                    Panel(
                        mcp_table,
                        title=title,
                        title_align="left",
                        border_style="cyan",
                        box=box.ROUNDED,
                        padding=(1, 2),
                    )
                )
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

        elif command == "/clear":
            self.agent.session.context_manager.clear()
            self.agent.session.loop_detector.clear()
            title = Text.assemble(("🗑  ", ""), ("Cleared", "bold bright_white"))
            console.print()
            console.print(
                Panel(
                    Text.assemble(
                        ("Conversation cleared", "bold cyan"),
                    ),
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return True

        elif command == "/save":
            session_manager = SessionManager()
            session_snapshot = SessionSnapshot(
                session_id=self.agent.session.session_id,
                created_at=self.agent.session.created_at,
                updated_at=self.agent.session.updated_at,
                turn_count=self.agent.session.turn_count,
                messages=self.agent.session.context_manager.get_messages(),
                total_usage=self.agent.session.context_manager.total_usage,
            )
            session_manager.save_session(session_snapshot)
            title = Text.assemble(("💾  ", ""), ("Session saved", "bold bright_white"))
            console.print()
            console.print(
                Panel(
                    Text.assemble(
                        (
                            f"Session: {self.agent.session.session_id}",
                            "bold cyan",
                        ),
                    ),
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return True

        elif command == "/sessions":
            session_manager = SessionManager()
            sessions = session_manager.list_sessions()
            if not sessions:
                console.print("[dim]No sessions found.[/dim]")
                return True

            table = Table(title="Available Sessions", box=box.SIMPLE)
            table.add_column("Session ID", style="bold cyan")
            table.add_column("Created At")
            table.add_column("Updated At")
            table.add_column("Turn Count")

            for session in sessions:
                created = datetime.fromisoformat(session["created_at"])
                updated = datetime.fromisoformat(session["updated_at"])
                table.add_row(
                    session["session_id"],
                    created.strftime("%b %d, %Y · %I:%M %p"),
                    updated.strftime("%b %d, %Y · %I:%M %p"),
                    str(session["turn_count"]),
                )

            console.print(table)
            return True

        elif command == "/resume":
            if not args:
                console.print(
                    "[error]Missing session ID.[/error]  [dim]Run [green]/sessions[/green] to list saved sessions, then use [green]/resume <session_id>[/green][/dim]"
                )
                return True

            session_id = args[0]
            session_manager = SessionManager()
            snapshot = session_manager.load_session(session_id)

            if snapshot is None:
                console.print(
                    f"[error]Session not found:[/error] [bold]{session_id}[/bold]. [dim]Run [green]/sessions[/green] to list saved sessions, then use [green]/resume <session_id>[/green][/dim]"
                )
                return True
            else:
                session = Session(
                    config=self.config,
                )
                session.session_id = snapshot.session_id
                session.created_at = snapshot.created_at
                session.updated_at = snapshot.updated_at
                session.turn_count = snapshot.turn_count

                await self.agent.session.client.close()
                await self.agent.session.mcp_manager.shutdown()
                await session.initialize()

                session.context_manager.set_messages(snapshot.messages)
                session.context_manager.total_usage = snapshot.total_usage
                self.agent.session = session

            title = Text.assemble(("💾  ", ""), ("Resumed", "bold bright_white"))
            console.print()
            console.print(
                Panel(
                    Text.assemble(
                        (
                            f"Session loaded: {session_id}",
                            "bold cyan",
                        ),
                    ),
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return True

        elif command == "/checkpoint":
            session_manager = SessionManager()
            session_snapshot = SessionSnapshot(
                session_id=self.agent.session.session_id,
                created_at=self.agent.session.created_at,
                updated_at=self.agent.session.updated_at,
                turn_count=self.agent.session.turn_count,
                messages=self.agent.session.context_manager.get_messages(),
                total_usage=self.agent.session.context_manager.total_usage,
            )
            checkpoint_id = session_manager.save_checkpoint(session_snapshot)
            title = Text.assemble(
                ("💾  ", ""), ("Checkpoint created", "bold bright_white")
            )
            console.print()
            console.print(
                Panel(
                    Text.assemble(
                        (
                            f"Checkpoint: {checkpoint_id}",
                            "bold cyan",
                        ),
                    ),
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return True

        elif command == "/restore":
            if not args:
                console.print(
                    "[error]Missing checkpoint ID.[/error]  [dim]Use [green]/restore <checkpoint_id>[/green] to restore a checkpoint.[/dim]"
                )
                return True

            checkpoint_id = args[0]
            session_manager = SessionManager()
            snapshot = session_manager.load_checkpoint(checkpoint_id)

            if snapshot is None:
                console.print(
                    f"[error]Checkpoint not found:[/error] [bold]{checkpoint_id}[/bold]"
                )
                return True
            else:
                session = Session(
                    config=self.config,
                )
                session.session_id = snapshot.session_id
                session.created_at = snapshot.created_at
                session.updated_at = snapshot.updated_at
                session.turn_count = snapshot.turn_count

                await self.agent.session.client.close()
                await self.agent.session.mcp_manager.shutdown()
                await session.initialize()

                session.context_manager.set_messages(snapshot.messages)
                session.context_manager.total_usage = snapshot.total_usage
                self.agent.session = session

            title = Text.assemble(
                ("💾  ", ""), ("Checkpoint Restored", "bold bright_white")
            )
            console.print()
            console.print(
                Panel(
                    Text.assemble(
                        (
                            f"Checkpoint: {checkpoint_id}",
                            "bold cyan",
                        ),
                    ),
                    title=title,
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )
            return True

        console.print(
            f"[error]Unknown command:[/error] [bold]{command}[/bold]  [dim]— type [green]/help[/green] for a list of commands[/dim]"
        )
        return True

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
