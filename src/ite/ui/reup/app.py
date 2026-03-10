from __future__ import annotations

import asyncio
import io
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static, TextArea

from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.agent.session import Session
from ite.agent.session_manager import SessionManager, SessionSnapshot
from ite.commands import build_registry
from ite.config.config import Config

from .adapters.registry import build_command_context


class ConfirmModal(ModalScreen[bool]):
    def __init__(
        self,
        title: str,
        body: str,
        yes_label: str = "Approve",
        no_label: str = "Deny",
    ) -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._yes = yes_label
        self._no = no_label

    def compose(self) -> ComposeResult:
        with Container(classes="modal"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._body, classes="modal-body")
            with Horizontal(classes="modal-actions"):
                yield Button(self._no, id="no", variant="default")
                yield Button(self._yes, id="yes", variant="success")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class PlanQuestionModal(ModalScreen[dict[str, Any]]):
    def __init__(
        self,
        *,
        question: str,
        options: list[str],
        recommended_index: int | None,
        allow_free_text: bool,
    ) -> None:
        super().__init__()
        self._question = question
        self._options = options
        self._recommended_index = recommended_index
        self._allow_free_text = allow_free_text

    def compose(self) -> ComposeResult:
        with Container(classes="modal"):
            yield Label("Planning Question", classes="modal-title")
            yield Static(self._question, classes="modal-body")
            with Vertical(classes="modal-options"):
                for idx, option in enumerate(self._options):
                    rec = " (recommended)" if self._recommended_index == idx else ""
                    yield Button(
                        f"{idx + 1}. {option}{rec}",
                        id=f"opt-{idx}",
                        variant="primary" if self._recommended_index == idx else "default",
                    )
            if self._allow_free_text:
                yield Input(placeholder="Custom answer", id="custom-input")
                yield Button("Submit Custom", id="custom-submit", variant="warning")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("opt-"):
            idx = int(bid.split("-", 1)[1])
            option = self._options[idx]
            self.dismiss(
                {
                    "selected_option": option,
                    "free_text": "",
                    "selected_index": idx,
                }
            )
            return

        if bid == "custom-submit":
            custom_input = self.query_one("#custom-input", Input)
            value = custom_input.value.strip()
            self.dismiss(
                {
                    "selected_option": "",
                    "free_text": value,
                    "selected_index": None,
                }
            )


class SessionResumeModal(ModalScreen[str | None]):
    """Toad-style resume modal with a session table."""

    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, sessions: list[dict[str, Any]]) -> None:
        super().__init__()
        self._sessions = sessions
        self._session_ids: list[str] = []

    def compose(self) -> ComposeResult:
        with Container(classes="modal"):
            yield Label("Resume Session", classes="modal-title")
            with Container(classes="modal-list"):
                yield DataTable(id="sessions", cursor_type="row")
            with Horizontal(classes="modal-actions"):
                yield Button("Resume", id="resume", variant="success", disabled=True)
                yield Button("Cancel", id="cancel", variant="default")

    async def on_mount(self) -> None:
        table = self.query_one("#sessions", DataTable)
        table.add_columns("Name", "Session", "Updated", "Turns")

        self._session_ids = []
        for session in self._sessions:
            sid = str(session.get("session_id", ""))
            name = str(session.get("name") or sid)
            updated = str(session.get("updated_at", ""))
            turns = str(session.get("turn_count", 0))
            try:
                updated = datetime.fromisoformat(updated).strftime("%b %d · %I:%M %p")
            except Exception:
                pass
            self._session_ids.append(sid)
            table.add_row(name, f"{sid[:8]}…", updated, turns)

    @on(DataTable.RowHighlighted, "#sessions")
    def on_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        self.query_one("#resume", Button).disabled = False

    @on(DataTable.RowSelected, "#sessions")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.cursor_row < 0 or event.cursor_row >= len(self._session_ids):
            return
        self.dismiss(self._session_ids[event.cursor_row])

    @on(Button.Pressed, "#resume")
    def on_resume_pressed(self, _event: Button.Pressed) -> None:
        table = self.query_one("#sessions", DataTable)
        row = table.cursor_row
        if row < 0 or row >= len(self._session_ids):
            return
        self.dismiss(self._session_ids[row])

    @on(Button.Pressed, "#cancel")
    def on_cancel_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class ReupTUIAdapter:
    """Adapter for existing command handlers expecting a TUI-like object."""

    def __init__(self, app: "ReupApp") -> None:
        self._app = app

    @property
    def cwd(self) -> Path:
        return self._app.config.cwd

    @cwd.setter
    def cwd(self, value: Path) -> None:
        self._app.config.cwd = Path(value)
        self._app.refresh_header()

    def print_welcome(
        self,
        model: str = "",
        cwd: str = "",
        commands: list[str] | None = None,
        version: str = "0.0.3",
    ) -> None:
        msg = f"ITE Reup ready\nModel: {model or 'not set'}\nWorkspace: {cwd}\nVersion: {version}"
        if commands:
            msg += "\nCommands: " + ", ".join(commands)
        self._app.post_system("Welcome", msg)

    def tool_call_start(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        arguments: dict[str, Any],
    ) -> None:
        self._app.run_worker(
            self._app.add_tool_call_start(
                call_id=call_id,
                name=name,
                tool_kind=tool_kind,
                arguments=arguments,
            ),
            exclusive=False,
        )

    def tool_call_complete(
        self,
        call_id: str,
        name: str,
        tool_kind: str | None,
        success: bool,
        output: str,
        error: str | None,
        metadata: dict[str, Any] | None,
        diff: str | None,
        truncated: bool,
        exit_code: int | None,
    ) -> None:
        self._app.run_worker(
            self._app.update_tool_call(
                call_id=call_id,
                name=name,
                tool_kind=tool_kind,
                success=success,
                output=output,
                error=error,
                metadata=metadata,
                diff=diff,
                truncated=truncated,
                exit_code=exit_code,
            ),
            exclusive=False,
        )

    async def _start_new_thread(self) -> None:
        await self._app.start_new_thread()


class ReupApp(App):
    CSS_PATH = "reup.tcss"
    BINDINGS = [
        Binding("ctrl+enter", "send", "Send"),
        Binding("ctrl+c", "interrupt_or_quit", "Interrupt/Quit", priority=True),
        Binding("ctrl+l", "clear_input", "Clear Input"),
        Binding("f1", "show_help", "Help"),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.agent: Agent | None = None
        self._command_registry = build_registry()
        self._active_turn_task: asyncio.Task | None = None
        self._is_turn_running: bool = False
        self._streaming_widget: Static | None = None
        self._streaming_buffer: str = ""
        self._tool_widgets: dict[str, Static] = {}
        self._tool_args_by_call_id: dict[str, dict[str, Any]] = {}
        self._adapter = ReupTUIAdapter(self)
        self._message_count: int = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="shell"):
            with Horizontal(id="topbar"):
                yield Static("iTE Reup", id="title")
                yield Static("idle", id="run-state")
                yield Static("", id="header-meta")
            with Container(id="chat-panel"):
                yield VerticalScroll(id="conversation")
                yield Static("", id="empty-state")
            with Horizontal(id="composer"):
                with Container(id="prompt-container"):
                    yield TextArea(id="prompt", language="markdown")
                    with Horizontal(id="composer-meta"):
                        yield Static("📎", classes="meta-icon")
                        yield Static(self.config.model_name, classes="meta-chip", id="model-chip")
                        yield Static("Plan", classes="meta-chip")
                        yield Static("", id="meta-spacer")
                        yield Static("tui_re", classes="meta-chip")
                        yield Button("Send", id="send", variant="default")
        yield Footer()

    async def on_mount(self) -> None:
        self.refresh_header()
        await self.ensure_agent()
        self._set_loading_state("idle", busy=False)
        self._refresh_empty_state()
        self.query_one("#prompt", TextArea).focus()

    async def on_unmount(self) -> None:
        await self.cancel_active_turn()
        if self.agent is not None:
            await self.agent.__aexit__(None, None, None)
            self.agent = None

    def refresh_header(self) -> None:
        meta = self.query_one("#header-meta", Static)
        meta.update(f"Model: {self.config.model_name}  |  Workspace: {self.config.cwd}")
        model_chip = self.query_one("#model-chip", Static)
        model_chip.update(self.config.model_name)

    def _build_empty_state_title(self) -> str:
        # Mirror GUI greeting logic so both surfaces stay consistent.
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 12:
            opener_variants = [
                "Good morning",
                "Fresh start",
                "Morning focus",
                "Let's get momentum",
            ]
        elif 12 <= hour < 17:
            opener_variants = [
                "Good afternoon",
                "Afternoon check-in",
                "Back to shipping",
                "Let's make progress",
            ]
        else:
            opener_variants = [
                "Good evening",
                "Evening build session",
                "Quiet hours, solid output",
                "Let's close the day strong",
            ]

        try:
            thread_count = len(
                [
                    s
                    for s in SessionManager().list_sessions(
                        workspace_path=self.config.cwd,
                        include_legacy_unscoped=False,
                    )
                    if s.get("turn_count", 0) > 0
                ]
            )
        except Exception:
            thread_count = 0

        if thread_count > 0:
            followup_variants = [
                "Continue where you left off.",
                "Pick up your last thread.",
                "Your workspace is ready.",
                "Resume the next step.",
            ]
        else:
            followup_variants = [
                "What should we build next?",
                "Start a thread and let's map it out.",
                "Drop in a goal to begin.",
                "Tell me what you want to ship.",
            ]

        workspace_key = str(self.config.cwd.resolve())
        seed = sum(ord(ch) for ch in f"{workspace_key}:{now.date().isoformat()}:{thread_count}")
        opener = opener_variants[seed % len(opener_variants)]
        followup = followup_variants[(seed // 3) % len(followup_variants)]
        return f"{opener}. {followup}"

    def _refresh_empty_state(self) -> None:
        empty = self.query_one("#empty-state", Static)
        if self._message_count > 0 or self._is_turn_running:
            empty.display = False
            return
        # Reuse exact legacy TUI logo rows for stable terminal glyph alignment.
        logo_lines = [
            "  ██╗ ██████╗ ███████╗",
            "  ╚═╝ ╚═██╔═╝ ██╔═══╝",
            "  ██╗   ██║   ████╗  ",
            "  ██║   ██║   ██╔═╝  ",
            "  ██║   ██║   ███████╗",
            "  ╚═╝   ╚═╝   ╚══════╝",
        ]
        art = "\n".join(logo_lines)
        greeting = self._build_empty_state_title()
        content = Text()
        content.append(art + "\n\n", style="bold #8d94a0")
        content.append(greeting, style="bold #e3e7ef")
        empty.update(content)
        empty.display = True

    def _set_loading_state(self, state: str, busy: bool) -> None:
        state_widget = self.query_one("#run-state", Static)
        state_widget.update(state)

        prompt = self.query_one("#prompt", TextArea)
        send = self.query_one("#send", Button)

        prompt.disabled = busy
        send.disabled = False
        if busy:
            send.label = "Stop"
            send.variant = "warning"
        else:
            send.label = "Send"
            send.variant = "default"
        self._refresh_empty_state()

    async def ensure_agent(self) -> None:
        if self.agent is not None:
            return
        self.agent = Agent(
            config=self.config,
            confirmation_callback=self.confirmation_callback,
            plan_question_callback=self.plan_question_callback,
        )
        await self.agent.__aenter__()

    async def _open_modal(self, screen: ModalScreen[Any]) -> Any:
        """Open a modal and await dismissal from regular event handlers safely."""
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[Any] = loop.create_future()

        def _on_dismiss(result: Any) -> None:
            if not result_future.done():
                result_future.set_result(result)

        self.push_screen(screen, callback=_on_dismiss)
        return await result_future

    def _is_plan_only_phase(self) -> bool:
        return bool(
            self.agent
            and self.agent.session
            and self.agent.session.plan_mode_enabled
            and self.agent.session.plan_phase != "executing"
        )

    def _normalize_plan_execution_request(self, message: str) -> str | None:
        raw = message.strip()
        lowered = raw.lower()
        if lowered not in {
            "implement plan",
            "implement the plan",
            "go ahead and implement",
            "execute plan",
            "approve plan",
            "yes, implement plan",
        }:
            return raw

        if not self.agent or not self.agent.session:
            return raw

        session = self.agent.session
        if session.plan_mode_enabled and session.plan_phase == "awaiting_implementation_confirmation":
            session.clear_pending_plan()
            session.set_plan_mode(False)
            session.set_plan_phase("idle")
            return Agent.PLAN_EXECUTE_PROMPT

        self.post_system(
            "Plan Mode",
            "No pending plan is waiting for approval. Ask for a plan first.",
        )
        return None

    def action_show_help(self) -> None:
        self.post_system(
            "Help",
            "Enter text and use Ctrl+Enter to send.\n"
            "Commands begin with /.\n"
            "Use Ctrl+C to interrupt a running turn, or quit when idle.",
        )

    def action_clear_input(self) -> None:
        prompt = self.query_one("#prompt", TextArea)
        prompt.text = ""

    async def action_interrupt_or_quit(self) -> None:
        if self._is_turn_running:
            await self.cancel_active_turn()
            self.post_system("Interrupted", "Stopped current run.")
        else:
            self.exit()

    async def action_send(self) -> None:
        await self.handle_send()

    @on(Button.Pressed, "#send")
    async def on_send_button(self, _event: Button.Pressed) -> None:
        await self.handle_send()

    async def handle_send(self) -> None:
        if self._is_turn_running:
            await self.cancel_active_turn()
            return

        prompt = self.query_one("#prompt", TextArea)
        message = prompt.text.strip()
        if not message:
            return

        prompt.text = ""

        normalized = self._normalize_plan_execution_request(message)
        if normalized is None:
            return
        message = normalized

        if message.startswith("/"):
            await self.run_command(message)
            return

        await self.run_agent_message(message)

    async def _list_resume_sessions(self, all_workspaces: bool = False) -> list[dict[str, Any]]:
        sessions = SessionManager().list_sessions(
            workspace_path=None if all_workspaces else self.config.cwd,
            include_legacy_unscoped=all_workspaces,
        )
        return [s for s in sessions if s.get("turn_count", 0) > 0]

    @work
    async def _open_resume_flow(self, all_workspaces: bool = False) -> None:
        """Open resume modal and restore a selected session (toad-style worker flow)."""
        sessions = await self._list_resume_sessions(all_workspaces=all_workspaces)
        if not sessions:
            self.post_system("Sessions", "No saved sessions found.")
            return

        selected_id = await self.push_screen_wait(SessionResumeModal(sessions))
        if not selected_id:
            return

        snapshot = SessionManager().load_session(selected_id)
        if snapshot is None:
            self.post_system("Sessions", f"Session not found: {selected_id}", is_error=True)
            return

        await self._resume_snapshot(snapshot)

    async def _resume_snapshot(self, snapshot: SessionSnapshot) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            return

        if snapshot.workspace_path:
            target_workspace = Path(snapshot.workspace_path).resolve()
            if target_workspace != self.config.cwd.resolve():
                self.config.cwd = target_workspace
                self.refresh_header()

        resumed = Session(config=self.config)
        resumed.session_id = snapshot.session_id
        resumed.name = snapshot.name
        resumed.created_at = snapshot.created_at
        resumed.updated_at = snapshot.updated_at
        resumed.turn_count = snapshot.turn_count
        resumed.plan_mode_enabled = snapshot.plan_mode_enabled
        resumed.plan_phase = snapshot.plan_phase
        resumed.plan_questions_asked = snapshot.plan_questions_asked
        resumed.plan_target_questions = snapshot.plan_target_questions
        resumed.pending_plan_text = snapshot.pending_plan_text

        await self.agent.session.client.close()
        await self.agent.session.mcp_manager.shutdown()
        await resumed.initialize()

        resumed.context_manager.set_messages(snapshot.messages)
        resumed.context_manager.total_usage = snapshot.total_usage
        resumed.approval_manager.confirmation_callback = self.confirmation_callback
        self.agent.session = resumed

        await self._hydrate_chat_from_snapshot(snapshot.messages)
        self.post_system(
            "Session Loaded",
            f"{snapshot.name or snapshot.session_id} · {snapshot.turn_count} turns",
        )

    async def _hydrate_chat_from_snapshot(self, messages: list[dict[str, Any]]) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        await conversation.remove_children()
        self._message_count = 0

        max_render = 220
        rendered = messages[-max_render:]

        for message in rendered:
            role = message.get("role")
            content = message.get("content", "")
            if role == "system":
                continue
            if role == "user":
                await self.add_assistant_card("You", str(content), css_class="user")
                continue
            if role == "assistant" and content:
                await self.add_assistant_card("ite", RichMarkdown(str(content)), css_class="assistant")
        self._refresh_empty_state()

    async def run_command(self, command_line: str) -> None:
        parts = command_line.split()
        command = parts[0].lower()
        args = parts[1:]

        if command in {"/exit", "/quit"}:
            self.exit()
            return

        # Native in-app session picker flow (replaces curses picker in old /sessions command).
        if command == "/sessions" and "--list" not in args:
            self._open_resume_flow(all_workspaces=("--all" in args))
            return

        if command == "/resume" and not args:
            self._open_resume_flow(all_workspaces=False)
            return

        if command == "/resume" and args:
            snapshot = SessionManager().load_session(args[0])
            if snapshot is None:
                self.post_system("Resume", f"Session not found: {args[0]}", is_error=True)
                return
            await self._resume_snapshot(snapshot)
            return

        await self.ensure_agent()
        if not self.agent:
            self.post_system("Error", "Agent is not initialized", is_error=True)
            return

        output = io.StringIO()
        ctx = build_command_context(
            config=self.config,
            agent=self.agent,
            tui=self._adapter,
            output_stream=output,
        )

        try:
            await self._command_registry.dispatch(command, args, ctx)
        except SystemExit:
            self.exit()
            return
        except Exception as exc:
            self.post_system("Command Error", str(exc), is_error=True)
            return

        rendered = output.getvalue().strip()
        if rendered:
            self.post_system(f"Command {command}", rendered)

    async def run_agent_message(self, message: str) -> None:
        await self.ensure_agent()
        if not self.agent:
            self.post_system("Error", "Agent is not initialized", is_error=True)
            return

        await self.add_user_message(message)
        self._active_turn_task = asyncio.create_task(self._agent_turn(message))
        self._is_turn_running = True
        self._set_loading_state("thinking", busy=True)

        try:
            await self._active_turn_task
            await self.auto_save()
        except asyncio.CancelledError:
            self.post_system("Interrupted", "Turn was interrupted.")
        finally:
            self._active_turn_task = None
            self._is_turn_running = False
            self._set_loading_state("idle", busy=False)

    async def _agent_turn(self, message: str) -> None:
        assert self.agent is not None

        async for event in self.agent.run(message):
            await self.handle_agent_event(event)

    async def handle_agent_event(self, event: AgentEvent) -> None:
        plan_only_phase = self._is_plan_only_phase()
        suppressed_tools = {"memory", "plan_question", "todos", "web_search", "web_fetch"}

        if event.type == AgentEventType.TEXT_DELTA:
            content = event.data.get("content", "")
            if content:
                await self.stream_assistant_delta(content)
            return

        if event.type == AgentEventType.TEXT_COMPLETE:
            content = event.data.get("content", "")
            if self._streaming_widget is not None:
                await self.finalize_streaming_message()
            elif content and not plan_only_phase:
                await self.add_assistant_message(content)
            return

        if event.type == AgentEventType.AGENT_ERROR:
            self.post_system("Error", str(event.data.get("error", "Unknown error")), is_error=True)
            return

        if event.type == AgentEventType.CONTEXT_COMPACTED:
            trigger_tokens = int(event.data.get("trigger_tokens", 0))
            context_window = int(event.data.get("context_window", 0))
            used_pct = (trigger_tokens / context_window * 100) if context_window else 0
            self.post_system(
                "Context",
                f"Compacted at {trigger_tokens}/{context_window} tokens ({used_pct:.1f}% used).",
            )
            return

        if event.type == AgentEventType.TOOL_CALL_START:
            tool_name = event.data.get("name", "tool")
            if tool_name in suppressed_tools or plan_only_phase:
                self._set_loading_state("thinking", busy=True)
                return
            tool_kind = self.get_tool_kind(tool_name)
            self._set_loading_state("running tool", busy=True)
            await self.add_tool_call_start(
                call_id=event.data.get("call_id", ""),
                name=tool_name,
                tool_kind=tool_kind,
                arguments=event.data.get("arguments", {}),
            )
            return

        if event.type == AgentEventType.TOOL_CALL_COMPLETE:
            tool_name = event.data.get("name", "tool")
            if tool_name in suppressed_tools:
                self._set_loading_state("thinking", busy=True)
                return
            if plan_only_phase and event.data.get("success", False):
                self._set_loading_state("thinking", busy=True)
                return
            tool_kind = self.get_tool_kind(tool_name)
            await self.update_tool_call(
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
            self._set_loading_state("thinking", busy=True)
            return

        if event.type == AgentEventType.PLAN_READY:
            plan_text = event.data.get("plan_text", "")
            if isinstance(plan_text, str) and plan_text.strip():
                await self.add_assistant_card("Plan", RichMarkdown(plan_text))
            approved = await self._open_modal(
                ConfirmModal(
                    title="Plan Ready",
                    body="Implement this plan now?",
                    yes_label="Implement",
                    no_label="Keep Plan Mode",
                )
            )
            if approved and self.agent and self.agent.session:
                self.agent.session.clear_pending_plan()
                self.agent.session.set_plan_phase("executing")
                await self.run_agent_message(Agent.PLAN_EXECUTE_PROMPT)
            elif self.agent and self.agent.session:
                self.agent.session.set_plan_phase("awaiting_implementation_confirmation")
                self.post_system("Plan Mode", "Plan kept for refinement. Use 'implement plan' later.")
            return

    def get_tool_kind(self, tool_name: str) -> str | None:
        if not self.agent or not self.agent.session:
            return None
        tool = self.agent.session.tool_registry.get(tool_name)
        if not tool:
            return None
        return tool.kind.value

    async def stream_assistant_delta(self, content: str) -> None:
        self._streaming_buffer += content
        conversation = self.query_one("#conversation", VerticalScroll)
        if self._streaming_widget is None:
            self._streaming_widget = Static(classes="block assistant")
            await conversation.mount(self._streaming_widget)
            self._message_count += 1
            self._refresh_empty_state()
        self._streaming_widget.update(RichMarkdown(self._streaming_buffer))
        conversation.scroll_end(animate=False)

    async def finalize_streaming_message(self) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        if self._streaming_widget is not None:
            self._streaming_widget.update(RichMarkdown(self._streaming_buffer))
            conversation.scroll_end(animate=False)
        self._streaming_widget = None
        self._streaming_buffer = ""

    async def add_user_message(self, message: str) -> None:
        await self.add_assistant_card("You", message, css_class="user")

    async def add_assistant_message(self, message: str) -> None:
        await self.add_assistant_card("ite", RichMarkdown(message), css_class="assistant")

    def post_system(self, title: str, message: str, is_error: bool = False) -> None:
        css_class = "system error" if is_error else "system"
        self.run_worker(self.add_assistant_card(title, message, css_class=css_class), exclusive=False)

    async def add_assistant_card(self, title: str, body: Any, css_class: str = "assistant") -> None:
        conversation = self.query_one("#conversation", VerticalScroll)

        body_widget = Static(classes="card-body")
        body_widget.update(body if not isinstance(body, str) else str(body))

        card = Container(
            Static(title, classes="card-title"),
            body_widget,
            classes=f"block {css_class}",
        )

        await conversation.mount(card)
        self._message_count += 1
        self._refresh_empty_state()
        conversation.scroll_end(animate=False)

    async def add_tool_call_start(
        self,
        *,
        call_id: str,
        name: str,
        tool_kind: str | None,
        arguments: dict[str, Any],
    ) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        self._tool_args_by_call_id[call_id] = arguments

        args_lines = "\n".join(f"{k}: {v}" for k, v in arguments.items()) or "(no args)"
        card = Static(classes="block tool running")
        kind = f"[{tool_kind}] " if tool_kind else ""
        card.update(f"🔧 {kind}{name}\nstatus: running\n\n{args_lines}")
        self._tool_widgets[call_id] = card

        await conversation.mount(card)
        conversation.scroll_end(animate=False)

    async def update_tool_call(
        self,
        *,
        call_id: str,
        name: str,
        tool_kind: str | None,
        success: bool,
        output: str,
        error: str | None,
        metadata: dict[str, Any] | None,
        diff: str | None,
        truncated: bool,
        exit_code: int | None,
    ) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        card = self._tool_widgets.get(call_id)
        if card is None:
            await self.add_tool_call_start(
                call_id=call_id,
                name=name,
                tool_kind=tool_kind,
                arguments=self._tool_args_by_call_id.get(call_id, {}),
            )
            card = self._tool_widgets.get(call_id)
            if card is None:
                return

        status = "done" if success else "failed"
        icon = "✅" if success else "❌"
        kind = f"[{tool_kind}] " if tool_kind else ""

        payload = output if success else (error or output)
        payload = payload or "No output"
        if diff:
            payload_renderable: Any = Syntax(diff, "diff", theme="monokai", word_wrap=True)
        else:
            payload_renderable = payload

        wrapper = Panel.fit(
            payload_renderable,
            title=f"{icon} {kind}{name}",
            subtitle=f"{status}" + (f" · exit {exit_code}" if exit_code is not None else ""),
        )
        card.update(wrapper)
        card.remove_class("running")
        if success:
            card.add_class("success")
        else:
            card.add_class("error")

        if truncated:
            await conversation.mount(Static("... [truncated]", classes="block system"))

        conversation.scroll_end(animate=False)

    async def confirmation_callback(self, confirmation) -> bool:
        body = confirmation.description
        if confirmation.command:
            body += f"\n\n$ {confirmation.command}"
        if confirmation.diff:
            body += f"\n\n{confirmation.diff.to_diff()}"

        approved = await self._open_modal(
            ConfirmModal(
                title=f"Approval required: {confirmation.tool_name}",
                body=body,
                yes_label="Approve",
                no_label="Deny",
            )
        )
        return bool(approved)

    async def plan_question_callback(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._set_loading_state("planning", busy=True)
        try:
            question = str(payload.get("question", "")).strip()
            options = [str(o) for o in payload.get("options", []) if str(o).strip()]
            recommended_index = payload.get("recommended_index")
            allow_free_text = bool(payload.get("allow_free_text", True))

            result = await self._open_modal(
                PlanQuestionModal(
                    question=question,
                    options=options,
                    recommended_index=recommended_index,
                    allow_free_text=allow_free_text,
                )
            )

            if not result:
                return {"selected_option": "", "free_text": "", "selected_index": None}
            return result
        finally:
            self._set_loading_state("thinking", busy=True)

    async def cancel_active_turn(self) -> None:
        task = self._active_turn_task
        if not task:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._active_turn_task = None
        self._is_turn_running = False
        self._set_loading_state("idle", busy=False)

    async def start_new_thread(self) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            return

        await self.cancel_active_turn()

        if self.agent.session.turn_count > 0:
            await self.auto_save()

        previous = self.agent.session
        fresh = Session(config=self.config)

        await previous.client.close()
        await previous.mcp_manager.shutdown()
        await fresh.initialize()
        fresh.approval_manager.confirmation_callback = self.confirmation_callback
        self.agent.session = fresh

        conversation = self.query_one("#conversation", VerticalScroll)
        await conversation.remove_children()

        self._tool_widgets.clear()
        self._tool_args_by_call_id.clear()
        self._streaming_widget = None
        self._streaming_buffer = ""
        self._message_count = 0
        self._refresh_empty_state()

        self.post_system("Thread", "Started a fresh session.")

    async def auto_save(self) -> None:
        if not self.agent or not self.agent.session:
            return

        session = self.agent.session
        if session.turn_count == 0:
            return

        if session.name is None:
            session.name = await self.generate_session_name(session)

        snapshot = SessionSnapshot(
            session_id=session.session_id,
            name=session.name,
            workspace_path=str(self.config.cwd.resolve()),
            created_at=session.created_at,
            updated_at=session.updated_at,
            turn_count=session.turn_count,
            messages=session.context_manager.get_messages(),
            total_usage=session.context_manager.total_usage,
            plan_mode_enabled=session.plan_mode_enabled,
            plan_phase=session.plan_phase,
            plan_questions_asked=session.plan_questions_asked,
            plan_target_questions=session.plan_target_questions,
            pending_plan_text=session.pending_plan_text,
        )
        SessionManager().save_session(snapshot)

    async def generate_session_name(self, session: Session) -> str:
        first_user = ""
        try:
            messages = session.context_manager.get_messages()
            first_assistant = ""
            for msg in messages:
                if msg.get("role") == "user" and not first_user:
                    first_user = msg.get("content", "")[:200]
                elif msg.get("role") == "assistant" and first_user and not first_assistant:
                    first_assistant = msg.get("content", "")[:200]
                    break

            if not first_user:
                return "New thread"

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
                naming_messages,
                tools=None,
                stream=True,
            ):
                if event.text_delta and event.text_delta.content:
                    title += event.text_delta.content

            title = title.strip()[:60]
            if title:
                return title

        except Exception:
            pass

        fallback = first_user.split(".")[0].split("?")[0].split("!")[0][:60]
        return fallback.strip() or "New thread"



def run_reup(config: Config) -> None:
    app = ReupApp(config)
    app.run()
