from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static, TextArea
from textual.widget import Widget

from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.agent.session import Session
from ite.agent.session_manager import SessionManager, SessionSnapshot
from ite.commands import build_registry
from ite.config.config import Config
from ite.config.config import ApprovalPolicy
from ite.config.loader import save_global_approval_mode, save_system_config
from ite.git.branches import (
    checkout_branch,
    create_and_checkout,
    current_branch,
    is_git_repo,
    list_local_branches,
)
from ite.attachments import MAX_ATTACHMENTS
from ite.commands.aside import execute_aside, is_aside_command_text
from ite.ui.tool_narrative import activity_title, describe_tool_activity, progress_label

from .adapters.registry import build_command_context
from .change_views import build_change_card_body
from .composer_views import (
    SlashCommandOption,
    build_command_palette_options,
    build_empty_state_title,
    build_turn_action_options,
    build_turn_payload,
    composer_meta_text,
    filtered_command_palette,
    render_command_palette,
    render_turn_action_palette,
)
from .modals import (
    AttachPickerModal,
    BranchPickerModal,
    ConfirmModal,
    PlanQuestionModal,
    SessionResumeModal,
    SetupModal,
)
from .tool_views import (
    display_path,
    extract_read_file_code,
    guess_language,
    render_args_table,
    render_grep_output,
    render_list_dir_output,
    render_shell_command_line,
    render_shell_result_payload,
    render_shell_running_card,
    render_text_payload,
    render_todo_payload,
    todo_start_hint,
    truncate_for_tool,
)


class ReupPromptTextArea(TextArea):
    class Submitted(Message):
        pass

    BINDINGS = []

    def action_submit(self) -> None:
        self.post_message(self.Submitted())

    def action_newline(self) -> None:
        self.insert("\n")

    def on_key(self, event: events.Key) -> None:
        handler = getattr(self.app, "handle_prompt_palette_key", None)
        if callable(handler) and handler(event):
            event.stop()
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            return
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
        version: str = "0.0.13",
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
        Binding("ctrl+c", "interrupt_or_quit", "Interrupt", priority=True),
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
    COMMAND_PALETTE_MAX_ROWS = 8

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.title = "iTE"
        self.config = config
        self.agent: Agent | None = None
        self._command_registry = build_registry()
        self._active_turn_task: asyncio.Task | None = None
        self._active_turn_id: int = 0
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
        self._activity_suffix_frames: tuple[str, ...] = ("", ".", "..", "...")
        self._activity_suffix_index: int = 0
        self._top_state_text: str = ""
        self._activity_widget: Static | None = None
        self._activity_version: int = 0
        self._plan_ready_future: asyncio.Future[bool] | None = None
        self._plan_ready_action_card: Widget | None = None
        self._plan_question_future: asyncio.Future[dict[str, Any]] | None = None
        self._plan_question_card: Widget | None = None
        self._plan_question_options: list[str] = []
        self._plan_question_number: int = 0
        self._plan_question_prompt: str = ""
        self._plan_question_option_buttons: list[Button] = []
        self._plan_question_custom_input: Input | None = None
        self._plan_question_custom_submit: Button | None = None
        self._plan_question_status: Static | None = None
        self._plan_question_recommended_index: int | None = None
        self._composer_attach_hitbox: tuple[int, int] = (0, 0)
        self._composer_plan_hitbox: tuple[int, int] = (0, 0)
        self._composer_branch_hitbox: tuple[int, int] = (0, 0)
        self._command_palette_options = self._build_command_palette_options()
        self._filtered_command_palette_options: list[SlashCommandOption] = []
        self._command_palette_index: int = 0
        self._command_palette_rows: int = 0
        self._turn_action_payload: dict[str, Any] | None = None
        self._turn_action_replacing_queue: bool = False
        self._turn_action_options: list[SlashCommandOption] = []
        self._last_rendered_plan_text: str | None = None
        self._aside_panel_visible: bool = False
        self._aside_entries: list[dict[str, str]] = []
        self._aside_entry_seq: int = 0
        self._aside_pending_widgets: dict[str, Static] = {}
        self._queued_turn_payload: dict[str, Any] | None = None
        self._turn_had_error: bool = False
        self._suppress_pending_restore_once: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="shell"):
            with Horizontal(id="topbar"):
                yield Static("New thread", id="title")
                yield Static("", id="header-meta")
                yield Button("/aside", id="aside-toggle", variant="default")
            with Container(id="chat-panel"):
                with Horizontal(id="chat-body"):
                    with Container(id="conversation-shell"):
                        yield VerticalScroll(id="conversation")
                        yield Static("", id="empty-state")
                    with Container(id="aside-panel"):
                        with Horizontal(id="aside-panel-header"):
                            yield Static("Aside", id="aside-panel-title")
                        yield VerticalScroll(id="aside-panel-body")
            with Horizontal(id="composer"):
                with Container(id="prompt-container"):
                    yield ReupPromptTextArea(id="prompt", language="markdown")
                    yield Static("", id="command-palette")
                    yield Static("", id="composer-gap")
                    yield Static("", id="composer-meta-line")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#aside-toggle", Button).display = False
        self.refresh_header()
        self._set_loading_state("idle", busy=False)
        self._refresh_empty_state()
        self._resize_composer_for_prompt()
        self._apply_aside_panel_state()
        self.set_interval(0.1, self._tick_top_indicator)
        if self.config.needs_setup:
            completed = await self._open_setup_modal(exit_on_cancel=True)
            if not completed:
                return
        await self.ensure_agent()
        self.query_one("#prompt", TextArea).focus()
        self._sync_command_palette("")

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
        composer_meta_line = self.query_one("#composer-meta-line", Static)
        composer_meta_line.update(self._composer_meta_text())

    async def _show_activity_indicator(self, label: str, version: int | None = None) -> None:
        if version is not None and version != self._activity_version:
            return
        conversation = self.query_one("#conversation", VerticalScroll)
        content = self._render_activity_indicator_text(label)
        if self._activity_widget is None:
            self._activity_widget = Static(classes="activity-indicator")
            await conversation.mount(self._activity_widget)
            self._message_count += 1
            self._refresh_empty_state()
        if version is not None and version != self._activity_version:
            return
        self._activity_widget.update(content)
        conversation.scroll_end(animate=False)

    async def _hide_activity_indicator(self, version: int | None = None) -> None:
        if version is not None and version != self._activity_version:
            return
        if self._activity_widget is None:
            return
        try:
            await self._activity_widget.remove()
        except Exception:
            pass
        self._activity_widget = None
        self._message_count = max(0, self._message_count - 1)
        self._refresh_empty_state()

    def _render_activity_indicator_text(self, label: str) -> Text:
        frame = self._top_spinner_frames[self._top_spinner_index % len(self._top_spinner_frames)]
        suffix = self._activity_suffix_frames[
            self._activity_suffix_index % len(self._activity_suffix_frames)
        ]
        content = Text()
        content.append(frame, style="bold #b8d8ff")
        content.append(" ")
        content.append(label, style="bold #eef4ff")
        content.append(suffix, style="bold #b8d8ff")
        return content

    def _composer_meta_text(self) -> Text:
        plan_enabled = bool(self.agent and self.agent.session and self.agent.session.plan_mode_enabled)
        branch_label = "no-git"
        attachment_count = 0
        if self.agent and self.agent.session:
            attachment_count = len(self.agent.session.pending_attachment_paths)
        try:
            cwd = Path(self.config.cwd).resolve()
            if is_git_repo(cwd):
                branch_label = current_branch(cwd)
        except Exception:
            pass
        text, attach_hitbox, branch_hitbox, plan_hitbox = composer_meta_text(
            cwd=Path(self.config.cwd),
            model_name=self.config.model_name,
            attachment_count=attachment_count,
            plan_enabled=plan_enabled,
            branch_label=branch_label,
        )
        self._composer_attach_hitbox = attach_hitbox
        self._composer_branch_hitbox = branch_hitbox
        self._composer_plan_hitbox = plan_hitbox
        return text

    def _build_command_palette_options(self) -> list[SlashCommandOption]:
        return build_command_palette_options(self._command_registry)

    @staticmethod
    def _extract_slash_query(text: str) -> str | None:
        from .composer_views import extract_slash_query

        return extract_slash_query(text)

    def _filtered_command_palette(self, text: str) -> list[SlashCommandOption]:
        return filtered_command_palette(
            text,
            command_palette_options=self._command_palette_options,
        )

    def _command_palette_window(self) -> list[SlashCommandOption]:
        if not self._filtered_command_palette_options:
            return []
        max_rows = min(self.COMMAND_PALETTE_MAX_ROWS, len(self._filtered_command_palette_options))
        start = max(0, self._command_palette_index - max_rows + 1)
        end = min(len(self._filtered_command_palette_options), start + max_rows)
        start = max(0, end - max_rows)
        return self._filtered_command_palette_options[start:end]

    def _render_command_palette(self) -> Text:
        return render_command_palette(
            filtered_options=self._filtered_command_palette_options,
            command_palette_index=self._command_palette_index,
            max_rows=self.COMMAND_PALETTE_MAX_ROWS,
        )

    def _build_turn_action_options(self, *, replacing_queue: bool) -> list[SlashCommandOption]:
        return build_turn_action_options(replacing_queue=replacing_queue)

    def _render_turn_action_palette(self) -> Text:
        return render_turn_action_palette(self._turn_action_options, self._command_palette_index)

    def _show_turn_action_palette(self, payload: dict[str, Any], *, replacing_queue: bool) -> None:
        self._turn_action_payload = payload
        self._turn_action_replacing_queue = replacing_queue
        self._turn_action_options = self._build_turn_action_options(replacing_queue=replacing_queue)
        self._command_palette_index = 0
        self._command_palette_rows = len(self._turn_action_options)
        if not self.is_mounted:
            return
        try:
            palette = self.query_one("#command-palette", Static)
        except Exception:
            return
        palette.display = True
        palette.update(self._render_turn_action_palette())
        self._resize_composer_for_prompt()

    def _hide_turn_action_palette(self) -> None:
        self._turn_action_payload = None
        self._turn_action_replacing_queue = False
        self._turn_action_options = []
        self._sync_command_palette(self.query_one("#prompt", TextArea).text)
        self._resize_composer_for_prompt()

    def _move_turn_action_selection(self, delta: int) -> bool:
        if not self._turn_action_options:
            return False
        self._command_palette_index = max(
            0,
            min(len(self._turn_action_options) - 1, self._command_palette_index + delta),
        )
        if self.is_mounted:
            try:
                self.query_one("#command-palette", Static).update(self._render_turn_action_palette())
            except Exception:
                pass
        return True

    async def _execute_turn_action_selection(self, action: str) -> None:
        payload = self._turn_action_payload
        replacing_queue = self._turn_action_replacing_queue
        self._hide_turn_action_palette()
        if payload is None:
            return
        if action == "steer":
            self.post_notice("Shift", "Stopping current turn. Sending next.")
            self._restore_payload_to_composer(payload)
            await self.action_interrupt_or_quit()
            if self._is_turn_running:
                return
            await self.handle_send()
            return
        if action == "queue":
            self._queued_turn_payload = payload
            self._clear_composer_after_submit(clear_attachments=True)
            if replacing_queue:
                self.post_notice("Queue", "Queued. Replaced previous draft.")
            else:
                self.post_notice("Queue", "Queued for after the current turn.")
            return
        if action == "aside":
            message = str(payload.get("message", "")).strip()
            if not message:
                return
            self.post_notice("Aside", "Sending in the side panel.")
            aside_payload = dict(payload)
            aside_payload["message"] = f"/aside {message}"
            self._restore_payload_to_composer(aside_payload)
            await self.handle_send()
            return

    def _sync_command_palette(self, text: str) -> None:
        if self._turn_action_payload is not None:
            return
        options = self._filtered_command_palette(text)
        if self._filtered_command_palette_options == options and (
            not options or self._command_palette_index < len(options)
        ):
            self._command_palette_rows = min(len(options), self.COMMAND_PALETTE_MAX_ROWS)
        else:
            self._filtered_command_palette_options = options
            self._command_palette_index = 0
            self._command_palette_rows = min(len(options), self.COMMAND_PALETTE_MAX_ROWS)

        if not self.is_mounted:
            return

        try:
            palette = self.query_one("#command-palette", Static)
        except Exception:
            return
        palette.display = bool(options)
        if options:
            palette.update(self._render_command_palette())
        else:
            palette.update("")

    def _move_command_palette_selection(self, delta: int) -> bool:
        if self._turn_action_payload is not None:
            return self._move_turn_action_selection(delta)
        if not self._filtered_command_palette_options:
            return False
        self._command_palette_index = max(
            0,
            min(
                len(self._filtered_command_palette_options) - 1,
                self._command_palette_index + delta,
            ),
        )
        if self.is_mounted:
            try:
                self.query_one("#command-palette", Static).update(self._render_command_palette())
            except Exception:
                pass
        return True

    def _replace_prompt_with_command(self, command_name: str) -> None:
        prompt = self.query_one("#prompt", TextArea)
        updated = f"{command_name} "
        prompt.load_text(updated)
        prompt.move_cursor((0, len(updated)))
        self._sync_command_palette(updated)
        self._resize_composer_for_prompt()

    async def _execute_command_palette_selection(self, command_name: str) -> None:
        prompt = self.query_one("#prompt", TextArea)
        prompt.load_text("")
        self._sync_command_palette("")
        self._resize_composer_for_prompt()
        await self.run_command(command_name)

    def _apply_command_palette_selection(self) -> bool:
        if self._turn_action_payload is not None:
            if not self._turn_action_options:
                return False
            action = ("steer", "queue", "aside", "cancel")[self._command_palette_index]
            self.run_worker(self._execute_turn_action_selection(action), exclusive=False)
            return True
        if not self._filtered_command_palette_options:
            return False
        option = self._filtered_command_palette_options[self._command_palette_index]
        self.run_worker(
            self._execute_command_palette_selection(option.name),
            exclusive=False,
        )
        return True

    def handle_prompt_palette_key(self, event: events.Key) -> bool:
        focused = self.focused
        if not isinstance(focused, TextArea) or focused.id != "prompt":
            return False
        if self._turn_action_payload is not None:
            if event.key == "up":
                return self._move_turn_action_selection(-1)
            if event.key == "down":
                return self._move_turn_action_selection(1)
            if event.key in {"tab", "enter"}:
                return self._apply_command_palette_selection()
            if event.key in {"1", "2", "3", "4"}:
                self._command_palette_index = int(event.key) - 1
                return self._apply_command_palette_selection()
            if event.key == "escape":
                self._hide_turn_action_palette()
                return True
            return False
        if not self._filtered_command_palette_options:
            return False
        if event.key == "up":
            return self._move_command_palette_selection(-1)
        if event.key == "down":
            return self._move_command_palette_selection(1)
        if event.key in {"tab", "enter"}:
            return self._apply_command_palette_selection()
        if event.key == "escape":
            self._sync_command_palette("")
            self._resize_composer_for_prompt()
            return True
        return False

    @on(events.Click, "#composer-meta-line")
    def on_composer_meta_line_click(self, event: events.Click) -> None:
        attach_start, attach_end = self._composer_attach_hitbox
        branch_start, branch_end = self._composer_branch_hitbox
        start, end = self._composer_plan_hitbox
        if attach_start <= event.x < attach_end:
            self.run_worker(self._open_attach_picker_from_meta(), exclusive=False)
            event.stop()
            return
        if branch_start <= event.x < branch_end:
            self.run_worker(self._open_branch_picker_from_meta(), exclusive=False)
            event.stop()
            return
        if start <= event.x < end:
            self.run_worker(self._toggle_plan_mode_from_meta(), exclusive=False)
            event.stop()

    @on(events.Click, "#command-palette")
    def on_command_palette_click(self, event: events.Click) -> None:
        if self._turn_action_payload is None:
            return
        row = max(0, min(len(self._turn_action_options) - 1, event.y))
        self._command_palette_index = row
        event.stop()
        action = ("steer", "queue", "aside", "cancel")[row]
        self.run_worker(self._execute_turn_action_selection(action), exclusive=False)

    async def _toggle_plan_mode_from_meta(self) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            return
        session = self.agent.session
        target = "off" if session.plan_mode_enabled else "on"
        await self._run_plan_command_native([target])

    async def _open_branch_picker_from_meta(self) -> None:
        cwd = Path(self.config.cwd).resolve()
        if not await asyncio.to_thread(is_git_repo, cwd):
            self.post_system("Branch", "Current workspace is not a git repository.", is_error=True)
            return

        branches = await asyncio.to_thread(list_local_branches, cwd)
        current = await asyncio.to_thread(current_branch, cwd)
        result = await self._open_modal(BranchPickerModal(current, branches))
        if not result:
            return

        action = str(result.get("action", "")).strip().lower()
        branch = str(result.get("branch", "")).strip()
        if not branch:
            self.post_system("Branch", "Branch name is required.", is_error=True)
            return

        if action == "create":
            branch_result = await asyncio.to_thread(create_and_checkout, cwd, branch)
        else:
            branch_result = await asyncio.to_thread(checkout_branch, cwd, branch)

        if branch_result.ok:
            self.post_system("Branch", branch_result.message)
        else:
            self.post_system("Branch", branch_result.message, is_error=True)
        self.refresh_header()

    async def _open_attach_picker_from_meta(self) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            return
        cwd = Path(self.config.cwd).resolve()
        queued = list(self.agent.session.pending_attachment_paths)
        files = await asyncio.to_thread(AttachPickerModal._discover_files, cwd)
        selected = await self._open_modal(AttachPickerModal(cwd, queued, files))
        if selected is None:
            return
        self.agent.session.pending_attachment_paths = list(selected)[:MAX_ATTACHMENTS]
        self.refresh_header()

    def _queue_attachment_paths(self, paths: list[str]) -> int:
        if not self.agent or not self.agent.session:
            return 0
        queue = self.agent.session.pending_attachment_paths
        added = 0
        for raw in paths:
            path = str(Path(raw).expanduser().resolve())
            if path in queue:
                continue
            if len(queue) >= MAX_ATTACHMENTS:
                break
            queue.append(path)
            added += 1
        return added

    def _consume_dropped_path_text(self, message: str) -> bool:
        if not self.agent or not self.agent.session:
            return False
        raw = (message or "").strip()
        if not raw:
            return False

        candidates: list[str]
        if "\n" in raw:
            candidates = [
                line.strip().strip('"').strip("'")
                for line in raw.splitlines()
                if line.strip()
            ]
        else:
            try:
                candidates = shlex.split(raw)
            except ValueError:
                candidates = [raw.strip().strip('"').strip("'")]

        if not candidates or len(candidates) > MAX_ATTACHMENTS:
            return False

        paths: list[str] = []
        for candidate in candidates:
            if not any(sep in candidate for sep in ("/", "\\")) and not candidate.startswith("~"):
                return False
            path = Path(candidate).expanduser()
            if not path.exists() or not path.is_file():
                return False
            paths.append(str(path))

        added = self._queue_attachment_paths(paths)
        self.refresh_header()
        if added > 0:
            noun = "file" if added == 1 else "files"
            self.post_attachment_note(f"Queued {added} {noun} for the next message.")
        return True

    def _build_empty_state_title(self) -> str:
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
        return build_empty_state_title(cwd=Path(self.config.cwd), thread_count=thread_count)

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
        self._top_state_text = state
        self._top_busy = busy
        self._activity_version += 1
        version = self._activity_version
        if busy:
            self.run_worker(self._show_activity_indicator(state, version), exclusive=False)
        else:
            self.run_worker(self._hide_activity_indicator(version), exclusive=False)

        try:
            prompt = self.query_one("#prompt", TextArea)
        except NoMatches:
            return
        prompt.disabled = False
        self._refresh_empty_state()

    def _apply_aside_panel_state(self) -> None:
        panel = self.query_one("#aside-panel", Container)
        body = self.query_one("#aside-panel-body", VerticalScroll)
        has_content = bool(self._aside_entries)
        panel.display = self._aside_panel_visible and has_content
        toggle = self.query_one("#aside-toggle", Button)
        toggle.display = has_content
        toggle.label = "/aside" if not self._aside_panel_visible else "Close"
        body.display = has_content

    def _render_aside_pending_text(self) -> Text:
        text = Text("Thinking", style="#8fdad4 italic")
        suffix = self._activity_suffix_frames[
            self._activity_suffix_index % len(self._activity_suffix_frames)
        ]
        text.append(suffix, style="#8fdad4 italic")
        return text

    async def _render_aside_panel(self) -> None:
        body = self.query_one("#aside-panel-body", VerticalScroll)
        await body.remove_children()
        self._aside_pending_widgets = {}
        for entry in self._aside_entries:
            state = str(entry.get("state", "done")).strip().lower()
            question = str(entry.get("question", "")).strip()
            answer = str(entry.get("answer", "")).strip()
            entry_id = str(entry.get("id", "")).strip()
            user_row = Horizontal(
                Static(question, classes="aside-user-entry"),
                classes="aside-user-row",
            )
            if state == "pending":
                response_widget = Static(
                    self._render_aside_pending_text(),
                    classes="aside-thinking",
                )
                if entry_id:
                    self._aside_pending_widgets[entry_id] = response_widget
            elif state == "error":
                response_widget = Static(answer, classes="aside-error")
            else:
                response_widget = Static(RichMarkdown(answer), classes="aside-assistant-body")
            await body.mount(Vertical(user_row, response_widget, classes="aside-thread"))
        self._apply_aside_panel_state()
        body.scroll_end(animate=False)

    async def _push_aside_entry(self, question: str, answer: str) -> None:
        self._aside_entries.append({"question": question, "answer": answer, "state": "done"})
        self._aside_panel_visible = True
        await self._render_aside_panel()

    async def _create_pending_aside_entry(self, question: str) -> str:
        self._aside_entry_seq += 1
        entry_id = f"aside-{self._aside_entry_seq}"
        self._aside_entries.append(
            {
                "id": entry_id,
                "question": question,
                "answer": "Thinking...",
                "state": "pending",
            }
        )
        self._aside_panel_visible = True
        await self._render_aside_panel()
        return entry_id

    async def _complete_aside_entry(self, entry_id: str, *, answer: str, state: str = "done") -> None:
        for entry in self._aside_entries:
            if str(entry.get("id", "")) == entry_id:
                entry["answer"] = answer
                entry["state"] = state
                break
        await self._render_aside_panel()

    def _toggle_aside_panel(self) -> None:
        if not self._aside_entries:
            return
        self._aside_panel_visible = not self._aside_panel_visible
        self._apply_aside_panel_state()

    @on(Button.Pressed, "#aside-toggle")
    def on_aside_toggle_pressed(self, _event: Button.Pressed) -> None:
        self._toggle_aside_panel()

    async def _apply_setup_result(self, result: dict[str, str]) -> None:
        try:
            save_system_config(
                api_key=result["api_key"],
                base_url=result["base_url"],
                model_name=result["model_name"],
            )
            save_global_approval_mode(result["approval"])
        except Exception as exc:
            self.post_system("Setup failed", str(exc), is_error=True)
            self.exit()
            return

        self.config.api_key = result["api_key"]
        self.config.base_url = result["base_url"]
        self.config.model.name = result["model_name"]
        self.config.approval = ApprovalPolicy(result["approval"])
        self.refresh_header()
        self.post_notice("Setup complete", "Saved credentials and defaults. Reup is ready.")

    async def _open_setup_modal(self, *, exit_on_cancel: bool = False) -> bool:
        result = await self._open_modal(SetupModal(self.config))
        if not result:
            if exit_on_cancel and self.config.needs_setup:
                self.exit()
            return False
        await self._apply_setup_result(result)
        return True

    def _tick_top_indicator(self) -> None:
        if not self._top_busy and not self._aside_pending_widgets:
            return
        self._top_spinner_index += 1
        if self._top_spinner_index % 3 == 0:
            self._activity_suffix_index += 1
        if self._activity_widget is not None and self._top_busy:
            self._activity_widget.update(
                self._render_activity_indicator_text(self._top_state_text)
            )
        if self._aside_pending_widgets:
            pending_text = self._render_aside_pending_text()
            for widget in list(self._aside_pending_widgets.values()):
                widget.update(pending_text)
        for call_id in getattr(self, "_running_shell_call_ids", set()):
            card = self._tool_widgets.get(call_id)
            args = self._tool_args_by_call_id.get(call_id, {})
            if card is not None:
                card.update(
                    render_shell_running_card(
                        args,
                        cwd=self.config.cwd,
                        spinner_index=self._top_spinner_index,
                    )
                )

    def _progress_state_label(
        self,
        *,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        phase: str = "reasoning",
    ) -> str:
        return progress_label(
            tool_name=tool_name,
            arguments=arguments,
            metadata=metadata,
            phase=phase,
            plan_mode=self._is_plan_only_phase(),
        ).lower()

    def _with_implementation_plan_title(self, plan_text: str) -> str:
        text = (plan_text or "").strip()
        if not text:
            return "# Implementation Plan"
        if "implementation plan" in text.lower():
            return text
        return f"# Implementation Plan\n\n{text}"

    @staticmethod
    def _normalize_plan_text(plan_text: str) -> str:
        return (plan_text or "").strip()

    def _should_render_plan_text(self, plan_text: str) -> bool:
        normalized = self._normalize_plan_text(plan_text)
        if not normalized:
            return False
        return normalized != self._last_rendered_plan_text

    async def _render_plan_text_if_needed(self, plan_text: str) -> bool:
        normalized = self._normalize_plan_text(plan_text)
        if not self._should_render_plan_text(normalized):
            return False
        await self.add_assistant_card(
            "Implementation Plan",
            RichMarkdown(self._with_implementation_plan_title(normalized)),
            css_class="plan",
        )
        self._last_rendered_plan_text = normalized
        return True

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

    def _resolve_todo_scope_for_event(
        self,
        *,
        arguments: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if isinstance(metadata, dict) and isinstance(metadata.get("scope"), str):
            return str(metadata.get("scope")).strip().lower()
        if isinstance(arguments, dict) and isinstance(arguments.get("scope"), str):
            return str(arguments.get("scope")).strip().lower()
        if self._is_plan_only_phase():
            return "planning"
        return "execution"

    def _should_hide_todo_scope(self, scope: str) -> bool:
        if scope != "planning":
            return False
        if not self.agent or not self.agent.session:
            return True
        return not bool(self.agent.session.show_planning_todos)

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
            session.seed_execution_todos_from_plan(session.pending_plan_text)
            session.promote_pending_plan_to_active()
            session.set_plan_mode(False)
            session.set_plan_phase("idle")
            self.refresh_header()
            return Agent.PLAN_EXECUTE_PROMPT

        self.post_plan_note(
            "Plan mode",
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
                self.refresh_header()
                self.post_plan_note("Plan mode enabled", "Planning mode is now active for this thread.")
            return message

        if plan_enabled and self._detect_execution_intent(message):
            choice = await self._open_modal(
                ConfirmModal(
                    title="Run In Execution Mode?",
                    body="This prompt looks like execution while Plan mode is ON. Choose the execution option below or type /plan off to leave Plan mode manually.",
                    yes_label="Turn Off Plan Mode",
                    no_label="Stay in Plan Mode",
                )
            )
            if choice is None:
                return None
            if bool(choice):
                session.set_plan_mode(False)
                session.set_plan_phase("idle")
                self.refresh_header()
                self.post_plan_note("Plan mode disabled", "Execution mode is now active.")
                return message

            self.post_plan_note(
                "Staying in plan mode",
                "Continuing in planning mode. I will ask clarifying questions before execution. Type /plan off whenever you want to start executing instead.",
            )
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
        else:
            self.post_notice("Exit", "Use `/exit` or `/quit` to close reup.")

    async def action_send(self) -> None:
        await self.handle_send()

    @on(TextArea.Changed, "#prompt")
    def on_prompt_changed(self, _event: TextArea.Changed) -> None:
        if self._suppress_history_reset_once:
            self._suppress_history_reset_once = False
            self._sync_command_palette(self.query_one("#prompt", TextArea).text)
            self._resize_composer_for_prompt()
            return
        if self._composer_history_index is not None and not self._applying_history_nav:
            self._composer_history_index = None
            self._composer_history_draft = ""
        self._sync_command_palette(self.query_one("#prompt", TextArea).text)
        self._resize_composer_for_prompt()

    async def on_reup_prompt_text_area_submitted(
        self, _event: ReupPromptTextArea.Submitted
    ) -> None:
        await self.handle_send()

    def on_key(self, event: events.Key) -> None:
        # Global modal escape hatch: always allow resolving confirm prompts,
        # even if focus gets stuck or terminal mouse support is flaky.
        if event.key == "ctrl+c":
            self.run_worker(self.action_interrupt_or_quit(), exclusive=False)
            event.stop()
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            return

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
        if self._plan_ready_future is not None and not self._plan_ready_future.done():
            if event.key in {"2", "y"}:
                self._resolve_plan_ready_choice(True)
                event.stop()
                if hasattr(event, "prevent_default"):
                    event.prevent_default()
                return
            if event.key in {"1", "n", "escape", "ctrl+c"}:
                self._resolve_plan_ready_choice(False)
                event.stop()
                if hasattr(event, "prevent_default"):
                    event.prevent_default()
                return

        if self._plan_question_future is not None and not self._plan_question_future.done():
            if event.key in {"escape", "ctrl+c"}:
                self.run_worker(
                    self._resolve_plan_question_choice(
                        selected_index=None, selected_option="", free_text=""
                    ),
                    exclusive=False,
                )
                event.stop()
                if hasattr(event, "prevent_default"):
                    event.prevent_default()
                return

            if event.key.isdigit():
                idx = int(event.key) - 1
                if 0 <= idx < len(self._plan_question_options):
                    self.run_worker(
                        self._resolve_plan_question_choice(
                            selected_index=idx,
                            selected_option=self._plan_question_options[idx],
                            free_text="",
                        ),
                        exclusive=False,
                    )
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
            + self._command_palette_rows
            + self.COMPOSER_GAP_HEIGHT
            + self.META_ROW_HEIGHT
            + self.CONTAINER_EXTRA
        )
        composer_height = container_height + self.COMPOSER_EXTRA

        prompt.styles.height = prompt_height
        prompt_container.styles.height = container_height
        composer.styles.height = composer_height

    def _build_turn_payload(self, message: str) -> dict[str, Any]:
        attachments: list[str] = []
        if self.agent and self.agent.session:
            attachments = list(self.agent.session.pending_attachment_paths)
        return build_turn_payload(message, attachments, max_attachments=MAX_ATTACHMENTS)

    def _clear_composer_after_submit(self, *, clear_attachments: bool = False) -> None:
        prompt = self.query_one("#prompt", TextArea)
        self._record_composer_history(prompt.text.strip())
        self._composer_history_index = None
        self._composer_history_draft = ""
        prompt.text = ""
        self._resize_composer_for_prompt()
        if clear_attachments and self.agent and self.agent.session:
            self.agent.session.pending_attachment_paths = []

    def _restore_payload_to_composer(self, payload: dict[str, Any]) -> None:
        prompt = self.query_one("#prompt", TextArea)
        prompt.text = str(payload.get("message", "")).strip()
        self._resize_composer_for_prompt()
        if self.agent and self.agent.session:
            self.agent.session.pending_attachment_paths = list(payload.get("attachments", []))[:MAX_ATTACHMENTS]

    async def _dispatch_payload(self, payload: dict[str, Any]) -> None:
        message = str(payload.get("message", "")).strip()
        if not message:
            return
        if self.agent and self.agent.session:
            self.agent.session.pending_attachment_paths = list(payload.get("attachments", []))[:MAX_ATTACHMENTS]

        normalized = self._normalize_plan_execution_request(message)
        if normalized is None:
            return
        message = normalized

        if message.startswith("/"):
            await self.run_command(message)
            return

        self.run_worker(
            self._handle_agent_send_with_intent(message),
            exclusive=False,
        )

    async def _resolve_active_turn_send(self, payload: dict[str, Any]) -> bool:
        replacing_queue = self._queued_turn_payload is not None
        self._show_turn_action_palette(payload, replacing_queue=replacing_queue)
        return True

    async def _dispatch_queued_payload_if_ready(self) -> None:
        if self._queued_turn_payload is None:
            return
        payload = self._queued_turn_payload
        self._queued_turn_payload = None
        self.post_notice("Queue", "Sending queued draft.")
        await self._dispatch_payload(payload)

    def _restore_queued_payload_after_unsuccessful_turn(self) -> None:
        if self._suppress_pending_restore_once:
            self._suppress_pending_restore_once = False
            return
        if self._queued_turn_payload is None:
            return
        payload = self._queued_turn_payload
        self._queued_turn_payload = None
        self._restore_payload_to_composer(payload)
        self.post_notice(
            "Queue",
            "Previous turn ended early. Restored queued draft to composer.",
        )

    async def handle_send(self) -> None:
        prompt = self.query_one("#prompt", TextArea)
        message = prompt.text.strip()
        if not message:
            return
        if self._is_turn_running and not is_aside_command_text(message):
            payload = self._build_turn_payload(message)
            handled = await self._resolve_active_turn_send(payload)
            if handled:
                return
            return

        payload = self._build_turn_payload(message)
        self._clear_composer_after_submit()

        if self._consume_dropped_path_text(message):
            return
        await self._dispatch_payload(payload)

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
        resumed.active_plan_text = snapshot.active_plan_text
        resumed.show_planning_todos = snapshot.show_planning_todos

        await self.agent.session.client.close()
        await self.agent.session.mcp_manager.shutdown()
        await resumed.initialize()

        resumed.context_manager.set_messages(snapshot.messages)
        resumed.context_manager.total_usage = snapshot.total_usage
        resumed.restore_todos_state(snapshot.todos_state)
        resumed.restore_change_history_state(snapshot.change_history_state)
        resumed.approval_manager.confirmation_callback = self.confirmation_callback
        self.agent.session = resumed
        self.refresh_header()

        await self._hydrate_chat_from_snapshot(snapshot.messages)
        await self._remove_cards_by_title({"Session Loaded"})

    async def _hydrate_chat_from_snapshot(self, messages: list[dict[str, Any]]) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        await conversation.remove_children()
        self._message_count = 0
        self._tool_widgets.clear()
        self._tool_args_by_call_id.clear()
        tool_call_names: dict[str, str] = {}

        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role == "system":
                continue
            if role == "user":
                await self.add_assistant_card("You", RichMarkdown(str(content)), css_class="user")
                continue
            if role == "assistant":
                if content:
                    await self.add_assistant_card("iTE", RichMarkdown(str(content)), css_class="assistant")
                for tool_call in message.get("tool_calls") or []:
                    call_id = str(tool_call.get("id", "") or "")
                    function = tool_call.get("function", {}) or {}
                    tool_name = str(function.get("name", "tool") or "tool")
                    raw_args = function.get("arguments", "") or ""
                    try:
                        parsed_args = json.loads(raw_args) if raw_args else {}
                    except Exception:
                        parsed_args = {"raw": raw_args}
                    tool_call_names[call_id] = tool_name
                    await self.add_tool_call_start(
                        call_id=call_id,
                        name=tool_name,
                        tool_kind=self.get_tool_kind(tool_name),
                        arguments=parsed_args if isinstance(parsed_args, dict) else {},
                    )
                continue
            if role == "tool":
                call_id = str(message.get("tool_call_id", "") or "")
                tool_name = tool_call_names.get(call_id, "tool")
                output = content if isinstance(content, str) else str(content)
                success = not output.lstrip().startswith("Error:")
                await self.update_tool_call(
                    call_id=call_id,
                    name=tool_name,
                    tool_kind=self.get_tool_kind(tool_name),
                    success=success,
                    output=output,
                    error=None if success else output,
                    metadata={},
                    diff=None,
                    truncated=False,
                    exit_code=None,
                )
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

        if command == "/plan":
            await self._run_plan_command_native(args)
            return

        if command == "/workboard":
            await self._run_workboard_command_native()
            return

        if command == "/aside":
            await self._run_aside_command_native(args)
            return

        if command == "/undo":
            await self._run_undo_command_native(args)
            return

        if command == "/redo":
            await self._run_redo_command_native(args)
            return

        if command == "/setup":
            await self._open_setup_modal(exit_on_cancel=False)
            return

        if command == "/branch" and not args:
            await self._open_branch_picker_from_meta()
            return

        if command == "/attach" and not args:
            await self._open_attach_picker_from_meta()
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
        if command in {"/branch", "/attach", "/model"}:
            self.refresh_header()
        if rendered:
            self.post_notice(f"Command {command}", rendered)

    async def _run_aside_command_native(self, args: list[str]) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            self.post_system("Aside", "No active session.", is_error=True)
            return

        question = " ".join(args).strip()
        if not question:
            self.post_system("Aside", "Use `/aside <question>`.", is_error=True)
            return

        entry_id = await self._create_pending_aside_entry(question)
        result = await execute_aside(self.agent.session, question)
        if result.error:
            await self._complete_aside_entry(
                entry_id,
                answer=result.error,
                state="error",
            )
            return
        await self._complete_aside_entry(
            entry_id,
            answer=result.answer,
            state="done",
        )

    async def _run_undo_command_native(self, args: list[str]) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            self.post_system("Undo", "No active session.", is_error=True)
            return

        force = "--force" in args
        try:
            change_set = self.agent.session.change_history.undo(force=force)
        except ChangeConflictError as exc:
            self.post_system("Undo", str(exc), is_error=True)
            return

        body = build_change_card_body(
            change_set,
            cwd=self.config.cwd,
            verb="Reverted",
            footer="Run /redo to reapply.",
            mode="undone",
        )
        await self.add_assistant_card("Undid changes", body, css_class="change")

    async def _run_redo_command_native(self, args: list[str]) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            self.post_system("Redo", "No active session.", is_error=True)
            return

        force = "--force" in args
        try:
            change_set = self.agent.session.change_history.redo(force=force)
        except ChangeConflictError as exc:
            self.post_system("Redo", str(exc), is_error=True)
            return

        body = build_change_card_body(
            change_set,
            cwd=self.config.cwd,
            verb="Reapplied",
            footer="Run /undo to revert again.",
            mode="redone",
        )
        await self.add_assistant_card("Reapplied changes", body, css_class="change")

    async def _run_plan_command_native(self, args: list[str]) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            self.post_system("Plan Mode", "No active session.", is_error=True)
            return

        session = self.agent.session

        if not args:
            enabled = "on" if session.plan_mode_enabled else "off"
            pending = "yes" if session.has_pending_plan() else "no"
            target_questions = int(getattr(session, "plan_target_questions", 3))
            status_md = (
                "## Plan Mode\n\n"
                f"- **Status:** `{enabled}`\n"
                f"- **Phase:** `{session.plan_phase}`\n"
                f"- **Questions asked:** `{session.plan_questions_asked}`\n"
                f"- **Question target:** `{target_questions}`\n"
                f"- **Pending plan:** `{pending}`\n\n"
                "Use `/plan on` or `/plan off`."
            )
            self.post_plan_note("Command `/plan`", status_md)
            return

        arg = args[0].lower()
        if arg not in {"on", "off"}:
            self.post_plan_note(
                "Plan command usage",
                "Invalid usage. Use `/plan`, `/plan on`, or `/plan off`.",
            )
            return

        enable = arg == "on"
        session.set_plan_mode(enable)
        if enable:
            session.set_plan_phase("idle")
        else:
            session.set_plan_phase("idle")

        mode = "ON" if enable else "OFF"
        details = (
            "Planning flow is active; the agent will ask clarifying questions first."
            if enable
            else "Normal execution behavior is active."
        )
        self.refresh_header()
        self.post_plan_note(
            "Plan Mode Updated",
            f"## Plan Mode `{mode}`\n\n{details}",
        )

    async def _run_workboard_command_native(self) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            self.post_system("Workboard", "No active session.", is_error=True)
            return

        session = self.agent.session
        todos_state = session.export_todos_state()
        if not isinstance(todos_state, dict):
            todos_state = {}

        show_planning = bool(session.show_planning_todos)
        scopes = ["execution"]
        if show_planning:
            scopes.append("planning")

        total = 0
        completed = 0
        pending = 0
        for scope in scopes:
            entries = todos_state.get(scope, [])
            if not isinstance(entries, list):
                continue
            total += len(entries)
            for entry in entries:
                if bool(entry.get("completed", False)):
                    completed += 1
                else:
                    pending += 1

        plan_text = (session.current_plan_text() or "").strip()
        body = self._build_workboard_body(
            plan_mode_enabled=session.plan_mode_enabled,
            plan_phase=str(session.plan_phase),
            show_planning=show_planning,
            completed=completed,
            pending=pending,
            total=total,
            todos_state=todos_state,
            scopes=scopes,
            plan_text=plan_text,
        )
        await self.add_assistant_card("Workboard", body, css_class="workboard")

    def _build_workboard_body(
        self,
        *,
        plan_mode_enabled: bool,
        plan_phase: str,
        show_planning: bool,
        completed: int,
        pending: int,
        total: int,
        todos_state: dict[str, Any],
        scopes: list[str],
        plan_text: str,
    ) -> Widget:
        sections: list[Widget] = []

        summary_md = (
            f"- **Plan mode:** `{'on' if plan_mode_enabled else 'off'}`\n"
            f"- **Phase:** `{plan_phase}`\n"
            f"- **Planning todos:** `{'shown' if show_planning else 'hidden'}`\n"
            f"- **Overall progress:** `{completed}/{total} completed` · `{pending} pending`"
        )
        sections.append(self._make_workboard_section("Summary", RichMarkdown(summary_md), tone="summary"))

        checklist_children: list[Widget] = []
        rendered_any_scope = False
        for scope in scopes:
            entries = todos_state.get(scope, [])
            if not isinstance(entries, list) or not entries:
                continue
            rendered_any_scope = True
            done_entries = [entry for entry in entries if bool(entry.get("completed", False))]
            pending_entries = [entry for entry in entries if not bool(entry.get("completed", False))]
            scope_title = "Execution Checklist" if scope == "execution" else "Planning Checklist"
            lines = [
                f"**{len(done_entries)}/{len(entries)} completed** · **{len(pending_entries)} pending**",
            ]
            if pending_entries:
                lines.extend(["", "**Up next**"])
                for entry in pending_entries[:6]:
                    content = str(entry.get("content", "")).strip()
                    if content:
                        lines.append(f"- [ ] {content}")
                if len(pending_entries) > 6:
                    lines.append(f"- `{len(pending_entries) - 6} more pending`")
            if done_entries:
                lines.extend(["", "**Done**"])
                for entry in done_entries[:3]:
                    content = str(entry.get("content", "")).strip()
                    if content:
                        lines.append(f"- [x] {content}")
                if len(done_entries) > 3:
                    lines.append(f"- `{len(done_entries) - 3} more completed`")
            checklist_children.append(
                self._make_workboard_section(
                    scope_title,
                    RichMarkdown("\n".join(lines)),
                    tone="execution" if scope == "execution" else "planning",
                    compact=True,
                )
            )

        if not rendered_any_scope:
            checklist_children.append(
                self._make_workboard_section(
                    "Checklists",
                    Static("No visible todos.", classes="workboard-empty"),
                    tone="muted",
                    compact=True,
                )
            )

        sections.append(Vertical(*checklist_children, classes="workboard-stack"))

        plan_body: Widget
        if plan_text:
            plan_body = RichMarkdown(plan_text)
        else:
            plan_body = Static("No current plan saved.", classes="workboard-empty")
        sections.append(self._make_workboard_section("Implementation Plan", plan_body, tone="plan"))

        return Vertical(*sections, classes="workboard-root")

    def _make_workboard_section(
        self,
        title: str,
        body: Widget | Any,
        *,
        tone: str,
        compact: bool = False,
    ) -> Widget:
        body_widget = body if isinstance(body, Widget) else Static()
        if not isinstance(body, Widget):
            body_widget.update(body)
        classes = f"workboard-section {tone}"
        if compact:
            classes += " compact"
        return Container(
            Static(title, classes="workboard-section-title"),
            body_widget if isinstance(body_widget, Widget) else Static(),
            classes=classes,
        )

    async def run_agent_message(self, message: str) -> None:
        await self.ensure_agent()
        if not self.agent:
            self.post_system("Error", "Agent is not initialized", is_error=True)
            return

        self._last_rendered_plan_text = None
        self._turn_had_error = False
        await self.add_user_message(message)
        self._active_turn_id += 1
        turn_id = self._active_turn_id
        self._active_turn_task = asyncio.create_task(self._agent_turn(message, turn_id))
        self._is_turn_running = True
        self._set_loading_state(self._progress_state_label(), busy=True)
        completed_normally = False

        try:
            await self._active_turn_task
            await self.auto_save()
            completed_normally = not self._turn_had_error
        except asyncio.CancelledError:
            self.post_notice("Interrupted", "Stopped current run.")
            await self.auto_save()
        finally:
            self._active_turn_task = None
            self._is_turn_running = False
            self._set_loading_state("idle", busy=False)

        if completed_normally:
            await self._dispatch_queued_payload_if_ready()
        else:
            self._restore_queued_payload_after_unsuccessful_turn()

    async def _agent_turn(self, message: str, turn_id: int) -> None:
        assert self.agent is not None

        async for event in self.agent.run(message):
            await self.handle_agent_event(event, turn_id)

    async def handle_agent_event(self, event: AgentEvent, turn_id: int) -> None:
        if turn_id != self._active_turn_id:
            return
        plan_only_phase = self._is_plan_only_phase()
        suppressed_tools = {"memory", "plan_question"}

        if event.type == AgentEventType.AGENT_END:
            self._activity_version += 1
            await self._hide_activity_indicator(self._activity_version)
            await self._post_turn_change_summary()
            return

        if event.type == AgentEventType.TEXT_DELTA:
            content = event.data.get("content", "")
            if content:
                self._activity_version += 1
                await self._hide_activity_indicator(self._activity_version)
                await self.stream_assistant_delta(content)
            return

        if event.type == AgentEventType.TEXT_COMPLETE:
            content = event.data.get("content", "")
            self._activity_version += 1
            await self._hide_activity_indicator(self._activity_version)
            if self._streaming_widget is not None:
                await self.finalize_streaming_message()
                if (
                    content
                    and plan_only_phase
                    and self.agent
                    and self.agent.session
                    and self.agent.session.plan_phase == "awaiting_implementation_confirmation"
                ):
                    self._last_rendered_plan_text = self._normalize_plan_text(content)
            elif content and not plan_only_phase:
                await self.add_assistant_message(content)
            elif (
                content
                and plan_only_phase
                and self.agent
                and self.agent.session
                and self.agent.session.plan_phase == "awaiting_implementation_confirmation"
            ):
                await self._render_plan_text_if_needed(content)
            if self._is_turn_running:
                self._activity_version += 1
                await self._show_activity_indicator(
                    self._progress_state_label(),
                    self._activity_version,
                )
            return

        if event.type == AgentEventType.AGENT_ERROR:
            self._activity_version += 1
            await self._hide_activity_indicator(self._activity_version)
            self._turn_had_error = True
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
            if tool_name == "todos":
                scope = self._resolve_todo_scope_for_event(arguments=event.data.get("arguments"))
                if self._should_hide_todo_scope(scope):
                    self._set_loading_state(
                        self._progress_state_label(
                            tool_name=tool_name,
                            arguments=event.data.get("arguments", {}),
                        ),
                        busy=True,
                    )
                    return
            if tool_name in suppressed_tools:
                self._set_loading_state(
                    self._progress_state_label(
                        tool_name=tool_name,
                        arguments=event.data.get("arguments", {}),
                    ),
                    busy=True,
                )
                return
            if plan_only_phase and tool_name not in {"todos", "web_search", "web_fetch"}:
                self._set_loading_state(
                    self._progress_state_label(
                        tool_name=tool_name,
                        arguments=event.data.get("arguments", {}),
                    ),
                    busy=True,
                )
                return
            self._activity_version += 1
            await self._hide_activity_indicator(self._activity_version)
            tool_kind = self.get_tool_kind(tool_name)
            self._set_loading_state(
                self._progress_state_label(
                    tool_name=tool_name,
                    arguments=event.data.get("arguments", {}),
                ),
                busy=True,
            )
            await self.add_tool_call_start(
                call_id=event.data.get("call_id", ""),
                name=tool_name,
                tool_kind=tool_kind,
                arguments=event.data.get("arguments", {}),
            )
            return

        if event.type == AgentEventType.TOOL_CALL_COMPLETE:
            tool_name = event.data.get("name", "tool")
            if tool_name == "todos":
                scope = self._resolve_todo_scope_for_event(metadata=event.data.get("metadata"))
                if self._should_hide_todo_scope(scope):
                    self._set_loading_state(
                        self._progress_state_label(
                            tool_name=tool_name,
                            metadata=event.data.get("metadata"),
                            phase="post_tool",
                        ),
                        busy=True,
                    )
                    return
            if tool_name in suppressed_tools:
                self._set_loading_state(
                    self._progress_state_label(
                        tool_name=tool_name,
                        metadata=event.data.get("metadata"),
                        phase="post_tool",
                    ),
                    busy=True,
                )
                return
            if (
                plan_only_phase
                and tool_name not in {"todos", "web_search", "web_fetch"}
                and event.data.get("success", False)
            ):
                self._set_loading_state(
                    self._progress_state_label(
                        tool_name=tool_name,
                        metadata=event.data.get("metadata"),
                        phase="post_tool",
                    ),
                    busy=True,
                )
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
            self._set_loading_state(
                self._progress_state_label(
                    tool_name=tool_name,
                    metadata=event.data.get("metadata"),
                    phase="post_tool",
                ),
                busy=True,
            )
            return

        if event.type == AgentEventType.PLAN_READY:
            plan_text = event.data.get("plan_text", "")
            if isinstance(plan_text, str) and plan_text.strip():
                await self._render_plan_text_if_needed(plan_text)
            approved = await self._present_plan_ready_action_card()
            if approved and self.agent and self.agent.session:
                self.agent.session.seed_execution_todos_from_plan(
                    self.agent.session.pending_plan_text
                )
                self.agent.session.promote_pending_plan_to_active()
                self.agent.session.set_plan_phase("executing")
                self.refresh_header()
                await self.run_agent_message(Agent.PLAN_EXECUTE_PROMPT)
            elif self.agent and self.agent.session:
                self.agent.session.set_plan_phase("awaiting_implementation_confirmation")
                self.refresh_header()
                self.post_plan_note(
                    "Plan saved for refinement",
                    "Use `implement plan` any time to start execution.",
                )
            return

    async def _post_turn_change_summary(self) -> None:
        if not self.agent or not self.agent.session:
            return
        change_set = self.agent.session.change_history.last_turn_change_set
        if not getattr(change_set, "changes", None):
            return
        body = build_change_card_body(
            change_set,
            cwd=self.config.cwd,
            verb="Changed",
            footer="Run /undo to revert.",
            mode="changed",
        )
        await self.add_assistant_card("Changed", body, css_class="change")

    async def _present_plan_ready_action_card(self) -> bool:
        conversation = self.query_one("#conversation", VerticalScroll)
        loop = asyncio.get_running_loop()
        if self._plan_ready_action_card is not None:
            try:
                await self._plan_ready_action_card.remove()
            except Exception:
                pass
            self._plan_ready_action_card = None
        self._plan_ready_future = loop.create_future()
        keep_button = Button("Keep in Plan Mode", id="plan-ready-keep", variant="default")
        implement_button = Button("Implement", id="plan-ready-implement", variant="success")

        action_card = Container(
            Static("Plan ready. Choose next step.", classes="card-title"),
            Static(
                "Stay in planning mode to refine the plan, or implement it now.",
                classes="card-body plan-ready-body",
            ),
            Horizontal(
                keep_button,
                implement_button,
                classes="plan-ready-actions",
            ),
            classes="block plan plan-ready",
        )
        self._plan_ready_action_card = action_card

        await conversation.mount(action_card)
        self._message_count += 1
        self._refresh_empty_state()
        conversation.scroll_end(animate=False)
        return bool(await self._plan_ready_future)

    def _resolve_plan_ready_choice(self, approved: bool) -> None:
        future = self._plan_ready_future
        if future is None or future.done():
            return
        future.set_result(approved)
        self._plan_ready_future = None
        if self._plan_ready_action_card is not None:
            self._plan_ready_action_card.remove()
            self._plan_ready_action_card = None

    @on(Button.Pressed, "#plan-ready-implement")
    def on_plan_ready_implement(self, _event: Button.Pressed) -> None:
        self._resolve_plan_ready_choice(True)

    @on(Button.Pressed, "#plan-ready-keep")
    def on_plan_ready_keep(self, _event: Button.Pressed) -> None:
        self._resolve_plan_ready_choice(False)

    async def _present_plan_question_card(
        self,
        *,
        question_number: int,
        question: str,
        options: list[str],
        recommended_index: int | None,
        allow_free_text: bool,
    ) -> dict[str, Any]:
        conversation = self.query_one("#conversation", VerticalScroll)
        loop = asyncio.get_running_loop()
        self._plan_question_future = loop.create_future()
        self._plan_question_options = list(options)
        self._plan_question_number = max(1, question_number)
        self._plan_question_prompt = question
        self._plan_question_recommended_index = recommended_index

        option_buttons: list[Button] = []
        for idx, option in enumerate(options):
            rec = " (recommended)" if recommended_index == idx else ""
            btn = Button(
                f"{idx + 1}. {option}{rec}",
                id=f"pq-opt-{idx}",
                variant="default",
                classes="plan-question-option",
            )
            option_buttons.append(btn)
        option_container = Container(*option_buttons, classes="plan-question-options")
        self._plan_question_option_buttons = option_buttons

        status = Static("", classes="plan-question-status")
        status.display = False
        self._plan_question_status = status

        custom_input: Input | None = None
        custom_submit: Button | None = None
        if allow_free_text:
            custom_input = Input(placeholder="Custom answer", id="pq-custom-input")
            custom_submit = Button("Submit", id="pq-custom-submit", variant="default")
            custom_row = Horizontal(
                custom_input,
                custom_submit,
                classes="plan-question-custom-row",
            )
        else:
            custom_row = Horizontal(classes="plan-question-custom-row")
            custom_row.display = False
        self._plan_question_custom_input = custom_input
        self._plan_question_custom_submit = custom_submit

        card = Container(
            Static(f"Asking questions {self._plan_question_number}", classes="card-title"),
            Static(question, classes="card-body plan-question-prompt"),
            option_container,
            custom_row,
            status,
            classes="block plan plan-question",
        )
        self._plan_question_card = card

        await conversation.mount(card)
        self._message_count += 1
        self._refresh_empty_state()
        conversation.scroll_end(animate=False)

        if self._plan_question_option_buttons:
            self._plan_question_option_buttons[0].focus()
        elif self._plan_question_custom_input is not None:
            self._plan_question_custom_input.focus()

        return await self._plan_question_future

    async def _resolve_plan_question_choice(
        self, *, selected_index: int | None, selected_option: str, free_text: str
    ) -> None:
        future = self._plan_question_future
        if future is None or future.done():
            return

        free_text_clean = (free_text or "").strip()
        result = {
            "selected_option": selected_option,
            "free_text": free_text_clean,
            "selected_index": selected_index,
        }

        for button in self._plan_question_option_buttons:
            button.disabled = True
        if self._plan_question_custom_input is not None:
            self._plan_question_custom_input.disabled = True
        if self._plan_question_custom_submit is not None:
            self._plan_question_custom_submit.disabled = True

        if isinstance(selected_index, int) and 0 <= selected_index < len(self._plan_question_option_buttons):
            selected_button = self._plan_question_option_buttons[selected_index]
            selected_button.variant = "primary"
            selected_button.add_class("selected")
        if free_text_clean and self._plan_question_custom_submit is not None:
            self._plan_question_custom_submit.variant = "primary"
            self._plan_question_custom_submit.add_class("selected")
        if free_text_clean and self._plan_question_status is not None:
            self._plan_question_status.update(f"Custom answer\n{free_text_clean}")
            self._plan_question_status.display = True

        future.set_result(result)
        self._plan_question_future = None
        self._plan_question_options = []
        self._plan_question_number = 0
        self._plan_question_prompt = ""
        self._plan_question_option_buttons = []
        self._plan_question_custom_input = None
        self._plan_question_custom_submit = None
        self._plan_question_status = None
        self._plan_question_recommended_index = None

    @on(Button.Pressed)
    async def on_plan_question_button_pressed(self, event: Button.Pressed) -> None:
        if self._plan_question_future is None or self._plan_question_future.done():
            return
        button_id = event.button.id or ""
        if button_id.startswith("pq-opt-"):
            idx = int(button_id.split("-", 2)[2])
            if 0 <= idx < len(self._plan_question_options):
                await self._resolve_plan_question_choice(
                    selected_index=idx,
                    selected_option=self._plan_question_options[idx],
                    free_text="",
                )
            return
        if button_id == "pq-custom-submit":
            value = (
                self._plan_question_custom_input.value.strip()
                if self._plan_question_custom_input is not None
                else ""
            )
            await self._resolve_plan_question_choice(
                selected_index=None,
                selected_option="",
                free_text=value,
            )

    @on(Input.Submitted, "#pq-custom-input")
    async def on_plan_question_custom_submitted(self, event: Input.Submitted) -> None:
        if self._plan_question_future is None or self._plan_question_future.done():
            return
        value = event.value.strip()
        await self._resolve_plan_question_choice(
            selected_index=None,
            selected_option="",
            free_text=value,
        )

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

    async def _clear_inflight_turn_ui(self) -> None:
        if self._streaming_widget is not None:
            try:
                await self._streaming_widget.remove()
            except Exception:
                pass
            self._streaming_widget = None
            self._streaming_buffer = ""
            self._message_count = max(0, self._message_count - 1)

        running_widgets = [card for card in self._tool_widgets.values() if card.has_class("running")]
        for card in running_widgets:
            try:
                await card.remove()
            except Exception:
                pass
            self._message_count = max(0, self._message_count - 1)

        if running_widgets:
            running_ids = {
                call_id
                for call_id, card in list(self._tool_widgets.items())
                if card in running_widgets
            }
            for call_id in running_ids:
                self._tool_widgets.pop(call_id, None)
                self._tool_args_by_call_id.pop(call_id, None)

        self._refresh_empty_state()

    async def add_user_message(self, message: str) -> None:
        await self.add_assistant_card("You", RichMarkdown(message), css_class="user")

    async def add_assistant_message(self, message: str) -> None:
        await self.add_assistant_card("iTE", RichMarkdown(message), css_class="assistant")

    def post_system(self, title: str, message: str, is_error: bool = False) -> None:
        css_class = "system error" if is_error else "system"
        self.run_worker(self.add_assistant_card(title, message, css_class=css_class), exclusive=False)

    def post_notice(self, title: str, message: str) -> None:
        self.run_worker(
            self.add_assistant_card(title, Text(message, style="#d7deea"), css_class="note"),
            exclusive=False,
        )

    def post_plan_note(self, title: str, markdown_text: str) -> None:
        self.run_worker(
            self.add_assistant_card(title, RichMarkdown(markdown_text), css_class="plan"),
            exclusive=False,
        )

    def post_attachment_note(self, message: str) -> None:
        self.run_worker(
            self.add_assistant_card(
                "Attachments",
                Text(message, style="#d7deea"),
                css_class="attachment",
            ),
            exclusive=False,
        )

    async def add_assistant_card(self, title: str, body: Any, css_class: str = "assistant") -> None:
        conversation = self.query_one("#conversation", VerticalScroll)

        if isinstance(body, Widget):
            body_widget = body
            body_widget.add_class("card-body")
            body_widget.add_class(f"{css_class}-body")
        else:
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

    async def _remove_cards_by_title(self, titles: set[str]) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        for child in list(conversation.children):
            try:
                title_widget = child.query_one(".card-title", Static)
            except Exception:
                continue
            renderable = getattr(title_widget, "renderable", "")
            if str(renderable).strip() in titles:
                await child.remove()
                self._message_count = max(0, self._message_count - 1)
        self._refresh_empty_state()

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
        if name == "todos":
            blocks.extend([Text(""), Text(todo_start_hint(arguments), style="#d5d9e2")])
        elif arguments:
            blocks.extend([Text(""), render_args_table(name, arguments, cwd=self.config.cwd)])
        else:
            blocks.extend([Text(""), Text("(no args)", style="#8c97ab")])

        if name == "shell":
            running_shells = getattr(self, "_running_shell_call_ids", set())
            running_shells.add(call_id)
            self._running_shell_call_ids = running_shells
            card.update(
                render_shell_running_card(
                    arguments,
                    cwd=self.config.cwd,
                    spinner_index=self._top_spinner_index,
                )
            )
        else:
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
        running_shells = getattr(self, "_running_shell_call_ids", set())
        running_shells.discard(call_id)

        blocks: list[Any] = [Text(narrative, style="#8c97ab"), Text("")]

        payload = output if success else (error or output)
        payload = payload or ""
        local_truncated = False
        md = metadata if isinstance(metadata, dict) else {}
        primary_path = md.get("path") if isinstance(md.get("path"), str) else None

        if name == "read_file" and success:
            extracted = extract_read_file_code(payload) if primary_path else None
            if primary_path and extracted is not None:
                start_line, code = extracted
                code_display, was_truncated = truncate_for_tool(name, code)
                local_truncated = local_truncated or was_truncated
                blocks.append(Text(display_path(primary_path, cwd=self.config.cwd), style="#8c97ab"))
                blocks.append(Text(""))
                language = guess_language(primary_path)
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
                output_display, was_truncated = truncate_for_tool(name, payload)
                local_truncated = local_truncated or was_truncated
                blocks.append(render_text_payload(output_display, success=True))
        elif name in {"write_file", "edit"} and success and diff:
            if payload.strip():
                blocks.append(Text(payload.strip(), style="#d9dee8"))
                blocks.append(Text(""))
            diff_display, was_truncated = truncate_for_tool(name, diff)
            local_truncated = local_truncated or was_truncated
            blocks.append(Syntax(diff_display, "diff", theme="monokai", word_wrap=True))
        elif name == "shell":
            command = args.get("command")
            if isinstance(command, str) and command.strip():
                blocks.append(
                    render_shell_command_line(
                        command.strip(),
                        cwd=self.config.cwd,
                        shell_cwd=md.get("cwd") if isinstance(md.get("cwd"), str) else None,
                    )
                )
                blocks.append(Text(""))
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            blocks.extend(
                render_shell_result_payload(
                    payload=output_display,
                    metadata=md,
                    exit_code=exit_code,
                )
            )
        elif name == "web_search" and success:
            query = md.get("query") or args.get("query")
            results_count = md.get("results")
            provider = md.get("provider")
            summary_parts: list[str] = []
            if isinstance(query, str) and query.strip():
                summary_parts.append(f"\"{query.strip()}\"")
            if isinstance(results_count, int):
                summary_parts.append(f"{results_count} result{'s' if results_count != 1 else ''}")
            if isinstance(provider, str) and provider.strip():
                summary_parts.append(provider)
            if summary_parts:
                blocks.append(Text(" • ".join(summary_parts), style="#8c97ab"))
                blocks.append(Text(""))
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            blocks.append(render_text_payload(output_display, success=success))
        elif name == "web_fetch" and success:
            summary_parts: list[str] = []
            url = md.get("url") or args.get("url")
            status_code = md.get("status_code")
            content_type = md.get("content_type")
            if isinstance(status_code, int):
                summary_parts.append(str(status_code))
            if isinstance(content_type, str) and content_type.strip():
                summary_parts.append(content_type.strip())
            if isinstance(url, str) and url.strip():
                summary_parts.append(url.strip())
            if summary_parts:
                blocks.append(Text(" • ".join(summary_parts), style="#8c97ab"))
                blocks.append(Text(""))
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            blocks.append(render_text_payload(output_display, success=success))
        elif name in {"list_dir", "glob", "grep"}:
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            if name == "list_dir":
                blocks.append(render_list_dir_output(output_display))
            elif name == "grep":
                blocks.append(render_grep_output(output_display, cwd=self.config.cwd))
            else:
                blocks.append(render_text_payload(output_display, success=success))
        elif name == "todos" and success:
            todo_blocks, was_truncated = render_todo_payload(
                output=payload,
                metadata=md,
            )
            local_truncated = local_truncated or was_truncated
            blocks.extend(todo_blocks)
        else:
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            if diff:
                diff_display, diff_truncated = truncate_for_tool(name, diff)
                local_truncated = local_truncated or diff_truncated
                blocks.append(Syntax(diff_display, "diff", theme="monokai", word_wrap=True))
            elif output_display.strip():
                blocks.append(render_text_payload(output_display, success=success))
            else:
                blocks.append(Text("No output", style="#8c97ab"))

        if local_truncated or truncated:
            blocks.extend([Text(""), Text("... [truncated]", style="#f5b54f")])

        header = Text()
        header.append(f"{icon} ", style=title_style)
        if name == "shell":
            header.append(
                "Command finished" if success else "Command failed",
                style=title_style,
            )
        else:
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

            result = await self._present_plan_question_card(
                question_number=question_number,
                question=question,
                options=options,
                recommended_index=recommended_index,
                allow_free_text=allow_free_text,
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
        self._active_turn_id += 1
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
        await self._clear_inflight_turn_ui()
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
        self._activity_widget = None
        self._last_rendered_plan_text = None
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
            active_plan_text=session.active_plan_text,
            todos_state=session.export_todos_state(),
            show_planning_todos=session.show_planning_todos,
            change_history_state=session.export_change_history_state(),
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
