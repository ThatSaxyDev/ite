from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.syntax import Syntax
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, Static, TextArea

from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.agent.session import Session
from ite.agent.session_manager import SessionManager, SessionSnapshot
from ite.commands import build_registry
from ite.config.config import Config

from .adapters.registry import build_command_context


class ConfirmModal(ModalScreen[bool]):
    def __init__(self, title: str, body: str, yes_label: str = "Approve", no_label: str = "Deny") -> None:
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

    def print_welcome(self, model: str = "", cwd: str = "", commands: list[str] | None = None, version: str = "0.0.3") -> None:
        msg = f"ITE Reup ready\nModel: {model or 'not set'}\nWorkspace: {cwd}\nVersion: {version}"
        if commands:
            msg += "\nCommands: " + ", ".join(commands)
        self._app.post_system("Welcome", msg)

    def tool_call_start(self, call_id: str, name: str, tool_kind: str | None, arguments: dict[str, Any]) -> None:
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="shell"):
            with Horizontal(id="topbar"):
                yield Static("iTE Reup", id="title")
                yield Static("", id="header-meta")
            yield VerticalScroll(id="conversation")
            with Horizontal(id="composer"):
                yield TextArea(id="prompt", language="markdown")
                with Vertical(id="composer-actions"):
                    yield Button("Send", id="send", variant="primary")
                    yield Button("Stop", id="stop", variant="warning")
        yield Footer()

    async def on_mount(self) -> None:
        self.refresh_header()
        await self.ensure_agent()
        self.post_system(
            "Welcome",
            f"Textual TUI enabled via --reup\nModel: {self.config.model_name}\nWorkspace: {self.config.cwd}",
        )
        self.query_one("#prompt", TextArea).focus()

    async def on_unmount(self) -> None:
        await self.cancel_active_turn()
        if self.agent is not None:
            await self.agent.__aexit__(None, None, None)
            self.agent = None

    def refresh_header(self) -> None:
        meta = self.query_one("#header-meta", Static)
        meta.update(f"Model: {self.config.model_name}  |  Workspace: {self.config.cwd}")

    async def ensure_agent(self) -> None:
        if self.agent is not None:
            return
        self.agent = Agent(
            config=self.config,
            confirmation_callback=self.confirmation_callback,
            plan_question_callback=self.plan_question_callback,
        )
        await self.agent.__aenter__()

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

    @on(Button.Pressed, "#stop")
    async def on_stop_button(self, _event: Button.Pressed) -> None:
        await self.cancel_active_turn()

    async def handle_send(self) -> None:
        if self._is_turn_running:
            await self.cancel_active_turn()
            return

        prompt = self.query_one("#prompt", TextArea)
        message = prompt.text.strip()
        if not message:
            return

        prompt.text = ""

        if message.startswith("/"):
            await self.run_command(message)
            return

        await self.run_agent_message(message)

    async def run_command(self, command_line: str) -> None:
        parts = command_line.split()
        command = parts[0].lower()
        args = parts[1:]

        if command in {"/exit", "/quit"}:
            self.exit()
            return

        # Avoid curses picker inside Textual app.
        if command == "/sessions" and "--list" not in args:
            args.append("--list")

        await self.ensure_agent()
        if not self.agent:
            self.post_system("Error", "Agent is not initialized")
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

        try:
            await self._active_turn_task
            await self.auto_save()
        except asyncio.CancelledError:
            self.post_system("Interrupted", "Turn was interrupted.")
        finally:
            self._active_turn_task = None
            self._is_turn_running = False

    async def _agent_turn(self, message: str) -> None:
        assert self.agent is not None

        async for event in self.agent.run(message):
            await self.handle_agent_event(event)

    async def handle_agent_event(self, event: AgentEvent) -> None:
        if event.type == AgentEventType.TEXT_DELTA:
            content = event.data.get("content", "")
            await self.stream_assistant_delta(content)
            return

        if event.type == AgentEventType.TEXT_COMPLETE:
            content = event.data.get("content", "")
            if self._streaming_widget is not None:
                await self.finalize_streaming_message()
            elif content:
                await self.add_assistant_message(content)
            return

        if event.type == AgentEventType.AGENT_ERROR:
            self.post_system("Error", str(event.data.get("error", "Unknown error")), is_error=True)
            return

        if event.type == AgentEventType.TOOL_CALL_START:
            tool_name = event.data.get("name", "tool")
            if tool_name in {"memory", "plan_question"}:
                return
            tool_kind = self.get_tool_kind(tool_name)
            await self.add_tool_call_start(
                call_id=event.data.get("call_id", ""),
                name=tool_name,
                tool_kind=tool_kind,
                arguments=event.data.get("arguments", {}),
            )
            return

        if event.type == AgentEventType.TOOL_CALL_COMPLETE:
            tool_name = event.data.get("name", "tool")
            if tool_name in {"memory", "plan_question"}:
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
            return

        if event.type == AgentEventType.PLAN_READY:
            plan_text = event.data.get("plan_text", "")
            await self.add_assistant_card("Plan", RichMarkdown(plan_text))
            approved = await self.push_screen_wait(
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
        if isinstance(body, str):
            body_widget.update(body)
        else:
            body_widget.update(body)

        card = Container(
            Static(title, classes="card-title"),
            body_widget,
            classes=f"block {css_class}",
        )

        await conversation.mount(card)
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

        approved = await self.push_screen_wait(
            ConfirmModal(
                title=f"Approval required: {confirmation.tool_name}",
                body=body,
                yes_label="Approve",
                no_label="Deny",
            )
        )
        return bool(approved)

    async def plan_question_callback(self, payload: dict[str, Any]) -> dict[str, Any]:
        question = str(payload.get("question", "")).strip()
        options = [str(o) for o in payload.get("options", []) if str(o).strip()]
        recommended_index = payload.get("recommended_index")
        allow_free_text = bool(payload.get("allow_free_text", True))

        result = await self.push_screen_wait(
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

        self.post_system("New Thread", "Started a fresh session.")

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
