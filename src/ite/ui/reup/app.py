from __future__ import annotations

import asyncio
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static, TextArea

from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.agent.session import Session
from ite.agent.session_manager import SessionManager, SessionSnapshot
from ite.commands import build_registry
from ite.config.config import Config
from ite.ui.tool_narrative import activity_title, describe_tool_activity

from .adapters.registry import build_command_context


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        ("enter", "accept", "Accept"),
        ("y", "accept", "Accept"),
        ("n", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "cancel", "Cancel"),
        ("1", "cancel", "Option 1"),
        ("2", "accept", "Option 2"),
    ]

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
        with Container(classes="modal confirm-modal"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._body, classes="modal-body")
            with Horizontal(classes="modal-actions"):
                yield Button(self._no, id="no", variant="default")
                yield Button(self._yes, id="yes", variant="success")

    async def on_mount(self) -> None:
        # Default to the affirmative action, mirroring previous TUI defaults.
        self.query_one("#yes", Button).focus()

    def action_accept(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#yes")
    def on_yes_pressed(self, _event: Button.Pressed) -> None:
        self.action_accept()

    @on(Button.Pressed, "#no")
    def on_no_pressed(self, _event: Button.Pressed) -> None:
        self.action_cancel()


class PlanQuestionModal(ModalScreen[dict[str, Any]]):
    def __init__(
        self,
        *,
        question_number: int,
        question: str,
        options: list[str],
        recommended_index: int | None,
        allow_free_text: bool,
    ) -> None:
        super().__init__()
        self._question_number = max(1, question_number)
        self._question = question
        self._options = options
        self._recommended_index = recommended_index
        self._allow_free_text = allow_free_text

    def compose(self) -> ComposeResult:
        with Container(classes="modal plan-modal"):
            yield Label(f"Asking questions {self._question_number}", classes="modal-title")
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
        with Container(classes="modal resume-modal"):
            yield Label("Resume Session", classes="modal-title resume-title")
            yield Static("Pick a session to resume.", classes="modal-body resume-body")
            with Container(classes="modal-list resume-list"):
                yield DataTable(id="sessions", classes="resume-table", cursor_type="row")
            with Horizontal(classes="modal-actions resume-actions"):
                yield Button("Resume", id="resume", variant="primary", disabled=True)
                yield Button("Cancel", id="cancel", variant="default")

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        if not value:
            return "-"
        text = str(value)
        try:
            return datetime.fromisoformat(text).strftime("%b %d · %I:%M %p")
        except Exception:
            return text

    async def on_mount(self) -> None:
        table = self.query_one("#sessions", DataTable)
        table.add_columns("Name", "Session", "Created", "Last Used")

        self._session_ids = []
        for session in self._sessions:
            sid = str(session.get("session_id", ""))
            name = str(session.get("name") or sid)
            created = self._format_timestamp(session.get("created_at"))
            updated = self._format_timestamp(session.get("updated_at"))
            self._session_ids.append(sid)
            table.add_row(name, f"{sid[:8]}…", created, updated)
        if self._session_ids:
            table.move_cursor(row=0, column=0)
            self.query_one("#resume", Button).disabled = False

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


class ReupPromptTextArea(TextArea):
    class Submitted(Message):
        pass

    BINDINGS = []

    def action_submit(self) -> None:
        self.post_message(self.Submitted())

    def action_newline(self) -> None:
        self.insert("\n")

    def on_key(self, event: events.Key) -> None:
        if event.key in {"shift+enter", "ctrl+j"}:
            event.stop()
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            self.action_newline()
            return
        if event.key == "enter":
            event.stop()
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            self.action_submit()
            return


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
    TITLE = "iTE"
    BINDINGS = [
        Binding("ctrl+enter", "send", "Send"),
        Binding("ctrl+c", "interrupt_or_quit", "Interrupt/Quit", priority=True),
        Binding("ctrl+l", "clear_input", "Clear Input"),
        Binding("f1", "show_help", "Help"),
    ]
    MIN_PROMPT_LINES = 2
    MAX_PROMPT_LINES = 8
    META_ROW_HEIGHT = 3
    COMPOSER_GAP_HEIGHT = 1
    PROMPT_TOP_PAD = 1
    CONTAINER_EXTRA = 0
    COMPOSER_EXTRA = 1

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.title = "iTE"
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
        self._composer_history: list[str] = []
        self._composer_history_index: int | None = None
        self._composer_history_draft: str = ""
        self._applying_history_nav: bool = False
        self._suppress_history_reset_once: bool = False
        self._top_busy: bool = False
        self._top_spinner_index: int = 0
        self._top_spinner_frames: tuple[str, ...] = ("|", "/", "-", "\\")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="shell"):
            with Horizontal(id="topbar"):
                yield Static("New thread", id="title")
                yield Static("idle", id="run-state")
                yield Static("·", id="top-throbber")
                yield Static("", id="header-meta")
            with Container(id="chat-panel"):
                yield VerticalScroll(id="conversation")
                yield Static("", id="empty-state")
            with Horizontal(id="composer"):
                with Container(id="prompt-container"):
                    yield ReupPromptTextArea(id="prompt", language="markdown")
                    yield Static("", id="composer-gap")
                    with Horizontal(id="composer-meta"):
                        yield Static("📎", classes="meta-icon")
                        yield Static(self.config.model_name, classes="meta-chip", id="model-chip")
                        yield Static("Plan", classes="meta-chip")
                        yield Static("", id="meta-spacer")
                        yield Static("tui_re", classes="meta-chip")
                        yield Button("Send", id="send", variant="default")
        yield Footer()

    async def on_mount(self) -> None:
        await self.ensure_agent()
        self.refresh_header()
        self._set_loading_state("idle", busy=False)
        self._refresh_empty_state()
        self._resize_composer_for_prompt()
        self.set_interval(0.1, self._tick_top_indicator)
        self.query_one("#prompt", TextArea).focus()

    async def on_unmount(self) -> None:
        await self.cancel_active_turn()
        if self.agent is not None:
            await self.agent.__aexit__(None, None, None)
            self.agent = None

    def _current_session_title(self) -> str:
        if not self.agent or not self.agent.session:
            return "New thread"

        session = self.agent.session
        if isinstance(session.name, str) and session.name.strip():
            return session.name.strip()
        if session.turn_count > 0:
            return "Untitled thread"
        return "New thread"

    def refresh_header(self) -> None:
        title = self.query_one("#title", Static)
        meta = self.query_one("#header-meta", Static)
        title.update(self._current_session_title())
        meta.update(f"Workspace: {self.config.cwd}")
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
        state_widget.update(state if busy else "")
        self._top_busy = busy
        if not busy:
            self.query_one("#top-throbber", Static).update(" ")

        prompt = self.query_one("#prompt", TextArea)
        send = self.query_one("#send", Button)

        prompt.disabled = busy
        send.disabled = False
        if busy:
            send.label = "Stop"
        else:
            send.label = "Send"
        send.variant = "default"
        self._refresh_empty_state()

    def _tick_top_indicator(self) -> None:
        throbber = self.query_one("#top-throbber", Static)
        if not self._top_busy:
            throbber.update(" ")
            return
        frame = self._top_spinner_frames[self._top_spinner_index % len(self._top_spinner_frames)]
        self._top_spinner_index += 1
        throbber.update(frame)

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

    def _should_suppress_intent_detection(self, message: str, *, plan_enabled: bool) -> bool:
        text = (message or "").strip()
        min_len = 7 if plan_enabled else 12
        if len(text) < min_len:
            return True
        if len(text.split()) < 3:
            if not (plan_enabled and re.search(r"\b(let'?s|lets|let us)\b", text.lower())):
                return True
        if message == Agent.PLAN_EXECUTE_PROMPT:
            return True
        return False

    def _detect_plan_intent(self, message: str) -> bool:
        text = (message or "").strip().lower()
        strong_phrases = (
            "make a plan",
            "implementation plan",
            "before coding",
            "steps to build",
            "plan this",
            "create a plan",
            "draft a plan",
            "what is the plan",
            "outline the plan",
        )
        if any(p in text for p in strong_phrases):
            return True

        if bool(re.search(r"\b(let'?s|lets|let us)\s+(build|create|design|architect)\b", text)):
            return True

        build_intent_markers = (
            "i want to build",
            "i want to create",
            "help me build",
            "help me create",
            "how should i build",
            "how do i build",
            "design a",
            "build a",
            "create a",
            "architect a",
        )
        product_targets = (
            "app",
            "game",
            "website",
            "web app",
            "tool",
            "platform",
            "system",
            "project",
            "feature",
            "api",
            "dashboard",
        )
        if any(m in text for m in build_intent_markers) and any(t in text for t in product_targets):
            return True

        return bool(re.search(r"\b(plan|roadmap|steps)\b", text) and "implement" not in text)

    def _detect_execution_intent(self, message: str) -> bool:
        text = (message or "").strip().lower()
        phrases = (
            "implement now",
            "go ahead and build",
            "apply the changes",
            "start coding",
            "execute this",
            "ship it",
            "go implement",
            "build it now",
            "start implementation",
            "let's build",
            "lets build",
            "let's implement",
            "lets implement",
            "let us build",
            "let us implement",
            "build then",
            "implement then",
            "lets built",
            "let's built",
        )
        if any(p in text for p in phrases):
            return True
        if bool(re.search(r"\b(let'?s|lets|let us)\s+(build|built|implement|code|execute)\b", text)):
            return True
        if bool(
            re.search(r"\b(build|implement|start coding|execute)\b", text)
            and re.search(r"\b(then|next)\b", text)
        ):
            return True
        return bool(
            re.search(r"\b(implement|build|built|code|execute|apply)\b", text)
            and re.search(r"\b(now|this|it|changes)\b", text)
        )

    async def _apply_intent_assist(self, message: str) -> str | None:
        if message.startswith("/"):
            return message

        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            return message

        session = self.agent.session
        plan_enabled = bool(session.plan_mode_enabled)
        if self._should_suppress_intent_detection(message, plan_enabled=plan_enabled):
            return message

        if not plan_enabled and self._detect_plan_intent(message):
            choice = await self._open_modal(
                ConfirmModal(
                    title="Enable Plan Mode?",
                    body="This prompt looks like planning. Switch to Plan mode before sending?",
                    yes_label="Enable Plan Mode",
                    no_label="Send Normally",
                )
            )
            if choice is None:
                return None
            if bool(choice):
                session.set_plan_mode(True)
                session.set_plan_phase("idle")
                self.post_system("Plan Mode", "Plan mode enabled.")
            return message

        if plan_enabled and self._detect_execution_intent(message):
            choice = await self._open_modal(
                ConfirmModal(
                    title="Run In Execution Mode?",
                    body="This prompt looks like execution while Plan mode is ON.",
                    yes_label="Turn Off Plan Mode",
                    no_label="Stay in Plan Mode",
                )
            )
            if choice is None:
                return None
            if bool(choice):
                session.set_plan_mode(False)
                session.set_plan_phase("idle")
                self.post_system("Plan Mode", "Plan mode disabled.")
                return message

            self.post_system("Plan Mode", "Staying in plan mode; continuing with planning flow.")
            return (
                f"{message}\n\n"
                "Stay in plan mode. Do not execute changes yet. "
                "Ask clarifying questions first, then provide an implementation plan."
            )

        return message

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
        self._composer_history_index = None
        self._composer_history_draft = ""
        self._resize_composer_for_prompt()

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

    @on(TextArea.Changed, "#prompt")
    def on_prompt_changed(self, _event: TextArea.Changed) -> None:
        if self._suppress_history_reset_once:
            self._suppress_history_reset_once = False
            self._resize_composer_for_prompt()
            return
        if self._composer_history_index is not None and not self._applying_history_nav:
            self._composer_history_index = None
            self._composer_history_draft = ""
        self._resize_composer_for_prompt()

    async def on_reup_prompt_text_area_submitted(
        self, _event: ReupPromptTextArea.Submitted
    ) -> None:
        await self.handle_send()

    def on_key(self, event: events.Key) -> None:
        # Global modal escape hatch: always allow resolving confirm prompts,
        # even if focus gets stuck or terminal mouse support is flaky.
        if self.screen_stack:
            top = self.screen_stack[-1]
            if isinstance(top, ConfirmModal):
                key = event.key
                if key in {"enter", "y", "2"}:
                    top.dismiss(True)
                    event.stop()
                    if hasattr(event, "prevent_default"):
                        event.prevent_default()
                    return
                if key in {"n", "escape", "ctrl+c", "1"}:
                    top.dismiss(False)
                    event.stop()
                    if hasattr(event, "prevent_default"):
                        event.prevent_default()
                    return

        focused = self.focused
        if not isinstance(focused, TextArea) or focused.id != "prompt":
            return
        if event.key not in {"up", "down"}:
            return
        if self._is_turn_running or not self._composer_history:
            return
        handled = self._handle_composer_history_navigation(event.key)
        if not handled:
            return
        event.stop()
        if hasattr(event, "prevent_default"):
            event.prevent_default()

    def _record_composer_history(self, message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        if self._composer_history and self._composer_history[-1] == text:
            return
        self._composer_history.append(text)
        if len(self._composer_history) > 300:
            self._composer_history = self._composer_history[-300:]

    def _set_prompt_text_from_history(self, text: str) -> None:
        prompt = self.query_one("#prompt", TextArea)
        self._suppress_history_reset_once = True
        self._applying_history_nav = True
        try:
            prompt.text = text
            if hasattr(prompt, "action_cursor_document_end"):
                prompt.action_cursor_document_end()
        finally:
            self._applying_history_nav = False
        self._resize_composer_for_prompt()

    def _handle_composer_history_navigation(self, key: str) -> bool:
        prompt = self.query_one("#prompt", TextArea)

        if key == "up":
            if self._composer_history_index is None:
                self._composer_history_draft = prompt.text or ""
                self._composer_history_index = len(self._composer_history) - 1
            else:
                self._composer_history_index = max(0, self._composer_history_index - 1)
            self._set_prompt_text_from_history(self._composer_history[self._composer_history_index])
            return True

        if key == "down" and self._composer_history_index is not None:
            if self._composer_history_index < len(self._composer_history) - 1:
                self._composer_history_index += 1
                self._set_prompt_text_from_history(
                    self._composer_history[self._composer_history_index]
                )
            else:
                self._set_prompt_text_from_history(self._composer_history_draft)
                self._composer_history_index = None
                self._composer_history_draft = ""
            return True

        return False

    def _resize_composer_for_prompt(self) -> None:
        prompt = self.query_one("#prompt", TextArea)
        prompt_container = self.query_one("#prompt-container", Container)
        composer = self.query_one("#composer", Horizontal)

        line_count = max(1, prompt.text.count("\n") + 1)
        prompt_lines = min(max(line_count, self.MIN_PROMPT_LINES), self.MAX_PROMPT_LINES)
        prompt_height = prompt_lines + self.PROMPT_TOP_PAD
        container_height = (
            prompt_height
            + self.COMPOSER_GAP_HEIGHT
            + self.META_ROW_HEIGHT
            + self.CONTAINER_EXTRA
        )
        composer_height = container_height + self.COMPOSER_EXTRA

        prompt.styles.height = prompt_height
        prompt_container.styles.height = container_height
        composer.styles.height = composer_height

    async def handle_send(self) -> None:
        if self._is_turn_running:
            await self.cancel_active_turn()
            return

        prompt = self.query_one("#prompt", TextArea)
        message = prompt.text.strip()
        if not message:
            return

        self._record_composer_history(message)
        self._composer_history_index = None
        self._composer_history_draft = ""
        prompt.text = ""
        self._resize_composer_for_prompt()

        normalized = self._normalize_plan_execution_request(message)
        if normalized is None:
            return
        message = normalized

        if message.startswith("/"):
            await self.run_command(message)
            return

        # Important: run intent-assist modal flow in a worker so the
        # Textual message pump remains interactive (mouse + keyboard).
        self.run_worker(
            self._handle_agent_send_with_intent(message),
            exclusive=False,
        )

    async def _handle_agent_send_with_intent(self, message: str) -> None:
        assisted = await self._apply_intent_assist(message)
        if assisted is None:
            return
        await self.run_agent_message(assisted)

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
        self.refresh_header()

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
                await self.add_assistant_card("You", RichMarkdown(str(content)), css_class="user")
                continue
            if role == "assistant" and content:
                await self.add_assistant_card("iTE", RichMarkdown(str(content)), css_class="assistant")
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

    def _ordered_args(self, tool_name: str, args: dict[str, Any]) -> list[tuple[str, Any]]:
        preferred_order = {
            "read_file": ["path", "offset", "limit"],
            "write_file": ["path", "create_directories", "content"],
            "edit": ["path", "replace_all", "old_string", "new_string"],
            "shell": ["command", "timeout", "cwd"],
            "list_dir": ["path", "include_hidden"],
            "grep": ["path", "case_insensitive", "pattern"],
            "glob": ["path", "pattern"],
        }

        preferred = preferred_order.get(tool_name, [])
        ordered: list[tuple[str, Any]] = []
        seen: set[str] = set()

        for key in preferred:
            if key in args:
                ordered.append((key, args[key]))
                seen.add(key)

        for key, value in args.items():
            if key not in seen:
                ordered.append((key, value))

        return ordered

    def _display_path(self, path: str) -> str:
        try:
            base = self.config.cwd.resolve()
            target = Path(path).expanduser().resolve()
            return str(target.relative_to(base))
        except Exception:
            return path

    def _render_args_table(self, tool_name: str, args: dict[str, Any]) -> Table:
        table = Table.grid(padding=(0, 1))
        table.add_column(style="#7d8aa5", justify="right", no_wrap=True)
        table.add_column(style="#d5d9e2", overflow="fold")

        for key, value in self._ordered_args(tool_name, args):
            if key in {"path", "cwd"} and isinstance(value, str):
                value = self._display_path(value)
            elif isinstance(value, str) and key in {"content", "old_string", "new_string"}:
                line_count = len(value.splitlines())
                byte_count = len(value.encode("utf-8", errors="replace"))
                value = f"<{line_count} lines, {byte_count} bytes>"
            elif not isinstance(value, str):
                value = str(value)
            table.add_row(key, value)

        return table

    def _truncate_for_tool(self, name: str, text: str) -> tuple[str, bool]:
        if not text:
            return "", False

        max_lines_by_tool = {
            "read_file": 28,
            "write_file": 40,
            "edit": 40,
            "list_dir": 32,
            "glob": 32,
            "grep": 52,
            "shell": 42,
            "web_fetch": 46,
        }
        max_chars_by_tool = {
            "read_file": 4200,
            "write_file": 5200,
            "edit": 5200,
            "list_dir": 3200,
            "glob": 3200,
            "grep": 7200,
            "shell": 6400,
            "web_fetch": 7200,
        }

        max_lines = max_lines_by_tool.get(name, 36)
        max_chars = max_chars_by_tool.get(name, 5600)

        clipped = text
        was_truncated = False

        lines = clipped.splitlines()
        if len(lines) > max_lines:
            clipped = "\n".join(lines[:max_lines])
            was_truncated = True

        if len(clipped) > max_chars:
            clipped = clipped[:max_chars]
            was_truncated = True

        return clipped, was_truncated

    def _extract_read_file_code(self, text: str) -> tuple[int, str] | None:
        body = text
        header_match = re.match(r"Showing lines (\d+)-(\d+) of (\d+)\n\n", text)
        if header_match:
            body = text[header_match.end() :]

        code_lines: list[str] = []
        start_line: int | None = None
        for line in body.splitlines():
            match = re.match(r"^\s*(\d+)\|(.*)$", line)
            if not match:
                return None
            line_no = int(match.group(1))
            if start_line is None:
                start_line = line_no
            code_lines.append(match.group(2))

        if start_line is None:
            return None
        return start_line, "\n".join(code_lines)

    def _guess_language(self, path: str | None) -> str:
        if not path:
            return "text"
        ext = Path(path).suffix.lower()
        return {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".js": "javascript",
            ".jsx": "jsx",
            ".json": "json",
            ".md": "markdown",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".toml": "toml",
            ".css": "css",
            ".html": "html",
            ".sh": "bash",
            ".diff": "diff",
            ".patch": "diff",
        }.get(ext, "text")

    def _looks_like_markdown(self, text: str) -> bool:
        if "```" in text:
            return True
        return bool(re.search(r"(?m)^(#{1,6}\s|\* |\d+\.\s|>\s)", text))

    def _looks_like_json(self, text: str) -> bool:
        stripped = text.strip()
        return (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        )

    def _render_list_dir_output(self, output: str) -> Text:
        def strip_existing_icon(text: str) -> str:
            cleaned = text.lstrip()
            while cleaned and cleaned[0] in {
                "📁",
                "📂",
                "📄",
                "🗀",
                "🗁",
                "🗂",
                "🗃",
                "🗄",
                "🗋",
                "🗎",
            }:
                cleaned = cleaned[1:].lstrip()
            return cleaned

        result = Text()
        for raw_line in output.splitlines():
            line = strip_existing_icon(raw_line.rstrip())
            if not line:
                result.append("\n")
                continue
            if line.endswith("/"):
                result.append("📁 ", style="#9bc7ff")
                result.append(line, style="#dce6ff")
            else:
                result.append("📄 ", style="#9da9bd")
                result.append(line, style="#d5d9e2")
            result.append("\n")
        return result

    def _render_grep_output(self, output: str) -> Any:
        groups: list[tuple[str, list[str]]] = []
        current_file: str | None = None
        current_lines: list[str] = []

        for raw in output.splitlines():
            line = raw.rstrip()
            if line.startswith("=== ") and line.endswith(" ==="):
                if current_file is not None:
                    groups.append((current_file, current_lines))
                current_file = line[4:-4].strip()
                current_lines = []
                continue
            if current_file is not None and line:
                current_lines.append(line)
        if current_file is not None:
            groups.append((current_file, current_lines))

        if not groups:
            return Syntax(output, "text", theme="monokai", word_wrap=True)

        table = Table.grid(padding=(0, 1))
        table.add_column(style="#8c97ab", justify="right", no_wrap=True)
        table.add_column(style="#d5d9e2")

        for file_path, lines in groups:
            table.add_row("", Text(self._display_path(file_path), style="bold #9bc7ff"))
            for line in lines:
                match = re.match(r"^\s*(\d+):(.*)$", line)
                if match:
                    table.add_row(match.group(1), Text(match.group(2).lstrip(), style="#d5d9e2"))
                else:
                    table.add_row("", Text(line, style="#d5d9e2"))
            table.add_row("", Text(""))

        return table

    def _render_text_payload(self, text: str, *, success: bool, language: str = "text") -> Any:
        if not text.strip():
            return Text("No output", style="#8c97ab")
        if "\x1b" in text:
            return Text.from_ansi(text)
        if success and self._looks_like_markdown(text):
            return RichMarkdown(text)
        if success and self._looks_like_json(text):
            try:
                payload = json.loads(text)
            except Exception:
                pass
            else:
                return Syntax(
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    "json",
                    theme="monokai",
                    word_wrap=True,
                )
        return Syntax(text, language, theme="monokai", word_wrap=True)

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
        await self.add_assistant_card("You", RichMarkdown(message), css_class="user")

    async def add_assistant_message(self, message: str) -> None:
        await self.add_assistant_card("iTE", RichMarkdown(message), css_class="assistant")

    def post_system(self, title: str, message: str, is_error: bool = False) -> None:
        css_class = "system error" if is_error else "system"
        self.run_worker(self.add_assistant_card(title, message, css_class=css_class), exclusive=False)

    async def add_assistant_card(self, title: str, body: Any, css_class: str = "assistant") -> None:
        conversation = self.query_one("#conversation", VerticalScroll)

        body_widget = Static(classes=f"card-body {css_class}-body")
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

        card = Static(classes="block tool running")
        border_style = "#2a6edb"
        title_text = activity_title(name, stage="start")
        narrative = describe_tool_activity(name, arguments, stage="start")

        blocks: list[Any] = [Text(narrative, style="#8c97ab")]
        if arguments:
            blocks.extend([Text(""), self._render_args_table(name, arguments)])
        else:
            blocks.extend([Text(""), Text("(no args)", style="#8c97ab")])

        header = Text()
        header.append("⌛ ", style="bold #9bc7ff")
        header.append(title_text, style="bold #9bc7ff")
        header.append("  running", style="#8c97ab")
        card.update(Group(header, Text(""), *blocks))
        self._tool_widgets[call_id] = card

        await conversation.mount(card)
        self._message_count += 1
        self._refresh_empty_state()
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
        args = self._tool_args_by_call_id.get(call_id, {})
        narrative = describe_tool_activity(
            name,
            args,
            metadata if isinstance(metadata, dict) else {},
            stage="complete",
            success=success,
        )

        border_style = "#2f9e63" if success else "#b23a3a"
        title_style = "bold #a9ebbe" if success else "bold #ffb0b0"
        title_text = activity_title(name, stage="complete", success=success)

        blocks: list[Any] = [Text(narrative, style="#8c97ab"), Text("")]

        payload = output if success else (error or output)
        payload = payload or ""
        local_truncated = False
        md = metadata if isinstance(metadata, dict) else {}
        primary_path = md.get("path") if isinstance(md.get("path"), str) else None

        if name == "read_file" and success:
            extracted = self._extract_read_file_code(payload) if primary_path else None
            if primary_path and extracted is not None:
                start_line, code = extracted
                code_display, was_truncated = self._truncate_for_tool(name, code)
                local_truncated = local_truncated or was_truncated
                blocks.append(Text(self._display_path(primary_path), style="#8c97ab"))
                blocks.append(Text(""))
                language = self._guess_language(primary_path)
                if language == "markdown":
                    blocks.append(RichMarkdown(code_display))
                else:
                    blocks.append(
                        Syntax(
                            code_display,
                            language,
                            theme="monokai",
                            line_numbers=True,
                            start_line=start_line,
                            word_wrap=False,
                        )
                    )
            else:
                output_display, was_truncated = self._truncate_for_tool(name, payload)
                local_truncated = local_truncated or was_truncated
                blocks.append(self._render_text_payload(output_display, success=True))
        elif name in {"write_file", "edit"} and success and diff:
            if payload.strip():
                blocks.append(Text(payload.strip(), style="#d9dee8"))
                blocks.append(Text(""))
            diff_display, was_truncated = self._truncate_for_tool(name, diff)
            local_truncated = local_truncated or was_truncated
            blocks.append(Syntax(diff_display, "diff", theme="monokai", word_wrap=True))
        elif name == "shell":
            command = args.get("command")
            if isinstance(command, str) and command.strip():
                blocks.append(Text(f"$ {command.strip()}", style="#8c97ab"))
            if exit_code is not None:
                blocks.append(Text(f"exit code {exit_code}", style="#8c97ab"))
            if command or exit_code is not None:
                blocks.append(Text(""))

            output_display, was_truncated = self._truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            if output_display.strip():
                blocks.append(self._render_text_payload(output_display, success=success))
            else:
                blocks.append(Text("No output", style="#8c97ab"))
        elif name in {"list_dir", "glob", "grep"}:
            output_display, was_truncated = self._truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            if name == "list_dir":
                blocks.append(self._render_list_dir_output(output_display))
            elif name == "grep":
                blocks.append(self._render_grep_output(output_display))
            else:
                blocks.append(self._render_text_payload(output_display, success=success))
        else:
            output_display, was_truncated = self._truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            if diff:
                diff_display, diff_truncated = self._truncate_for_tool(name, diff)
                local_truncated = local_truncated or diff_truncated
                blocks.append(Syntax(diff_display, "diff", theme="monokai", word_wrap=True))
            elif output_display.strip():
                blocks.append(self._render_text_payload(output_display, success=success))
            else:
                blocks.append(Text("No output", style="#8c97ab"))

        if local_truncated or truncated:
            blocks.extend([Text(""), Text("... [truncated]", style="#f5b54f")])

        header = Text()
        header.append(f"{icon} ", style=title_style)
        header.append(title_text, style=title_style)
        header.append(
            "  "
            + status
            + (f" · exit {exit_code}" if exit_code is not None else ""),
            style="#8c97ab",
        )

        card.update(Group(header, Text(""), *blocks))
        card.remove_class("running")
        if success:
            card.add_class("success")
        else:
            card.add_class("error")

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
            question_number = int(
                payload.get("question_number")
                or (
                    (self.agent.session.plan_questions_asked + 1)
                    if self.agent and self.agent.session
                    else 1
                )
            )

            result = await self._open_modal(
                PlanQuestionModal(
                    question_number=question_number,
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
        self.refresh_header()

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
            self.refresh_header()

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
