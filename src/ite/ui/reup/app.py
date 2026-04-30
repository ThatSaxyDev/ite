from __future__ import annotations

import asyncio
import difflib
import io
import json
import os
import re
import shlex
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, cast
from urllib.parse import urlparse

from rich.cells import cell_len
from rich.console import Group
from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult, ScreenStackError, SystemCommand
from textual.binding import Binding
from textual.command import CommandPalette, DiscoveryHit, Hit, Hits, Provider
from textual.containers import (
    Container,
    Horizontal,
    HorizontalScroll,
    ScrollableContainer,
    Vertical,
    VerticalScroll,
)
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TextArea,
    Tree,
)
from textual.widgets import Markdown as TextualMarkdown

from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.agent.session import Session
from ite.agent.session_manager import SessionManager, SessionSnapshot
from ite.attachment_refs import (
    discover_attachable_files,
    extract_at_query,
    extract_inline_attachment_refs,
    resolve_inline_attachment_refs,
    suggest_inline_attachment_paths,
)
from ite.attachments import (
    MAX_ATTACHMENTS,
    Attachment,
    AttachmentManager,
    build_user_model_content,
    build_user_text_with_manifest,
)
from ite.cloud import (
    CloudAuthError,
    CloudConnectionError,
    clear_cloud_auth,
    ensure_cloud_auth,
    get_activity,
    get_bundled_models,
    get_usage_summary,
    has_stored_cloud_auth,
    has_valid_cloud_auth,
)
from ite.commands import build_registry
from ite.commands.aside import execute_aside, is_aside_command_text
from ite.config.config import ApprovalPolicy, Config, DEFAULT_CONTEXT_WINDOW
from ite.config.loader import (
    get_workspace_agents_recommendation,
    load_saved_custom_provider,
    load_theme,
    remove_saved_custom_provider,
    save_cloud_settings,
    save_global_approval_mode,
    save_onboarding_settings,
    save_saved_custom_provider,
    save_system_config,
    save_theme,
)
from ite.git.branches import (
    checkout_branch,
    create_and_checkout,
    current_branch,
    is_git_repo,
    list_local_branches,
)
from ite.git.remotes import upsert_remote
from ite.git.working_tree import (
    commit_changes,
    discard_all,
    discard_path,
    git_outbound_state,
    outbound_commit_subjects,
    push_current_branch,
    stage_all,
    stage_path,
    unstage_all,
    unstage_path,
    working_tree_change_set,
)
from ite.memory import MemoryManager
from ite.remote import RemoteRuntimeServer
from ite.remote.protocol import (
    build_remote_transcript,
    json_safe,
    serialize_agent_event,
    serialize_approval_request,
    serialize_plan_question_request,
    serialize_plan_ready_request,
)
from ite.skills import (
    build_skill_detail_renderable,
    build_skill_feedback_renderable,
    build_skills_overview_renderable,
)
from ite.skills.manager import SkillDefinition
from ite.skills.rendering import skill_state
from ite.tools.base import Tool, ToolRiskLevel
from ite.tools.mcp.mcp_tool import MCPTool
from ite.tools.subagent import SubagentTool
from ite.ui.reup.markdown_widget import CopyableMarkdown
from ite.ui.tool_narrative import activity_title, describe_tool_activity, progress_label

from .adapters.registry import StreamingCommandOutput, build_command_context
from .change_tree import ChangedFilesTree
from .change_views import (
    build_change_card_body,
    build_change_card_payload,
    change_entry_label,
)
from .command_views import (
    build_mcp_command_renderable,
    build_memory_command_renderable,
    build_memory_prompt_command_renderable,
    build_stats_command_renderable,
    build_tools_command_renderable,
    build_workboard_command_renderable,
)
from .composer_views import (
    SlashCommandOption,
    build_command_palette_options,
    build_empty_state_renderable,
    build_signed_out_state_renderable,
    build_turn_action_options,
    build_turn_payload,
    composer_meta_text,
    filtered_command_palette,
    render_command_palette,
    render_turn_action_palette,
)
from .modals import (
    ActivityModal,
    ApprovalPickerModal,
    AttachPickerModal,
    BranchPickerModal,
    CommitModal,
    ConfirmModal,
    ContextSummaryModal,
    ModelPickerModal,
    PlanQuestionModal,
    PushReviewModal,
    RemoteSetupModal,
    SessionResumeModal,
    SetupModal,
    ThemePickerModal,
    UsageSummaryModal,
)
from .tool_views import (
    detect_host_textual_theme,
    display_path,
    extract_read_file_code,
    format_mcp_identity,
    guess_language,
    is_light_background,
    normalize_style_color,
    normalize_unified_diff_paths,
    render_args_table,
    render_git_log_output,
    render_grep_output,
    render_line_numbered_text,
    render_list_dir_output,
    render_mcp_start_payload,
    render_numbered_unified_diff,
    render_palette,
    render_shell_command_line,
    render_shell_result_payload,
    render_shell_running_card,
    render_skills_payload,
    render_subagent_metrics_payload,
    render_subagent_payload,
    render_subagent_runtime_payload,
    render_terminal_snapshot_payload,
    render_text_payload,
    render_todo_payload,
    shell_session_state,
    summarize_diff_hunk_ranges,
    summarize_mcp_success,
    summarize_subagent_goal,
    syntax_background_color,
    todo_start_hint,
    truncate_for_tool,
)


class ReupPromptTextArea(TextArea):
    class Submitted(Message):
        pass

    BINDINGS = list(TextArea.BINDINGS)

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


def _skills_action_title(action: str) -> str:
    action_map = {
        "use": "Skill activated",
        "activate": "Skill activated",
        "drop": "Skill deactivated",
        "deactivate": "Skill deactivated",
        "clear": "Skills cleared",
        "trust": "Workspace trusted",
        "untrust": "Workspace untrusted",
        "add": "Skills installed",
    }
    return action_map.get(str(action or "").strip().lower(), "Skills update")


ONBOARDING_ROLE_OPTIONS: tuple[str, ...] = (
    "Software engineer",
    "Founder",
    "Product manager",
    "Designer",
    "Doctor",
    "Student",
    "Researcher",
    "Marketer",
    "Sales",
    "Operations",
    "Writer",
    "Consultant",
)

ONBOARDING_USE_CASE_OPTIONS: tuple[str, ...] = (
    "Writing code",
    "Debugging an issue",
    "Shipping a feature",
    "Researching a topic",
    "Planning a project",
    "Reviewing code",
    "Writing content",
    "Analyzing data",
    "Studying",
    "Automating a workflow",
    "Designing a product",
    "Brainstorming ideas",
)

ONBOARDING_OTHER_VALUE = "__other__"


class ReupTUIAdapter:
    """Adapter that wraps ReupApp to provide TUI-like interface."""

    def __init__(self, app: "ReupApp") -> None:
        self._app = app
        # Track spinner state locally to avoid race conditions with async workers
        self._spinner_handle: str | None = None
        self._spinner_lines: list[str] = []
        self._spinner_started: bool = False

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
        version: str = "0.0.38",
    ) -> None:
        msg = f"iTE ready\nModel: {model or 'not set'}\nWorkspace: {cwd}\nVersion: {version}"
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

    async def _close_current_thread(self) -> None:
        await self._app.close_current_thread()

    def start_spinner(self, command: str, message: str = "Thinking") -> None:
        """Show streaming command card like /mcp start - fixed title with spinner."""
        self._spinner_handle = command  # Use command as handle (/init, /mcp, etc.)
        self._spinner_lines = []
        # Create card with message as pending_text - this displays with spinner
        # but isn't a persistent line, so it can be replaced
        self._app.run_worker(
            self._app.start_streaming_command_result(command, pending_text=message),
            exclusive=False,
        )

    def change_spinner(self, message: str) -> None:
        """Update spinner status - replaces current line with new status (like tool calls)."""
        if not self._spinner_handle:
            return
        # Update pending text and clear lines so spinner shows with new message
        self._app.start_streaming_command_result_update_pending(
            self._spinner_handle, message
        )

    def step_spinner(self, message: str) -> None:
        """Commit current step as completed line, start new pending step with spinner.

        Unlike change_spinner() which replaces the current line, step_spinner()
        appends the current pending message as a completed line and starts a
        new pending step. This creates a progress trail like subagents show.
        """
        if not self._spinner_handle:
            # No active spinner, just start one
            self.start_spinner(self._spinner_handle or "/init", message)
            return
        # Commit current pending as a line, start new pending
        self._app.run_worker(
            self._app._commit_and_update_streaming_pending(
                self._spinner_handle, message
            ),
            exclusive=False,
        )

    def stream_content(self, chunk: str) -> None:
        """Stream content into the card body (like LLM token streaming).

        This appends text incrementally to show live generation progress.
        """
        if not self._spinner_handle:
            return
        self._app.run_worker(
            self._app._append_streaming_content(self._spinner_handle, chunk),
            exclusive=False,
        )

    def stop_spinner(self) -> None:
        """Finalize spinner card."""
        if self._spinner_handle:
            self._app.finalize_streaming_command_result(self._spinner_handle)
            self._spinner_handle = None
            self._spinner_lines = []

    def post_success_card(self, title: str, message: str, details: str = "") -> None:
        """Post a professional success notification card."""
        from rich.text import Text

        body = Text()
        body.append(message, style=self._app._style("success"))
        if details:
            body.append("\n", style=self._app._style("muted"))
            body.append(details, style=self._app._style("muted"))

        self._app.run_worker(
            self._app.add_assistant_card(title, body, css_class="system"),
            exclusive=False,
        )


@dataclass
class SessionRunState:
    active_turn_task: asyncio.Task | None = None
    active_turn_id: int = 0
    is_turn_running: bool = False
    turn_had_error: bool = False
    turn_made_progress: bool = False
    context_meter_floor_pct: int | None = None
    auto_resume_payload: dict[str, Any] | None = None
    failure_recovery_payload: dict[str, Any] | None = None
    failure_recovery_attempts: int = 0
    queued_turn_payload: dict[str, Any] | None = None
    last_turn_payload: dict[str, Any] | None = None
    retryable_turn_payload: dict[str, Any] | None = None
    last_error_message: str | None = None
    running_shell_call_ids: set[str] = field(default_factory=set)
    running_subagent_call_ids: set[str] = field(default_factory=set)
    running_wait_subagent_call_ids: set[str] = field(default_factory=set)


@dataclass
class ShellSessionCardState:
    card: Widget
    name: str
    arguments: dict[str, Any]
    metadata: dict[str, Any]
    payload: str
    success: bool
    exit_code: int | None


class ShellToolCard(Vertical):
    def __init__(
        self,
        *,
        classes: str | None = None,
    ) -> None:
        super().__init__(classes=classes)
        self._header = Static(classes="shell-card-header")
        self._body = Static(classes="shell-card-body")

    def compose(self) -> ComposeResult:
        yield self._header
        with VerticalScroll(classes="shell-card-scroll"):
            yield self._body

    def set_shell_content(self, *, header: Any, body: Any) -> None:
        self._header.update(header)
        self._body.update(body)
        if self.is_mounted:
            self.call_after_refresh(self._scroll_terminal_end)

    def _scroll_terminal_end(self) -> None:
        try:
            viewport = self.query_one(".shell-card-scroll", VerticalScroll)
        except NoMatches:
            return
        viewport.scroll_end(animate=False)


class RemoteBridgeField(Horizontal):
    def __init__(
        self,
        label: str,
        value: str,
        *,
        copy_value: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(classes=classes)
        self._label = label
        self._value = value
        self._copy_value = copy_value if copy_value is not None else value

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="remote-bridge-field-label")
        yield Static(self._value, classes="remote-bridge-field-value")
        yield Button("Copy", id="copy", classes="remote-bridge-copy", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "copy":
            return
        event.stop()
        value = self._copy_value.strip()
        if not value:
            return
        try:
            self.app.copy_to_clipboard(value)
            self.notify("Copied to clipboard", timeout=2)
        except Exception:
            try:
                import pyperclip

                pyperclip.copy(value)
                self.notify("Copied to clipboard", timeout=2)
            except Exception:
                self.notify(
                    "Failed to copy to clipboard", severity="error", title="Copy Error"
                )


class RemoteBridgeCard(Vertical):
    def __init__(
        self,
        *,
        intro: str,
        runtime_name: str,
        exposure_mode: str,
        host: str,
        port: int | str,
        pair_code: str,
        fingerprint: str,
        connect_uri: str | None = None,
        authenticated_clients: int | None = None,
        trusted_devices: int | None = None,
        footer: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(classes=classes)
        self._intro = intro
        self._runtime_name = str(runtime_name)
        self._exposure_mode = str(exposure_mode)
        self._host = str(host)
        self._port = str(port)
        self._pair_code = str(pair_code)
        self._fingerprint = str(fingerprint)
        self._connect_uri = str(connect_uri or "").strip()
        self._authenticated_clients = authenticated_clients
        self._trusted_devices = trusted_devices
        self._footer = str(footer or "").strip()

    def compose(self) -> ComposeResult:
        yield Static(self._intro, classes="remote-bridge-intro")

        if self._runtime_name:
            yield RemoteBridgeField(
                "Runtime",
                self._runtime_name,
                classes="remote-bridge-field",
            )
        if self._exposure_mode:
            yield RemoteBridgeField(
                "Exposure",
                "LAN" if self._exposure_mode == "lan" else "Local only",
                classes="remote-bridge-field",
            )
        yield RemoteBridgeField("Host", self._host, classes="remote-bridge-field")
        yield RemoteBridgeField("Port", self._port, classes="remote-bridge-field")
        yield RemoteBridgeField(
            "Pair code",
            self._pair_code,
            classes="remote-bridge-field",
        )
        if self._fingerprint:
            yield RemoteBridgeField(
                "Fingerprint",
                self._fingerprint,
                classes="remote-bridge-field wide",
            )
        if self._authenticated_clients is not None:
            yield RemoteBridgeField(
                "Connected phones",
                str(self._authenticated_clients),
                classes="remote-bridge-field",
            )
        if self._trusted_devices is not None:
            yield RemoteBridgeField(
                "Trusted devices",
                str(self._trusted_devices),
                classes="remote-bridge-field",
            )

        if self._connect_uri:
            yield RemoteBridgeField(
                "Secure Connect Link",
                self._connect_uri,
                classes="remote-bridge-field wide emph",
            )

        if self._footer:
            yield Static(self._footer, classes="remote-bridge-footer")


class CommandsSidePanel(Widget):
    ALLOW_MAXIMIZE = False

    def __init__(
        self,
        *,
        commands: list[tuple[str, str]],
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._commands = commands

    def compose(self) -> ComposeResult:
        with Horizontal(classes="commands-panel-header"):
            yield Static("Commands", classes="commands-panel-title")
            yield Button(
                "Close", id="commands-panel-close", classes="commands-panel-close"
            )
        yield Static(
            "Available slash commands and what they do.",
            classes="commands-panel-subtitle",
        )
        yield DataTable(id="commands-panel-table", classes="commands-panel-table")

    def on_mount(self) -> None:
        table = self.query_one("#commands-panel-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Command", "Description")
        for name, description in self._commands:
            table.add_row(name, description)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "commands-panel-close":
            return
        event.stop()
        self.app.run_worker(self.app._hide_commands_panel(), exclusive=False)


class ReupSystemCommandsProvider(Provider):
    async def discover(self) -> Hits:
        for command in self.app.get_system_commands(self.screen):
            if command.discover:
                yield DiscoveryHit(
                    command.title,
                    command.callback,
                    help=command.help,
                )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for command in self.app.get_system_commands(self.screen):
            if (match := matcher.match(command.title)) > 0:
                yield Hit(
                    match,
                    matcher.highlight(command.title),
                    command.callback,
                    help=command.help,
                )


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
        self._session_agents: dict[str, Agent] = {}
        self._session_run_states: dict[str, SessionRunState] = {}
        self._fallback_run_state = SessionRunState()
        self._command_registry = None
        self._command_registry_ready: bool = False
        self._command_registry_loading: bool = False
        self._streaming_widget: Static | None = None
        self._streaming_buffer: str = ""
        self._tool_widgets: dict[str, Static] = {}
        self._tool_args_by_call_id: dict[str, dict[str, Any]] = {}
        self._tool_name_by_call_id: dict[str, str] = {}
        self._tool_completion_state: dict[str, dict[str, Any]] = {}
        self._assistant_card_rich_states: dict[
            str, dict[str, Any]
        ] = {}  # Track cards that need re-render on theme change
        self._change_card_states: dict[
            int, dict[str, Any]
        ] = {}  # Track change cards by message index for theme re-rendering
        self._live_shell_call_state: dict[str, ShellSessionCardState] = {}
        self._adapter = ReupTUIAdapter(self)
        self._message_count: int = 0
        self._streaming_command_cards: dict[
            str, tuple[Container, Static, VerticalScroll, list[str], bool, str | None]
        ] = {}
        # Lock to prevent race conditions on streaming card operations
        self._streaming_cards_lock = asyncio.Lock()
        self._composer_history: list[str] = []
        self._composer_history_index: int | None = None
        self._composer_history_draft: str = ""
        self._applying_history_nav: bool = False
        self._suppress_history_reset_once: bool = False
        self._top_busy: bool = False
        self._top_spinner_index: int = 0
        self._top_spinner_frames: tuple[str, ...] = (
            "⠋",
            "⠙",
            "⠹",
            "⠸",
            "⠼",
            "⠴",
            "⠦",
            "⠧",
            "⠇",
            "⠏",
        )
        self._activity_suffix_frames: tuple[str, ...] = ("", ".", "..", "...")
        self._activity_suffix_index: int = 0
        self._top_state_text: str = ""
        self._activity_widget: Static | None = None
        self._live_compaction_card: Container | None = None
        self._live_compaction_body: Static | None = None
        self._live_compaction_active: bool = False
        self._activity_resume_timer = None
        self._activity_version: int = 0
        self._empty_state_cached_thread_count: int = 0
        self._cloud_signed_out: bool = False
        self._cloud_auth_busy: bool = False
        self._cloud_bootstrap_busy: bool = False
        self._startup_active: bool = True
        self._startup_phase_text: str = "Preparing your workspace"
        self._startup_error_text: str | None = None
        self._onboarding_active: bool = False
        self._onboarding_busy: bool = False
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
        self._composer_model_hitbox: tuple[int, int] = (0, 0)
        self._composer_plan_hitbox: tuple[int, int] = (0, 0)
        self._composer_branch_hitbox: tuple[int, int] = (0, 0)
        self._composer_usage_hitbox: tuple[int, int] | None = None
        self._composer_context_hitbox: tuple[int, int] = (0, 0)
        self._composer_activity_hitbox: tuple[int, int] = (0, 0)
        self._usage_remaining_percent: int | None = None
        self._usage_refresh_in_flight: bool = False
        self._bundled_access_announced: bool = False
        self._command_palette_options: list[SlashCommandOption] = []
        self._filtered_command_palette_options: list[SlashCommandOption] = []
        self._command_palette_index: int = 0
        self._command_palette_rows: int = 0
        self._palette_mode: str = "command"
        self._turn_action_payload: dict[str, Any] | None = None
        self._turn_action_replacing_queue: bool = False
        self._turn_action_options: list[SlashCommandOption] = []
        self._attachable_files_cache: list[Path] = []
        self._attachable_files_cache_cwd: Path | None = None
        self._last_rendered_plan_text: str | None = None
        self._aside_panel_visible: bool = False
        self._aside_entries: list[dict[str, str]] = []
        self._aside_entry_seq: int = 0
        self._aside_pending_widgets: dict[str, Static] = {}
        self._change_review_visible: bool = False
        self._change_review_change_set: Any = None
        self._change_review_mode: str = "changed"
        self._change_review_title: str = "Changes"
        self._change_review_source: str = "git"
        self._change_review_diff_lookup: dict[str, Any] = {}
        self._change_review_selected_rel_path: str | None = None
        self._change_review_snapshot_key: tuple[Any, ...] | None = None
        self._change_review_bulk_action: str = "stage"
        self._change_review_preview_version: int = 0
        self._git_outbound_state: Any = None
        self._suppress_pending_restore_once: bool = False
        self._open_sessions: dict[str, Session] = {}
        self._open_session_order: list[str] = []
        self._open_session_workspaces: dict[str, Path] = {}
        self._session_tabs_version: int = 0
        self._shutdown_started: bool = False
        self._suppress_theme_prompt_sync: bool = False
        self._remote_server: RemoteRuntimeServer | None = None
        self._remote_port_preference: int = 0
        self._commands_panel: CommandsSidePanel | None = None
        self._agents_recommendation_last_workspace_key: str | None = None
        self._agents_recommendation_current_visit: tuple[str, str] | None = None
        self._suppress_agents_recommendation_once: bool = False
        self._remote_command_feed: list[dict[str, Any]] = []
        self._remote_command_seq: int = 0
        self._remote_change_feed: list[dict[str, Any]] = []
        self._remote_change_seq: int = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="shell"):
            with Horizontal(id="topbar"):
                yield Static("New thread", id="title")
                yield Static("", id="header-meta")
                yield Button("/changes", id="changes-toggle", variant="default")
                yield Button("/aside", id="aside-toggle", variant="default")
            with HorizontalScroll(id="session-tabs-scroll"):
                yield Horizontal(id="session-tabs")
            with Container(id="chat-panel"):
                with Horizontal(id="chat-body"):
                    with Container(id="change-review-panel"):
                        with Horizontal(id="change-review-header"):
                            yield Static("Changes", id="change-review-title")
                            yield Static(
                                "Stage All",
                                id="change-review-stage-all",
                                classes="change-review-action",
                            )
                            yield Static(
                                "Discard All",
                                id="change-review-discard-all",
                                classes="change-review-action",
                            )
                            yield Static(
                                "Commit",
                                id="change-review-commit",
                                classes="change-review-action",
                            )
                            yield Button(
                                "Close", id="change-review-close", variant="default"
                            )
                        with Horizontal(id="change-review-body"):
                            yield ChangedFilesTree(id="change-review-tree")
                            with Vertical(id="change-review-preview-column"):
                                with Horizontal(id="change-review-preview-actions"):
                                    yield Static(
                                        "Stage",
                                        id="change-review-stage-file",
                                        classes="change-review-action",
                                    )
                                    yield Static(
                                        "Unstage",
                                        id="change-review-unstage-file",
                                        classes="change-review-action",
                                    )
                                    yield Static(
                                        "Discard",
                                        id="change-review-discard-file",
                                        classes="change-review-action",
                                    )
                                yield ScrollableContainer(id="change-review-preview")
                    with Container(id="conversation-shell"):
                        yield VerticalScroll(id="conversation")
                        yield Static("", id="empty-state")
                        with Container(id="startup-state"):
                            with Vertical(id="startup-stack"):
                                yield Static("Launching iTE", id="startup-title")
                                yield Static(
                                    "Preparing your workspace and checking your session.",
                                    id="startup-copy",
                                )
                                yield Static("", id="startup-status")
                        with Container(id="signed-out-state"):
                            with Vertical(id="signed-out-stack"):
                                yield Static("", id="signed-out-copy")
                                with Horizontal(id="signed-out-actions"):
                                    yield Button(
                                        "Sign in", id="cloud-sign-in", variant="primary"
                                    )
                                    yield Button(
                                        "Exit", id="cloud-exit", variant="default"
                                    )
                                yield Static("", id="signed-out-status")
                        with Container(id="onboarding-state"):
                            with Vertical(id="onboarding-stack"):
                                yield Static(
                                    "Welcome to iTE",
                                    id="onboarding-title",
                                )
                                yield Static(
                                    "A quick setup before you start. Tell iTE a little about you, then choose how you want iTE to reach your model: Ollama on this computer, OpenRouter, or another compatible API.",
                                    id="onboarding-copy",
                                )
                                yield Input(
                                    placeholder="Your name",
                                    id="onboarding-name",
                                )
                                yield Select(
                                    [
                                        (option, option)
                                        for option in ONBOARDING_ROLE_OPTIONS
                                    ]
                                    + [("Other", ONBOARDING_OTHER_VALUE)],
                                    prompt="What do you do?",
                                    allow_blank=True,
                                    id="onboarding-role-select",
                                )
                                yield Input(
                                    placeholder="What do you do? e.g. software engineer, doctor, founder",
                                    id="onboarding-role-other",
                                )
                                yield Select(
                                    [
                                        (option, option)
                                        for option in ONBOARDING_USE_CASE_OPTIONS
                                    ]
                                    + [("Other", ONBOARDING_OTHER_VALUE)],
                                    prompt="What are you using iTE for right now?",
                                    allow_blank=True,
                                    id="onboarding-use-case-select",
                                )
                                yield Input(
                                    placeholder="What are you using iTE for right now?",
                                    id="onboarding-use-case-other",
                                )
                                with Horizontal(id="onboarding-actions"):
                                    yield Button(
                                        "Skip",
                                        id="onboarding-skip",
                                        variant="default",
                                    )
                                    yield Button(
                                        "Continue",
                                        id="onboarding-continue",
                                        variant="primary",
                                    )
                                yield Static("", id="onboarding-status")
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
        saved_theme = load_theme()
        self._suppress_theme_prompt_sync = True
        try:
            self.theme = saved_theme or detect_host_textual_theme()
        finally:
            self._suppress_theme_prompt_sync = False
        self.query_one("#aside-toggle", Button).display = False
        self.query_one("#changes-toggle", Button).display = False
        self.refresh_header()
        self._set_loading_state("idle", busy=False)
        self._refresh_empty_state()
        self._resize_composer_for_prompt()
        self._apply_aside_panel_state()
        self._apply_change_review_panel_state()
        self.set_interval(0.1, self._tick_top_indicator)
        self.set_interval(0.35, self._tick_live_context_meter)
        self.set_interval(1.0, self._poll_change_review_panel)
        self._set_loading_state("starting up", busy=True)
        if self.config.cloud_auth_enabled:
            self._cloud_bootstrap_busy = True
            self._set_signed_out_state(True)
        self.run_worker(self._initialize_command_palette(), exclusive=False)
        self.run_worker(self._bootstrap_after_mount(), exclusive=False)

    async def _initialize_command_palette(self) -> None:
        if self._command_registry_ready or self._command_registry_loading:
            return
        self._command_registry_loading = True
        try:
            self._command_registry = await asyncio.to_thread(build_registry)
            self._command_palette_options = self._build_command_palette_options()
            self._command_registry_ready = True
            if self.is_mounted:
                try:
                    prompt = self.query_one("#prompt", TextArea)
                except Exception:
                    prompt = None
                if prompt is not None:
                    self._sync_command_palette(str(getattr(prompt, "text", "") or ""))
        finally:
            self._command_registry_loading = False

    async def _ensure_command_registry(self) -> None:
        if self._command_registry_ready and self._command_registry is not None:
            return
        await self._initialize_command_palette()

    async def _bootstrap_after_mount(self) -> None:
        try:
            if self.config.cloud_auth_enabled:
                self._set_startup_phase("Checking iTE Cloud")
                has_cloud_session = await asyncio.to_thread(
                    has_stored_cloud_auth, self.config
                )
                if not has_cloud_session:
                    self._cloud_bootstrap_busy = False
                    self._set_startup_state(False)
                    self._set_signed_out_state(True)
                    self._set_loading_state("idle", busy=False)
                    return

                self._set_signed_out_state(False)
                self._cloud_bootstrap_busy = False
                # Cloud verification is on-demand; startup should not block on network reachability.

            if self._should_show_onboarding():
                self._set_startup_state(False)
                self._set_onboarding_state(True)
                self._set_loading_state("idle", busy=False)
                self.query_one("#onboarding-name", Input).focus()
                return

            self._set_startup_phase("Starting runtime")
            await self.ensure_agent()
            self._set_startup_state(False)
            self._schedule_usage_meta_refresh()
            await self._refresh_change_review_source()
            self._set_loading_state("idle", busy=False)
            self.query_one("#prompt", TextArea).focus()
            self._sync_command_palette("")
        except Exception as exc:
            self._cloud_bootstrap_busy = False
            self._set_loading_state("idle", busy=False)
            self._fail_startup(exc)

    def _should_show_onboarding(self) -> bool:
        return not bool(self.config.onboarding_completed)

    # REMOVED: _verify_cloud_auth_after_startup()
    # Background timer-based auth checks removed.
    # Cloud auth is now handled on-demand via ensure_cloud_auth() before cloud API calls.

    def _syntax_theme_name(self) -> str:
        syntax_theme = getattr(self.current_theme, "syntax_theme", None)
        if isinstance(syntax_theme, str) and syntax_theme.strip():
            return syntax_theme.strip()
        # Map Textual themes to appropriate Pygments code themes
        light_themes = {
            "atom-one-light",
            "rose-pine-dawn",
            "solarized-light",
            "textual-light",
            "catppuccin-latte",
        }
        if (
            self.theme in light_themes
            or getattr(self.current_theme, "dark", not True) is False
        ):
            return "default"  # Pygments light theme
        return "monokai"  # Pygments dark theme

    def _theme_tokens(self) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in self.current_theme.to_color_system().generate().items()
        }

    def _theme_style(self, token: str, fallback: str) -> str:
        return normalize_style_color(self._theme_tokens().get(token), fallback)

    def _prefer_terminal_safe_source_rendering(self) -> bool:
        return is_light_background(self._theme_tokens())

    def _render_styles(self) -> dict[str, str]:
        theme_tokens = self._theme_tokens()
        palette = render_palette(theme_tokens)
        return {
            "background": palette["background"],
            "fg": palette["fg"],
            "muted": palette["muted"],
            "disabled": palette["disabled"],
            "button_fg": self._theme_style("button-color-foreground", "#07140f"),
            "panel": self._theme_style("panel", "#242f38"),
            "surface": self._theme_style("surface", "#1e1e1e"),
            "border": palette["border"],
            "primary": palette["primary"],
            "secondary": palette["secondary"],
            "accent": palette["accent"],
            "warning": palette["warning"],
            "error": palette["error"],
            "success": palette["success"],
        }

    def _style(self, key: str) -> str:
        return self._render_styles()[key]

    async def _rerender_assistant_cards_for_theme(self) -> None:
        """Re-render assistant cards that use Rich colors when theme changes."""
        from ite.skills.rendering import (
            build_skill_detail_renderable,
            build_skill_feedback_renderable,
            build_skills_overview_renderable,
        )
        from ite.ui.reup.change_views import build_change_card_body

        conversation = self.query_one("#conversation", VerticalScroll)
        styles = self._render_styles()
        is_light = self._prefer_terminal_safe_source_rendering()

        async def replace_card_body(card: Widget, body_widget: Static, body: Any) -> None:
            new_body_widget = Static(classes=" ".join(body_widget.classes))
            new_body_widget.update(body)
            await body_widget.remove()
            await card.mount(new_body_widget)

        for child in list(conversation.children):
            # Check if this is a Container widget with class checking capability
            try:
                if not hasattr(child, "has_class"):
                    continue
            except Exception:
                continue

            # Re-render skills cards
            if child.has_class("skills"):
                try:
                    body_widget = child.query_one(".card-body", Static)
                    # Skills cards need session context - skip if no session
                    if not self.agent or not self.agent.session:
                        continue
                    session = self.agent.session
                    active_ids = {
                        skill.identifier for skill in session.get_active_skills()
                    }
                    # Re-render overview
                    new_body = build_skills_overview_renderable(
                        session.skill_manager.list_skills(),
                        active_ids,
                        styles=styles,
                    )
                    body_widget.update(new_body)
                except Exception:
                    pass

            # Re-render native command cards whose Rich bodies depend on theme colors.
            if child.has_class("stats"):
                try:
                    body_widget = child.query_one(".card-body", Static)
                    if not self.agent or not self.agent.session:
                        continue
                    new_body = build_stats_command_renderable(
                        self.agent.session.get_stats(),
                        styles=styles,
                    )
                    await replace_card_body(child, body_widget, new_body)
                except Exception:
                    pass

            # Re-render change cards
            if child.has_class("change"):
                try:
                    body_widget = child.query_one(".card-body", Static)
                    # Find stored state for this change card
                    card_index = conversation.children.index(child)
                    state = self._change_card_states.get(card_index)
                    if state:
                        from ite.ui.reup.change_views import build_change_card_body

                        new_body = build_change_card_body(
                            state["change_set"],
                            cwd=self.config.cwd,
                            verb=state["verb"],
                            footer=state["footer"],
                            mode=state["mode"],
                            is_light=is_light,
                        )
                        body_widget.update(new_body)
                except Exception:
                    pass

    async def _rerender_change_review_for_theme(self) -> None:
        """Re-render change review panel when theme changes."""
        if not self._change_review_visible or not self._change_review_change_set:
            return
        tree = self.query_one("#change-review-tree", ChangedFilesTree)
        # Update tree styles
        tree._styles = self._render_styles()
        # Re-populate with current selection
        current_selection = self._change_review_selected_rel_path
        await self._populate_change_review_panel()

    def watch_theme(self, _old_theme: str, _new_theme: str) -> None:
        self.refresh_header()
        self._refresh_empty_state()
        self._update_composer_meta_line()
        try:
            prompt = self.query_one("#prompt", TextArea)
        except Exception:
            prompt = None
        if prompt is not None and not self._suppress_theme_prompt_sync:
            self._sync_command_palette(str(getattr(prompt, "text", "") or ""))
        if self._cloud_signed_out:
            try:
                self.query_one("#signed-out-copy", Static).update(
                    build_signed_out_state_renderable(styles=self._render_styles())
                )
                self.query_one("#signed-out-status", Static).update(
                    self._signed_out_status_text()
                )
            except NoMatches:
                pass

        def _rerender_theme_sensitive_ui() -> None:
            self.run_worker(
                self._rerender_completed_tool_cards_for_theme(), exclusive=False
            )
            self.run_worker(
                self._rerender_assistant_cards_for_theme(), exclusive=False
            )
            if self._change_review_visible:
                self.run_worker(
                    self._rerender_change_review_for_theme(), exclusive=False
                )

        self.call_after_refresh(_rerender_theme_sensitive_ui)

    async def _rerender_completed_tool_cards_for_theme(self) -> None:
        for call_id, state in list(self._tool_completion_state.items()):
            card = self._tool_widgets.get(call_id)
            if card is None:
                continue
            await self.update_tool_call(
                call_id=call_id,
                name=str(state.get("name") or ""),
                tool_kind=state.get("tool_kind"),
                success=bool(state.get("success")),
                output=str(state.get("output") or ""),
                error=state.get("error")
                if isinstance(state.get("error"), str)
                else None,
                metadata=state.get("metadata")
                if isinstance(state.get("metadata"), dict)
                else None,
                diff=state.get("diff") if isinstance(state.get("diff"), str) else None,
                truncated=bool(state.get("truncated")),
                exit_code=state.get("exit_code")
                if isinstance(state.get("exit_code"), int)
                else None,
                pin_after_update=False,
            )

    async def on_unmount(self) -> None:
        await self._shutdown_remote_server()
        await self._shutdown_agents()

    async def _shutdown_agents(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True

        try:
            await asyncio.wait_for(self.cancel_active_turn(), timeout=1.5)
        except Exception:
            pass

        agents_to_close: dict[str, Agent] = {}
        if self.agent is not None and self.agent.session is not None:
            session_id = self._session_id(self.agent.session)
            if session_id:
                agents_to_close[session_id] = self.agent
        agents_to_close.update(self._session_agents)

        for agent in agents_to_close.values():
            try:
                await asyncio.wait_for(agent.__aexit__(None, None, None), timeout=2.0)
            except Exception:
                pass

        if self.agent is not None:
            self.agent = None

    async def _shutdown_remote_server(self) -> None:
        if self._remote_server is None:
            return
        try:
            await self._remote_server.stop()
        finally:
            self._remote_server = None

    async def _ensure_remote_server(
        self,
        *,
        port: int | None = None,
        lan: bool = True,
    ) -> dict[str, Any]:
        if self._remote_server is None:
            self._remote_server = RemoteRuntimeServer(
                state_provider=self._build_remote_runtime_state,
                submit_prompt=self._submit_remote_prompt,
                cancel_turn=self._cancel_remote_turn,
                switch_session=self._switch_remote_session,
            )
        selected_port = (
            int(port)
            if isinstance(port, int) and port >= 0
            else int(self._remote_port_preference or 0)
        )
        bind_host = "0.0.0.0" if lan else "127.0.0.1"
        if (
            self._remote_server.is_running
            and self._remote_server.connection_info().get("exposure_mode")
            != ("lan" if lan else "local")
        ):
            await self._remote_server.stop()
        info = await self._remote_server.start(host=bind_host, port=selected_port)
        self._remote_port_preference = int(info.get("port") or selected_port or 0)
        return info

    def _build_remote_runtime_state(self) -> dict[str, Any]:
        session = self.agent.session if self.agent and self.agent.session else None
        active_session_id = self._active_session_id()
        run_state = self._run_state(active_session_id)
        transcript: list[dict[str, Any]] = []
        if session and session.context_manager is not None:
            transcript_state = session.context_manager.export_transcript_state()
            transcript = build_remote_transcript(
                transcript_state.get("events", [])
                if isinstance(transcript_state, dict)
                else []
            )

        open_sessions: list[dict[str, Any]] = []
        for session_id in self._open_session_order:
            open_session = self._open_sessions.get(session_id)
            if open_session is None:
                continue
            workspace = self._open_session_workspaces.get(session_id)
            open_sessions.append(
                {
                    "session_id": session_id,
                    "title": self._session_title(open_session),
                    "turn_count": int(getattr(open_session, "turn_count", 0) or 0),
                    "is_active": session_id == active_session_id,
                    "workspace": str(workspace) if workspace is not None else "",
                    "is_running": bool(self._run_state(session_id).is_turn_running),
                }
            )

        return {
            "app": {"name": "iTE", "surface": "reup"},
            "current_session": {
                "session_id": active_session_id or "",
                "title": self._current_session_title(),
                "workspace": str(self.config.cwd.resolve()),
                "model": str(self.config.model_name or ""),
                "approval_mode": str(self.config.approval.value),
                "plan_mode_enabled": bool(session.plan_mode_enabled)
                if session
                else False,
                "plan_phase": str(session.plan_phase) if session else "idle",
                "active_turn_id": int(run_state.active_turn_id),
                "is_turn_running": bool(run_state.is_turn_running),
                "activity_label": str(self._top_state_text or ""),
                "activity_busy": bool(self._top_busy),
                "turn_had_error": bool(run_state.turn_had_error),
                "last_error_message": str(run_state.last_error_message or ""),
            },
            "open_sessions": open_sessions,
            "transcript": transcript,
            "command_feed": list(self._remote_command_feed),
            "change_feed": list(self._remote_change_feed),
        }

    async def _broadcast_remote_state(self) -> None:
        if self._remote_server is None or not self._remote_server.is_running:
            return
        await self._remote_server.publish_state()

    async def _broadcast_remote_agent_event(
        self,
        session_id: str,
        turn_id: int,
        event: AgentEvent,
    ) -> None:
        if self._remote_server is None or not self._remote_server.is_running:
            return
        await self._remote_server.publish_event(
            serialize_agent_event(event, session_id=session_id, turn_id=turn_id)
        )

    async def _submit_remote_prompt(self, message: str) -> None:
        payload = self._build_turn_payload(message)
        await self._dispatch_payload(payload)

    async def _cancel_remote_turn(self) -> None:
        if self._is_turn_running:
            await self.cancel_active_turn()

    async def _switch_remote_session(self, session_id: str) -> bool:
        if not session_id:
            return False
        return await self._activate_open_session(session_id)

    async def _run_remote_command_from_registry(self, args: list[str]) -> None:
        await self._run_remote_command_native(args)

    async def _run_remote_command_native(self, args: list[str]) -> None:
        action = args[0].lower() if args else "start"
        option_args = args[1:]
        if action.isdigit():
            option_args = [action, *option_args]
            action = "start"

        if action in {"start", "on"}:
            lan = True
            port = None
            for arg in option_args:
                if arg == "--lan":
                    lan = True
                    continue
                if arg == "--local":
                    lan = False
                    continue
                try:
                    port = int(arg)
                except ValueError:
                    self.post_system(
                        "Remote",
                        "Usage: /remote on [port] [--local]",
                        is_error=True,
                    )
                    return
            info = await self._ensure_remote_server(port=port, lan=lan)
            self.post_remote_bridge(
                runtime_name=str(info.get("runtime_name") or ""),
                exposure_mode=str(info.get("exposure_mode") or "local"),
                host=str(info["display_host"]),
                port=int(info["port"]),
                pair_code=str(info["pair_code"]),
                fingerprint=str(info.get("fingerprint") or ""),
                connect_uri=str(info["connect_uri"]),
                authenticated_clients=int(info.get("authenticated_clients") or 0),
                trusted_devices=int(info.get("trusted_devices") or 0),
                intro="Mobile bridge ready." if lan else "Remote bridge ready for local-only mode.",
                footer="Open the mobile app and use Paste and Connect with the secure link."
                if lan
                else "This bridge is local-only. Run `/remote on` when you want your phone to connect.",
            )
            return

        if action in {"status"}:
            if self._remote_server is None or not self._remote_server.is_running:
                self.post_system("Remote", "Remote bridge is off.")
                return
            info = self._remote_server.connection_info()
            self.post_remote_bridge(
                runtime_name=str(info.get("runtime_name") or ""),
                exposure_mode=str(info.get("exposure_mode") or "local"),
                host=str(info["display_host"]),
                port=int(info["port"]),
                pair_code=str(info["pair_code"]),
                fingerprint=str(info.get("fingerprint") or ""),
                connect_uri=str(info["connect_uri"]),
                authenticated_clients=int(info.get("authenticated_clients") or 0),
                trusted_devices=int(info.get("trusted_devices") or 0),
                intro="Remote bridge is running.",
                footer="Use the secure link for trusted pairing. Existing trusted devices can reconnect automatically.",
            )
            return

        if action in {"code", "pair"}:
            info = await self._ensure_remote_server()
            assert self._remote_server is not None
            self._remote_server.regenerate_pair_code()
            info = self._remote_server.connection_info()
            self.post_remote_bridge(
                runtime_name=str(info.get("runtime_name") or ""),
                exposure_mode=str(info.get("exposure_mode") or "local"),
                host=str(info["display_host"]),
                port=int(info["port"]),
                pair_code=str(info["pair_code"]),
                fingerprint=str(info.get("fingerprint") or ""),
                connect_uri=str(info["connect_uri"]),
                authenticated_clients=int(info.get("authenticated_clients") or 0),
                trusted_devices=int(info.get("trusted_devices") or 0),
                intro="Pair code refreshed.",
                footer="Reconnect with the updated secure link if the app is not already trusted.",
            )
            await self._broadcast_remote_state()
            return

        if action in {"devices", "trusted"}:
            if self._remote_server is None or not self._remote_server.is_running:
                self.post_system("Remote", "Remote bridge is off.")
                return
            devices = self._remote_server.trusted_devices_snapshot()
            if not devices:
                self.post_system("Remote", "No trusted mobile devices.")
                return
            lines = ["Trusted mobile devices:"]
            for device in devices:
                lines.append(
                    f"- {device['device_id_short']} · {device['name'] or 'iTE Remote'} [{device['platform'] or 'unknown'}] "
                    f"{device['status']} last seen {device['last_seen_at']}"
                )
            self.post_system("Remote", "\n".join(lines))
            return

        if action in {"revoke"}:
            if self._remote_server is None or not self._remote_server.is_running:
                self.post_system("Remote", "Remote bridge is off.")
                return
            selector = option_args[0].strip() if option_args else ""
            if not selector:
                self.post_system(
                    "Remote",
                    "Usage: /remote revoke <device-id-prefix>",
                    is_error=True,
                )
                return
            revoked = self._remote_server.revoke_device(selector)
            if revoked is None:
                self.post_system(
                    "Remote",
                    f"No trusted device matched '{selector}'.",
                    is_error=True,
                )
                return
            await self._broadcast_remote_state()
            self.post_system(
                "Remote",
                f"Revoked device {revoked.device_id[:8]} ({revoked.name or 'iTE Remote'}).",
            )
            return

        if action in {"revoke-all", "reset"}:
            if self._remote_server is None or not self._remote_server.is_running:
                self.post_system("Remote", "Remote bridge is off.")
                return
            revoked = self._remote_server.revoke_all_devices()
            await self._broadcast_remote_state()
            self.post_system(
                "Remote",
                "Revoked all trusted mobile devices."
                if revoked
                else "No trusted mobile devices were active.",
            )
            return

        if action in {"stop", "off"}:
            if self._remote_server is None or not self._remote_server.is_running:
                self.post_system("Remote", "Remote bridge is already off.")
                return
            await self._shutdown_remote_server()
            self.post_system("Remote", "Remote bridge stopped.")
            return

        self.post_system(
            "Remote",
            "Usage: /remote\n/remote on [port]\n/remote on [port] --local\n/remote status\n/remote code\n/remote devices\n/remote revoke <device-id-prefix>\n/remote revoke-all\n/remote off",
            is_error=True,
        )

    def _current_session_title(self) -> str:
        return self._session_title(self.agent.session if self.agent else None)

    def _session_title(self, session: Session | None) -> str:
        if session is None:
            return "New thread"
        if isinstance(session.name, str) and session.name.strip():
            return session.name.strip()
        if session.turn_count > 0:
            return "Untitled thread"
        return "New thread"

    def _session_id(self, session: Session | None) -> str | None:
        if session is None:
            return None
        session_id = str(getattr(session, "session_id", "") or "").strip()
        return session_id or None

    def _active_session_id(self) -> str | None:
        return self._session_id(self.agent.session if self.agent else None)

    def _run_state(self, session_id: str | None = None) -> SessionRunState:
        sid = session_id or self._active_session_id()
        if not sid:
            return self._fallback_run_state
        state = self._session_run_states.get(sid)
        if state is None:
            state = SessionRunState()
            self._session_run_states[sid] = state
        return state

    @property
    def _active_turn_task(self) -> asyncio.Task | None:
        return self._run_state().active_turn_task

    @_active_turn_task.setter
    def _active_turn_task(self, value: asyncio.Task | None) -> None:
        self._run_state().active_turn_task = value

    @property
    def _active_turn_id(self) -> int:
        return self._run_state().active_turn_id

    @_active_turn_id.setter
    def _active_turn_id(self, value: int) -> None:
        self._run_state().active_turn_id = value

    @property
    def _is_turn_running(self) -> bool:
        return self._run_state().is_turn_running

    @_is_turn_running.setter
    def _is_turn_running(self, value: bool) -> None:
        self._run_state().is_turn_running = value

    @property
    def _turn_had_error(self) -> bool:
        return self._run_state().turn_had_error

    @_turn_had_error.setter
    def _turn_had_error(self, value: bool) -> None:
        self._run_state().turn_had_error = value

    @property
    def _queued_turn_payload(self) -> dict[str, Any] | None:
        return self._run_state().queued_turn_payload

    @_queued_turn_payload.setter
    def _queued_turn_payload(self, value: dict[str, Any] | None) -> None:
        self._run_state().queued_turn_payload = value

    def _remember_open_session(
        self,
        session: Session,
        *,
        workspace: Path | None = None,
        agent: Agent | None = None,
        move_to_end: bool = False,
    ) -> None:
        session_id = self._session_id(session)
        if not session_id:
            return
        self._open_sessions[session_id] = session
        if agent is not None:
            self._session_agents[session_id] = agent
        self._open_session_workspaces[session_id] = (
            workspace or self.config.cwd
        ).resolve()
        self._run_state(session_id)
        if session_id not in self._open_session_order:
            self._open_session_order.append(session_id)
        elif move_to_end:
            self._open_session_order.remove(session_id)
            self._open_session_order.append(session_id)

    def _workspace_for_session_id(self, session_id: str | None) -> Path:
        if session_id and session_id in self._open_session_workspaces:
            return self._open_session_workspaces[session_id]
        return Path(self.config.cwd).resolve()

    def _find_reusable_empty_session_id(
        self, *, exclude_session_id: str | None = None
    ) -> str | None:
        for session_id in self._open_session_order:
            if exclude_session_id and session_id == exclude_session_id:
                continue
            session = self._open_sessions.get(session_id)
            if session is None:
                continue
            if session.turn_count != 0:
                continue
            if self._run_state(session_id).is_turn_running:
                continue
            return session_id
        return None

    def _neighbor_session_id_for_close(self, session_id: str) -> str | None:
        if session_id not in self._open_session_order:
            return None
        remaining = [sid for sid in self._open_session_order if sid != session_id]
        if not remaining:
            return None
        index = self._open_session_order.index(session_id)
        if index > 0:
            return self._open_session_order[index - 1]
        return remaining[0]

    def _drop_open_session(self, session_id: str) -> Agent | None:
        self._open_sessions.pop(session_id, None)
        self._open_session_workspaces.pop(session_id, None)
        self._open_session_order = [
            sid for sid in self._open_session_order if sid != session_id
        ]
        self._session_run_states.pop(session_id, None)
        return self._session_agents.pop(session_id, None)

    def _session_tab_label(self, session_id: str) -> str:
        session = self._open_sessions.get(session_id)
        title = self._session_title(session)
        title = re.sub(r"\s+", " ", title).strip() or "New thread"
        if self._run_state(session_id).is_turn_running:
            title = f"●●● {title}"
        return title

    def _queue_session_tabs_refresh(self) -> None:
        self._session_tabs_version += 1
        self.run_worker(
            self._refresh_session_tabs(),
            exclusive=True,
            group="session-tabs",
        )

    async def _refresh_session_tabs(self) -> None:
        version = self._session_tabs_version
        if not self.is_mounted:
            return
        try:
            tabs = self.query_one("#session-tabs", Horizontal)
            tabs_scroll = self.query_one("#session-tabs-scroll", HorizontalScroll)
        except Exception:
            return
        await tabs.remove_children()
        if version != self._session_tabs_version:
            return
        active_session_id = self._session_id(self.agent.session if self.agent else None)
        if self._cloud_signed_out:
            tabs.display = False
            tabs_scroll.display = False
            return
        tabs.display = len(self._open_session_order) > 1
        tabs_scroll.display = tabs.display
        if not tabs.display:
            return
        for session_id in self._open_session_order:
            if version != self._session_tabs_version:
                return
            label = self._session_tab_label(session_id)
            variant = "primary" if session_id == active_session_id else "default"
            classes = "session-tab"
            if self._run_state(session_id).is_turn_running:
                classes += " session-tab-live"
            await tabs.mount(
                Button(
                    label,
                    id=f"session-tab-{session_id}",
                    variant=variant,
                    classes=classes,
                )
            )

    def refresh_header(self) -> None:
        current_workspace_key = str(Path(self.config.cwd).resolve())
        if (
            self._agents_recommendation_last_workspace_key is not None
            and self._agents_recommendation_last_workspace_key != current_workspace_key
        ):
            self._agents_recommendation_current_visit = None
        self._agents_recommendation_last_workspace_key = current_workspace_key
        title = self.query_one("#title", Static)
        meta = self.query_one("#header-meta", Static)
        if self._cloud_signed_out:
            title.update("Sign in")
            meta.update("iTE Cloud required")
        else:
            title.update(self._current_session_title())
            meta.update(f"Workspace: {self.config.cwd}")
        self._update_composer_meta_line()
        self.run_worker(self._refresh_change_review_source(), exclusive=False)
        self._queue_session_tabs_refresh()

    def _update_composer_meta_line(self) -> None:
        try:
            composer_meta_line = self.query_one("#composer-meta-line", Static)
        except Exception:
            return
        composer_meta_line.update(self._composer_meta_text())

    def _tick_live_context_meter(self) -> None:
        if not self.is_mounted or not self._is_turn_running:
            return
        self._update_composer_meta_line()

    async def _show_activity_indicator(
        self, label: str, version: int | None = None
    ) -> None:
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
        await self._pin_activity_indicator_to_end()

    async def _pin_activity_indicator_to_end(self) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        if self._activity_widget is None:
            conversation.scroll_end(animate=False)
            return
        children = list(conversation.children)
        if children and children[-1] is not self._activity_widget:
            try:
                await self._activity_widget.remove()
                await conversation.mount(self._activity_widget)
            except Exception:
                pass
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

    def _render_live_compaction_body(self, message: str, *, active: bool) -> Text:
        styles = self._render_styles()
        content = Text()
        if active:
            frame = self._top_spinner_frames[
                self._top_spinner_index % len(self._top_spinner_frames)
            ]
            suffix = self._activity_suffix_frames[
                self._activity_suffix_index % len(self._activity_suffix_frames)
            ]
            content.append(frame, style=f"bold {self._style('success')}")
            content.append(" ")
            content.append(
                message.strip() or "Compacting context", style=self._style("fg")
            )
            content.append(suffix, style=f"bold {self._style('muted')}")
            return content
        content.append(message.strip(), style=self._style("fg"))
        return content

    async def _start_live_compaction_card(
        self, message: str = "Compacting context"
    ) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        if self._live_compaction_body is None or self._live_compaction_card is None:
            title_widget = Static("Context", classes="card-title note-title")
            body_widget = Static(classes="card-body note-body")
            card = Container(
                title_widget,
                body_widget,
                classes="block note",
            )
            await conversation.mount(card)
            self._live_compaction_card = card
            self._live_compaction_body = body_widget
            self._message_count += 1
            self._refresh_empty_state()
        self._live_compaction_active = True
        self._live_compaction_body.update(
            self._render_live_compaction_body(message, active=True)
        )
        await self._pin_activity_indicator_to_end()

    async def _finish_live_compaction_card(self, message: str) -> None:
        if self._live_compaction_body is None or self._live_compaction_card is None:
            await self._start_live_compaction_card()
        self._live_compaction_active = False
        if self._live_compaction_body is not None:
            self._live_compaction_body.update(
                self._render_live_compaction_body(message, active=False)
            )
        await self._pin_activity_indicator_to_end()

    def _cancel_activity_resume_timer(self) -> None:
        timer = self._activity_resume_timer
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            pass
        self._activity_resume_timer = None

    def _schedule_activity_indicator_resume(self, *, delay: float = 0.7) -> None:
        self._cancel_activity_resume_timer()
        version = self._activity_version

        def _resume() -> None:
            self._activity_resume_timer = None
            if version != self._activity_version:
                return
            if not self._is_turn_running:
                return
            self.run_worker(
                self._show_activity_indicator(
                    self._progress_state_label(),
                    version,
                ),
                exclusive=False,
            )

        self._activity_resume_timer = self.set_timer(delay, _resume)

    def _render_activity_indicator_text(self, label: str) -> Text:
        styles = self._render_styles()
        frame = self._top_spinner_frames[
            self._top_spinner_index % len(self._top_spinner_frames)
        ]
        suffix = self._activity_suffix_frames[
            self._activity_suffix_index % len(self._activity_suffix_frames)
        ]
        content = Text()
        content.append(frame, style=f"bold {styles['success']}")
        content.append(" ")
        content.append(
            (label or "Thinking").strip().title() or "Thinking",
            style=f"bold {styles['fg']}",
        )
        content.append(suffix, style=f"bold {styles['secondary']}")
        return content

    def _composer_meta_text(self) -> Text:
        plan_enabled = bool(
            self.agent and self.agent.session and self.agent.session.plan_mode_enabled
        )
        context_used_percent: int | None = None
        branch_label = "no-git"
        try:
            cwd = Path(self.config.cwd).resolve()
            if is_git_repo(cwd):
                branch_label = current_branch(cwd)
        except Exception:
            pass
        if self.agent and self.agent.session and self.agent.session.context_manager:
            try:
                context_used_percent = int(
                    round(
                        float(
                            self.agent.session.get_stats().get("context_used_pct", 0.0)
                        )
                    )
                )
            except Exception:
                context_used_percent = None
        floor_pct = self._run_state().context_meter_floor_pct
        if context_used_percent is not None and floor_pct is not None:
            context_used_percent = max(context_used_percent, floor_pct)
        model_display_name = self._model_display_name()
        (
            text,
            attach_hitbox,
            model_hitbox,
            branch_hitbox,
            plan_hitbox,
            usage_hitbox,
            context_hitbox,
            activity_hitbox,
        ) = composer_meta_text(
            cwd=Path(self.config.cwd),
            model_name=model_display_name,
            plan_enabled=plan_enabled,
            branch_label=branch_label,
            usage_remaining_percent=self._usage_remaining_percent,
            context_used_percent=context_used_percent,
            styles=self._render_styles(),
            show_usage=self._is_bundled_model(),
        )
        self._composer_attach_hitbox = attach_hitbox
        self._composer_model_hitbox = model_hitbox
        self._composer_branch_hitbox = branch_hitbox
        self._composer_plan_hitbox = plan_hitbox
        self._composer_usage_hitbox = usage_hitbox
        self._composer_context_hitbox = context_hitbox
        self._composer_activity_hitbox = activity_hitbox
        return text

    def _setup_required_for_model_selection(self) -> bool:
        if self._has_active_user_provider_credentials():
            return False
        if load_saved_custom_provider():
            return False
        if get_bundled_models(self.config):
            return False
        return True

    def _has_active_user_provider_credentials(self) -> bool:
        return bool(
            str(self.config.api_key or "").strip()
            and str(self.config.base_url or "").strip()
        )

    def _model_display_name(self) -> str:
        if self._setup_required_for_model_selection():
            return "/setup"
        return self.config.model_name

    def _schedule_usage_meta_refresh(self) -> None:
        if self._usage_refresh_in_flight or self._cloud_signed_out:
            return
        self.run_worker(self._refresh_usage_meta(), exclusive=False)

    def _is_bundled_model(self) -> bool:
        """Check if current model is a bundled (backend-provided) model.

        Returns False for user keys (Ollama, OpenRouter, custom providers).
        """
        model = str(self.config.model_name or "").strip()
        if not model or self._has_active_user_provider_credentials():
            return False
        saved_providers = load_saved_custom_provider()
        if model in saved_providers:
            return False
        bundled_models = {
            str(item.get("model_name") or "").strip()
            for item in get_bundled_models(self.config)
        }
        return model in bundled_models

    def _schedule_usage_meta_refresh_for_cloud_model(self) -> None:
        if not self._is_bundled_model():
            if self._usage_remaining_percent is not None:
                self._usage_remaining_percent = None
                self.refresh_header()
            return
        self._schedule_usage_meta_refresh()

    async def _refresh_usage_meta(self) -> None:
        if self._usage_refresh_in_flight:
            return
        self._usage_refresh_in_flight = True
        try:
            summary = await asyncio.to_thread(get_usage_summary, self.config)
            remaining: int | None = None
            if summary:
                quotas = summary.get("quotas") or {}
                five_hour = quotas.get("fiveHour") or {}
                used = int(five_hour.get("usedUsdCents") or 0)
                cap = max(1, int(five_hour.get("capUsdCents") or 1))
                remaining = max(0, min(100, round(((cap - used) / cap) * 100)))
            if remaining != self._usage_remaining_percent:
                self._usage_remaining_percent = remaining
                self.refresh_header()
        finally:
            self._usage_refresh_in_flight = False

    def _build_command_palette_options(self) -> list[SlashCommandOption]:
        registry = self._command_registry
        if registry is None:
            return []
        options = build_command_palette_options(registry)
        if not any(option.name == "/theme" for option in options):
            options.append(
                SlashCommandOption(
                    name="/theme",
                    description="Choose a Textual theme for this session",
                )
            )
        return sorted(options, key=lambda option: option.name.lower())

    @staticmethod
    def _extract_slash_query(text: str) -> str | None:
        from .composer_views import extract_slash_query

        return extract_slash_query(text)

    @staticmethod
    def _extract_at_query(text: str) -> str | None:
        return extract_at_query(text)

    def _discover_attachable_files(self) -> list[Path]:
        cwd = Path(self.config.cwd).resolve()
        if self._attachable_files_cache_cwd == cwd and self._attachable_files_cache:
            return self._attachable_files_cache
        files = discover_attachable_files(cwd)
        self._attachable_files_cache = files
        self._attachable_files_cache_cwd = cwd
        return files

    def _filtered_attachment_palette(self, text: str) -> list[SlashCommandOption]:
        query = self._extract_at_query(text)
        if query is None:
            return []
        cwd = Path(self.config.cwd).resolve()
        matches = suggest_inline_attachment_paths(
            query,
            cwd=cwd,
            files=self._discover_attachable_files(),
            limit=50,
        )
        options: list[SlashCommandOption] = []
        for path in matches:
            try:
                rel = str(path.resolve().relative_to(cwd))
            except Exception:
                rel = str(path.resolve())
            rel_path = Path(rel)
            parent = str(rel_path.parent)
            secondary = "workspace root" if parent in {"", "."} else parent
            display_ref = self._attachment_ref_for_path(path.resolve())
            options.append(
                SlashCommandOption(
                    name=display_ref,
                    description=secondary,
                    insert_text=display_ref,
                    attachment_path=str(path.resolve()),
                )
            )
        return options

    def _filtered_command_palette(self, text: str) -> list[SlashCommandOption]:
        return filtered_command_palette(
            text,
            command_palette_options=self._command_palette_options,
        )

    def _command_palette_window(self) -> list[SlashCommandOption]:
        if not self._filtered_command_palette_options:
            return []
        max_rows = min(
            self.COMMAND_PALETTE_MAX_ROWS, len(self._filtered_command_palette_options)
        )
        start = max(0, self._command_palette_index - max_rows + 1)
        end = min(len(self._filtered_command_palette_options), start + max_rows)
        start = max(0, end - max_rows)
        return self._filtered_command_palette_options[start:end]

    def _render_command_palette(self) -> Text:
        return render_command_palette(
            filtered_options=self._filtered_command_palette_options,
            command_palette_index=self._command_palette_index,
            max_rows=self.COMMAND_PALETTE_MAX_ROWS,
            styles=self._render_styles(),
        )

    def _build_turn_action_options(
        self, *, replacing_queue: bool
    ) -> list[SlashCommandOption]:
        return build_turn_action_options(replacing_queue=replacing_queue)

    def _render_turn_action_palette(self) -> Text:
        return render_turn_action_palette(
            self._turn_action_options,
            self._command_palette_index,
            styles=self._render_styles(),
        )

    def _show_turn_action_palette(
        self, payload: dict[str, Any], *, replacing_queue: bool
    ) -> None:
        self._turn_action_payload = payload
        self._turn_action_replacing_queue = replacing_queue
        self._turn_action_options = self._build_turn_action_options(
            replacing_queue=replacing_queue
        )
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
            min(
                len(self._turn_action_options) - 1, self._command_palette_index + delta
            ),
        )
        if self.is_mounted:
            try:
                self.query_one("#command-palette", Static).update(
                    self._render_turn_action_palette()
                )
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
        at_options = self._filtered_attachment_palette(text)
        if at_options:
            self._palette_mode = "attachment"
            options = at_options
        else:
            self._palette_mode = "command"
            options = self._filtered_command_palette(text)
        if self._filtered_command_palette_options == options and (
            not options or self._command_palette_index < len(options)
        ):
            self._command_palette_rows = min(
                len(options), self.COMMAND_PALETTE_MAX_ROWS
            )
        else:
            self._filtered_command_palette_options = options
            self._command_palette_index = 0
            self._command_palette_rows = min(
                len(options), self.COMMAND_PALETTE_MAX_ROWS
            )

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

    def _clear_command_palette(self) -> None:
        self._filtered_command_palette_options = []
        self._command_palette_index = 0
        self._command_palette_rows = 0
        self._palette_mode = "command"
        if not self.is_mounted:
            return
        try:
            palette = self.query_one("#command-palette", Static)
        except Exception:
            return
        palette.display = False
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
                self.query_one("#command-palette", Static).update(
                    self._render_command_palette()
                )
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

    def _apply_attachment_palette_selection(self, option: SlashCommandOption) -> None:
        prompt = self.query_one("#prompt", TextArea)
        text = prompt.text or ""
        insert_text = option.insert_text or option.name
        updated = re.sub(
            r"(?:^|[\s(\[{])@[^\s@]*$",
            lambda match: (
                match.group(0)[:1] + insert_text
                if match.group(0)[:1].isspace() or match.group(0)[:1] in "([{"
                else insert_text
            ),
            text,
        )
        if updated == text:
            updated = (text + " " + insert_text).strip()
        prompt.load_text(updated + " ")
        prompt.move_cursor((0, len(prompt.text)))
        self._clear_command_palette()
        self._resize_composer_for_prompt()

    def _attachment_ref_for_path(self, path: Path) -> str:
        resolved = path.expanduser().resolve()
        cwd = Path(self.config.cwd).resolve()
        try:
            display = str(resolved.relative_to(cwd))
        except Exception:
            display = str(resolved)
        display = display.replace("\\", "/")
        if any(ch.isspace() for ch in display):
            return f'@"{display}"'
        return f"@{display}"

    def _insert_attachment_refs_into_prompt(self, paths: list[str]) -> int:
        prompt = self.query_one("#prompt", TextArea)
        existing = prompt.text or ""
        refs: list[str] = []
        for raw in paths:
            ref = self._attachment_ref_for_path(Path(raw))
            if ref in existing or ref in refs:
                continue
            refs.append(ref)
        if not refs:
            return 0
        separator = "\n" if existing.strip() else ""
        updated = f"{existing.rstrip()}{separator}{' '.join(refs)}".strip()
        prompt.load_text(updated + " ")
        prompt.move_cursor((0, len(prompt.text)))
        self._sync_command_palette(prompt.text)
        self._resize_composer_for_prompt()
        return len(refs)

    def _apply_command_palette_selection(self) -> bool:
        if self._turn_action_payload is not None:
            if not self._turn_action_options:
                return False
            action = ("steer", "queue", "aside", "cancel")[self._command_palette_index]
            self.run_worker(
                self._execute_turn_action_selection(action), exclusive=False
            )
            return True
        if not self._filtered_command_palette_options:
            return False
        option = self._filtered_command_palette_options[self._command_palette_index]
        if self._palette_mode == "attachment":
            self._apply_attachment_palette_selection(option)
            return True
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
        model_start, model_end = self._composer_model_hitbox
        branch_start, branch_end = self._composer_branch_hitbox
        usage_hitbox = self._composer_usage_hitbox
        usage_start = usage_hitbox[0] if usage_hitbox else -1
        usage_end = usage_hitbox[1] if usage_hitbox else -1
        context_start, context_end = self._composer_context_hitbox
        activity_start, activity_end = self._composer_activity_hitbox
        start, end = self._composer_plan_hitbox
        if attach_start <= event.x < attach_end:
            self.run_worker(self._open_attach_picker_from_meta(), exclusive=False)
            event.stop()
            return
        if model_start <= event.x < model_end:
            self.run_worker(self._open_model_picker_from_meta(), exclusive=False)
            event.stop()
            return
        if branch_start <= event.x < branch_end:
            self.run_worker(self._open_branch_picker_from_meta(), exclusive=False)
            event.stop()
            return
        if usage_hitbox is not None and 0 <= usage_start <= event.x < usage_end:
            self.run_worker(self._open_usage_modal_from_meta(), exclusive=False)
            event.stop()
            return
        if context_start <= event.x < context_end:
            self.run_worker(self._open_context_modal_from_meta(), exclusive=False)
            event.stop()
            return
        if activity_start <= event.x < activity_end:
            self.run_worker(self._open_activity_modal_from_meta(), exclusive=False)
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
            self.post_system(
                "Git", "Current workspace is not a git repository.", is_error=True
            )
            return

        branches = await asyncio.to_thread(list_local_branches, cwd)
        current = await asyncio.to_thread(current_branch, cwd)
        result = await self._open_modal(BranchPickerModal(current, branches))
        if not result:
            return

        action = str(result.get("action", "")).strip().lower()
        branch = str(result.get("branch", "")).strip()
        if not branch:
            self.post_system("Git", "Branch name is required.", is_error=True)
            return

        if action == "create":
            branch_result = await asyncio.to_thread(create_and_checkout, cwd, branch)
        else:
            branch_result = await asyncio.to_thread(checkout_branch, cwd, branch)

        if branch_result.ok:
            self.post_system("Git", branch_result.message)
        else:
            self.post_system("Git", branch_result.message, is_error=True)
        self.refresh_header()

    async def _open_model_picker_from_meta(self) -> None:
        await self.ensure_agent()
        if self._setup_required_for_model_selection():
            await self._open_setup_modal()
            return
        while True:
            current_model = self.config.model_name
            bundled_items = get_bundled_models(self.config)
            saved_providers = load_saved_custom_provider()
            bundled_model_names = {
                str(item.get("model_name") or "").strip() for item in bundled_items
            }

            model_options: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()

            def _current_entry_id() -> str:
                normalized_current = str(current_model or "").strip()
                if not normalized_current:
                    return ""
                if self._has_active_user_provider_credentials():
                    if normalized_current in saved_providers:
                        return f"saved:{normalized_current}"
                    return f"custom:{normalized_current}"
                if normalized_current in bundled_model_names:
                    return f"bundled:{normalized_current}"
                if normalized_current in saved_providers:
                    return f"saved:{normalized_current}"
                return f"custom:{normalized_current}"

            def _saved_provider_label(profile: dict[str, Any]) -> str:
                base_url = str(profile.get("base_url") or "").strip().lower()
                api_key = str(profile.get("api_key") or "").strip().lower()
                if (
                    not base_url
                    or "localhost:11434" in base_url
                    or "127.0.0.1:11434" in base_url
                    or api_key == "ollama"
                ):
                    return "Ollama"
                if "openrouter.ai" in base_url:
                    return "OpenRouter"
                parsed = urlparse(base_url)
                host = (parsed.netloc or parsed.path or "").strip().lower()
                if not host:
                    return "Custom provider"
                host = host.split("@")[-1].split(":")[0].strip(".")
                if host.startswith("www."):
                    host = host[4:]
                if not host:
                    return "Custom provider"
                return host

            def _append(
                source_kind: str,
                model_name: str,
                label: str,
                provider: str,
                *,
                context_window: int | None = None,
                context_window_source: str | None = None,
                available: bool = True,
                unavailable_reason: str = "",
                saved_profile: bool = False,
            ) -> None:
                normalized = str(model_name or "").strip()
                entry_id = f"{source_kind}:{normalized}"
                dedupe_key = (source_kind, normalized)
                if not normalized or dedupe_key in seen:
                    return
                seen.add(dedupe_key)
                option = {
                    "entry_id": entry_id,
                    "source_kind": source_kind,
                    "model_name": normalized,
                    "label": label,
                    "provider": provider,
                    "context_window": context_window,
                    "context_window_source": context_window_source,
                    "available": available,
                    "unavailable_reason": unavailable_reason,
                    "saved_profile": saved_profile,
                }
                if source_kind == "bundled":
                    insert_at = next(
                        (
                            index
                            for index, existing in enumerate(model_options)
                            if str(existing.get("model_name") or "").strip() == normalized
                        ),
                        len(model_options),
                    )
                    model_options.insert(insert_at, option)
                    return
                model_options.append(option)

            for profile in saved_providers.values():
                _append(
                    "saved",
                    profile["model_name"],
                    profile["model_name"],
                    _saved_provider_label(profile),
                    context_window=(
                        int(profile.get("context_window"))
                        if isinstance(profile.get("context_window"), int)
                        else None
                    ),
                    context_window_source=str(profile.get("context_window_source") or "").strip()
                    or None,
                    saved_profile=True,
                )

            if (
                current_model
                and not str(current_model).endswith(":cloud")
                and current_model
                not in {item.get("model_name", "") for item in bundled_items}
            ):
                _append(
                    "custom",
                    current_model,
                    current_model,
                    "Custom",
                    context_window=int(self.config.model.context_window or 0) or None,
                    context_window_source=str(
                        getattr(self.config.model, "context_window_source", "") or ""
                    ).strip()
                    or None,
                )

            for item in bundled_items:
                _append(
                    "bundled",
                    str(item.get("model_name") or ""),
                    str(item.get("label") or item.get("model_name") or ""),
                    "Bundled",
                    context_window=(
                        int(item.get("context_window"))
                        if isinstance(item.get("context_window"), int)
                        else None
                    ),
                    context_window_source=str(item.get("context_window_source") or "").strip()
                    or None,
                    available=bool(item.get("available", True)),
                    unavailable_reason=str(item.get("unavailable_reason") or ""),
                )

            if not model_options:
                self.post_system(
                    "Model",
                    "No saved models are available right now.",
                    is_error=True,
                )
                return

            available_options = [
                item for item in model_options if bool(item.get("available", True))
            ]
            if (
                not available_options
                and current_model
                and any(
                    item.get("model_name") == current_model for item in model_options
                )
            ):
                reason = ""
                for item in model_options:
                    if item.get("model_name") == current_model:
                        reason = str(item.get("unavailable_reason") or "").strip()
                        break
                message = "Bundled models are unavailable right now."
                if reason:
                    message = f"{message} {reason}"
                self.post_system("Model", message, is_error=True)

            current_entry_id = _current_entry_id()
            result = await self._open_modal(
                ModelPickerModal(
                    current_model,
                    model_options,
                    current_entry_id=current_entry_id,
                )
            )
            if not result:
                return

            action = str(result.get("action") or "").strip().lower()
            selected_entry_id = str(result.get("entry_id") or "").strip()
            selected = str(result.get("model_name") or "").strip()
            if not selected and selected_entry_id:
                selected = next(
                    (
                        str(item.get("model_name") or "").strip()
                        for item in model_options
                        if str(item.get("entry_id") or "").strip() == selected_entry_id
                    ),
                    "",
                )
            if not selected_entry_id and selected:
                if selected in bundled_model_names:
                    selected_entry_id = f"bundled:{selected}"
                elif selected in saved_providers:
                    selected_entry_id = f"saved:{selected}"
                else:
                    selected_entry_id = f"custom:{selected}"
            if not selected:
                return

            if action == "delete":
                if selected_entry_id == current_entry_id:
                    self.post_system(
                        "Model",
                        "Switch to another model before deleting the current saved profile.",
                        is_error=True,
                    )
                    continue
                try:
                    remove_saved_custom_provider(model_name=selected)
                except Exception as exc:
                    self.post_system("Model", str(exc), is_error=True)
                    return
                self.post_notice("Model", f"Removed saved model {selected}.")
                continue

            if action != "select":
                return
            if selected_entry_id == current_entry_id:
                return
            break

        restored_profile = (
            saved_providers.get(selected)
            if selected_entry_id == f"saved:{selected}" and selected in saved_providers
            else None
        )
        selected_item = next(
            (
                item
                for item in model_options
                if str(item.get("entry_id") or "").strip() == selected_entry_id
            ),
            None,
        )
        next_api_key = (
            str(restored_profile.get("api_key") or "")
            if restored_profile
            else (
                ""
                if bool(selected_item)
                and not bool(selected_item.get("saved_profile"))
                and str(selected_item.get("source_kind") or "").strip().lower()
                == "bundled"
                else (self.config.api_key or "")
            )
        )
        next_base_url = (
            str(restored_profile.get("base_url") or "")
            if restored_profile
            else (
                ""
                if bool(selected_item)
                and not bool(selected_item.get("saved_profile"))
                and str(selected_item.get("source_kind") or "").strip().lower()
                == "bundled"
                else (self.config.base_url or "")
            )
        )
        next_context_window = (
            int(restored_profile.get("context_window"))
            if restored_profile
            and isinstance(restored_profile.get("context_window"), int)
            and int(restored_profile.get("context_window")) > 0
            else (
                int(selected_item.get("context_window"))
                if selected_item
                and isinstance(selected_item.get("context_window"), int)
                and int(selected_item.get("context_window")) > 0
                else DEFAULT_CONTEXT_WINDOW
            )
        )
        next_context_window_source = (
            str(restored_profile.get("context_window_source") or "").strip()
            if restored_profile
            else (
                str(selected_item.get("context_window_source") or "").strip()
                if selected_item
                else ""
            )
        ) or "fallback_default"

        try:
            save_system_config(
                api_key=next_api_key,
                base_url=next_base_url,
                model_name=selected,
                context_window=next_context_window,
                context_window_source=next_context_window_source,
                cloud_auth_enabled=self.config.cloud_auth_enabled,
                cloud_api_url=self.config.cloud_api_url,
                cloud_client_id=self.config.cloud_client_id,
            )
        except Exception as exc:
            self.post_system("Model", str(exc), is_error=True)
            return

        old_model = self.config.model_name
        self.config.api_key = next_api_key
        self.config.base_url = next_base_url
        self.config.model.name = selected
        self.config.model.context_window = next_context_window
        self.config.model.context_window_source = next_context_window_source
        await self._reset_active_provider_client()
        self.refresh_header()

    async def _open_theme_picker_from_meta(self) -> None:
        old_theme = str(self.theme or "textual-dark")
        selected = await self._open_modal(ThemePickerModal(old_theme))
        if not selected or selected == self.theme:
            return
        self.theme = selected
        save_theme(selected)
        self.refresh_header()
        self._sync_command_palette(self.query_one("#prompt", TextArea).text)
        self.post_notice("Theme", f"{old_theme} → selected")

    def action_change_theme(self) -> None:
        """Route Textual's built-in theme action through the Reup theme modal."""
        self.run_worker(self._open_theme_picker_from_meta(), exclusive=False)

    def action_quit(self) -> None:
        """Confirm before quitting the app."""
        self.run_worker(self._confirm_quit(), exclusive=False)

    def action_command_palette(self) -> None:
        """Open the command palette while preserving Reup system command order."""
        if not CommandPalette.is_open(self):
            self.push_screen(
                CommandPalette(
                    providers=[ReupSystemCommandsProvider],
                    id="--command-palette",
                )
            )

    def _commands_panel_is_open(self) -> bool:
        panel = self._commands_panel
        return bool(panel is not None and panel.is_mounted)

    async def _toggle_commands_panel(self) -> None:
        if self._commands_panel_is_open():
            await self._hide_commands_panel()
            return
        await self._show_commands_panel()

    async def _show_commands_panel(self) -> None:
        await self._ensure_command_registry()
        registry = self._command_registry
        if registry is None:
            return
        self.screen.query("HelpPanel").remove()
        commands = sorted(
            [
                (command.name, command.description)
                for command in registry.all_commands()
            ],
            key=lambda item: item[0].lower(),
        )
        panel = CommandsSidePanel(commands=commands, id="commands-panel")
        self._commands_panel = panel
        await self.screen.mount(panel)

    async def _hide_commands_panel(self) -> None:
        panel = self._commands_panel
        self._commands_panel = None
        if panel is None:
            return
        try:
            await panel.remove()
        except Exception:
            pass

    def get_system_commands(self, screen) -> Iterable[SystemCommand]:
        theme_command: SystemCommand | None = None
        commands_command: SystemCommand | None = None
        screenshot_command: SystemCommand | None = None
        quit_command: SystemCommand | None = None
        extras: list[SystemCommand] = []

        for command in super().get_system_commands(screen):
            if command.title == "Theme":
                theme_command = SystemCommand(
                    "Theme",
                    "Choose a Textual theme for the current session.",
                    self.action_change_theme,
                )
            elif command.title == "Keys":
                commands_command = (
                    SystemCommand(
                        "Commands",
                        "Hide the commands side panel.",
                        lambda: self.run_worker(
                            self._hide_commands_panel(), exclusive=False
                        ),
                    )
                    if self._commands_panel_is_open()
                    else SystemCommand(
                        "Commands",
                        "Show available commands and what they do.",
                        lambda: self.run_worker(
                            self._show_commands_panel(), exclusive=False
                        ),
                    )
                )
            elif command.title == "Screenshot":
                screenshot_command = command
            elif command.title == "Quit":
                quit_command = command
            elif command.title in {"Maximize", "Minimize"}:
                continue
            else:
                extras.append(command)

        if theme_command is not None:
            yield theme_command
        if commands_command is not None:
            yield commands_command
        for command in extras:
            yield command
        if screenshot_command is not None:
            yield screenshot_command
        if quit_command is not None:
            yield quit_command

    async def _open_approval_picker_from_meta(
        self, args: list[str] | None = None
    ) -> None:
        """Open the approval mode picker modal."""
        from ite.config.config import ApprovalPolicy
        from ite.config.loader import save_global_approval_mode

        old_approval = self.config.approval.value
        selected = await self._open_modal(ApprovalPickerModal(old_approval))

        # Handle command with arguments (e.g., `/approval on_request`)
        if args:
            new_mode = args[0].lower() if args else ""
            valid_modes = [p.value for p in ApprovalPolicy]
            if new_mode not in valid_modes:
                self.post_system(
                    "Approval",
                    f"Invalid mode. Valid modes: {', '.join(valid_modes)}",
                    is_error=True,
                )
                return
            if new_mode == old_approval:
                self.post_notice("Approval", f"Already set to {new_mode}")
                return
            # Apply the change
            selected_policy = ApprovalPolicy(new_mode)
            self.config.approval = selected_policy
            if self.agent and self.agent.session:
                self.agent.session.approval_manager.approval_policy = selected_policy
            save_global_approval_mode(selected_policy)
            self.refresh_header()
            self.post_notice("Approval", f"{old_approval} → {new_mode}")
            return

        # Handle modal selection (no args or `args` is None)
        if not selected or selected == old_approval:
            return

        # Apply the change from modal
        selected_policy = ApprovalPolicy(selected)
        self.config.approval = selected_policy
        if self.agent and self.agent.session:
            self.agent.session.approval_manager.approval_policy = selected_policy
        save_global_approval_mode(selected_policy)
        self.refresh_header()
        self.post_notice("Approval", f"{old_approval} → {selected}")

    async def _open_usage_modal_from_meta(self) -> None:
        await self.ensure_agent()
        if not self._is_bundled_model():
            self.post_system(
                "Usage",
                "Usage tracking is only available for bundled models.",
                is_error=True,
            )
            return
        summary = get_usage_summary(self.config)
        if not summary:
            self.post_system(
                "Usage", "Usage is not available right now.", is_error=True
            )
            return
        quotas = summary.get("quotas") or {}
        five_hour = quotas.get("fiveHour") or {}
        used = int(five_hour.get("usedUsdCents") or 0)
        cap = max(1, int(five_hour.get("capUsdCents") or 1))
        self._usage_remaining_percent = max(
            0, min(100, round(((cap - used) / cap) * 100))
        )
        self.refresh_header()
        await self._open_modal(UsageSummaryModal(summary))

    async def _open_context_modal_from_meta(self) -> None:
        await self.ensure_agent()
        if (
            not self.agent
            or not self.agent.session
            or not self.agent.session.context_manager
        ):
            self.post_system(
                "Context", "Context state is not available right now.", is_error=True
            )
            return
        session = self.agent.session
        stats = session.get_stats()
        compaction = session.context_manager.get_compaction_status()
        payload = {**stats, **compaction}
        payload["status"] = (
            "compaction recommended"
            if bool(compaction.get("needs_compression"))
            else "healthy"
        )
        self.refresh_header()
        await self._open_modal(ContextSummaryModal(payload))

    async def _open_activity_modal_from_meta(self) -> None:
        await self.ensure_agent()
        payload = get_activity(self.config)
        if not payload:
            self.post_system(
                "Activity",
                "Usage analytics are not available right now.",
                is_error=True,
            )
            return
        await self._open_modal(ActivityModal(payload))

    async def _open_attach_picker_from_meta(self) -> None:
        await self.ensure_agent()
        if not self.agent:
            return
        cwd = Path(self.config.cwd).resolve()
        selected = await self._open_modal(AttachPickerModal(cwd, []))
        if selected is None:
            return
        added = self._insert_attachment_refs_into_prompt(
            list(selected)[:MAX_ATTACHMENTS]
        )
        if added:
            noun = "reference" if added == 1 else "references"
            self.post_attachment_note(
                f"Inserted {added} attachment {noun} into the composer."
            )

    def _consume_dropped_path_text(self, message: str) -> bool:
        if not self.agent:
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
            if not any(
                sep in candidate for sep in ("/", "\\")
            ) and not candidate.startswith("~"):
                return False
            path = Path(candidate).expanduser()
            if not path.exists() or not path.is_file():
                return False
            paths.append(str(path))

        added = self._insert_attachment_refs_into_prompt(paths[:MAX_ATTACHMENTS])
        if added > 0:
            noun = "reference" if added == 1 else "references"
            self.post_attachment_note(
                f"Inserted {added} attachment {noun} into the composer."
            )
        return True

    def _empty_state_thread_count(self) -> int:
        try:
            return len(
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
            return 0

    def _refresh_empty_state(self) -> None:
        try:
            empty = self.query_one("#empty-state", Static)
        except (NoMatches, ScreenStackError):
            return
        if self._cloud_signed_out or self._startup_active or self._onboarding_active:
            empty.display = False
            return
        if self._message_count > 0 or self._is_turn_running:
            empty.display = False
            return
        self._empty_state_cached_thread_count = self._empty_state_thread_count()
        empty.update(self._empty_state_renderable())
        empty.display = True
        if self._suppress_agents_recommendation_once:
            self._suppress_agents_recommendation_once = False
            return
        self._maybe_post_workspace_agents_recommendation()

    def _empty_state_renderable(self) -> Any:
        return build_empty_state_renderable(
            cwd=Path(self.config.cwd),
            thread_count=self._empty_state_cached_thread_count,
            styles=self._render_styles(),
        )

    def _maybe_post_workspace_agents_recommendation(self) -> None:
        if self._startup_active or self._cloud_signed_out or self._onboarding_active:
            return
        workspace = Path(self.config.cwd).resolve()
        workspace_key = str(workspace)
        recommendation = get_workspace_agents_recommendation(workspace)
        if recommendation is None:
            return
        recommendation_key = (workspace_key, recommendation.reason)
        if self._agents_recommendation_current_visit == recommendation_key:
            return
        self._agents_recommendation_current_visit = recommendation_key
        self.post_notice(
            recommendation.notice_title(),
            recommendation.notice_message(),
            timeout=8,
        )

    def _set_loading_state(self, state: str, busy: bool) -> None:
        self._top_state_text = state
        self._top_busy = busy
        self._activity_version += 1
        version = self._activity_version
        self.run_worker(self._broadcast_remote_state(), exclusive=False)
        if busy:
            self.run_worker(
                self._show_activity_indicator(state, version), exclusive=False
            )
        else:
            self.run_worker(self._hide_activity_indicator(version), exclusive=False)

        try:
            prompt = self.query_one("#prompt", TextArea)
        except NoMatches:
            return
        prompt.disabled = (
            self._cloud_signed_out or self._startup_active or self._onboarding_active
        )
        self._refresh_empty_state()

    def _set_signed_out_state(self, enabled: bool) -> None:
        self._cloud_signed_out = enabled
        if enabled:
            self._onboarding_active = False
        self._apply_shell_surface()

    def _set_startup_state(self, enabled: bool) -> None:
        self._startup_active = enabled
        self._apply_shell_surface()

    def _set_startup_phase(self, message: str) -> None:
        self._startup_phase_text = (message or "").strip() or "Preparing your workspace"
        self._startup_error_text = None
        if self.is_mounted:
            self._apply_shell_surface()

    def _fail_startup(self, exc: Exception) -> None:
        self._startup_active = True
        self._startup_error_text = str(exc).strip() or exc.__class__.__name__
        self._apply_shell_surface()

    def _set_onboarding_state(self, enabled: bool) -> None:
        self._onboarding_active = enabled
        if enabled:
            self._cloud_signed_out = False
            try:
                self.query_one("#onboarding-role-other", Input).display = False
                self.query_one("#onboarding-role-other", Input).value = ""
                self.query_one("#onboarding-use-case-other", Input).display = False
                self.query_one("#onboarding-use-case-other", Input).value = ""
            except NoMatches:
                pass
        self._apply_shell_surface()

    def _apply_shell_surface(self) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        empty = self.query_one("#empty-state", Static)
        startup = self.query_one("#startup-state", Container)
        signed_out = self.query_one("#signed-out-state", Container)
        onboarding = self.query_one("#onboarding-state", Container)
        composer = self.query_one("#composer", Horizontal)
        topbar = self.query_one("#topbar", Horizontal)
        chat_body = self.query_one("#chat-body", Horizontal)
        prompt = self.query_one("#prompt", TextArea)
        session_tabs = self.query_one("#session-tabs-scroll", HorizontalScroll)
        sign_in = self.query_one("#cloud-sign-in", Button)
        footer = self.query_one(Footer)
        header = self.query_one(Header)

        in_startup = self._startup_active
        in_signed_out = (not in_startup) and self._cloud_signed_out
        in_onboarding = (not in_signed_out) and self._onboarding_active
        in_chat = (not in_startup) and (not in_signed_out) and (not in_onboarding)

        startup.display = in_startup
        signed_out.display = in_signed_out
        onboarding.display = in_onboarding
        conversation.display = in_chat
        empty.display = False if not in_chat else empty.display
        composer.display = in_chat
        topbar.display = in_chat
        session_tabs.display = in_chat and len(self._open_session_order) > 1
        footer.display = in_chat
        header.display = in_chat
        chat_body.styles.padding = (
            (0, 0, 0, 0)
            if (in_startup or in_signed_out or in_onboarding)
            else (0, 2, 0, 2)
        )
        prompt.disabled = not in_chat
        sign_in.disabled = self._cloud_auth_busy
        sign_in.label = "Sign in"
        self.query_one("#startup-status", Static).update(self._startup_status_text())
        self.query_one("#signed-out-copy", Static).update(
            build_signed_out_state_renderable(styles=self._render_styles())
        )
        self.query_one("#signed-out-status", Static).update(
            self._signed_out_status_text()
        )
        if in_onboarding:
            self.query_one("#onboarding-status", Static).update(
                self._onboarding_status_text()
            )
        if in_chat:
            self._refresh_empty_state()
        self._apply_aside_panel_state()
        self._apply_change_review_panel_state()
        self.refresh_header()

    def _startup_status_text(self) -> Text:
        status = Text(justify="center")
        if self._startup_error_text:
            status.append(
                "Startup failed: ", style=f"bold {self._render_styles()['error']}"
            )
            status.append(
                self._startup_error_text,
                style=self._render_styles()["fg"],
            )
            return status
        frame = self._top_spinner_frames[
            self._top_spinner_index % len(self._top_spinner_frames)
        ]
        status.append(
            f"{frame} {self._startup_phase_text}",
            style=f"bold {self._render_styles()['fg']}",
        )
        return status

    def _onboarding_status_text(self) -> Text:
        status = Text(justify="center")
        if self._onboarding_busy:
            frame = self._top_spinner_frames[
                self._top_spinner_index % len(self._top_spinner_frames)
            ]
            status.append(
                f"{frame} Saving your first-run setup",
                style=f"bold {self._render_styles()['fg']}",
            )
        else:
            status.append(" ", style=self._render_styles()["muted"])
        return status

    def _signed_out_status_text(self) -> Text:
        status = Text(justify="center")
        if self._cloud_bootstrap_busy:
            frame = self._top_spinner_frames[
                self._top_spinner_index % len(self._top_spinner_frames)
            ]
            status.append(
                f"{frame} Checking iTE Cloud",
                style=f"bold {self._render_styles()['fg']}",
            )
        elif self._cloud_auth_busy:
            frame = self._top_spinner_frames[
                self._top_spinner_index % len(self._top_spinner_frames)
            ]
            status.append(
                f"{frame} Opening your browser",
                style=f"bold {self._render_styles()['fg']}",
            )
        else:
            status.append(" ", style=self._render_styles()["muted"])
        return status

    async def _run_cloud_login_flow(self) -> None:
        if self._cloud_auth_busy:
            return
        if not self.config.cloud_auth_enabled:
            self.config.cloud_auth_enabled = True
            save_cloud_settings(enabled=True)
        self._cloud_auth_busy = True
        self._set_signed_out_state(True)
        try:
            await asyncio.to_thread(ensure_cloud_auth, None, self.config)
        except CloudConnectionError as exc:
            self._cloud_auth_busy = False
            self._set_signed_out_state(True)
            self.query_one("#signed-out-status", Static).update(
                Text(
                    f"Cloud API unreachable: {exc}",
                    style="bold #ffcf92",
                    justify="center",
                )
            )
            return
        except CloudAuthError as exc:
            self._cloud_auth_busy = False
            self._set_signed_out_state(True)
            self.query_one("#signed-out-status", Static).update(
                Text(f"Sign-in failed: {exc}", style="bold #ffcf92", justify="center")
            )
            return

        self._cloud_auth_busy = False
        self._set_signed_out_state(False)
        conversation = self.query_one("#conversation", VerticalScroll)
        await conversation.remove_children()
        self._message_count = 0
        self._reset_session_local_ui_state()
        if self._should_show_onboarding():
            self._set_onboarding_state(True)
            self.query_one("#onboarding-name", Input).focus()
            return
        await self.ensure_agent()
        self._refresh_empty_state()
        self.query_one("#prompt", TextArea).focus()

    async def _run_cloud_logout_flow(self) -> None:
        if self._is_turn_running:
            await self.cancel_active_turn()
        clear_cloud_auth()
        self._set_signed_out_state(True)

    async def _finish_onboarding_flow(self, *, skip: bool) -> None:
        if self._onboarding_busy:
            return
        if not skip:
            validation_error = self._validate_onboarding_inputs()
            if validation_error is not None:
                self.query_one("#onboarding-status", Static).update(
                    Text(validation_error, style="bold #ffcf92", justify="center")
                )
                return
        self._onboarding_busy = True
        self._apply_shell_surface()

        try:
            await self.ensure_agent()
            session = self.agent.session if self.agent else None
            if session is None:
                self.query_one("#onboarding-status", Static).update(
                    Text(
                        "Could not prepare onboarding right now.",
                        style="bold #ffcf92",
                        justify="center",
                    )
                )
                return

            if not skip:
                name = self.query_one("#onboarding-name", Input).value.strip()
                role = self._resolve_onboarding_choice(
                    select_id="onboarding-role-select",
                    other_input_id="onboarding-role-other",
                )
                use_case = self._resolve_onboarding_choice(
                    select_id="onboarding-use-case-select",
                    other_input_id="onboarding-use-case-other",
                )

                entries: list[tuple[str, str]] = []
                if name:
                    entries.append(("user_name", name))
                if role:
                    entries.append(("user_role", role))
                if use_case:
                    entries.append(("user_use_case", use_case))

                for key, value in entries:
                    await asyncio.to_thread(
                        session.memory_manager.set_entry,
                        "long_term",
                        key,
                        value,
                        source="onboarding",
                        metadata={"memory_type": "user"},
                    )

            await asyncio.to_thread(save_onboarding_settings, completed=True)
            self.config.onboarding_completed = True
        except Exception as exc:
            self.query_one("#onboarding-status", Static).update(
                Text(
                    f"Onboarding failed: {exc}", style="bold #ffcf92", justify="center"
                )
            )
            return
        finally:
            self._onboarding_busy = False
            if self._onboarding_active:
                self._apply_shell_surface()

        self._set_onboarding_state(False)
        if self.config.needs_setup:
            await self._open_setup_modal(exit_on_cancel=False)
        self._apply_shell_surface()
        self._refresh_empty_state()
        self.query_one("#prompt", TextArea).focus()

    def _resolve_onboarding_choice(self, *, select_id: str, other_input_id: str) -> str:
        value = self.query_one(f"#{select_id}", Select).value
        if value in {Select.BLANK, Select.NULL, None}:
            return ""
        if value == ONBOARDING_OTHER_VALUE:
            return self.query_one(f"#{other_input_id}", Input).value.strip()
        return str(value).strip()

    def _validate_onboarding_inputs(self) -> str | None:
        name = self.query_one("#onboarding-name", Input).value.strip()
        if not name:
            self.query_one("#onboarding-name", Input).focus()
            return "Enter your name, or choose Skip to do this later."

        role_value = self.query_one("#onboarding-role-select", Select).value
        if role_value in {Select.BLANK, Select.NULL, None}:
            self.query_one("#onboarding-role-select", Select).focus()
            return "Choose what you do, or choose Other and type it in."
        if role_value == ONBOARDING_OTHER_VALUE:
            role_other = self.query_one("#onboarding-role-other", Input)
            if not role_other.value.strip():
                role_other.focus()
                return "Tell iTE what you do before continuing."

        use_case_value = self.query_one("#onboarding-use-case-select", Select).value
        if use_case_value in {Select.BLANK, Select.NULL, None}:
            self.query_one("#onboarding-use-case-select", Select).focus()
            return "Choose what you're using iTE for right now, or choose Other and type it in."
        if use_case_value == ONBOARDING_OTHER_VALUE:
            use_case_other = self.query_one("#onboarding-use-case-other", Input)
            if not use_case_other.value.strip():
                use_case_other.focus()
                return "Tell iTE what you're using it for before continuing."

        return None

    def _focus_next_onboarding_field(self, current_id: str | None) -> bool:
        if current_id == "onboarding-name":
            self.query_one("#onboarding-role-select", Select).focus()
            return True
        if current_id == "onboarding-role-other":
            self.query_one("#onboarding-use-case-select", Select).focus()
            return True
        return False

    def _set_onboarding_other_visibility(
        self, *, other_input_id: str, value: object
    ) -> None:
        other_input = self.query_one(f"#{other_input_id}", Input)
        is_other = value == ONBOARDING_OTHER_VALUE
        other_input.display = is_other
        if not is_other:
            other_input.value = ""
            return
        other_input.focus()

    def _apply_aside_panel_state(self) -> None:
        panel = self.query_one("#aside-panel", Container)
        body = self.query_one("#aside-panel-body", VerticalScroll)
        has_content = bool(self._aside_entries)
        panel.display = (
            (not self._cloud_signed_out) and self._aside_panel_visible and has_content
        )
        toggle = self.query_one("#aside-toggle", Button)
        toggle.display = (not self._cloud_signed_out) and has_content
        toggle.label = "/aside" if not self._aside_panel_visible else "Close"
        body.display = has_content

    def _apply_change_review_panel_state(self) -> None:
        panel = self.query_one("#change-review-panel", Container)
        toggle = self.query_one("#changes-toggle", Button)
        has_content = bool(
            self._change_review_change_set
            and getattr(self._change_review_change_set, "changes", None)
        )
        panel.display = (
            (not self._cloud_signed_out) and self._change_review_visible and has_content
        )
        has_outgoing = bool(
            self._git_outbound_state and self._git_outbound_state.needs_attention
        )
        wants_publish = bool(
            self._git_outbound_state and self._git_outbound_state.needs_publish
        )
        toggle.display = (
            (has_content or has_outgoing)
            and not self._change_review_visible
            and not self._cloud_signed_out
        )
        if has_content:
            toggle.label = "/changes"
        elif wants_publish:
            count = (
                self._git_outbound_state.ahead_count if self._git_outbound_state else 0
            )
            if count > 0:
                noun = "commit" if count == 1 else "commits"
                toggle.label = f"/publish {count} {noun} ↑"
            else:
                toggle.label = "/publish ↑"
        else:
            count = (
                self._git_outbound_state.ahead_count if self._git_outbound_state else 0
            )
            noun = "commit" if count == 1 else "commits"
            toggle.label = f"/push {count} {noun} ↑"
        self._update_change_review_action_state()

    def _change_review_path_flags(self, rel_path: str | None) -> tuple[bool, bool]:
        if not rel_path or not self._change_review_change_set:
            return False, False
        staged = {
            self._change_review_relpath(diff)
            for diff in getattr(self._change_review_change_set, "staged_changes", [])
        }
        unstaged = {
            self._change_review_relpath(diff)
            for diff in getattr(self._change_review_change_set, "unstaged_changes", [])
        }
        return rel_path in staged, rel_path in unstaged

    def _update_change_review_action_state(self) -> None:
        try:
            stage_file = self.query_one("#change-review-stage-file", Static)
            unstage_file = self.query_one("#change-review-unstage-file", Static)
            discard_file = self.query_one("#change-review-discard-file", Static)
            stage_all_button = self.query_one("#change-review-stage-all", Static)
            discard_all_button = self.query_one("#change-review-discard-all", Static)
            commit_button = self.query_one("#change-review-commit", Static)
        except NoMatches:
            return

        has_content = bool(
            self._change_review_change_set
            and getattr(self._change_review_change_set, "changes", None)
        )
        selected = self._change_review_selected_rel_path
        has_staged, has_unstaged = self._change_review_path_flags(selected)
        stage_file.display = bool(selected and has_unstaged)
        unstage_file.display = bool(selected and has_staged and not has_unstaged)
        stage_file.disabled = not bool(selected and has_unstaged)
        unstage_file.disabled = not bool(selected and has_staged and not has_unstaged)
        discard_file.disabled = not bool(selected)

        stage_all_button.display = self._change_review_source == "git" and has_content
        discard_all_button.display = self._change_review_source == "git" and has_content
        commit_button.display = self._change_review_source == "git" and has_content
        has_any_staged = bool(
            self._change_review_change_set
            and getattr(self._change_review_change_set, "staged_changes", [])
        )
        has_any_unstaged = bool(
            self._change_review_change_set
            and (
                getattr(self._change_review_change_set, "unstaged_changes", [])
                or getattr(self._change_review_change_set, "untracked_changes", [])
            )
        )
        if has_any_unstaged:
            stage_all_button.update("Stage All")
            self._change_review_bulk_action = "stage"
            stage_all_button.disabled = False
        elif has_any_staged:
            stage_all_button.update("Unstage All")
            self._change_review_bulk_action = "unstage"
            stage_all_button.disabled = False
        else:
            stage_all_button.update("Stage All")
            self._change_review_bulk_action = "stage"
            stage_all_button.disabled = True
        discard_all_button.disabled = not bool(
            self._change_review_source == "git" and has_content
        )
        commit_button.disabled = not bool(
            self._change_review_source == "git"
            and (has_any_staged or (has_any_unstaged and has_content))
        )

    async def _refresh_change_review_source(
        self, *, prefer_git_only: bool = False
    ) -> None:
        cwd = Path(self.config.cwd).resolve()
        change_set = None
        source = "git"
        title = "Working tree"
        mode = "changed"
        if await asyncio.to_thread(is_git_repo, cwd):
            self._git_outbound_state = await asyncio.to_thread(git_outbound_state, cwd)
            change_set = await asyncio.to_thread(working_tree_change_set, cwd)
            if change_set is not None:
                source = "git"
                title = (
                    f"Working tree  {change_set.staged_count} staged"
                    f"  {change_set.unstaged_count} unstaged"
                )
                mode = "changed"
        else:
            self._git_outbound_state = None
        self._change_review_source = source
        self._change_review_change_set = change_set
        self._change_review_title = title
        self._change_review_mode = mode
        if change_set is None:
            self._change_review_visible = False
            self._change_review_snapshot_key = None
        self._apply_change_review_panel_state()

    def _change_review_signature(
        self, change_set: Any | None
    ) -> tuple[Any, ...] | None:
        if not change_set or not getattr(change_set, "changes", None):
            return None

        def _diff_key(diff: Any) -> tuple[Any, ...]:
            return (
                self._change_review_relpath(diff),
                hash(getattr(diff, "old_content", "")),
                hash(getattr(diff, "new_content", "")),
                bool(getattr(diff, "is_new_file", False)),
                bool(getattr(diff, "is_deletion", False)),
            )

        return (
            self._change_review_source,
            tuple(_diff_key(diff) for diff in getattr(change_set, "changes", [])),
            tuple(
                self._change_review_relpath(diff)
                for diff in getattr(change_set, "staged_changes", [])
            ),
            tuple(
                self._change_review_relpath(diff)
                for diff in getattr(change_set, "unstaged_changes", [])
            ),
            tuple(
                self._change_review_relpath(diff)
                for diff in getattr(change_set, "untracked_changes", [])
            ),
        )

    def _change_review_entry_label(self, diff: Any) -> Text:
        action, color = change_entry_label(diff, mode=self._change_review_mode)
        rel = self._change_review_relpath(diff)
        parts = Path(rel).parts
        name = parts[-1] if parts else rel
        label = Text()
        label.append(name, style="bold #e7eefb")
        label.append("  ")
        label.append(action, style=f"bold {color}")
        if self._change_review_mode == "changed" and not getattr(
            diff, "is_deletion", False
        ):
            additions = len([line for line in diff.new_content.splitlines() if line])
            if additions and getattr(diff, "is_new_file", False):
                label.append(f"  +{additions}", style="bold #4edea3")
        return label

    def _change_review_relpath(self, diff: Any) -> str:
        try:
            return str(diff.path.resolve().relative_to(Path(self.config.cwd).resolve()))
        except Exception:
            return str(diff.path)

    def _change_review_relpath_from_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(Path(self.config.cwd).resolve()))
        except Exception:
            return str(path)

    def _change_review_diff_text(self, diff: Any) -> str:
        import difflib

        if self._change_review_mode == "undone":
            old_lines = diff.new_content.splitlines(keepends=True)
            new_lines = diff.old_content.splitlines(keepends=True)
            fromfile = str(diff.path)
            tofile = (
                "/dev/null"
                if getattr(diff, "is_new_file", False)
                and not getattr(diff, "is_deletion", False)
                else str(diff.path)
            )
            if getattr(diff, "is_deletion", False):
                fromfile = "/dev/null"
        else:
            return diff.to_diff()

        if old_lines and not old_lines[-1].endswith("\n"):
            old_lines[-1] += "\n"
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        return "".join(
            difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile)
        )

    def _change_review_numbered_diff_renderable(self, diff: Any) -> Text:
        import re

        raw_diff = self._change_review_diff_text(diff)
        hunk_re = re.compile(
            r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? \+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@"
        )
        rendered = Text(no_wrap=True)
        old_lineno = 0
        new_lineno = 0
        gutter_style = self._style("muted")
        context_style = self._style("fg")
        add_style = self._style("success")
        del_style = self._style("warning")
        hunk_style = self._style("primary")

        def append_line(
            old_label: str,
            new_label: str,
            marker: str,
            content: str,
            *,
            marker_style: str,
            content_style: str,
        ) -> None:
            rendered.append(f"{old_label:>5} ", style=gutter_style)
            rendered.append(f"{new_label:>5} ", style=gutter_style)
            rendered.append(marker, style=marker_style)
            rendered.append(" ")
            rendered.append(content, style=content_style)
            rendered.append("\n")

        for line in raw_diff.splitlines():
            if line.startswith("--- ") or line.startswith("+++ "):
                style = del_style if line.startswith("--- ") else add_style
                rendered.append(line, style=style)
                rendered.append("\n")
                continue

            match = hunk_re.match(line)
            if match:
                old_lineno = int(match.group("old"))
                new_lineno = int(match.group("new"))
                rendered.append("  old   new    \n", style=gutter_style)
                rendered.append(line, style=hunk_style)
                rendered.append("\n")
                continue

            if line.startswith("-") and not line.startswith("--- "):
                append_line(
                    str(old_lineno),
                    "",
                    "-",
                    line[1:],
                    marker_style=del_style,
                    content_style=del_style,
                )
                old_lineno += 1
                continue

            if line.startswith("+") and not line.startswith("+++ "):
                append_line(
                    "",
                    str(new_lineno),
                    "+",
                    line[1:],
                    marker_style=add_style,
                    content_style=add_style,
                )
                new_lineno += 1
                continue

            if line.startswith(" "):
                append_line(
                    str(old_lineno),
                    str(new_lineno),
                    " ",
                    line[1:],
                    marker_style=gutter_style,
                    content_style=context_style,
                )
                old_lineno += 1
                new_lineno += 1
                continue

            rendered.append(line, style=context_style)
            rendered.append("\n")

        return rendered

    async def _render_change_review_preview(
        self, diff: Any | None, *, version: int | None = None
    ) -> None:
        if version is not None and version != self._change_review_preview_version:
            return
        preview = self.query_one("#change-review-preview", ScrollableContainer)
        await preview.remove_children()
        if version is not None and version != self._change_review_preview_version:
            return
        if diff is None:
            await preview.mount(
                Static("Select a file to inspect.", classes="change-review-empty")
            )
            return
        header = Text()
        try:
            rel = str(diff.path.resolve().relative_to(Path(self.config.cwd).resolve()))
        except Exception:
            rel = str(diff.path)
        action, color = change_entry_label(diff, mode=self._change_review_mode)
        header.append(rel, style=f"bold {self._style('fg')}")
        header.append("  ")
        header.append(action, style=f"bold {color}")
        if self._change_review_source == "git":
            stage_label_for = getattr(
                self._change_review_change_set, "stage_label_for", None
            )
            if callable(stage_label_for):
                header.append("  ")
                header.append(stage_label_for(diff.path), style="bold #8c93a1")
        body = Static(
            self._change_review_numbered_diff_renderable(diff),
            classes="change-review-diff",
        )
        if version is not None and version != self._change_review_preview_version:
            return
        await preview.mount(Static(header, classes="change-review-path"), body)

    async def _populate_change_review_panel(self) -> None:
        tree = self.query_one("#change-review-tree", ChangedFilesTree)
        preview = self.query_one("#change-review-preview", ScrollableContainer)
        await preview.remove_children()
        title = self.query_one("#change-review-title", Static)
        title.update(self._change_review_title)
        change_set = self._change_review_change_set
        if not change_set or not getattr(change_set, "changes", None):
            self._apply_change_review_panel_state()
            return

        # Set theme-aware styles on tree
        tree._styles = self._render_styles()

        first_diff: Any | None = None
        self._change_review_diff_lookup = {}
        for diff in getattr(change_set, "changes", []):
            if first_diff is None:
                first_diff = diff
            rel = self._change_review_relpath(diff)
            self._change_review_diff_lookup[rel] = diff

        self._apply_change_review_panel_state()
        first_rel = None
        if self._change_review_source == "git":
            staged_paths = [
                self._change_review_relpath(diff)
                for diff in getattr(change_set, "staged_changes", [])
            ]
            unstaged_paths = [
                self._change_review_relpath(diff)
                for diff in getattr(change_set, "unstaged_changes", [])
            ]
            untracked_paths = {
                self._change_review_relpath(diff)
                for diff in getattr(change_set, "untracked_changes", [])
            }
            plain_unstaged = [
                path for path in unstaged_paths if path not in untracked_paths
            ]
            groups = [
                ("Staged", staged_paths),
                ("Unstaged", plain_unstaged),
                ("Untracked", sorted(untracked_paths)),
            ]
            first_rel = tree.populate_groups(
                groups, selected_rel_path=self._change_review_selected_rel_path
            )
        else:
            first_rel = tree.populate_groups(
                [
                    (
                        "Changed",
                        [
                            self._change_review_relpath(diff)
                            for diff in getattr(change_set, "changes", [])
                        ],
                    )
                ],
                selected_rel_path=self._change_review_selected_rel_path,
            )

        self._change_review_selected_rel_path = first_rel
        initial_diff = (
            self._change_review_diff_lookup.get(first_rel) if first_rel else first_diff
        )
        self._change_review_snapshot_key = self._change_review_signature(change_set)
        self._update_change_review_action_state()
        self._change_review_preview_version += 1
        await self._render_change_review_preview(
            initial_diff,
            version=self._change_review_preview_version,
        )

    async def _open_change_review_panel(
        self,
        change_set: Any,
        *,
        title: str,
        mode: str,
    ) -> None:
        if self._change_review_visible and self._change_review_source == "git":
            await self._refresh_change_review_source()
            if self._change_review_change_set and getattr(
                self._change_review_change_set, "changes", None
            ):
                self._change_review_visible = True
                await self._populate_change_review_panel()
            return
        self._change_review_change_set = change_set
        self._change_review_title = title
        self._change_review_mode = mode
        self._change_review_visible = True
        await self._populate_change_review_panel()

    async def _toggle_change_review_panel(self) -> None:
        await self._refresh_change_review_source()
        if not self._change_review_change_set or not getattr(
            self._change_review_change_set, "changes", None
        ):
            return
        self._change_review_visible = not self._change_review_visible
        self._apply_change_review_panel_state()
        if self._change_review_visible:
            await self._populate_change_review_panel()

    def _poll_change_review_panel(self) -> None:
        self.run_worker(
            self._sync_change_review_panel_state(),
            exclusive=True,
            group="change-review-sync",
        )

    async def _sync_change_review_panel_state(self) -> None:
        previous_signature = self._change_review_snapshot_key
        was_visible = self._change_review_visible
        await self._refresh_change_review_source()
        change_set = self._change_review_change_set
        if not change_set or not getattr(change_set, "changes", None):
            self._change_review_snapshot_key = None
            return
        current_signature = self._change_review_signature(change_set)
        self._change_review_snapshot_key = current_signature
        if not was_visible or not self._change_review_visible:
            return
        if current_signature != previous_signature:
            await self._populate_change_review_panel()

    def _render_aside_pending_text(self) -> Text:
        styles = self._render_styles()
        text = Text("Thinking", style=f"{self._style('success')} italic")
        suffix = self._activity_suffix_frames[
            self._activity_suffix_index % len(self._activity_suffix_frames)
        ]
        text.append(suffix, style=f"{self._style('success')} italic")
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
                response_widget = Static(
                    CopyableMarkdown(answer), classes="aside-assistant-body"
                )
            await body.mount(
                Vertical(user_row, response_widget, classes="aside-thread")
            )
        self._apply_aside_panel_state()
        body.scroll_end(animate=False)

    async def _push_aside_entry(self, question: str, answer: str) -> None:
        self._aside_entries.append(
            {"question": question, "answer": answer, "state": "done"}
        )
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

    async def _complete_aside_entry(
        self, entry_id: str, *, answer: str, state: str = "done"
    ) -> None:
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

    @on(Button.Pressed, "#cloud-sign-in")
    def on_cloud_sign_in_pressed(self, _event: Button.Pressed) -> None:
        self.run_worker(self._run_cloud_login_flow(), exclusive=False)

    @on(Button.Pressed, "#cloud-exit")
    def on_cloud_exit_pressed(self, _event: Button.Pressed) -> None:
        self.run_worker(self._exit_app(), exclusive=False)

    async def _exit_app(self) -> None:
        await self._shutdown_remote_server()
        await self._shutdown_agents()
        self.exit()

    @on(Button.Pressed, "#onboarding-continue")
    def on_onboarding_continue_pressed(self, _event: Button.Pressed) -> None:
        self.run_worker(self._finish_onboarding_flow(skip=False), exclusive=False)

    @on(Button.Pressed, "#onboarding-skip")
    def on_onboarding_skip_pressed(self, _event: Button.Pressed) -> None:
        self.run_worker(self._finish_onboarding_flow(skip=True), exclusive=False)

    @on(Input.Submitted, "#onboarding-name")
    @on(Input.Submitted, "#onboarding-role-other")
    @on(Input.Submitted, "#onboarding-use-case-other")
    def on_onboarding_input_submitted(self, event: Input.Submitted) -> None:
        if self._focus_next_onboarding_field(getattr(event.input, "id", None)):
            return
        self.run_worker(self._finish_onboarding_flow(skip=False), exclusive=False)

    @on(Select.Changed, "#onboarding-role-select")
    def on_onboarding_role_select_changed(self, event: Select.Changed) -> None:
        self._set_onboarding_other_visibility(
            other_input_id="onboarding-role-other",
            value=event.value,
        )
        if event.value not in {Select.BLANK, Select.NULL, ONBOARDING_OTHER_VALUE}:
            self.query_one("#onboarding-use-case-select", Select).focus()

    @on(Select.Changed, "#onboarding-use-case-select")
    def on_onboarding_use_case_select_changed(self, event: Select.Changed) -> None:
        self._set_onboarding_other_visibility(
            other_input_id="onboarding-use-case-other",
            value=event.value,
        )

    @on(Button.Pressed, "#changes-toggle")
    async def on_changes_toggle_pressed(self, _event: Button.Pressed) -> None:
        has_content = bool(
            self._change_review_change_set
            and getattr(self._change_review_change_set, "changes", None)
        )
        if has_content:
            await self._toggle_change_review_panel()
            return
        if self._git_outbound_state and self._git_outbound_state.needs_attention:
            self.run_worker(self._run_publish_flow(), exclusive=False)

    async def _configure_remote_for_publish(
        self,
        *,
        remote_name: str,
        remote_url: str,
    ) -> bool:
        cwd = Path(self.config.cwd).resolve()
        result = await asyncio.to_thread(
            upsert_remote,
            cwd,
            remote_name,
            remote_url,
        )
        await self._refresh_change_review_source(prefer_git_only=True)
        if not result.ok:
            self.post_system("Git", result.message, is_error=True)
            return False
        self.post_notice("Git", result.message)
        return True

    async def _prompt_for_remote_setup(self, branch: str) -> bool:
        result = await self._open_modal(
            RemoteSetupModal(branch=branch, remote_name="origin")
        )
        if not result:
            return False
        return await self._configure_remote_for_publish(
            remote_name=result["remote_name"],
            remote_url=result["remote_url"],
        )

    async def _run_publish_flow(
        self,
        *,
        configured_remote: tuple[str, str] | None = None,
    ) -> None:
        if configured_remote is not None:
            configured = await self._configure_remote_for_publish(
                remote_name=configured_remote[0],
                remote_url=configured_remote[1],
            )
            if not configured:
                return

        outbound = self._git_outbound_state
        if not outbound or not outbound.needs_attention:
            await self._refresh_change_review_source(prefer_git_only=True)
            outbound = self._git_outbound_state
        if not outbound or not outbound.needs_attention:
            self.post_notice("Git", "Nothing to publish.")
            return
        if not outbound.has_remote:
            configured = await self._prompt_for_remote_setup(outbound.branch)
            if configured:
                await self._run_publish_flow()
            return
        commit_subjects = await asyncio.to_thread(
            outbound_commit_subjects,
            Path(self.config.cwd).resolve(),
        )
        confirmed = await self._open_modal(
            PushReviewModal(
                branch=outbound.branch,
                target=outbound.target_label,
                action_label=outbound.action_label,
                ahead_count=outbound.ahead_count,
                behind_count=outbound.behind_count,
                commit_subjects=commit_subjects,
            )
        )
        if not confirmed:
            return
        result = await asyncio.to_thread(
            push_current_branch, Path(self.config.cwd).resolve()
        )
        await self._refresh_change_review_source(prefer_git_only=True)
        if not result.ok:
            self.post_system("Git", result.message, is_error=True)
            return
        self.post_notice("Git", result.message)

    @on(Button.Pressed, "#change-review-close")
    def on_change_review_close_pressed(self, _event: Button.Pressed) -> None:
        self._change_review_visible = False
        self._apply_change_review_panel_state()

    def _show_change_review_row(self, row_key_value: str | None) -> None:
        if not row_key_value:
            return
        self._change_review_selected_rel_path = row_key_value
        self._update_change_review_action_state()
        diff = self._change_review_diff_lookup.get(row_key_value)
        if diff is not None:
            self._change_review_preview_version += 1
            self.run_worker(
                self._render_change_review_preview(
                    diff,
                    version=self._change_review_preview_version,
                ),
                exclusive=False,
            )

    @on(Tree.NodeSelected, "#change-review-tree")
    def on_change_review_node_selected(self, event: Tree.NodeSelected) -> None:
        data = getattr(event.node, "data", None)
        rel_path = getattr(data, "rel_path", None)
        if isinstance(rel_path, str):
            self._show_change_review_row(rel_path)

    @on(Tree.NodeHighlighted, "#change-review-tree")
    def on_change_review_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = getattr(event.node, "data", None)
        rel_path = getattr(data, "rel_path", None)
        if isinstance(rel_path, str):
            self._show_change_review_row(rel_path)

    async def _refresh_change_review_after_git_action(self) -> None:
        await self._refresh_change_review_source(
            prefer_git_only=self._change_review_source == "git"
        )
        change_set = self._change_review_change_set
        if not change_set or not getattr(change_set, "changes", None):
            self._change_review_visible = False
            self._change_review_selected_rel_path = None
            self._apply_change_review_panel_state()
            preview = self.query_one("#change-review-preview", ScrollableContainer)
            await preview.remove_children()
            await preview.mount(
                Static("No changes to inspect.", classes="change-review-empty")
            )
            return
        if (
            self._change_review_selected_rel_path
            and self._change_review_selected_rel_path
            not in {
                self._change_review_relpath(diff)
                for diff in getattr(change_set, "changes", [])
            }
        ):
            self._change_review_selected_rel_path = None
        await self._populate_change_review_panel()

    async def _confirm_change_review_discard(self, *, title: str, body: str) -> bool:
        result = await self._open_modal(
            ConfirmModal(
                title=title,
                body=body,
                yes_label="Discard",
                no_label="Cancel",
            )
        )
        return bool(result)

    async def _open_commit_modal(self) -> dict[str, Any] | None:
        cwd = Path(self.config.cwd).resolve()
        change_set = self._change_review_change_set
        if not change_set:
            return None
        branch = await asyncio.to_thread(current_branch, cwd)
        changes = list(getattr(change_set, "changes", []) or [])
        additions = 0
        deletions = 0
        diff_sections: list[str] = []
        for diff in changes:
            old_lines = getattr(diff, "old_content", "").splitlines()
            new_lines = getattr(diff, "new_content", "").splitlines()
            for line in difflib.ndiff(old_lines, new_lines):
                if line.startswith("+ "):
                    additions += 1
                elif line.startswith("- "):
                    deletions += 1
            rel_path = self._change_review_relpath(diff)
            status = (
                "new"
                if getattr(diff, "is_new_file", False)
                else "deleted"
                if getattr(diff, "is_deletion", False)
                else "modified"
            )
            signal_lines: list[str] = []
            for line in difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
                lineterm="",
                n=2,
            ):
                if line.startswith(("---", "+++", "@@")):
                    continue
                if not line.startswith(("+", "-")):
                    continue
                body = line[1:].strip()
                if not body:
                    continue
                if body in {"{", "}", "[", "]", "(", ")"}:
                    continue
                if len(body) > 120:
                    body = body[:117] + "..."
                signal_lines.append(f"{line[0]} {body}")
                if len(signal_lines) >= 6:
                    break
            section = [f"{rel_path} [{status}]"]
            section.extend(signal_lines)
            diff_sections.append("\n".join(section))
        diff_context = "\n\n".join(diff_sections[:12])[:5000]
        return await self._open_modal(
            CommitModal(
                config=self.config,
                llm_client=(
                    self.agent.session.client
                    if self.agent and self.agent.session
                    else None
                ),
                branch=branch,
                file_count=len(changes),
                additions=additions,
                deletions=deletions,
                changed_paths=[self._change_review_relpath(diff) for diff in changes],
                diff_context=diff_context,
                push_label=(
                    "Commit and publish"
                    if self._git_outbound_state
                    and self._git_outbound_state.needs_publish
                    else "Commit and push"
                ),
            )
        )

    @on(events.Click, "#change-review-stage-file")
    async def on_change_review_stage_file(self, _event: events.Click) -> None:
        if self.query_one("#change-review-stage-file", Static).disabled:
            return
        rel_path = self._change_review_selected_rel_path
        if not rel_path:
            return
        result = await asyncio.to_thread(
            stage_path, Path(self.config.cwd).resolve(), rel_path
        )
        if not result.ok:
            self.post_system("Git", result.message, is_error=True)
            return
        self.post_notice("Git", result.message)
        await self._refresh_change_review_after_git_action()

    @on(events.Click, "#change-review-unstage-file")
    async def on_change_review_unstage_file(self, _event: events.Click) -> None:
        if self.query_one("#change-review-unstage-file", Static).disabled:
            return
        rel_path = self._change_review_selected_rel_path
        if not rel_path:
            return
        result = await asyncio.to_thread(
            unstage_path, Path(self.config.cwd).resolve(), rel_path
        )
        if not result.ok:
            self.post_system("Git", result.message, is_error=True)
            return
        self.post_notice("Git", result.message)
        await self._refresh_change_review_after_git_action()

    async def _run_change_review_discard_file(self) -> None:
        if self.query_one("#change-review-discard-file", Static).disabled:
            return
        rel_path = self._change_review_selected_rel_path
        if not rel_path:
            return
        confirmed = await self._confirm_change_review_discard(
            title="Discard file changes?",
            body=f"Discard all staged and unstaged changes for `{rel_path}`?",
        )
        if not confirmed:
            return
        result = await asyncio.to_thread(
            discard_path, Path(self.config.cwd).resolve(), rel_path
        )
        if not result.ok:
            self.post_system("Git", result.message, is_error=True)
            return
        self.post_notice("Git", result.message)
        await self._refresh_change_review_after_git_action()

    @on(events.Click, "#change-review-discard-file")
    def on_change_review_discard_file(self, event: events.Click) -> None:
        event.stop()
        self.run_worker(self._run_change_review_discard_file(), exclusive=False)

    @on(events.Click, "#change-review-stage-all")
    async def on_change_review_stage_all(self, _event: events.Click) -> None:
        stage_all_chip = self.query_one("#change-review-stage-all", Static)
        if stage_all_chip.disabled:
            return
        git_fn = (
            stage_all if self._change_review_bulk_action == "stage" else unstage_all
        )
        result = await asyncio.to_thread(git_fn, Path(self.config.cwd).resolve())
        if not result.ok:
            self.post_system("Git", result.message, is_error=True)
            return
        self.post_notice("Git", result.message)
        await self._refresh_change_review_after_git_action()

    async def _run_change_review_commit(self) -> None:
        commit_chip = self.query_one("#change-review-commit", Static)
        if commit_chip.disabled:
            return
        result = await self._open_commit_modal()
        if not result:
            return
        action = str(result.get("action", "commit")).strip().lower()
        include_unstaged = bool(result.get("include_unstaged"))
        message = str(result.get("message", ""))
        commit_result = await asyncio.to_thread(
            commit_changes,
            Path(self.config.cwd).resolve(),
            message=message,
            include_unstaged=include_unstaged,
            push=action == "commit_push",
        )
        await self._refresh_change_review_after_git_action()
        if not commit_result.ok:
            self.post_system("Git", commit_result.message, is_error=True)
            return
        self.post_notice("Git", commit_result.message)

    @on(events.Click, "#change-review-commit")
    def on_change_review_commit(self, event: events.Click) -> None:
        event.stop()
        self.run_worker(self._run_change_review_commit(), exclusive=False)

    async def _run_change_review_discard_all(self) -> None:
        if self.query_one("#change-review-discard-all", Static).disabled:
            return
        confirmed = await self._confirm_change_review_discard(
            title="Discard all changes?",
            body="Discard all staged, unstaged, and untracked changes in the current working tree?",
        )
        if not confirmed:
            return
        result = await asyncio.to_thread(discard_all, Path(self.config.cwd).resolve())
        await self._refresh_change_review_after_git_action()
        if not result.ok:
            self.post_system("Git", result.message, is_error=True)
            return
        self.post_notice("Git", result.message)

    @on(events.Click, "#change-review-discard-all")
    def on_change_review_discard_all(self, event: events.Click) -> None:
        event.stop()
        self.run_worker(self._run_change_review_discard_all(), exclusive=False)

    async def _apply_setup_result(self, result: dict[str, Any]) -> None:
        try:
            save_system_config(
                api_key=result["api_key"],
                base_url=result["base_url"],
                model_name=result["model_name"],
                context_window=int(result.get("context_window") or DEFAULT_CONTEXT_WINDOW),
                context_window_source=str(result.get("context_window_source") or "").strip() or None,
            )
            save_saved_custom_provider(
                api_key=result["api_key"],
                base_url=result["base_url"],
                model_name=result["model_name"],
                context_window=int(result.get("context_window") or DEFAULT_CONTEXT_WINDOW),
                context_window_source=str(result.get("context_window_source") or "").strip() or None,
            )
            save_global_approval_mode(result["approval"])
        except Exception as exc:
            self.post_system("Setup failed", str(exc), is_error=True)
            self.exit()
            return

        self.config.api_key = result["api_key"]
        self.config.base_url = result["base_url"]
        self.config.model.name = result["model_name"]
        self.config.model.context_window = int(
            result.get("context_window") or DEFAULT_CONTEXT_WINDOW
        )
        self.config.model.context_window_source = (
            str(result.get("context_window_source") or "").strip() or None
        )
        self.config.approval = ApprovalPolicy(result["approval"])
        await self._reset_active_provider_client()
        self.refresh_header()
        self.post_notice("Setup complete", "Credentials saved and applied.")

    async def _open_setup_modal(self, *, exit_on_cancel: bool = False) -> bool:
        result = await self._open_modal(SetupModal(self.config))
        if not result:
            if exit_on_cancel and self.config.needs_setup:
                self.exit()
            return False
        await self._apply_setup_result(result)
        return True

    async def _reset_active_provider_client(self) -> None:
        if not self.agent or not self.agent.session or not self.agent.session.client:
            return
        try:
            await self.agent.session.client.close()
        except Exception:
            pass

    def _tick_top_indicator(self) -> None:
        has_pending_command_spinner = any(
            pending_active
            for _card, _body_widget, _scroll_widget, _lines, pending_active, _pending_text in self._streaming_command_cards.values()
        )
        if (
            not self._top_busy
            and not self._aside_pending_widgets
            and not has_pending_command_spinner
            and not self._cloud_auth_busy
        ):
            return
        self._top_spinner_index += 1
        if self._top_spinner_index % 3 == 0:
            self._activity_suffix_index += 1
        if self._activity_widget is not None and self._top_busy:
            self._activity_widget.update(
                self._render_activity_indicator_text(self._top_state_text)
            )
        if self._live_compaction_active and self._live_compaction_body is not None:
            self._live_compaction_body.update(
                self._render_live_compaction_body(
                    "Compacting context",
                    active=True,
                )
            )
        if self._cloud_signed_out:
            try:
                self.query_one("#signed-out-status", Static).update(
                    self._signed_out_status_text()
                )
            except NoMatches:
                pass
        if self._aside_pending_widgets:
            pending_text = self._render_aside_pending_text()
            for widget in list(self._aside_pending_widgets.values()):
                widget.update(pending_text)
        for _card, body_widget, _scroll, lines, pending_active, pending_text in list(
            self._streaming_command_cards.values()
        ):
            if pending_active:
                body_widget.update(
                    self._build_streaming_command_renderable(
                        lines,
                        pending_active=pending_active,
                        pending_text=pending_text,
                        spinner_index=self._top_spinner_index,
                    )
                )
        for call_id in self._run_state().running_shell_call_ids:
            card = self._tool_widgets.get(call_id)
            args = self._tool_args_by_call_id.get(call_id, {})
            if card is not None:
                live_state = self._live_shell_call_state.get(call_id)
                if live_state is not None:
                    header, body = self._build_shell_session_card_content(
                        name=live_state.name,
                        arguments=live_state.arguments,
                        metadata=live_state.metadata,
                        payload=live_state.payload,
                        success=live_state.success,
                        exit_code=live_state.exit_code,
                        animate_running=True,
                    )
                    if isinstance(card, ShellToolCard):
                        card.set_shell_content(header=header, body=body)
                    else:
                        card.update(Group(header, body))
                else:
                    if isinstance(card, ShellToolCard):
                        header, body = self._build_shell_session_card_content(
                            name="shell",
                            arguments=args,
                            metadata={"running": True, "status": "command_running"},
                            payload="",
                            success=True,
                            exit_code=None,
                            animate_running=True,
                        )
                        card.set_shell_content(header=header, body=body)
                    else:
                        card.update(
                            render_shell_running_card(
                                args,
                                cwd=self.config.cwd,
                                spinner_index=self._top_spinner_index,
                            )
                        )
        for call_id in self._run_state().running_subagent_call_ids:
            card = self._tool_widgets.get(call_id)
            args = self._tool_args_by_call_id.get(call_id, {})
            if card is not None:
                card.update(
                    self._render_subagent_running_card(
                        call_id=call_id,
                        name=self._tool_name_by_call_id.get(call_id, "subagent"),
                        args=args,
                        spinner_index=self._top_spinner_index,
                    )
                )
        for call_id in self._run_state().running_wait_subagent_call_ids:
            card = self._tool_widgets.get(call_id)
            args = self._tool_args_by_call_id.get(call_id, {})
            if card is not None:
                card.update(
                    self._render_wait_subagent_running_card(
                        args=args,
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
            CopyableMarkdown(self._with_implementation_plan_title(normalized)),
            css_class="plan",
        )
        self._last_rendered_plan_text = normalized
        return True

    async def ensure_agent(self) -> None:
        if self.agent is not None:
            if self.agent.session is not None:
                self._remember_open_session(self.agent.session, agent=self.agent)
                await self._broadcast_remote_state()
            return
        fresh = Session(config=self.config)
        self.agent = self._build_session_agent(fresh)
        await self.agent.__aenter__()
        if self.agent.session is not None:
            self._remember_open_session(self.agent.session, agent=self.agent)
        await self._broadcast_remote_state()

    def _build_session_agent(self, session: Session) -> Agent:
        session_id = self._session_id(session) or ""

        async def _confirm(confirmation, sid: str = session_id) -> bool:
            return await self._confirmation_callback_for_session(sid, confirmation)

        async def _plan_question(
            payload: dict[str, Any], sid: str = session_id
        ) -> dict[str, Any]:
            return await self._plan_question_callback_for_session(sid, payload)

        return Agent(
            config=self.config,
            session=session,
            confirmation_callback=_confirm,
            plan_question_callback=_plan_question,
        )

    async def _confirmation_callback_for_session(
        self, session_id: str, confirmation
    ) -> bool:
        if session_id and session_id != self._active_session_id():
            await self._activate_open_session(
                session_id,
                announce="Switched to thread requiring approval.",
            )
        return await self.confirmation_callback(confirmation)

    async def _plan_question_callback_for_session(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if session_id and session_id != self._active_session_id():
            await self._activate_open_session(
                session_id,
                announce="Switched to thread asking a planning question.",
            )
        return await self.plan_question_callback(payload)

    def _reset_session_local_ui_state(self) -> None:
        self._tool_widgets.clear()
        self._tool_args_by_call_id.clear()
        self._tool_name_by_call_id.clear()
        self._tool_completion_state.clear()
        self._live_shell_call_state.clear()
        self._streaming_widget = None
        self._streaming_buffer = ""
        self._activity_widget = None
        self._last_rendered_plan_text = None
        self._aside_panel_visible = False
        self._aside_entries = []
        self._aside_pending_widgets = {}
        self._run_state().running_shell_call_ids.clear()
        self._run_state().running_subagent_call_ids.clear()
        self._run_state().running_wait_subagent_call_ids.clear()
        if self.is_mounted:
            self._apply_aside_panel_state()

    async def _activate_open_session(
        self,
        session_id: str,
        *,
        announce: str | None = None,
    ) -> bool:
        if self.agent is None:
            await self.ensure_agent()
        if not self.agent:
            return False
        target = self._open_sessions.get(session_id)
        if target is None:
            return False
        target_agent = self._session_agents.get(session_id)
        if target_agent is None:
            return False
        current_id = self._session_id(self.agent.session)
        if current_id == session_id:
            self.refresh_header()
            return True
        if (
            current_id
            and current_id in self._open_sessions
            and self.agent.session
            and self.agent.session.turn_count > 0
            and not self._run_state(current_id).is_turn_running
        ):
            await self.auto_save()

        workspace = self._workspace_for_session_id(session_id)
        self.config.cwd = workspace
        self.agent = target_agent
        self._remember_open_session(target, workspace=workspace, agent=target_agent)
        self.refresh_header()
        await self._hydrate_chat_from_snapshot(
            target.context_manager.get_messages() if target.context_manager else []
        )
        if self._is_turn_running:
            self._set_loading_state(self._progress_state_label(), busy=True)
        else:
            self._set_loading_state("idle", busy=False)
        if announce:
            self.post_notice("Thread", announce)
        await self._broadcast_remote_state()
        return True

    async def _open_modal(self, screen: ModalScreen[Any]) -> Any:
        """Open a modal and await dismissal from regular event handlers safely."""
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[Any] = loop.create_future()

        def _on_dismiss(result: Any) -> None:
            if not result_future.done():
                result_future.set_result(result)

        self.push_screen(screen, callback=_on_dismiss)
        return await result_future

    async def _perform_quit(self) -> None:
        try:
            await self.auto_save()
        except Exception:
            pass
        await self._shutdown_remote_server()
        await self._shutdown_agents()
        self.exit()

    async def _confirm_quit(self) -> None:
        confirmed = await self._open_modal(
            ConfirmModal(
                title="Quit iTE?",
                body=("Any local threads running on this machine will be interrupted."),
                yes_label="Quit",
                no_label="Stay",
            )
        )
        if not confirmed:
            return
        await self._perform_quit()

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

    @staticmethod
    def _is_internal_todo_event(call_id: str | None) -> bool:
        value = str(call_id or "").strip()
        return value.startswith(
            (
                "todos_seed_",
                "todos_progress_",
                "todos_exec_seed_",
                "todos_exec_progress_",
            )
        )

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
        if (
            session.plan_mode_enabled
            and session.plan_phase == "awaiting_implementation_confirmation"
        ):
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

    def _should_suppress_intent_detection(
        self, message: str, *, plan_enabled: bool
    ) -> bool:
        text = (message or "").strip()
        min_len = 7 if plan_enabled else 12
        if len(text) < min_len:
            return True
        if len(text.split()) < 3:
            if not (
                plan_enabled and re.search(r"\b(let'?s|lets|let us)\b", text.lower())
            ):
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

        if bool(
            re.search(
                r"\b(let'?s|lets|let us)\s+(build|create|design|architect)\b", text
            )
        ):
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
        if any(m in text for m in build_intent_markers) and any(
            t in text for t in product_targets
        ):
            return True

        return bool(
            re.search(r"\b(plan|roadmap|steps)\b", text) and "implement" not in text
        )

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
        if bool(
            re.search(
                r"\b(let'?s|lets|let us)\s+(build|built|implement|code|execute)\b", text
            )
        ):
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
                self.post_plan_note(
                    "Plan mode enabled", "Planning mode is now active for this thread."
                )
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
                self.post_plan_note(
                    "Plan mode disabled", "Execution mode is now active."
                )
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
            self.post_notice("Exit", "Use `/exit` or `/quit` to close iTE.")

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

        if (
            self._plan_question_future is not None
            and not self._plan_question_future.done()
        ):
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
            self._set_prompt_text_from_history(
                self._composer_history[self._composer_history_index]
            )
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
        prompt_lines = min(
            max(line_count, self.MIN_PROMPT_LINES), self.MAX_PROMPT_LINES
        )
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
        return build_turn_payload(
            message,
            attachments,
            max_attachments=MAX_ATTACHMENTS,
            display_message=message,
        )

    @staticmethod
    def _is_retryable_bundled_inference_error(message: str) -> bool:
        text = str(message or "").strip().lower()
        if not text:
            return False
        return (
            "bundled inference provider failed" in text
            or "bundled usage is temporarily unavailable right now" in text
            or "bundled inference request failed" in text
        )

    def _mark_retryable_turn_failure(self, session_id: str, error_message: str) -> None:
        run_state = self._run_state(session_id)
        run_state.last_error_message = error_message
        if (
            self._is_retryable_bundled_inference_error(error_message)
            and run_state.last_turn_payload is not None
        ):
            run_state.retryable_turn_payload = dict(run_state.last_turn_payload)
        else:
            run_state.retryable_turn_payload = None

    def _build_followup_recovery_payload(
        self, session_id: str
    ) -> dict[str, Any] | None:
        run_state = self._run_state(session_id)
        if not run_state.last_turn_payload:
            return None
        return {
            "message": (
                "Continue from the last successful step only. "
                "Do not repeat completed tool work, repeated file reads, or already-finished analysis. "
                "Use the existing results already in the conversation and finish the interrupted task."
            ),
            "display_message": "",
            "attachments": [],
            "suppress_user_echo": True,
        }

    async def _retry_last_turn(self) -> None:
        session_id = self._active_session_id()
        if not session_id:
            self.post_system("Retry", "No active thread.", is_error=True)
            return
        run_state = self._run_state(session_id)
        if self._is_turn_running:
            self.post_system(
                "Retry", "Wait for the current turn to finish first.", is_error=True
            )
            return
        payload = run_state.retryable_turn_payload
        if payload is None:
            self.post_system(
                "Retry",
                "No retryable turn is available in this thread.",
                is_error=True,
            )
            return
        self.post_notice("Retry", "Retrying last turn.")
        run_state.retryable_turn_payload = None
        await self._dispatch_payload(dict(payload))

    def _resolve_inline_attachment_payload(
        self,
        *,
        message: str,
        attachments: list[str],
    ) -> tuple[dict[str, Any] | None, list[str]]:
        resolution = resolve_inline_attachment_refs(
            message,
            cwd=Path(self.config.cwd).resolve(),
            existing_paths=attachments,
            files=self._discover_attachable_files(),
        )
        if resolution.errors:
            return None, resolution.errors
        return (
            build_turn_payload(
                resolution.message,
                resolution.queued_paths,
                max_attachments=MAX_ATTACHMENTS,
                display_message=message,
            ),
            [],
        )

    def _prepare_attachments_for_turn(
        self,
        *,
        message: str,
        attachments: list[str],
        turn_id: int,
    ) -> tuple[str, str | list[dict] | None, str | None, list[Attachment]] | None:
        if not attachments:
            return message, None, None, []
        manager = AttachmentManager(self.config.cwd)
        temp_turn_id = f"reup_{turn_id}"
        staged, errors = manager.stage_paths(attachments, temp_turn_id)
        if errors:
            for error in errors:
                self.post_attachment_note(error)
        if not staged:
            return None
        user_model_content = build_user_model_content(message, staged, self.config.cwd)
        prepared_message = build_user_text_with_manifest(
            message, staged, self.config.cwd
        )
        return prepared_message, user_model_content, temp_turn_id, staged

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
        prompt.text = str(
            payload.get("display_message", payload.get("message", ""))
        ).strip()
        self._resize_composer_for_prompt()
        if self.agent and self.agent.session:
            self.agent.session.pending_attachment_paths = []

    async def _dispatch_payload(self, payload: dict[str, Any]) -> None:
        message = str(payload.get("message", "")).strip()
        display_message = str(
            payload.get("display_message", payload.get("message", ""))
        ).strip()
        suppress_user_echo = bool(payload.get("suppress_user_echo", False))
        attachments = [
            str(path).strip()
            for path in list(payload.get("attachments") or [])
            if str(path).strip()
        ]
        if not message:
            return
        if self.agent and self.agent.session:
            self.agent.session.pending_attachment_paths = list(attachments)

        normalized = self._normalize_plan_execution_request(message)
        if normalized is None:
            return
        message = normalized

        if message.startswith("/"):
            await self.run_command(message)
            return

        self.run_worker(
            self._handle_agent_send_with_intent(
                message,
                display_message=display_message or message,
                suppress_user_echo=suppress_user_echo,
            ),
            exclusive=False,
        )

    async def _resolve_active_turn_send(self, payload: dict[str, Any]) -> bool:
        replacing_queue = self._queued_turn_payload is not None
        self._show_turn_action_palette(payload, replacing_queue=replacing_queue)
        return True

    async def _dispatch_queued_payload_if_ready(self) -> None:
        run_state = self._run_state()
        if run_state.auto_resume_payload is not None:
            payload = run_state.auto_resume_payload
            run_state.auto_resume_payload = None
            self._set_loading_state("resuming after compaction", busy=True)
            await self._dispatch_payload(payload)
            return
        if run_state.failure_recovery_payload is not None:
            payload = run_state.failure_recovery_payload
            run_state.failure_recovery_payload = None
            self._set_loading_state("continuing after transient failure", busy=True)
            await self._dispatch_payload(payload)
            return
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
        attachments: list[str] = []
        if self.agent and self.agent.session:
            attachments = list(self.agent.session.pending_attachment_paths)
        payload, errors = self._resolve_inline_attachment_payload(
            message=message,
            attachments=attachments,
        )
        if payload is None:
            for error in errors:
                self.post_attachment_note(error)
            return
        if self._is_turn_running and not is_aside_command_text(message):
            handled = await self._resolve_active_turn_send(payload)
            if handled:
                return
            return

        if self._consume_dropped_path_text(message):
            return
        self._clear_composer_after_submit()
        await self._dispatch_payload(payload)

    async def _handle_agent_send_with_intent(
        self,
        message: str,
        *,
        display_message: str | None = None,
        suppress_user_echo: bool = False,
    ) -> None:
        assisted = await self._apply_intent_assist(message)
        if assisted is None:
            return
        await self.run_agent_message(
            assisted,
            display_message=display_message or message,
            suppress_user_echo=suppress_user_echo,
        )

    async def _list_resume_sessions(
        self, all_workspaces: bool = False
    ) -> list[dict[str, Any]]:
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
            self.post_system(
                "Sessions", f"Session not found: {selected_id}", is_error=True
            )
            return

        await self._resume_snapshot(snapshot)

    async def _resume_snapshot(self, snapshot: SessionSnapshot) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            return
        current_session = self.agent.session
        current_session_id = self._active_session_id()
        if snapshot.session_id in self._open_sessions:
            workspace = (
                Path(snapshot.workspace_path).resolve()
                if snapshot.workspace_path
                else Path(self.config.cwd).resolve()
            )
            self._open_session_workspaces[snapshot.session_id] = workspace
            await self._activate_open_session(
                snapshot.session_id,
                announce="Switched to already-open thread.",
            )
            return
        if snapshot.workspace_path:
            target_workspace = Path(snapshot.workspace_path).resolve()
            if target_workspace != self.config.cwd.resolve():
                self.config.cwd = target_workspace
                self.refresh_header()

        resumed = Session(config=self.config)
        if hasattr(resumed, "set_session_id"):
            resumed.set_session_id(snapshot.session_id)
        else:
            resumed.session_id = snapshot.session_id
        resumed.name = snapshot.name
        resumed.name_source = snapshot.name_source
        resumed.name_locked = snapshot.name_locked
        resumed.name_last_generated_turn = snapshot.name_last_generated_turn
        resumed.created_at = snapshot.created_at
        resumed.updated_at = snapshot.updated_at
        resumed.turn_count = snapshot.turn_count
        resumed.plan_mode_enabled = snapshot.plan_mode_enabled
        resumed.plan_phase = snapshot.plan_phase
        resumed.plan_questions_asked = snapshot.plan_questions_asked
        resumed.plan_target_questions = snapshot.plan_target_questions
        resumed.pending_plan_text = snapshot.pending_plan_text
        resumed.active_plan_text = snapshot.active_plan_text
        resumed.active_skill_refs = list(snapshot.active_skills or [])
        resumed.show_planning_todos = snapshot.show_planning_todos
        resumed_agent = self._build_session_agent(resumed)
        await resumed_agent.__aenter__()

        if snapshot.transcript_state:
            resumed.context_manager.restore_transcript_state(snapshot.transcript_state)
        else:
            resumed.context_manager.set_messages(snapshot.messages)
        resumed.context_manager.total_usage = snapshot.total_usage
        restored_messages = resumed.context_manager.get_snapshot_messages()
        if hasattr(resumed, "restore_active_skills"):
            resumed.restore_active_skills(snapshot.active_skills)
        resumed.restore_todos_state(snapshot.todos_state)
        resumed.restore_change_history_state(snapshot.change_history_state)
        if hasattr(resumed, "restore_subagent_runtime_state"):
            resumed.restore_subagent_runtime_state(snapshot.subagent_runtime_state)
        dropped_agent: Agent | None = None
        if (
            current_session_id
            and current_session_id != snapshot.session_id
            and getattr(current_session, "turn_count", 0) == 0
            and not self._run_state(current_session_id).is_turn_running
        ):
            dropped_agent = self._drop_open_session(current_session_id)
        self._remember_open_session(
            resumed,
            workspace=Path(snapshot.workspace_path).resolve()
            if snapshot.workspace_path
            else Path(self.config.cwd).resolve(),
            agent=resumed_agent,
        )
        self.agent = resumed_agent
        self.refresh_header()
        await self._hydrate_chat_from_snapshot(restored_messages)
        await self._broadcast_remote_state()
        await self._remove_cards_by_title({"Session Loaded"})
        if dropped_agent is not None:
            try:
                await dropped_agent.__aexit__(None, None, None)
            except Exception:
                pass

    async def _hydrate_chat_from_snapshot(self, messages: list[dict[str, Any]]) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        await conversation.remove_children()
        self._message_count = 0
        self._reset_session_local_ui_state()
        tool_call_names: dict[str, str] = {}

        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role == "system":
                continue
            if role == "user":
                await self.add_user_message(str(content))
                continue
            if role == "assistant":
                if content:
                    await self.add_assistant_card(
                        "iTE", CopyableMarkdown(str(content)), css_class="assistant"
                    )
                for tool_call in message.get("tool_calls") or []:
                    call_id = str(tool_call.get("id", "") or "")
                    function = tool_call.get("function", {}) or {}
                    tool_name = str(function.get("name", "tool") or "tool")
                    raw_args = function.get("arguments", "") or ""
                    try:
                        parsed_args = json.loads(raw_args) if raw_args else {}
                    except Exception:
                        parsed_args = {"raw_arguments": raw_args}
                    parsed_args = self._normalize_tool_start_arguments(
                        tool_name,
                        parsed_args if isinstance(parsed_args, dict) else {},
                    )
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
                tool_ui = (
                    message.get("tool_ui")
                    if isinstance(message.get("tool_ui"), dict)
                    else {}
                )
                tool_name = str(tool_ui.get("name") or tool_name or "tool")
                success = (
                    bool(tool_ui.get("success"))
                    if "success" in tool_ui
                    else not output.lstrip().startswith("Error:")
                )
                rendered_output = str(
                    tool_ui.get("output") if "output" in tool_ui else output
                )
                rendered_error = (
                    str(tool_ui.get("error"))
                    if tool_ui.get("error") is not None
                    else (None if success else output)
                )
                if (
                    not success
                    and isinstance(rendered_error, str)
                    and self._should_suppress_malformed_tool_card(
                        tool_name, rendered_error
                    )
                ):
                    continue
                await self.update_tool_call(
                    call_id=call_id,
                    name=tool_name,
                    tool_kind=self.get_tool_kind(tool_name),
                    success=success,
                    output=rendered_output,
                    error=rendered_error,
                    metadata=tool_ui.get("metadata")
                    if isinstance(tool_ui.get("metadata"), dict)
                    else {},
                    diff=str(tool_ui.get("diff"))
                    if tool_ui.get("diff") is not None
                    else None,
                    truncated=bool(tool_ui.get("truncated", False)),
                    exit_code=int(tool_ui["exit_code"])
                    if isinstance(tool_ui.get("exit_code"), int)
                    else None,
                )
        self._refresh_empty_state()

    @on(Button.Pressed)
    async def on_session_tab_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if not button_id.startswith("session-tab-"):
            return
        session_id = button_id.removeprefix("session-tab-").strip()
        if not session_id:
            return
        event.stop()
        await self._activate_open_session(session_id)

    async def run_command(self, command_line: str) -> None:
        parts = command_line.split()
        command = parts[0].lower()
        args = parts[1:]
        command_feed_id: str | None = None

        if command in {"/exit", "/quit"}:
            await self._confirm_quit()
            return

        # Native in-app session picker flow (replaces curses picker in old /sessions command).
        if command == "/sessions" and args and not args[0].startswith("-"):
            snapshot = SessionManager().load_session(args[0])
            if snapshot is None:
                self.post_system(
                    "Sessions", f"Session not found: {args[0]}", is_error=True
                )
                return
            await self._resume_snapshot(snapshot)
            return

        if command == "/sessions" and "--list" not in args:
            self._open_resume_flow(all_workspaces=("--all" in args))
            return

        if command == "/plan":
            await self._run_plan_command_native(args)
            return

        if command == "/workboard":
            command_feed_id = self._start_remote_command_feed_entry(command_line)
            await self._run_workboard_command_native(command_feed_id=command_feed_id)
            return

        if command == "/aside":
            await self._run_aside_command_native(args)
            return

        if command == "/changes":
            await self._run_changes_command_native()
            return

        if command == "/publish":
            await self._run_publish_command_native(args)
            return

        if command == "/remote":
            await self._run_remote_command_native(args)
            return

        if command == "/close":
            await self.close_current_thread()
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

        if command == "/cloud":
            subcommand = args[0].lower() if args else "status"
            if subcommand in {"status", "show"}:
                if self._cloud_signed_out:
                    self._set_signed_out_state(True)
                else:
                    self.post_notice("iTE Cloud", "Signed in.")
                return
            if subcommand == "login":
                await self._run_cloud_login_flow()
                return
            if subcommand == "logout":
                await self._run_cloud_logout_flow()
                return
            self.post_system(
                "iTE Cloud",
                "Use `/cloud status`, `/cloud login`, or `/cloud logout`.",
                is_error=True,
            )
            return

        if command == "/logout":
            await self._run_cloud_logout_flow()
            return

        if command == "/usage":
            await self._open_usage_modal_from_meta()
            return

        if command == "/activity":
            await self._open_activity_modal_from_meta()
            return

        if command == "/theme":
            await self._open_theme_picker_from_meta()
            return

        if command == "/help":
            await self._show_commands_panel()
            return

        if command == "/approval" and not args:
            await self._open_approval_picker_from_meta(args)
            return

        if command == "/retry":
            await self._retry_last_turn()
            return

        command_feed_id = self._start_remote_command_feed_entry(command_line)

        await self.ensure_agent()
        if not self.agent:
            if command_feed_id is not None:
                self._finish_remote_command_feed_entry(
                    command_feed_id,
                    status="failed",
                    output="Agent is not initialized",
                )
            self.post_system("Error", "Agent is not initialized", is_error=True)
            return

        live_stream_command = command in {"/mcp", "/init"} and (
            not args or args[0].lower() != "status"
        )
        output = (
            StreamingCommandOutput(
                on_line=lambda line: self._handle_streaming_command_line(
                    command,
                    line,
                    command_feed_id=command_feed_id,
                )
            )
            if live_stream_command
            else io.StringIO()
        )
        is_manual_compact = command == "/compact" and (
            not args or args[0].lower() != "status"
        )
        compact_before = None
        if (
            is_manual_compact
            and self.agent
            and self.agent.session
            and self.agent.session.context_manager
        ):
            compact_before = self.agent.session.context_manager.compaction_count
            self.post_notice("Context", "Compacting context")
        ctx = build_command_context(
            config=self.config,
            agent=self.agent,
            tui=self._adapter,
            output_stream=output,
        )

        try:
            await self._ensure_command_registry()
            registry = self._command_registry
            if registry is None:
                if command_feed_id is not None:
                    self._finish_remote_command_feed_entry(
                        command_feed_id,
                        status="failed",
                        output="Command registry is not ready yet. Try again.",
                    )
                self.post_system(
                    "Command Error",
                    "Command registry is not ready yet. Try again.",
                    is_error=True,
                )
                return
            await registry.dispatch(command, args, ctx)
        except SystemExit:
            self.exit()
            return
        except Exception as exc:
            if command_feed_id is not None:
                self._finish_remote_command_feed_entry(
                    command_feed_id,
                    status="failed",
                    output=str(exc),
                )
            self.post_system("Command Error", str(exc), is_error=True)
            return

        if isinstance(output, StreamingCommandOutput):
            output.flush_pending()
        rendered = output.getvalue().strip()
        command_metadata = self._build_remote_command_feed_metadata(
            command,
            args,
            rendered,
        )
        if command in {
            "/branch",
            "/attach",
            "/model",
            "/rename",
            "/theme",
            "/approval",
        }:
            self.refresh_header()
        had_live_output = (
            isinstance(output, StreamingCommandOutput) and output.had_live_output
        )
        if live_stream_command:
            self.finalize_streaming_command_result(command)
            if command_feed_id is not None:
                self._finish_remote_command_feed_entry(
                    command_feed_id,
                    status="completed",
                    output=rendered,
                    metadata=command_metadata,
                )
        if (
            is_manual_compact
            and self.agent
            and self.agent.session
            and self.agent.session.context_manager
            and compact_before is not None
        ):
            compact_after = self.agent.session.context_manager.compaction_count
            if compact_after > compact_before:
                self.post_system(
                    "Context compacted",
                    "Context compacted.",
                )
                if command_feed_id is not None:
                    self._finish_remote_command_feed_entry(
                        command_feed_id,
                        status="completed",
                        output="Context compacted.",
                        metadata=command_metadata,
                    )
                return
        if rendered and not had_live_output:
            if command == "/skills" and self._post_skills_command_result(
                args, rendered
            ):
                if command_feed_id is not None:
                    self._finish_remote_command_feed_entry(
                        command_feed_id,
                        status="completed",
                        output=rendered,
                        metadata=command_metadata,
                    )
                return
            if self._post_native_command_result(command, args):
                if command_feed_id is not None:
                    self._finish_remote_command_feed_entry(
                        command_feed_id,
                        status="completed",
                        output=rendered,
                        metadata=command_metadata,
                    )
                return
            self.post_command_result(command, rendered)
            if command_feed_id is not None:
                self._finish_remote_command_feed_entry(
                    command_feed_id,
                    status="completed",
                    output=rendered,
                    metadata=command_metadata,
                )
            return
        if command_feed_id is not None:
            self._finish_remote_command_feed_entry(
                command_feed_id,
                status="completed",
                output=rendered,
                metadata=command_metadata,
            )

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

    async def _run_changes_command_native(self) -> None:
        await self._refresh_change_review_source()
        change_set = self._change_review_change_set
        if not change_set or not getattr(change_set, "changes", None):
            self.post_system(
                "Changes", "No git working tree changes to inspect.", is_error=True
            )
            return

        await self._open_change_review_panel(
            change_set,
            title=self._change_review_title,
            mode=self._change_review_mode,
        )

    async def _run_publish_command_native(self, args: list[str]) -> None:
        if not await asyncio.to_thread(is_git_repo, Path(self.config.cwd).resolve()):
            self.post_system(
                "Publish", "Not a git repository in current workspace.", is_error=True
            )
            return
        if not args:
            await self._run_publish_flow()
            return
        if len(args) == 1:
            await self._run_publish_flow(configured_remote=("origin", args[0]))
            return
        if len(args) == 2:
            await self._run_publish_flow(configured_remote=(args[0], args[1]))
            return
        self.post_system(
            "Publish",
            "Usage: /publish\n/publish <remote-url>\n/publish <remote-name> <remote-url>",
            is_error=True,
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
            is_light=self._prefer_terminal_safe_source_rendering(),
        )
        await self.add_assistant_card("Undid changes", body, css_class="change")
        self._append_remote_change_feed_entry(
            title="Undid changes",
            change_set=change_set,
            verb="Reverted",
            footer="Run /redo to reapply.",
            mode="undone",
        )
        await self._open_change_review_panel(
            change_set, title="Undid changes", mode="undone"
        )

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
            is_light=self._prefer_terminal_safe_source_rendering(),
        )
        await self.add_assistant_card("Reapplied changes", body, css_class="change")
        self._append_remote_change_feed_entry(
            title="Reapplied changes",
            change_set=change_set,
            verb="Reapplied",
            footer="Run /undo to revert again.",
            mode="redone",
        )
        await self._open_change_review_panel(
            change_set, title="Reapplied changes", mode="redone"
        )

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
        await self._broadcast_remote_state()

    async def _run_workboard_command_native(
        self,
        *,
        command_feed_id: str | None = None,
    ) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            if command_feed_id is not None:
                self._finish_remote_command_feed_entry(
                    command_feed_id,
                    status="failed",
                    output="No active session.",
                )
            self.post_system("Workboard", "No active session.", is_error=True)
            return

        session = self.agent.session
        workboard_payload = self._serialize_remote_workboard_payload(session)
        body = self._build_workboard_body(
            plan_mode_enabled=bool(workboard_payload["plan_mode_enabled"]),
            plan_phase=str(workboard_payload["plan_phase"]),
            show_planning=bool(workboard_payload["show_planning"]),
            completed=int(workboard_payload["completed"]),
            pending=int(workboard_payload["pending"]),
            total=int(workboard_payload["total"]),
            todos_state=cast(dict[str, Any], workboard_payload["todos_state"]),
            scopes=cast(list[str], workboard_payload["scopes"]),
            plan_text=str(workboard_payload["plan_text"]),
        )
        await self.add_assistant_card("Workboard", body, css_class="workboard")
        if command_feed_id is not None:
            self._finish_remote_command_feed_entry(
                command_feed_id,
                status="completed",
                output="Loaded workboard.",
                metadata={
                    "kind": "workboard",
                    "summary": {
                        "plan_mode_enabled": bool(workboard_payload["plan_mode_enabled"]),
                        "plan_phase": str(workboard_payload["plan_phase"]),
                        "show_planning": bool(workboard_payload["show_planning"]),
                        "completed": int(workboard_payload["completed"]),
                        "pending": int(workboard_payload["pending"]),
                        "total": int(workboard_payload["total"]),
                    },
                    "checklists": workboard_payload["checklists"],
                    "plan_text": str(workboard_payload["plan_text"]),
                },
            )

    def _serialize_remote_workboard_payload(
        self,
        session: Session,
    ) -> dict[str, Any]:
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
        checklists: list[dict[str, Any]] = []

        for scope in scopes:
            entries = todos_state.get(scope, [])
            if not isinstance(entries, list):
                continue
            normalized_entries = [
                item for item in entries if isinstance(item, dict)
            ]
            done_entries = [
                entry
                for entry in normalized_entries
                if bool(entry.get("completed", False))
            ]
            pending_entries = [
                entry
                for entry in normalized_entries
                if not bool(entry.get("completed", False))
            ]
            total += len(normalized_entries)
            completed += len(done_entries)
            pending += len(pending_entries)
            if not normalized_entries:
                continue
            checklists.append(
                {
                    "scope": scope,
                    "title": (
                        "Execution Checklist"
                        if scope == "execution"
                        else "Planning Checklist"
                    ),
                    "completed": len(done_entries),
                    "pending": len(pending_entries),
                    "total": len(normalized_entries),
                    "pending_items": [
                        str(entry.get("content") or "").strip()
                        for entry in pending_entries[:6]
                        if str(entry.get("content") or "").strip()
                    ],
                    "completed_items": [
                        str(entry.get("content") or "").strip()
                        for entry in done_entries[:3]
                        if str(entry.get("content") or "").strip()
                    ],
                    "remaining_pending": max(0, len(pending_entries) - 6),
                    "remaining_completed": max(0, len(done_entries) - 3),
                }
            )

        return {
            "plan_mode_enabled": bool(session.plan_mode_enabled),
            "plan_phase": str(session.plan_phase),
            "show_planning": show_planning,
            "completed": completed,
            "pending": pending,
            "total": total,
            "todos_state": todos_state,
            "scopes": scopes,
            "plan_text": (session.current_plan_text() or "").strip(),
            "checklists": checklists,
        }

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
            f"- **Plan mode:** {'on' if plan_mode_enabled else 'off'}\n"
            f"- **Phase:** {plan_phase}\n"
            f"- **Planning todos:** {'shown' if show_planning else 'hidden'}\n"
            f"- **Overall progress:** **{completed}/{total} completed** · **{pending} pending**"
        )
        sections.append(
            self._make_workboard_section(
                "Summary", CopyableMarkdown(summary_md), tone="summary"
            )
        )

        checklist_children: list[Widget] = []
        rendered_any_scope = False
        for scope in scopes:
            entries = todos_state.get(scope, [])
            if not isinstance(entries, list) or not entries:
                continue
            rendered_any_scope = True
            done_entries = [
                entry for entry in entries if bool(entry.get("completed", False))
            ]
            pending_entries = [
                entry for entry in entries if not bool(entry.get("completed", False))
            ]
            scope_title = (
                "Execution Checklist" if scope == "execution" else "Planning Checklist"
            )
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
                    lines.append(f"- {len(pending_entries) - 6} more pending")
            if done_entries:
                lines.extend(["", "**Done**"])
                for entry in done_entries[:3]:
                    content = str(entry.get("content", "")).strip()
                    if content:
                        lines.append(f"- [x] {content}")
                if len(done_entries) > 3:
                    lines.append(f"- {len(done_entries) - 3} more completed")
            checklist_children.append(
                self._make_workboard_section(
                    scope_title,
                    CopyableMarkdown("\n".join(lines)),
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
            plan_body = CopyableMarkdown(plan_text)
        else:
            plan_body = Static("No current plan saved.", classes="workboard-empty")
        sections.append(
            self._make_workboard_section("Implementation Plan", plan_body, tone="plan")
        )

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

    async def run_agent_message(
        self,
        message: str,
        *,
        display_message: str | None = None,
        suppress_user_echo: bool = False,
    ) -> None:
        rendered_message = display_message or message
        if not suppress_user_echo:
            await self.add_user_message(rendered_message)
            await self._broadcast_remote_state()

        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            self.post_system("Error", "Agent is not initialized", is_error=True)
            return

        session_id = self._active_session_id()
        if not session_id:
            self.post_system("Error", "No active thread.", is_error=True)
            return
        active_agent = self.agent
        run_state = self._run_state(session_id)
        self._last_rendered_plan_text = None
        run_state.turn_had_error = False
        run_state.turn_made_progress = False
        run_state.last_error_message = None
        run_state.retryable_turn_payload = None
        if not suppress_user_echo:
            run_state.failure_recovery_attempts = 0
        run_state.failure_recovery_payload = None
        run_state.auto_resume_payload = None
        attachments = list(
            getattr(active_agent.session, "pending_attachment_paths", [])
        )
        run_state.active_turn_id += 1
        turn_id = run_state.active_turn_id
        try:
            baseline_context_pct = int(
                round(
                    float(active_agent.session.get_stats().get("context_used_pct", 0.0))
                )
            )
        except Exception:
            baseline_context_pct = None
        run_state.context_meter_floor_pct = baseline_context_pct
        run_state.last_turn_payload = {
            "message": message,
            "display_message": display_message or message,
            "attachments": list(attachments),
        }
        prepared = self._prepare_attachments_for_turn(
            message=message,
            attachments=attachments,
            turn_id=turn_id,
        )
        if prepared is None:
            return
        prepared_message, user_model_content, temp_attachment_turn_id, _staged = (
            prepared
        )
        active_agent.session.pending_attachment_paths = []
        run_state.active_turn_task = asyncio.create_task(
            self._agent_turn(
                active_agent,
                prepared_message,
                session_id,
                turn_id,
                user_model_content=user_model_content,
                attachment_turn_id=temp_attachment_turn_id,
            )
        )
        run_state.is_turn_running = True
        self._set_loading_state(self._progress_state_label(), busy=True)
        self.refresh_header()
        await self._broadcast_remote_state()
        completed_normally = False

        try:
            await run_state.active_turn_task
            run_state.active_turn_task = None
            run_state.is_turn_running = False
            run_state.context_meter_floor_pct = None
            self.refresh_header()
            if (
                self._active_session_id() == session_id
                and run_state.auto_resume_payload is None
            ):
                self._set_loading_state("idle", busy=False)
            if self._active_session_id() == session_id:
                await self.auto_save()
            else:
                previous_agent = self.agent
                self.agent = active_agent
                try:
                    await self.auto_save()
                finally:
                    self.agent = previous_agent
            await self._broadcast_remote_state()
            completed_normally = not run_state.turn_had_error
        except asyncio.CancelledError:
            if self._active_session_id() == session_id:
                self.post_notice("Interrupted", "Stopped current run.")
                run_state.active_turn_task = None
                run_state.is_turn_running = False
                run_state.context_meter_floor_pct = None
                self.refresh_header()
                self._set_loading_state("idle", busy=False)
                await self.auto_save()
                await self._broadcast_remote_state()
            return
        finally:
            run_state.active_turn_task = None
            run_state.is_turn_running = False
            if run_state.context_meter_floor_pct is not None and not completed_normally:
                run_state.context_meter_floor_pct = None
            self.refresh_header()
            if (
                self._active_session_id() == session_id
                and run_state.auto_resume_payload is None
            ):
                self._set_loading_state("idle", busy=False)
            await self._broadcast_remote_state()

        if completed_normally and self._active_session_id() == session_id:
            if (
                str(self.config.model_name or "").endswith(":cloud")
                and not self._bundled_access_announced
            ):
                # self.post_notice(
                #     "Bundled Access",
                #     "You're now using bundled access.",
                # )
                self._bundled_access_announced = True
            run_state.failure_recovery_payload = None
            await self._dispatch_queued_payload_if_ready()
        elif (
            self._active_session_id() == session_id
            and run_state.failure_recovery_payload is not None
        ):
            await self._clear_inflight_turn_ui()
            await self._dispatch_queued_payload_if_ready()
        elif self._active_session_id() == session_id:
            await self._clear_inflight_turn_ui()
            self._restore_queued_payload_after_unsuccessful_turn()

    async def _agent_turn(
        self,
        agent: Agent,
        message: str,
        session_id: str,
        turn_id: int,
        *,
        user_model_content: str | list[dict] | None = None,
        attachment_turn_id: str | None = None,
    ) -> None:
        try:
            async for event in agent.run(
                message, user_model_content=user_model_content
            ):
                await self.handle_agent_event(event, session_id, turn_id)
        finally:
            if attachment_turn_id:
                AttachmentManager(self.config.cwd).cleanup_turn(attachment_turn_id)

    async def handle_agent_event(
        self, event: AgentEvent, session_id: str, turn_id: int
    ) -> None:
        run_state = self._run_state(session_id)
        if turn_id != run_state.active_turn_id:
            return
        await self._broadcast_remote_agent_event(session_id, turn_id, event)
        if session_id != self._active_session_id():
            if event.type == AgentEventType.AGENT_ERROR:
                run_state.turn_had_error = True
            return
        plan_only_phase = self._is_plan_only_phase()
        suppressed_tools = {"memory", "plan_question"}

        if event.type == AgentEventType.AGENT_END:
            self._cancel_activity_resume_timer()
            self._activity_version += 1
            await self._hide_activity_indicator(self._activity_version)
            await self._post_turn_change_summary()
            self.refresh_header()
            self._schedule_usage_meta_refresh_for_cloud_model()
            return

        if event.type == AgentEventType.TEXT_DELTA:
            content = event.data.get("content", "")
            if content:
                run_state.turn_made_progress = True
                self._cancel_activity_resume_timer()
                self._activity_version += 1
                await self._hide_activity_indicator(self._activity_version)
                await self.stream_assistant_delta(content)
                self._schedule_activity_indicator_resume()
            return

        if event.type == AgentEventType.TEXT_COMPLETE:
            content = event.data.get("content", "")
            is_final_text = bool(event.data.get("final", True))
            if content:
                run_state.turn_made_progress = True
            self._cancel_activity_resume_timer()
            self._activity_version += 1
            await self._hide_activity_indicator(self._activity_version)
            if self._streaming_widget is not None:
                await self.finalize_streaming_message(content)
                if (
                    content
                    and plan_only_phase
                    and self.agent
                    and self.agent.session
                    and self.agent.session.plan_phase
                    == "awaiting_implementation_confirmation"
                ):
                    self._last_rendered_plan_text = self._normalize_plan_text(content)
            elif content and not plan_only_phase:
                await self.add_assistant_message(content)
            elif (
                content
                and plan_only_phase
                and self.agent
                and self.agent.session
                and self.agent.session.plan_phase
                == "awaiting_implementation_confirmation"
            ):
                await self._render_plan_text_if_needed(content)
            if self._is_turn_running and not is_final_text:
                self._activity_version += 1
                await self._show_activity_indicator(
                    self._progress_state_label(),
                    self._activity_version,
                )
            return

        if event.type == AgentEventType.AGENT_ERROR:
            self._cancel_activity_resume_timer()
            self._activity_version += 1
            await self._hide_activity_indicator(self._activity_version)
            run_state.turn_had_error = True
            run_state.context_meter_floor_pct = None
            error_message = str(event.data.get("error", "Unknown error"))
            self._mark_retryable_turn_failure(session_id, error_message)
            should_attempt_recovery = (
                run_state.retryable_turn_payload is not None
                and run_state.turn_made_progress
                and run_state.failure_recovery_attempts < 1
            )
            if should_attempt_recovery:
                recovery_payload = self._build_followup_recovery_payload(session_id)
                if recovery_payload is not None:
                    run_state.failure_recovery_payload = recovery_payload
                    run_state.failure_recovery_attempts += 1
                    self.post_recovery_status(
                        error_message=error_message,
                        recovering=True,
                        retry_available=False,
                    )
                else:
                    self.post_system("Error", error_message, is_error=True)
            else:
                if run_state.retryable_turn_payload is not None:
                    self.post_recovery_status(
                        error_message=error_message,
                        recovering=False,
                        retry_available=True,
                    )
                else:
                    self.post_system("Error", error_message, is_error=True)
            self.refresh_header()
            self._schedule_usage_meta_refresh_for_cloud_model()
            return

        if event.type == AgentEventType.CONTEXT_COMPACTING:
            self._cancel_activity_resume_timer()
            self._activity_version += 1
            await self._hide_activity_indicator(self._activity_version)
            await self._start_live_compaction_card("Compacting context")
            return

        if event.type == AgentEventType.CONTEXT_COMPACTED:
            auto_resume_required = bool(event.data.get("auto_resume_required", False))
            run_state.context_meter_floor_pct = 100
            if auto_resume_required:
                run_state.auto_resume_payload = {
                    "message": Agent.POST_COMPACTION_CONTINUE_PROMPT,
                    "display_message": "",
                    "attachments": [],
                    "suppress_user_echo": True,
                }
            await self._finish_live_compaction_card("Context compacted.")
            self.refresh_header()
            return

        if event.type == AgentEventType.TOOL_CALL_START:
            self._cancel_activity_resume_timer()
            if self._streaming_widget is not None:
                await self.finalize_streaming_message()
            tool_name = event.data.get("name", "tool")
            arguments = event.data.get("arguments", {}) or {}
            if tool_name == "todos":
                if bool(arguments.get("_suppress_ui")):
                    self._set_loading_state(
                        self._progress_state_label(
                            tool_name=tool_name,
                            arguments=arguments,
                        ),
                        busy=True,
                    )
                    return
                if self._is_internal_todo_event(event.data.get("call_id")):
                    self._set_loading_state(
                        self._progress_state_label(
                            tool_name=tool_name,
                            arguments=arguments,
                        ),
                        busy=True,
                    )
                    return
                scope = self._resolve_todo_scope_for_event(arguments=arguments)
                if self._should_hide_todo_scope(scope):
                    self._set_loading_state(
                        self._progress_state_label(
                            tool_name=tool_name,
                            arguments=arguments,
                        ),
                        busy=True,
                    )
                    return
            if tool_name in suppressed_tools:
                self._set_loading_state(
                    self._progress_state_label(
                        tool_name=tool_name,
                        arguments=arguments,
                    ),
                    busy=True,
                )
                return
            if plan_only_phase and tool_name not in {
                "todos",
                "web_search",
                "web_fetch",
            }:
                self._set_loading_state(
                    self._progress_state_label(
                        tool_name=tool_name,
                        arguments=arguments,
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
                    arguments=arguments,
                ),
                busy=True,
            )
            await self.add_tool_call_start(
                call_id=event.data.get("call_id", ""),
                name=tool_name,
                tool_kind=tool_kind,
                arguments=arguments,
            )
            return

        if event.type == AgentEventType.TOOL_CALL_COMPLETE:
            tool_name = event.data.get("name", "tool")
            run_state.turn_made_progress = True
            error_text = str(event.data.get("error") or "")
            metadata = event.data.get("metadata")
            if (
                tool_name == "todos"
                and isinstance(metadata, dict)
                and bool(metadata.get("suppressed"))
                and bool(metadata.get("runtime_reused_checklist"))
            ):
                self._set_loading_state(
                    self._progress_state_label(
                        tool_name=tool_name,
                        metadata=metadata,
                        phase="post_tool",
                    ),
                    busy=True,
                )
                return
            if not event.data.get(
                "success", False
            ) and self._should_suppress_malformed_tool_card(tool_name, error_text):
                self._set_loading_state(
                    self._progress_state_label(
                        tool_name=tool_name,
                        metadata=event.data.get("metadata"),
                        phase="post_tool",
                    ),
                    busy=True,
                )
                return
            if tool_name == "todos":
                if self._is_internal_todo_event(event.data.get("call_id")):
                    self._set_loading_state(
                        self._progress_state_label(
                            tool_name=tool_name,
                            metadata=event.data.get("metadata"),
                            phase="post_tool",
                        ),
                        busy=True,
                    )
                    return
                scope = self._resolve_todo_scope_for_event(
                    metadata=event.data.get("metadata")
                )
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

        if event.type == AgentEventType.TOOL_CALL_PROGRESS:
            await self._update_tool_call_progress(
                call_id=event.data.get("call_id", ""),
                name=event.data.get("name", "tool"),
                output=event.data.get("output", ""),
                metadata=event.data.get("metadata"),
                exit_code=event.data.get("exit_code"),
            )
            return

        if event.type == AgentEventType.PLAN_READY:
            plan_text = event.data.get("plan_text", "")
            if isinstance(plan_text, str) and plan_text.strip():
                await self._render_plan_text_if_needed(plan_text)
            approved = await self._present_plan_ready_with_remote(
                plan_text=str(plan_text or ""),
                question_count=(
                    int(self.agent.session.plan_questions_asked)
                    if self.agent and self.agent.session
                    else 0
                ),
            )
            if approved and self.agent and self.agent.session:
                self.agent.session.seed_execution_todos_from_plan(
                    self.agent.session.pending_plan_text
                )
                self.agent.session.promote_pending_plan_to_active()
                self.agent.session.set_plan_mode(False)
                self.agent.session.set_plan_phase("executing")
                self.refresh_header()
                await self.run_agent_message(Agent.PLAN_EXECUTE_PROMPT)
            elif self.agent and self.agent.session:
                self.agent.session.set_plan_phase(
                    "awaiting_implementation_confirmation"
                )
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
            is_light=self._prefer_terminal_safe_source_rendering(),
        )
        # Capture index before add_assistant_card increments it
        msg_index = self._message_count
        await self.add_assistant_card("Changed", body, css_class="change")
        # Store state for theme re-rendering (use message index before increment as key)
        self._change_card_states[msg_index] = {
            "change_set": change_set,
            "verb": "Changed",
            "footer": "Run /undo to revert.",
            "mode": "changed",
        }
        self._append_remote_change_feed_entry(
            title="Changed",
            change_set=change_set,
            verb="Changed",
            footer="Run /undo to revert.",
            mode="changed",
        )
        if self._change_review_visible:
            await self._open_change_review_panel(
                change_set, title="Changed", mode="changed"
            )

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
        keep_button = Button(
            "Keep in Plan Mode", id="plan-ready-keep", variant="default"
        )
        implement_button = Button(
            "Implement", id="plan-ready-implement", variant="success"
        )

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
        await self._pin_activity_indicator_to_end()
        return bool(await self._plan_ready_future)

    async def _present_plan_ready_with_remote(
        self,
        *,
        plan_text: str,
        question_count: int,
    ) -> bool:
        local_task = asyncio.create_task(self._present_plan_ready_action_card())
        await asyncio.sleep(0)
        remote_task: asyncio.Task[bool | None] | None = None
        request_id = ""
        if (
            self._remote_server is not None
            and self._remote_server.is_running
            and self._remote_server.has_authenticated_clients()
            and self.agent
            and self.agent.session
        ):
            request_id = str(uuid.uuid4())
            remote_task = asyncio.create_task(
                self._remote_server.request_plan_ready(
                    serialize_plan_ready_request(
                        request_id=request_id,
                        session_id=self._active_session_id()
                        or self.agent.session.session_id,
                        plan_text=plan_text,
                        question_count=question_count,
                    )
                )
            )

        pending: set[asyncio.Task[Any]] = {local_task}
        if remote_task is not None:
            pending.add(remote_task)
        winner: asyncio.Task[Any] | None = None
        approved: bool | None = None
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                result = task.result()
                if task is remote_task and result is None:
                    continue
                winner = task
                approved = bool(result)
                break
            if winner is not None:
                break

        if approved is None:
            approved = False

        if winner is local_task and remote_task is not None and request_id:
            assert self._remote_server is not None
            await self._remote_server.resolve_plan_ready_request(request_id, approved)
            await remote_task
            await self._broadcast_remote_state()
        elif winner is remote_task:
            self._resolve_plan_ready_choice(approved)
            await local_task
            await self._broadcast_remote_state()
        return approved

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
            Static(
                f"Asking questions {self._plan_question_number}", classes="card-title"
            ),
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
        await self._pin_activity_indicator_to_end()

        if self._plan_question_option_buttons:
            self._plan_question_option_buttons[0].focus()
        elif self._plan_question_custom_input is not None:
            self._plan_question_custom_input.focus()

        return await self._plan_question_future

    async def _present_plan_question_with_remote(
        self,
        *,
        question_number: int,
        question: str,
        options: list[str],
        recommended_index: int | None,
        allow_free_text: bool,
    ) -> dict[str, Any]:
        local_task = asyncio.create_task(
            self._present_plan_question_card(
                question_number=question_number,
                question=question,
                options=options,
                recommended_index=recommended_index,
                allow_free_text=allow_free_text,
            )
        )
        await asyncio.sleep(0)
        remote_task: asyncio.Task[dict[str, Any] | None] | None = None
        request_id = ""
        if (
            self._remote_server is not None
            and self._remote_server.is_running
            and self._remote_server.has_authenticated_clients()
            and self.agent
            and self.agent.session
        ):
            request_id = str(uuid.uuid4())
            remote_task = asyncio.create_task(
                self._remote_server.request_plan_question(
                    serialize_plan_question_request(
                        request_id=request_id,
                        session_id=self._active_session_id()
                        or self.agent.session.session_id,
                        question=question,
                        options=options,
                        recommended_index=recommended_index,
                        allow_free_text=allow_free_text,
                        question_number=question_number,
                    )
                )
            )

        pending: set[asyncio.Task[Any]] = {local_task}
        if remote_task is not None:
            pending.add(remote_task)
        winner: asyncio.Task[Any] | None = None
        answer: dict[str, Any] | None = None
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                result = task.result()
                if task is remote_task and result is None:
                    continue
                winner = task
                answer = result
                break
            if winner is not None:
                break

        if not isinstance(answer, dict):
            answer = {"selected_option": "", "free_text": "", "selected_index": None}

        selected_index = answer.get("selected_index")
        if not isinstance(selected_index, int):
            selected_index = None
        selected_option = str(answer.get("selected_option") or "")
        free_text = str(answer.get("free_text") or "")

        if winner is local_task and remote_task is not None and request_id:
            assert self._remote_server is not None
            await self._remote_server.resolve_plan_question_request(request_id, answer)
            await remote_task
            await self._broadcast_remote_state()
        elif winner is remote_task:
            await self._resolve_plan_question_choice(
                selected_index=selected_index,
                selected_option=selected_option,
                free_text=free_text,
            )
            await local_task
            await self._broadcast_remote_state()
        return {
            "selected_option": selected_option,
            "free_text": free_text.strip(),
            "selected_index": selected_index,
        }

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

        if isinstance(selected_index, int) and 0 <= selected_index < len(
            self._plan_question_option_buttons
        ):
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
        code_theme = self._syntax_theme_name()
        markdown = RichMarkdown(
            self._streaming_buffer,
            code_theme=code_theme,
        )
        self._streaming_widget.update(markdown)
        await self._pin_activity_indicator_to_end()

    async def finalize_streaming_message(self, final_text: str | None = None) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        rendered_text = final_text if final_text is not None else self._streaming_buffer
        if self._streaming_widget is not None and rendered_text:
            # Replace the streaming Static with a CopyableMarkdown widget
            # so code blocks have copy buttons
            old_widget = self._streaming_widget
            new_widget = Container(
                CopyableMarkdown(rendered_text),
                classes="block assistant",
            )
            try:
                await old_widget.remove()
                await conversation.mount(new_widget)
            except Exception:
                # Fallback: just update the existing widget with RichMarkdown
                code_theme = self._syntax_theme_name()
                old_widget.update(
                    RichMarkdown(
                        rendered_text,
                        code_theme=code_theme,
                    )
                )
            await self._pin_activity_indicator_to_end()
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

        running_widgets = [
            card for card in self._tool_widgets.values() if card.has_class("running")
        ]
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
                self._tool_name_by_call_id.pop(call_id, None)
                self._tool_completion_state.pop(call_id, None)

        self._refresh_empty_state()

    def _render_user_message(self, message: str) -> Text | RichMarkdown:
        styles = self._render_styles()
        refs = extract_inline_attachment_refs(message)
        if not refs:
            return RichMarkdown(message)

        text = Text(style=self._style("fg"))
        cursor = 0
        for ref in refs:
            if ref.start > cursor:
                text.append(message[cursor : ref.start], style=self._style("fg"))
            basename = Path(ref.value).name or ref.value
            text.append(basename, style=f"bold {self._style('primary')}")
            if ref.trailing:
                text.append(ref.trailing, style=self._style("fg"))
            cursor = ref.end
        if cursor < len(message):
            text.append(message[cursor:], style=self._style("fg"))
        return text

    def _user_bubble_width(self, message: str, max_width: int = 92) -> int:
        refs = extract_inline_attachment_refs(message)
        if refs:
            parts: list[str] = []
            cursor = 0
            for ref in refs:
                if ref.start > cursor:
                    parts.append(message[cursor : ref.start])
                parts.append(Path(ref.value).name or ref.value)
                if ref.trailing:
                    parts.append(ref.trailing)
                cursor = ref.end
            if cursor < len(message):
                parts.append(message[cursor:])
            display_text = "".join(parts)
        else:
            display_text = message

        lines = [line.strip() for line in display_text.splitlines()] or [
            display_text.strip()
        ]
        content_width = (
            max(cell_len(line) for line in lines if line) if any(lines) else 0
        )
        return max(12, min(max_width, content_width + 2))

    async def add_user_message(self, message: str) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        bubble = Static(
            self._render_user_message(message),
            classes="chat-user-bubble",
        )
        bubble.styles.width = self._user_bubble_width(message)
        row = Container(bubble, classes="chat-user-row")
        await conversation.mount(row)
        self._message_count += 1
        self._refresh_empty_state()
        await self._pin_activity_indicator_to_end()

    async def add_assistant_message(self, message: str) -> None:
        await self.add_assistant_card(
            "iTE", CopyableMarkdown(message), css_class="assistant"
        )

    def post_system(self, title: str, message: str, is_error: bool = False) -> None:
        css_class = "system error" if is_error else "system"
        self.run_worker(
            self.add_assistant_card(title, message, css_class=css_class),
            exclusive=False,
        )

    def post_remote_bridge(
        self,
        *,
        runtime_name: str,
        exposure_mode: str,
        host: str,
        port: int,
        pair_code: str,
        fingerprint: str,
        connect_uri: str,
        authenticated_clients: int | None,
        trusted_devices: int | None,
        intro: str,
        footer: str,
    ) -> None:
        self.run_worker(
            self.add_assistant_card(
                "Remote",
                RemoteBridgeCard(
                    intro=intro,
                    runtime_name=runtime_name,
                    exposure_mode=exposure_mode,
                    host=host,
                    port=port,
                    pair_code=pair_code,
                    fingerprint=fingerprint,
                    connect_uri=connect_uri,
                    authenticated_clients=authenticated_clients,
                    trusted_devices=trusted_devices,
                    footer=footer,
                    classes="remote-bridge-card",
                ),
                css_class="system",
            ),
            exclusive=False,
        )

    def post_notice(self, title: str, message: str, *, timeout: float = 3) -> None:
        self.notify(message, title=title, timeout=timeout)

    def post_recovery_status(
        self,
        *,
        error_message: str,
        recovering: bool,
        retry_available: bool,
    ) -> None:
        styles = self._render_styles()
        title = "Recovering" if recovering else "Inference Interrupted"
        body = Text()
        if recovering:
            body.append(
                "Bundled inference stalled after partial progress. Continuing automatically.\n\n",
                style=self._style("fg"),
            )
        else:
            body.append(
                "Bundled inference is temporarily unavailable.\n\n",
                style=self._style("fg"),
            )

        if error_message:
            body.append("Details\n", style=f"bold {self._style('error')}")
            body.append(f"{error_message}\n", style=self._style("error"))

        body.append("\nAction\n", style=f"bold {self._style('primary')}")
        if recovering:
            body.append(
                "Waiting for one automatic continuation attempt.",
                style=self._style("success"),
            )
        elif retry_available:
            body.append(
                "Run /retry to resend the last turn, or switch models if the provider stays unstable.",
                style=self._style("fg"),
            )
        else:
            body.append(
                "Try again in a moment, or switch models if the provider stays unstable.",
                style=self._style("fg"),
            )

        self.run_worker(
            self.add_assistant_card(title, body, css_class="recovery"),
            exclusive=False,
        )

    def post_command_result(self, command: str, message: str) -> None:
        self.run_worker(
            self.add_assistant_card(
                self._build_command_title_widget(command),
                self._build_command_result_renderable(message),
                css_class="command",
            ),
            exclusive=False,
        )

    def post_streaming_command_result(self, command: str, message: str) -> None:
        self.run_worker(
            self._append_command_result_card(command, message),
            exclusive=False,
        )

    def _handle_streaming_command_line(
        self,
        command: str,
        line: str,
        *,
        command_feed_id: str | None,
    ) -> None:
        self.post_streaming_command_result(command, line)
        if command_feed_id is not None:
            self._append_remote_command_feed_output(command_feed_id, line)

    def _build_remote_command_feed_metadata(
        self,
        command: str,
        args: list[str],
        rendered: str,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "kind": "generic",
            "command_name": command,
            "args": list(args),
        }
        if not self.agent or not self.agent.session:
            return metadata

        session = self.agent.session
        if command == "/tools":
            tools = session.tool_registry.get_tools()
            sections: dict[str, list[dict[str, Any]]] = {}
            order = [
                "Built-in",
                "Verification",
                "Subagent Runtime",
                "Subagent Specialists",
                "Custom",
                "MCP",
            ]
            for section_name in order:
                section_tools = [
                    tool
                    for tool in tools
                    if self._remote_tool_section_name(tool) == section_name
                ]
                if not section_tools:
                    continue
                sections[section_name] = [
                    self._serialize_remote_tool(tool) for tool in section_tools
                ]
            metadata.update(
                {
                    "kind": "tools",
                    "summary": {
                        "total": len(tools),
                        "built_in": len(sections.get("Built-in", [])),
                        "verification": len(sections.get("Verification", [])),
                        "runtime": len(sections.get("Subagent Runtime", [])),
                        "specialists": len(
                            sections.get("Subagent Specialists", [])
                        ),
                        "custom": len(sections.get("Custom", [])),
                        "mcp": len(sections.get("MCP", [])),
                    },
                    "sections": [
                        {
                            "title": section_name,
                            "count": len(items),
                            "items": items,
                        }
                        for section_name, items in sections.items()
                    ],
                }
            )
            return metadata

        if command == "/mcp" and (not args or args[0].lower() == "list"):
            servers = session.mcp_manager.get_all_servers()
            metadata.update(
                {
                    "kind": "mcp",
                    "summary": {
                        "total": len(servers),
                        "connected": sum(
                            1
                            for server in servers
                            if str(server.get("status", "")) == "connected"
                        ),
                        "ready": sum(
                            1
                            for server in servers
                            if str(server.get("status", "")) == "ready"
                        ),
                        "failed": sum(
                            1
                            for server in servers
                            if str(server.get("status", "")) == "error"
                        ),
                    },
                    "servers": [
                        {
                            "name": str(server.get("name") or ""),
                            "status": str(server.get("status") or ""),
                            "tools": int(server.get("tools") or 0),
                            "transport": str(server.get("transport") or ""),
                            "auto_connect": bool(server.get("auto_connect")),
                            "detail": str(
                                server.get("detail") or server.get("last_error") or ""
                            ),
                            "auth_phase": str(server.get("auth_phase") or ""),
                            "url": str(server.get("url") or ""),
                            "missing_env": [
                                str(item)
                                for item in list(server.get("missing_env") or [])
                                if str(item).strip()
                            ],
                        }
                        for server in servers
                    ],
                }
            )
            return metadata

        if command == "/stats":
            stats = session.get_stats()
            metadata.update(
                {
                    "kind": "stats",
                    "stats": {
                        "session_id": str(stats.get("session_id") or ""),
                        "created_at": str(stats.get("created_at") or ""),
                        "turn_count": int(stats.get("turn_count") or 0),
                        "message_count": int(stats.get("message_count") or 0),
                        "context_window": int(stats.get("context_window") or 0),
                        "latest_tokens": int(stats.get("latest_tokens") or 0),
                        "latest_cached_tokens": int(
                            stats.get("latest_cached_tokens") or 0
                        ),
                        "context_used_pct": float(
                            stats.get("context_used_pct") or 0.0
                        ),
                        "context_left_pct": float(
                            stats.get("context_left_pct") or 0.0
                        ),
                        "compaction_count": int(stats.get("compaction_count") or 0),
                        "last_compacted_at": str(
                            stats.get("last_compacted_at") or ""
                        ),
                        "pruned_tool_msgs": int(
                            stats.get("pruned_tool_msgs") or 0
                        ),
                        "plan_mode_enabled": bool(stats.get("plan_mode_enabled")),
                        "plan_phase": str(stats.get("plan_phase") or "idle"),
                        "plan_questions_asked": int(
                            stats.get("plan_questions_asked") or 0
                        ),
                        "plan_target_questions": int(
                            stats.get("plan_target_questions") or 0
                        ),
                        "pending_plan_available": bool(
                            stats.get("pending_plan_available")
                        ),
                        "active_plan_available": bool(
                            stats.get("active_plan_available")
                        ),
                        "pending_attachments": int(
                            stats.get("pending_attachments") or 0
                        ),
                        "tools_enabled": int(stats.get("tools_enabled") or 0),
                        "mcp_servers": int(stats.get("mcp_servers") or 0),
                        "mcp_tools": int(stats.get("mcp_tools") or 0),
                        "mcp_failed_servers": int(
                            stats.get("mcp_failed_servers") or 0
                        ),
                        "tool_discovery_errors": int(
                            stats.get("tool_discovery_errors") or 0
                        ),
                        "available_skills": int(
                            stats.get("available_skills") or 0
                        ),
                        "active_skills": int(stats.get("active_skills") or 0),
                        "token_usage": self._serialize_remote_token_usage(
                            stats.get("token_usage")
                        ),
                    },
                }
            )
            return metadata

        if command == "/workboard":
            workboard = self._serialize_remote_workboard_payload(session)
            metadata.update(
                {
                    "kind": "workboard",
                    "summary": {
                        "plan_mode_enabled": bool(workboard["plan_mode_enabled"]),
                        "plan_phase": str(workboard["plan_phase"]),
                        "show_planning": bool(workboard["show_planning"]),
                        "completed": int(workboard["completed"]),
                        "pending": int(workboard["pending"]),
                        "total": int(workboard["total"]),
                    },
                    "checklists": list(workboard["checklists"]),
                    "plan_text": str(workboard["plan_text"]),
                }
            )
            return metadata

        if command == "/skills":
            active_ids = {
                skill.identifier for skill in session.get_active_skills()
            }
            action = args[0].lower() if args else "list"
            if action in {"list", "ls"}:
                skills = session.skill_manager.list_skills()
                blocked_count = sum(
                    1
                    for skill in skills
                    if skill.identifier not in active_ids
                    and skill.requires_trust
                    and not skill.trusted
                )
                metadata.update(
                    {
                        "kind": "skills_overview",
                        "summary": {
                            "installed": len(skills),
                            "active": len(active_ids),
                            "ready": max(
                                0, len(skills) - len(active_ids) - blocked_count
                            ),
                            "blocked": blocked_count,
                        },
                        "items": [
                            self._serialize_remote_skill(skill, active_ids)
                            for skill in skills
                        ],
                    }
                )
                return metadata
            if action in {"show", "inspect"}:
                references = [item for item in args[1:] if not item.startswith("--")]
                reference = " ".join(references).strip()
                skill = session.resolve_skill(reference)
                if skill is not None:
                    metadata.update(
                        {
                            "kind": "skills_detail",
                            "skill": self._serialize_remote_skill(skill, active_ids),
                            "instructions": skill.instructions,
                        }
                    )
                return metadata

            metadata.update(
                {
                    "kind": "skills_feedback",
                    "title": _skills_action_title(action),
                    "message": rendered,
                    "active_count": len(active_ids),
                    "available_count": len(session.skill_manager.list_skills()),
                }
            )
        return metadata

    def _serialize_remote_skill(
        self,
        skill: SkillDefinition,
        active_ids: set[str],
    ) -> dict[str, Any]:
        return {
            "identifier": skill.identifier,
            "name": skill.name,
            "description": skill.description,
            "state": skill_state(skill, active_ids),
            "source": self._format_remote_skill_source_label(
                skill.source,
                author=skill.author,
            ),
            "user_invocable": bool(skill.user_invocable),
            "reference_count": len(skill.reference_files),
            "tags": list(skill.tags),
            "version": skill.version or "",
            "author": skill.author or "",
            "homepage": skill.homepage or "",
            "aliases": list(skill.aliases),
        }

    @staticmethod
    def _format_remote_skill_source_label(
        source: str,
        *,
        author: str | None = None,
    ) -> str:
        if source == "shared-project" and str(author or "").strip().lower() == "ite":
            return "ite bundled"
        label = str(source or "").strip().replace("compat-", "").replace("-", " ")
        return label or "skill root"

    def _serialize_remote_tool(self, tool: Tool) -> dict[str, Any]:
        metadata = tool.get_metadata({})
        access = "write" if metadata.mutating else "read"
        risk = {
            ToolRiskLevel.LOW: "low",
            ToolRiskLevel.MEDIUM: "med",
            ToolRiskLevel.HIGH: "high",
        }.get(metadata.risk_level, "med")
        name = tool.name
        server_name = ""
        if isinstance(tool, MCPTool):
            server_name, _, suffix = name.partition("__")
            name = suffix or name
        return {
            "name": name,
            "full_name": tool.name,
            "description": getattr(tool, "description", "") or "",
            "access": access,
            "risk": risk,
            "section": self._remote_tool_section_name(tool),
            "server_name": server_name,
        }

    @staticmethod
    def _serialize_remote_token_usage(value: object) -> dict[str, int]:
        return {
            "prompt_tokens": int(getattr(value, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(value, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(value, "total_tokens", 0) or 0),
            "cached_tokens": int(getattr(value, "cached_tokens", 0) or 0),
        }

    @staticmethod
    def _remote_tool_section_name(tool: Tool) -> str:
        if isinstance(tool, MCPTool):
            return "MCP"
        if isinstance(tool, SubagentTool):
            return "Subagent Specialists"
        module_name = tool.__class__.__module__
        if module_name.startswith("ite.tools.builtin.subagent_runtime_tools"):
            return "Subagent Runtime"
        if tool.name in {"run_tests", "run_linter", "run_typecheck"}:
            return "Verification"
        if module_name.startswith("ite.tools.builtin."):
            return "Built-in"
        if module_name.startswith("discovered_tool_") or not module_name.startswith(
            "ite."
        ):
            return "Custom"
        return "Built-in"

    def _start_remote_command_feed_entry(self, command_line: str) -> str:
        self._remote_command_seq += 1
        command_id = f"cmd_{self._remote_command_seq}"
        session_id = self._active_session_id() or ""
        parts = command_line.split()
        command_name = parts[0].lower() if parts else ""
        self._remote_command_feed.append(
            {
                "id": command_id,
                "session_id": session_id,
                "command": str(command_line).strip(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "running",
                "output": "",
                "metadata": {
                    "kind": "generic",
                    "command_name": command_name,
                    "args": parts[1:],
                },
            }
        )
        self._remote_command_feed = self._remote_command_feed[-30:]
        self.run_worker(self._broadcast_remote_state(), exclusive=False)
        return command_id

    def _append_remote_command_feed_output(self, command_id: str, line: str) -> None:
        text = str(line or "").rstrip()
        for entry in self._remote_command_feed:
            if entry.get("id") != command_id:
                continue
            existing = str(entry.get("output") or "")
            entry["output"] = (
                f"{existing}\n{text}".strip() if existing and text else existing or text
            )
            break
        self.run_worker(self._broadcast_remote_state(), exclusive=False)

    def _finish_remote_command_feed_entry(
        self,
        command_id: str,
        *,
        status: str,
        output: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        for entry in self._remote_command_feed:
            if entry.get("id") != command_id:
                continue
            entry["status"] = status
            final_output = str(output or "").strip()
            if final_output:
                entry["output"] = final_output
            if metadata is not None:
                entry["metadata"] = json_safe(metadata)
            break
        self.run_worker(self._broadcast_remote_state(), exclusive=False)

    def _append_remote_change_feed_entry(
        self,
        *,
        title: str,
        change_set: Any,
        verb: str,
        footer: str,
        mode: str,
    ) -> None:
        self._remote_change_seq += 1
        session_id = self._active_session_id() or ""
        payload = build_change_card_payload(
            change_set,
            cwd=self.config.cwd,
            title=title,
            verb=verb,
            footer=footer,
            mode=mode,
        )
        self._remote_change_feed.append(
            {
                "id": f"chg_{self._remote_change_seq}",
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **payload,
            }
        )
        self._remote_change_feed = self._remote_change_feed[-30:]
        self.run_worker(self._broadcast_remote_state(), exclusive=False)

    async def start_streaming_command_result(
        self, command: str, pending_text: str | None = None
    ) -> None:
        async with self._streaming_cards_lock:
            existing = self._streaming_command_cards.get(command)
            if existing is not None:
                (
                    card,
                    body_widget,
                    scroll_widget,
                    lines,
                    _old_pending_active,
                    _old_pending,
                ) = existing
                self._streaming_command_cards[command] = (
                    card,
                    body_widget,
                    scroll_widget,
                    lines,
                    True,
                    pending_text,
                )
                body_widget.update(
                    self._build_streaming_command_renderable(
                        lines,
                        pending_active=True,
                        pending_text=pending_text,
                        spinner_index=self._top_spinner_index,
                    )
                )
                await self._pin_activity_indicator_to_end()
                return

            body_static = Static(classes="card-body command-body")
            body_static.update(
                self._build_streaming_command_renderable(
                    [],
                    pending_active=True,
                    pending_text=pending_text,
                    spinner_index=self._top_spinner_index,
                )
            )
            body_widget = VerticalScroll(body_static, classes="command-card-scroll")
            card = Container(
                self._build_command_title_widget(command),
                body_widget,
                classes="block command",
            )
            conversation = self.query_one("#conversation", VerticalScroll)
            await conversation.mount(card)
            self._streaming_command_cards[command] = (
                card,
                body_static,  # Store the Static widget, not the VerticalScroll
                body_widget,  # Also store the VerticalScroll for auto-scrolling
                [],
                True,
                pending_text,
            )
        self._message_count += 1
        self._refresh_empty_state()
        await self._pin_activity_indicator_to_end()

    def post_plan_note(self, title: str, markdown_text: str) -> None:
        self.run_worker(
            self.add_assistant_card(
                title, CopyableMarkdown(markdown_text), css_class="plan"
            ),
            exclusive=False,
        )

    def post_attachment_note(self, message: str) -> None:
        styles = self._render_styles()
        self.run_worker(
            self.add_assistant_card(
                "Attachments",
                Text(message, style=self._style("fg")),
                css_class="attachment",
            ),
            exclusive=False,
        )

    async def add_assistant_card(
        self,
        title: Any,
        body: Any,
        css_class: str = "assistant",
        *,
        extra_classes: str = "",
        _track_state: dict[str, Any] | None = None,
    ) -> None:
        """Add an assistant card to the conversation. If _track_state is provided, the card
        can be re-rendered when theme changes."""
        conversation = self.query_one("#conversation", VerticalScroll)

        if isinstance(title, Widget):
            title_widget = title
            title_widget.add_class("card-title")
            title_widget.add_class(f"{css_class}-title")
        else:
            title_widget = Static(title, classes=f"card-title {css_class}-title")

        if isinstance(body, Widget):
            body_widget = body
            body_widget.add_class("card-body")
            body_widget.add_class(f"{css_class}-body")
        else:
            body_widget = Static(classes=f"card-body {css_class}-body")
            body_widget.update(body if not isinstance(body, str) else str(body))

        card = Container(
            title_widget,
            body_widget,
            classes=" ".join(
                item for item in ("block", css_class, extra_classes.strip()) if item
            ),
        )

        # Track card for theme re-rendering if state provided
        if _track_state is not None:
            card_id = f"{css_class}_{id(card)}_{self._message_count}"
            _track_state["id"] = card_id
            _track_state["css_class"] = css_class
            self._assistant_card_rich_states[card_id] = _track_state
            card.set_reactive("data-card-id", card_id)

        await conversation.mount(card)
        self._message_count += 1
        self._refresh_empty_state()
        await self._pin_activity_indicator_to_end()

    def start_streaming_command_result_update_pending(
        self, command: str, pending_text: str | None = None
    ) -> None:
        """Update just the pending text of an existing streaming card (clear lines)."""
        self.run_worker(
            self._update_streaming_command_pending(command, pending_text),
            exclusive=False,
        )

    async def _update_streaming_command_pending(
        self, command: str, pending_text: str | None = None
    ) -> None:
        """Update streaming card to show only pending text with spinner (like tool calls do)."""
        async with self._streaming_cards_lock:
            existing = self._streaming_command_cards.get(command)
            if existing is not None:
                (
                    card,
                    body_widget,
                    scroll_widget,
                    _lines,
                    _pending_active,
                    _old_pending,
                ) = existing
                # Clear lines and set new pending text so spinner shows with pending_text
                self._streaming_command_cards[command] = (
                    card,
                    body_widget,
                    scroll_widget,
                    [],  # Clear lines - this causes pending_text to show
                    True,
                    pending_text,
                )
                body_widget.update(
                    self._build_streaming_command_renderable(
                        [],
                        pending_active=True,
                        pending_text=pending_text,
                        spinner_index=self._top_spinner_index,
                    )
                )
                await self._pin_activity_indicator_to_end()
                return
            else:
                # Fall through to create new card outside the lock to avoid deadlock
                pass
        # Create new if doesn't exist (outside the lock)
        await self.start_streaming_command_result(command, pending_text=pending_text)

    async def _commit_and_update_streaming_pending(
        self, command: str, pending_text: str | None = None
    ) -> None:
        """Commit current pending as a completed line, start new pending step with spinner."""
        async with self._streaming_cards_lock:
            existing = self._streaming_command_cards.get(command)
            if existing is not None:
                (
                    card,
                    body_widget,
                    scroll_widget,
                    lines,
                    _pending_active,
                    old_pending,
                ) = existing
                # Commit the old pending as a completed line (with checkmark)
                if old_pending:
                    lines.append(f"✓ {old_pending}")
                # Start new pending
                self._streaming_command_cards[command] = (
                    card,
                    body_widget,
                    scroll_widget,
                    lines,
                    True,
                    pending_text,
                )
                body_widget.update(
                    self._build_streaming_command_renderable(
                        lines,
                        pending_active=True,
                        pending_text=pending_text,
                        spinner_index=self._top_spinner_index,
                    )
                )
                await self._pin_activity_indicator_to_end()
            else:
                # Fall through to create new card outside the lock
                pass
        # Create new if doesn't exist (outside the lock)
        await self.start_streaming_command_result(command, pending_text=pending_text)

    async def _append_streaming_content(self, command: str, chunk: str) -> None:
        """Append streaming content to the card body (for live LLM tokens)."""
        # Accumulate content in a separate buffer keyed by command
        attr_name = f"_streaming_content_buffer_{command.replace('/', '_')}"
        if not hasattr(self, attr_name):
            setattr(self, attr_name, [])
        buffer: list[str] = getattr(self, attr_name)
        buffer.append(chunk)

        async with self._streaming_cards_lock:
            existing = self._streaming_command_cards.get(command)
            if existing is None:
                return
            card, body_widget, scroll_widget, lines, _pending_active, pending_text = (
                existing
            )
            # Combine accumulated content as the last line
            content = "".join(buffer)
            # Split into lines, keep last partial line as streaming
            content_lines = content.split("\n")
            # Build up lines list: previous committed lines + current streaming lines
            if len(content_lines) > 1:
                # Commit completed lines (all but last)
                lines.extend(content_lines[:-1])
                # Keep last partial in buffer
                buffer[:] = [content_lines[-1]]
            # Update display with accumulated lines
            self._streaming_command_cards[command] = (
                card,
                body_widget,
                scroll_widget,
                lines,
                True,  # Still pending
                pending_text,
            )
            # Build renderable showing lines + streaming buffer
            display_lines = lines.copy()
            if buffer and buffer[0]:
                display_lines.append(buffer[0])  # Current streaming line
            body_widget.update(
                self._build_streaming_command_renderable(
                    display_lines,
                    pending_active=True,
                    pending_text=pending_text,
                    spinner_index=self._top_spinner_index,
                )
            )
        # Auto-scroll to follow the stream
        await self._scroll_streaming_card_to_end(scroll_widget)
        await self._pin_activity_indicator_to_end()

    async def _scroll_streaming_card_to_end(
        self, scroll_widget: VerticalScroll
    ) -> None:
        """Auto-scroll the streaming card to show latest content."""
        try:
            if scroll_widget.is_mounted:
                scroll_widget.scroll_end(animate=False)
        except Exception:
            pass

    async def _replace_last_command_result_line(
        self, command: str, message: str
    ) -> None:
        """Replace the most recent line in the streaming command card."""
        text = str(message).strip()
        if not text:
            return

        existing = self._streaming_command_cards.get(command)
        if existing is None:
            # Create new streaming card with this message as pending text
            await self.start_streaming_command_result(command, pending_text=text)
            return

        card, body_widget, scroll_widget, lines, _pending_active, _pending_text = (
            existing
        )
        if lines:
            # Replace the last line
            lines[-1] = text
        else:
            lines.append(text)
        if self._looks_like_command_error(text):
            card.add_class("command-error")
        body_widget.update(
            self._build_streaming_command_renderable(
                lines,
                pending_active=True,
                pending_text=None,  # No pending text, all lines shown
                spinner_index=self._top_spinner_index,
            )
        )
        await self._pin_activity_indicator_to_end()

    async def _append_command_result_card(self, command: str, message: str) -> None:
        text = str(message).strip()
        if not text:
            return

        existing = self._streaming_command_cards.get(command)
        if existing is None:
            await self.start_streaming_command_result(command, "")
            existing = self._streaming_command_cards.get(command)
            if existing is None:
                return

        card, body_widget, scroll_widget, lines, _pending_active, pending_text = (
            existing
        )
        lines.append(text)
        if self._looks_like_command_error(text):
            card.add_class("command-error")
        body_widget.update(
            self._build_streaming_command_renderable(
                lines,
                pending_active=True,
                pending_text=pending_text,
                spinner_index=self._top_spinner_index,
            )
        )
        await self._pin_activity_indicator_to_end()

    def finalize_streaming_command_result(self, command: str) -> None:
        existing = self._streaming_command_cards.pop(command, None)
        if existing is None:
            return
        card, body_widget, scroll_widget, lines, _pending_active, _pending_text = (
            existing
        )
        if any(self._looks_like_command_error(line) for line in lines):
            card.add_class("command-error")
        body_widget.update(
            self._build_streaming_command_renderable(
                lines,
                pending_active=False,
                pending_text=None,
            )
        )

    def _build_command_title_widget(self, command: str) -> Widget:
        return Horizontal(
            Static("command", classes="command-kicker"),
            Static(command, classes="command-name"),
            classes="command-title-row",
        )

    def _build_command_result_renderable(self, message: str) -> Group:
        styles = self._render_styles()
        lines = [line.rstrip() for line in str(message or "").strip().splitlines()]
        if not lines:
            return Group()
        if len(lines) == 1:
            return Group(Text(lines[0], style=self._style("fg")))
        renderables: list[Text] = []
        for index, line in enumerate(lines):
            if not line.strip():
                renderables.append(Text(""))
                continue
            style = self._style("fg") if index == 0 else self._style("secondary")
            if self._is_box_drawing_line(line):
                style = self._style("muted")
            renderables.append(Text(line, style=style))
        return Group(*renderables)

    def _build_streaming_command_renderable(
        self,
        lines: list[str],
        *,
        pending_active: bool,
        pending_text: str | None,
        spinner_index: int = 0,
    ) -> Group:
        styles = self._render_styles()
        blocks: list[Any] = []
        show_pending_row = pending_active and not lines
        if show_pending_row:
            status = Text()
            status.append(
                f"{self._top_spinner_frames[spinner_index % len(self._top_spinner_frames)]} ",
                style=f"bold {self._style('primary')}",
            )
            if pending_text:
                status.append(pending_text, style=self._style("muted"))
            blocks.append(status)
        if lines:
            if pending_active:
                # All lines except last are completed, last has spinner
                if len(lines) > 1:
                    blocks.extend(
                        self._build_command_result_renderable(
                            "\n".join(lines[:-1])
                        ).renderables
                    )
                # Last line gets the spinner (content being streamed)
                last_line = Text()
                last_line.append(
                    f"{self._top_spinner_frames[spinner_index % len(self._top_spinner_frames)]} ",
                    style=f"bold {self._style('primary')}",
                )
                last_line.append(lines[-1], style=self._style("fg"))
                blocks.append(last_line)
            else:
                blocks.extend(
                    self._build_command_result_renderable("\n".join(lines)).renderables
                )
        return Group(*blocks)

    @staticmethod
    def _looks_like_command_error(text: str) -> bool:
        lowered = str(text or "").strip().lower()
        return (
            lowered.startswith("failed ")
            or lowered.startswith("error ")
            or " error " in lowered
        )

    def _post_native_command_result(self, command: str, args: list[str]) -> bool:
        if not self.agent or not self.agent.session:
            return False

        session = self.agent.session
        body: Any | None = None
        if command == "/tools":
            body = build_tools_command_renderable(session.tool_registry.get_tools())
        elif command == "/stats":
            body = build_stats_command_renderable(
                session.get_stats(),
                styles=self._render_styles(),
            )
        elif command == "/workboard":
            body = build_workboard_command_renderable(
                session,
                styles=self._render_styles(),
            )
        elif command == "/mcp" and (not args or args[0].lower() == "list"):
            body = build_mcp_command_renderable(session.mcp_manager.get_all_servers())
        elif command == "/memory":
            manager = MemoryManager(self.config.cwd, session_id=session.session_id)
            if args and args[0].lower() == "prompt":
                query = " ".join(args[1:]).strip()
                if query:
                    body = build_memory_prompt_command_renderable(
                        query,
                        manager.debug_prompt_memory(query),
                    )
            else:
                body = build_memory_command_renderable(
                    session_id=session.session_id,
                    workspace=str(self.config.cwd),
                    controls=manager.load_active_controls(),
                    long_term=manager.list_entries("long_term"),
                    semantic=manager.list_entries("semantic"),
                    short_term=manager.list_entries("short_term"),
                    episodic=manager.list_episodes()[-5:],
                )

        if body is None:
            return False

        self.run_worker(
            self.add_assistant_card(
                self._build_command_title_widget(command),
                body,
                css_class="command",
                extra_classes="stats" if command == "/stats" else "",
            ),
            exclusive=False,
        )
        return True

    @staticmethod
    def _is_box_drawing_line(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        box_chars = set("│┃─━┌┐└┘├┤┬┴┼╭╮╯╰╞╡╤╧╪═║╔╗╚╝╠╣╦╩╬╭╮╰╯┏┓┗┛")
        content_chars = {ch for ch in stripped if not ch.isspace()}
        return bool(content_chars) and content_chars.issubset(box_chars)

    def _post_skills_command_result(self, args: list[str], rendered: str) -> bool:
        if not self.agent or not self.agent.session:
            return False

        session = self.agent.session
        active_ids = {skill.identifier for skill in session.get_active_skills()}
        action = args[0].lower() if args else "list"
        title = "/skills"
        body: Any

        if not args or action in {"list", "ls"}:
            body = build_skills_overview_renderable(
                session.skill_manager.list_skills(),
                active_ids,
                styles=self._render_styles(),
            )
        elif action in {"show", "inspect"}:
            references = [item for item in args[1:] if not item.startswith("--")]
            reference = " ".join(references).strip()
            skill = session.resolve_skill(reference)
            if skill is None:
                self.post_command_result("/skills", rendered)
                return True
            title = f"/skills show {skill.identifier}"
            body = build_skill_detail_renderable(
                skill, active_ids, styles=self._render_styles()
            )
        else:
            body = build_skill_feedback_renderable(
                title=_skills_action_title(action),
                message=rendered,
                active_count=len(active_ids),
                available_count=len(session.skill_manager.list_skills()),
                styles=self._render_styles(),
            )
        self.run_worker(
            self.add_assistant_card(title, body, css_class="skills"),
            exclusive=False,
        )
        return True

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

    @staticmethod
    def _is_session_shell_tool(name: str) -> bool:
        return name in {"shell_start", "shell_send", "shell_poll", "shell_stop"}

    def _shell_session_id_for_tool(
        self,
        *,
        name: str,
        arguments: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        args = arguments or {}
        md = metadata or {}
        if name not in {"shell_send", "shell_poll", "shell_stop"}:
            return None
        value = args.get("session_id") or md.get("session_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _shell_status_suffix(self) -> str:
        return self._activity_suffix_frames[
            self._activity_suffix_index % len(self._activity_suffix_frames)
        ]

    @staticmethod
    def _shell_card_icon_and_style(
        metadata: dict[str, Any] | None,
        *,
        success: bool,
    ) -> tuple[str, str]:
        if not success:
            return "❌", "bold #ffb0b0"
        state = shell_session_state(metadata)
        if state == "command_running":
            return "⌛", "bold #b7c8e1"
        if state == "idle":
            return "💤", "bold #8c93a1"
        if state == "stopped":
            return "⏹", "bold #8c93a1"
        if state == "exited":
            return "▫️", "bold #dfe4ea"
        return "▫️", "bold #dfe4ea"

    def _tool_completion_icon_and_style(
        self,
        name: str,
        *,
        success: bool,
        policy_redirect: bool,
        recoverable: bool,
    ) -> tuple[str, str]:
        """Return icon and Rich style for tool completion state."""
        if policy_redirect:
            return "↪", f"bold {self._style('primary')}"
        if recoverable and not success:
            return "↺", f"bold {self._style('warning')}"
        if not success:
            return "❌", f"bold {self._style('error')}"

        icon_by_tool = {
            "read_file": "📖",
            "read_json": "🧾",
            "read_toml": "📘",
            "read_yaml": "📗",
            "read_env": "🔐",
            "write_file": "💾",
            "edit": "✏️",
            "edit_json": "🛠️",
            "write_toml": "🛠️",
            "write_yaml": "🛠️",
            "write_env": "🛠️",
            "apply_patch": "🩹",
            "list_dir": "📁",
            "http_request": "🌐",
            "list_archive": "🗜️",
            "read_pdf": "📄",
            "read_image": "🖼️",
            "glob": "🗂️",
            "grep": "🔎",
            "web_search": "🌐",
            "web_fetch": "📄",
            "run_tests": "🧪",
            "run_linter": "🧹",
            "run_typecheck": "🔤",
            "git_status": "🌿",
            "git_diff": "🧬",
            "git_log": "🕘",
            "git_branch": "🌱",
            "git_remote": "🔗",
            "git_commit": "📦",
            "git_push": "🚀",
            "todos": "☑️",
            "memory": "🧠",
            "shell": "▫️",
        }
        return icon_by_tool.get(name, "✅"), f"bold {self._style('fg')}"

    @staticmethod
    def _normalize_tool_start_arguments(
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            return {}
        normalized = dict(arguments)
        raw = normalized.get("raw_arguments", normalized.get("raw"))
        if not isinstance(raw, str) or not raw.strip():
            return normalized

        raw_text = raw.strip()
        path_matches = re.findall(r'"path"\s*:\s*"([^"]+)"', raw_text)
        command_matches = re.findall(r'"command"\s*:\s*"([^"]+)"', raw_text)
        session_matches = re.findall(r'"session_id"\s*:\s*"([^"]+)"', raw_text)

        if tool_name == "read_file" and path_matches:
            summary = path_matches[0]
            if len(path_matches) > 1:
                summary = f"{summary} (+{len(path_matches) - 1} more)"
            return {"path": summary}
        if tool_name in {"shell", "shell_start"} and command_matches:
            return {"command": command_matches[0]}
        if tool_name in {"shell_poll", "shell_send", "shell_stop"} and session_matches:
            normalized_hint: dict[str, Any] = {"session_id": session_matches[0]}
            if tool_name == "shell_send" and command_matches:
                normalized_hint["input"] = command_matches[0]
            return normalized_hint

        if "raw" in normalized:
            normalized["raw"] = "<unparsed arguments>"
        if "raw_arguments" in normalized:
            normalized["raw_arguments"] = "<unparsed arguments>"
        return normalized

    @staticmethod
    def _should_suppress_malformed_tool_card(
        tool_name: str | None,
        validation_error: str,
    ) -> bool:
        if tool_name not in {
            "shell",
            "read_file",
            "read_json",
            "read_toml",
            "read_yaml",
            "read_env",
            "read_pdf",
            "read_image",
            "grep",
            "write_file",
            "edit",
            "apply_patch",
            "memory",
            "todos",
            "skills",
        }:
            return False
        normalized = validation_error.strip()
        if normalized.startswith("Error: "):
            normalized = normalized.removeprefix("Error: ").strip()
        if (
            tool_name == "todos"
            and "'content' or 'items' is required for 'add' action" in normalized
        ):
            return True
        if not normalized.startswith("Invalid parameters: "):
            return False
        detail = normalized.removeprefix("Invalid parameters: ").strip()
        detail = detail.split("\n\nOutput:", 1)[0].strip()
        detail = detail.split("\nOutput:", 1)[0].strip()
        required_errors = {
            "shell": {"Parameter 'command': Field required"},
            "read_file": {"Parameter 'path': Field required"},
            "read_json": {"Parameter 'path': Field required"},
            "read_toml": {"Parameter 'path': Field required"},
            "read_yaml": {"Parameter 'path': Field required"},
            "read_env": {"Parameter 'path': Field required"},
            "read_pdf": {"Parameter 'path': Field required"},
            "read_image": {"Parameter 'path': Field required"},
            "grep": {"Parameter 'pattern': Field required"},
            "write_file": {
                "Parameter 'path': Field required",
                "Parameter 'content': Field required",
                "Parameter 'path': Field required; Parameter 'content': Field required",
            },
            "edit": {
                "Parameter 'path': Field required",
                "Parameter 'new_string': Field required",
                "Parameter 'path': Field required; Parameter 'new_string': Field required",
            },
            "apply_patch": {"Parameter 'patch': Field required"},
            "memory": {"Parameter 'action': Field required"},
            "todos": set(),
            "skills": {"Parameter '': Value error, skill is required for show, activate, and deactivate"},
        }
        return detail in required_errors.get(tool_name, set())

    def _build_shell_session_card_content(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        metadata: dict[str, Any],
        payload: str,
        success: bool,
        exit_code: int | None,
        animate_running: bool = False,
    ) -> tuple[Text, Group]:
        styles = self._render_styles()
        md = metadata if isinstance(metadata, dict) else {}
        icon, title_style = self._shell_card_icon_and_style(md, success=success)
        running_suffix = ""
        if animate_running and md.get("running") is True:
            running_suffix = self._shell_status_suffix()

        blocks: list[Any] = []
        command = (
            md.get("last_input")
            or arguments.get("input")
            or arguments.get("command")
            or md.get("command")
        )
        if isinstance(command, str) and command.strip():
            blocks.append(
                render_shell_command_line(
                    command.strip(),
                    cwd=self.config.cwd,
                    shell_cwd=md.get("cwd") if isinstance(md.get("cwd"), str) else None,
                    theme_variables=self._theme_tokens(),
                )
            )
        display_payload = (
            payload
            if (
                name in {"shell", "shell_poll", "shell_stop"}
                or not success
                or md.get("running") is True
            )
            else ""
        )
        summary = Text()
        session_id = str(md.get("session_id") or "").strip()
        if session_id:
            summary.append(session_id, style=self._style("muted"))
        status_state = shell_session_state(md)
        if isinstance(md.get("running"), bool) or md.get("status"):
            if summary.plain:
                summary.append("  •  ", style=self._style("disabled"))
            status_label, status_style = status_state, self._style("muted")
            if status_state == "command_running":
                status_label = "command running" + running_suffix
                status_style = self._style("primary")
            elif status_state == "idle":
                status_label = "idle"
                status_style = self._style("muted")
            elif status_label == "exited":
                status_style = self._style("muted")
            summary.append(status_label.replace("_", " "), style=status_style)
        if exit_code is not None:
            if summary.plain:
                summary.append("  •  ", style=self._style("disabled"))
            summary.append(f"exit {exit_code}", style=self._style("muted"))
        if md.get("timed_out"):
            if summary.plain:
                summary.append("  •  ", style=self._style("disabled"))
            summary.append("timed out", style=self._style("warning"))
        if summary.plain:
            blocks.append(summary)
        blocks.append(
            render_terminal_snapshot_payload(
                display_payload,
                tone="stdout" if success else "stderr",
                max_lines=None,
                max_chars=64000,
                theme_variables=self._theme_tokens(),
            )
        )

        header = Text()
        header.append(icon, style=title_style)
        header.append("  ")
        header.append("Shell", style=title_style)
        return header, Group(*blocks)

    def _render_shell_session_card(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        metadata: dict[str, Any],
        payload: str,
        success: bool,
        exit_code: int | None,
        animate_running: bool = False,
    ) -> Group:
        header, body = self._build_shell_session_card_content(
            name=name,
            arguments=arguments,
            metadata=metadata,
            payload=payload,
            success=success,
            exit_code=exit_code,
            animate_running=animate_running,
        )
        return Group(header, body)

    async def _update_tool_call_progress(
        self,
        *,
        call_id: str,
        name: str,
        output: str,
        metadata: dict[str, Any] | None,
        exit_code: int | None,
    ) -> None:
        if name != "shell":
            return
        md = metadata if isinstance(metadata, dict) else {}
        card = self._tool_widgets.get(call_id)
        args = self._tool_args_by_call_id.get(call_id, {})
        accumulated_payload = output or ""
        if card is None:
            return
        state = ShellSessionCardState(
            card=card,
            name=name,
            arguments=args,
            metadata=md,
            payload=accumulated_payload,
            success=True,
            exit_code=exit_code,
        )
        self._live_shell_call_state[call_id] = state
        header, body = self._build_shell_session_card_content(
            name=name,
            arguments=args,
            metadata=md,
            payload=accumulated_payload,
            success=True,
            exit_code=exit_code,
            animate_running=True,
        )
        if isinstance(card, ShellToolCard):
            card.set_shell_content(header=header, body=body)
        else:
            card.update(Group(header, body))

        self._set_loading_state("idle", busy=False)

    async def _move_card_to_bottom(self, card: Static) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        try:
            await card.remove()
        except Exception:
            pass
        await conversation.mount(card)

    def _render_wait_subagent_running_card(
        self,
        *,
        args: dict[str, Any],
        spinner_index: int,
    ) -> Group:
        styles = self._render_styles()

        def compact_result_line(value: str) -> str:
            text = str(value or "").strip()
            if not text:
                return ""
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines:
                return ""
            first = lines[0]
            has_more = len(lines) > 1
            if len(first) > 72:
                first = first[:69].rstrip() + "..."
                has_more = False
            if has_more and not first.endswith("..."):
                first = first.rstrip() + " ..."
            return first

        def age_label(value: Any) -> str:
            if not isinstance(value, str) or not value.strip():
                return ""
            try:
                updated_at = datetime.fromisoformat(value)
                now = datetime.now(updated_at.tzinfo)
                seconds = max(0, int((now - updated_at).total_seconds()))
            except Exception:
                return ""
            if seconds < 2:
                return "just now"
            if seconds < 60:
                return f"{seconds}s ago"
            minutes = seconds // 60
            if minutes < 60:
                return f"{minutes}m ago"
            hours = minutes // 60
            return f"{hours}h ago"

        run_ids = args.get("run_ids")
        selected_ids = (
            [str(item).strip() for item in run_ids if str(item).strip()]
            if isinstance(run_ids, list)
            else []
        )
        return_when = str(args.get("return_when") or "all_completed").strip()
        header = Text()
        header.append(
            f"{self._top_spinner_frames[spinner_index % len(self._top_spinner_frames)]} ",
            style=f"bold {self._style('primary')}",
        )
        header.append("Waiting on specialists", style=f"bold {self._style('fg')}")
        header.append("  running", style=self._style("muted"))

        blocks: list[Any] = [
            Text("Watching active specialist runs.", style=self._style("muted"))
        ]
        summary = Text()
        if selected_ids:
            summary.append(f"{len(selected_ids)} selected", style=self._style("muted"))
            summary.append("  •  ", style=self._style("disabled"))
        summary.append(return_when, style=self._style("muted"))
        blocks.append(summary)

        runtime = getattr(
            getattr(self.agent, "session", None), "subagent_runtime", None
        )
        if runtime is not None:
            runs = runtime.list_runs()
            if selected_ids:
                runs = [run for run in runs if run.run_id in selected_ids]
            if runs:
                table = Table.grid(padding=(0, 1))
                table.add_column(style=self._style("primary"), no_wrap=True)
                table.add_column(style=self._style("muted"), no_wrap=True)
                table.add_column(style=self._style("fg"))
                for run in runs[:12]:
                    goal_label = summarize_subagent_goal(
                        str(getattr(run, "goal", "") or "").strip()
                    )
                    elapsed = ""
                    if isinstance(run.started_at, str) and run.started_at:
                        try:
                            started_at = datetime.fromisoformat(run.started_at)
                            elapsed_ms = max(
                                0,
                                int(
                                    (
                                        datetime.now(started_at.tzinfo) - started_at
                                    ).total_seconds()
                                    * 1000
                                ),
                            )
                            elapsed = f"{elapsed_ms} ms"
                        except Exception:
                            elapsed = ""
                    live = str(getattr(run, "current_activity", "") or "").strip()
                    freshness = age_label(getattr(run, "last_update_at", None))
                    status = str(getattr(run, "status", "")).strip()
                    if status in {"completed", "failed", "timeout", "cancelled"}:
                        details = compact_result_line(
                            run.summary or run.current_activity or run.goal or ""
                        )
                    else:
                        details = live or run.summary or run.goal or ""
                    if elapsed:
                        details = f"{elapsed}  •  {details}" if details else elapsed
                    if freshness:
                        details = f"{details}  •  {freshness}" if details else freshness
                    if len(details) > 80:
                        details = details[:77].rstrip() + "..."
                    status_text = Text(run.status)
                    if status == "completed":
                        status_text.stylize(self._style("success"))
                    elif status in {"failed", "timeout", "cancelled"}:
                        status_text.stylize(self._style("error"))
                    else:
                        status_text.stylize(self._style("muted"))
                    run_label = Text(str(run.run_id), style=self._style("primary"))
                    if goal_label:
                        run_label.append(" · ", style=self._style("disabled"))
                        run_label.append(goal_label, style=self._style("muted"))
                    table.add_row(run_label, status_text, details or "(no summary yet)")
                blocks.append(table)
                history_lines: list[Text] = []
                active_runs = [
                    run
                    for run in runs
                    if str(getattr(run, "status", "")).strip() in {"queued", "running"}
                ]
                for run in active_runs[:12]:
                    goal_label = summarize_subagent_goal(
                        str(getattr(run, "goal", "") or "").strip()
                    )
                    history = getattr(run, "activity_history", None)
                    if not isinstance(history, list) or not history:
                        continue
                    recent = []
                    for entry in history[-3:]:
                        if not isinstance(entry, dict):
                            continue
                        message = str(entry.get("message") or "").strip()
                        freshness = age_label(entry.get("at"))
                        line = "  •  ".join(
                            part for part in [freshness, message] if part
                        )
                        if line:
                            recent.append(line)
                    if not recent:
                        continue
                    history_header = Text(
                        str(run.run_id), style=f"bold {self._style('accent')}"
                    )
                    if goal_label:
                        history_header.append(" · ", style=self._style("disabled"))
                        history_header.append(goal_label, style=self._style("muted"))
                    history_header.append(
                        " recent activity", style=f"bold {self._style('accent')}"
                    )
                    history_lines.append(history_header)
                    for index, line in enumerate(recent):
                        style = (
                            self._style("fg")
                            if index == len(recent) - 1
                            else self._style("muted")
                        )
                        history_lines.append(Text(f"• {line}", style=style))
                if history_lines:
                    blocks.append(Text(""))
                blocks.extend(history_lines)
            else:
                blocks.append(
                    Text(
                        "No matching specialist runs found.", style=self._style("muted")
                    )
                )
        else:
            blocks.append(
                Text("Specialist runtime unavailable.", style=self._style("muted"))
            )

        return Group(header, *blocks)

    def _render_subagent_running_card(
        self,
        *,
        call_id: str,
        name: str,
        args: dict[str, Any],
        spinner_index: int,
    ) -> Group:
        styles = self._render_styles()

        def age_label(value: Any) -> str:
            if not isinstance(value, str) or not value.strip():
                return ""
            try:
                updated_at = datetime.fromisoformat(value)
                now = datetime.now(updated_at.tzinfo)
                seconds = max(0, int((now - updated_at).total_seconds()))
            except Exception:
                return ""
            if seconds < 2:
                return "just now"
            if seconds < 60:
                return f"{seconds}s ago"
            minutes = seconds // 60
            if minutes < 60:
                return f"{minutes}m ago"
            hours = minutes // 60
            return f"{hours}h ago"

        header = Text()
        header.append(
            f"{self._top_spinner_frames[spinner_index % len(self._top_spinner_frames)]} ",
            style=f"bold {self._style('primary')}",
        )
        header.append("Asking specialist", style=f"bold {self._style('fg')}")
        header.append("  running", style=self._style("muted"))

        blocks: list[Any] = []
        goal = str(args.get("goal") or "").strip()
        if goal:
            blocks.append(Text(f"goal  {goal}", style=self._style("fg")))

        registry = getattr(getattr(self.agent, "session", None), "tool_registry", None)
        tool = registry.get(name) if registry is not None else None
        live = (
            tool.get_live_progress(call_id)
            if tool is not None and hasattr(tool, "get_live_progress")
            else None
        )

        if isinstance(live, dict):
            activity = str(live.get("current_activity") or "").strip()
            freshness = age_label(live.get("last_update_at"))
            child_session_id = str(live.get("child_session_id") or "").strip()
            details = "  •  ".join(part for part in [freshness, activity] if part)
            if details:
                blocks.append(Text(details, style=self._style("muted")))
            if child_session_id:
                blocks.append(
                    Text(
                        f"child session {child_session_id}", style=self._style("muted")
                    )
                )
            history = live.get("activity_history")
            if isinstance(history, list) and history:
                blocks.append(
                    Text("Recent activity", style=f"bold {self._style('accent')}")
                )
                for entry in history[-3:]:
                    if not isinstance(entry, dict):
                        continue
                    message = str(entry.get("message") or "").strip()
                    freshness = age_label(entry.get("at"))
                    line = "  •  ".join(part for part in [freshness, message] if part)
                    if line:
                        style = (
                            self._style("fg")
                            if entry is history[-1]
                            else self._style("secondary")
                        )
                        blocks.append(Text(f"• {line}", style=style))
        elif not blocks:
            blocks.append(
                Text(
                    "Starting specialist session.", style=self._render_styles()["muted"]
                )
            )

        return Group(header, *blocks)

    async def add_tool_call_start(
        self,
        *,
        call_id: str,
        name: str,
        tool_kind: str | None,
        arguments: dict[str, Any],
    ) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        arguments = self._normalize_tool_start_arguments(name, arguments)
        self._tool_args_by_call_id[call_id] = arguments
        self._tool_name_by_call_id[call_id] = name
        existing_card = self._tool_widgets.get(call_id)

        if existing_card is not None:
            card = existing_card
        elif name == "shell":
            card = ShellToolCard(classes="block tool shell-card running")
        elif tool_kind == "mcp":
            card = Static(classes="block tool mcp-card running")
        else:
            card = Static(classes="block tool running")
        mcp_md: dict[str, Any] | None = None
        if tool_kind == "mcp":
            inferred_server, inferred_tool = (name.split("__", 1) + [""])[:2]
            mcp_md = {
                "mcp_server": inferred_server,
                "mcp_tool": inferred_tool,
            }
        border_style = "#2a6edb"
        title_text = activity_title(name, stage="start", metadata=mcp_md)
        narrative = describe_tool_activity(name, arguments, mcp_md, stage="start")

        blocks: list[Any] = []
        if name == "todos":
            blocks.append(
                Text(todo_start_hint(arguments), style=self._render_styles()["fg"])
            )
        elif tool_kind == "mcp":
            blocks.extend(
                render_mcp_start_payload(
                    tool_name=name,
                    arguments=arguments,
                    cwd=self.config.cwd,
                )
            )
        elif arguments:
            blocks.append(render_args_table(name, arguments, cwd=self.config.cwd))
        else:
            blocks.append(Text("(no args)", style=self._render_styles()["muted"]))

        if name == "shell":
            self._run_state().running_shell_call_ids.add(call_id)
            if isinstance(card, ShellToolCard):
                header, body = self._build_shell_session_card_content(
                    name=name,
                    arguments=arguments,
                    metadata={"running": True, "status": "command_running"},
                    payload="",
                    success=True,
                    exit_code=None,
                    animate_running=True,
                )
                card.set_shell_content(header=header, body=body)
            else:
                card.update(
                    render_shell_running_card(
                        arguments,
                        cwd=self.config.cwd,
                        spinner_index=self._top_spinner_index,
                    )
                )
        elif name.startswith("subagent_"):
            self._run_state().running_subagent_call_ids.add(call_id)
            card.update(
                self._render_subagent_running_card(
                    call_id=call_id,
                    name=name,
                    args=arguments,
                    spinner_index=self._top_spinner_index,
                )
            )
        elif name == "wait_subagent":
            self._run_state().running_wait_subagent_call_ids.add(call_id)
            card.update(
                self._render_wait_subagent_running_card(
                    args=arguments,
                    spinner_index=self._top_spinner_index,
                )
            )
        else:
            header = Text()
            header.append("⌛ ", style="bold #b7c8e1")
            header.append(title_text, style=f"bold {self._style('fg')}")
            header.append("  running", style=self._render_styles()["muted"])
            if tool_kind == "mcp" and narrative:
                blocks.insert(0, Text(narrative, style=self._render_styles()["muted"]))
            card.update(Group(header, *blocks))
        self._tool_widgets[call_id] = card

        if existing_card is not None:
            await self._move_card_to_bottom(card)
        else:
            await conversation.mount(card)
            self._message_count += 1
        self._refresh_empty_state()
        await self._pin_activity_indicator_to_end()

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
        pin_after_update: bool = True,
    ) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        card = self._tool_widgets.get(call_id)
        if card is None:
            return

        self._tool_completion_state[call_id] = {
            "name": name,
            "tool_kind": tool_kind,
            "success": success,
            "output": output,
            "error": error,
            "metadata": metadata if isinstance(metadata, dict) else None,
            "diff": diff,
            "truncated": truncated,
            "exit_code": exit_code,
        }

        md = metadata if isinstance(metadata, dict) else {}
        policy_redirect = bool(md.get("policy_blocked") and md.get("redirect_to"))
        recoverable = bool(md.get("recoverable")) or policy_redirect
        status = (
            "done"
            if success
            else (
                "redirected" if policy_redirect else ("" if recoverable else "failed")
            )
        )
        args = self._tool_args_by_call_id.get(call_id, {})
        narrative = describe_tool_activity(
            name,
            args,
            md,
            stage="complete",
            success=success,
        )

        border_style = (
            "#2f9e63"
            if success
            else (
                "#4d79c7"
                if policy_redirect
                else ("#a06b15" if recoverable else "#b23a3a")
            )
        )
        icon, title_style = self._tool_completion_icon_and_style(
            name,
            success=success,
            policy_redirect=policy_redirect,
            recoverable=recoverable,
        )
        title_text = activity_title(
            name, stage="complete", success=success, metadata=md
        )
        self._run_state().running_shell_call_ids.discard(call_id)
        self._live_shell_call_state.pop(call_id, None)
        self._run_state().running_subagent_call_ids.discard(call_id)
        self._run_state().running_wait_subagent_call_ids.discard(call_id)
        payload = output if success else (error or output)
        payload = payload or ""

        if name == "shell":
            shell_md = dict(md)
            shell_md.setdefault("running", False)
            shell_md.setdefault("status", "exited" if success else "failed")
            header, body = self._build_shell_session_card_content(
                name=name,
                arguments=args,
                metadata=shell_md,
                payload=payload,
                success=success,
                exit_code=exit_code,
            )
            if isinstance(card, ShellToolCard):
                card.set_shell_content(header=header, body=body)
            else:
                card.update(Group(header, body))
            card.remove_class("running")
            if success:
                card.add_class("success")
            else:
                card.add_class("error")
            if pin_after_update:
                await self._pin_activity_indicator_to_end()
            return

        styles = self._render_styles()
        blocks: list[Any] = []
        local_truncated = False
        primary_path = md.get("path") if isinstance(md.get("path"), str) else None
        redirect_to = str(md.get("redirect_to") or "").strip()

        if policy_redirect:
            if redirect_to:
                blocks.append(
                    Text(f"Continuing with `{redirect_to}`.", style=self._style("fg"))
                )
            payload = ""

        if name == "read_file" and success:
            blocks.append(Text(narrative, style=self._style("secondary")))
            extracted = extract_read_file_code(payload) if primary_path else None
            if primary_path and extracted is not None:
                start_line, code = extracted
                code_display, was_truncated = truncate_for_tool(name, code)
                local_truncated = local_truncated or was_truncated
                language = guess_language(primary_path)
                prefer_terminal_safe = self._prefer_terminal_safe_source_rendering()
                if language == "markdown":
                    blocks.append(RichMarkdown(code_display))
                elif self.current_theme.dark and not prefer_terminal_safe:
                    blocks.append(
                        Syntax(
                            code_display,
                            language,
                            theme=self._syntax_theme_name(),
                            background_color=syntax_background_color(
                                self._theme_tokens()
                            ),
                            line_numbers=True,
                            start_line=start_line,
                            word_wrap=False,
                        )
                    )
                else:
                    blocks.append(
                        render_line_numbered_text(
                            code_display,
                            start_line=start_line,
                            theme_variables=self._theme_tokens(),
                        )
                    )
            else:
                output_display, was_truncated = truncate_for_tool(name, payload)
                local_truncated = local_truncated or was_truncated
                blocks.append(
                    render_text_payload(
                        output_display,
                        success=True,
                        syntax_theme=self._syntax_theme_name(),
                        theme_variables=self._theme_tokens(),
                    )
                )
        elif (
            name
            in {
                "write_file",
                "edit",
                "edit_json",
                "write_toml",
                "write_yaml",
                "write_env",
            }
            and success
            and diff
        ):
            if primary_path:
                blocks.append(
                    Text(
                        display_path(primary_path, cwd=self.config.cwd),
                        style=self._style("muted"),
                    )
                )
            summary_parts: list[str] = []
            if name == "write_file":
                if md.get("is_new_file") is True:
                    summary_parts.append("created")
                else:
                    summary_parts.append("updated")
                lines_added = md.get("lines_added")
                if isinstance(lines_added, int):
                    summary_parts.append(
                        f"{lines_added} line{'s' if lines_added != 1 else ''}"
                    )
            elif name == "edit":
                replace_count = md.get("replace_count")
                line_diff = md.get("line_diff")
                if isinstance(replace_count, int):
                    summary_parts.append(
                        f"{replace_count} replacement{'s' if replace_count != 1 else ''}"
                    )
                if isinstance(line_diff, int) and line_diff != 0:
                    sign = "+" if line_diff > 0 else ""
                    summary_parts.append(
                        f"{sign}{line_diff} line{'s' if abs(line_diff) != 1 else ''}"
                    )
            else:
                operation = str(md.get("operation") or "").strip()
                if operation:
                    summary_parts.append(operation)
                if name == "write_env":
                    key = str(md.get("key") or "").strip()
                    if key:
                        summary_parts.append(key)
                else:
                    key_path = str(md.get("key_path") or "").strip()
                    if key_path:
                        summary_parts.append(key_path)
            hunk_ranges = summarize_diff_hunk_ranges(diff)
            if hunk_ranges:
                summary_parts.append("  |  ".join(hunk_ranges[:2]))
            if summary_parts:
                blocks.append(
                    Text("  •  ".join(summary_parts), style=self._style("muted"))
                )
            diff_display, was_truncated = truncate_for_tool(name, diff)
            local_truncated = local_truncated or was_truncated
            blocks.append(
                render_numbered_unified_diff(diff_display, self._theme_tokens())
            )
        elif name in {"run_tests", "run_linter", "run_typecheck", "http_request"}:
            blocks.append(Text(narrative, style=self._style("muted")))
            if name == "http_request":
                method = (
                    str(md.get("method") or args.get("method") or "GET").strip().upper()
                )
                url = str(md.get("url") or args.get("url") or "").strip()
                if url:
                    blocks.append(Text(f"{method} {url}", style=self._style("muted")))
            else:
                command = md.get("command") or args.get("command")
                if isinstance(command, str) and command.strip():
                    blocks.append(
                        render_shell_command_line(
                            command.strip(),
                            cwd=self.config.cwd,
                            shell_cwd=md.get("cwd")
                            if isinstance(md.get("cwd"), str)
                            else None,
                            theme_variables=self._theme_tokens(),
                        )
                    )
            duration_ms = md.get("duration_ms")
            if isinstance(duration_ms, int):
                blocks.append(
                    Text(
                        f"Completed in {duration_ms} ms",
                        style=self._style("muted"),
                    )
                )
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            if name == "http_request":
                blocks.append(
                    Text(
                        "  •  ".join(
                            part
                            for part in [
                                str(md.get("status_code"))
                                if md.get("status_code") is not None
                                else "",
                                str(md.get("content_type") or "").strip(),
                            ]
                            if part
                        ),
                        style=self._style("muted"),
                    )
                )
                blocks.append(
                    render_text_payload(
                        output_display,
                        success=success,
                        syntax_theme=self._syntax_theme_name(),
                        theme_variables=self._theme_tokens(),
                    )
                )
            else:
                blocks.extend(
                    render_shell_result_payload(
                        payload=output_display,
                        metadata=md,
                        exit_code=exit_code,
                        theme_variables=self._theme_tokens(),
                    )
                )
        elif name == "list_archive" and success:
            blocks.append(Text(narrative, style=self._style("muted")))
            if primary_path:
                blocks.append(
                    Text(
                        display_path(primary_path, cwd=self.config.cwd),
                        style=self._style("muted"),
                    )
                )
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            blocks.append(
                render_text_payload(
                    output_display,
                    success=True,
                    syntax_theme=self._syntax_theme_name(),
                    theme_variables=self._theme_tokens(),
                )
            )
        elif name in {"read_pdf", "read_image"} and success:
            if primary_path:
                blocks.append(
                    Text(
                        display_path(primary_path, cwd=self.config.cwd),
                        style=self._style("muted"),
                    )
                )
            summary_parts: list[str] = []
            if name == "read_pdf":
                page_count = md.get("page_count")
                if isinstance(page_count, int):
                    summary_parts.append(f"{page_count} pages")
                quality = str(md.get("text_extraction_quality") or "").strip()
                if quality:
                    summary_parts.append(quality)
            else:
                width = md.get("width")
                height = md.get("height")
                if isinstance(width, int) and isinstance(height, int):
                    summary_parts.append(f"{width}×{height}")
                image_format = str(md.get("format") or "").strip()
                if image_format:
                    summary_parts.append(image_format)
                if md.get("ocr_requested"):
                    summary_parts.append("ocr")
            if summary_parts:
                blocks.append(
                    Text("  •  ".join(summary_parts), style=self._style("muted"))
                )
        elif name in {"read_json", "read_toml", "read_yaml", "read_env"} and success:
            if primary_path:
                target = display_path(primary_path, cwd=self.config.cwd)
                if name == "read_json":
                    structured_path = str(md.get("json_path", "")).strip()
                elif name in {"read_toml", "read_yaml"}:
                    structured_path = str(md.get("key_path", "")).strip()
                else:
                    structured_path = str(md.get("key", "")).strip()
                if structured_path:
                    target = f"{target} :: {structured_path}"
                blocks.append(Text(target, style=self._style("secondary")))
            else:
                blocks.append(Text(narrative, style=self._style("secondary")))
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            language = "json"
            if name == "read_toml":
                language = "toml"
            elif name == "read_yaml":
                language = "yaml"
            blocks.append(
                render_text_payload(
                    output_display,
                    success=True,
                    language=(
                        language
                        if self.current_theme.dark
                        and not self._prefer_terminal_safe_source_rendering()
                        else "text"
                    ),
                    syntax_theme=self._syntax_theme_name(),
                    theme_variables=self._theme_tokens(),
                )
            )
        elif name in {"shell", "shell_poll", "shell_stop"}:
            blocks.append(Text(narrative, style=self._style("muted")))
            command = args.get("command")
            if isinstance(command, str) and command.strip():
                blocks.append(
                    render_shell_command_line(
                        command.strip(),
                        cwd=self.config.cwd,
                        shell_cwd=md.get("cwd")
                        if isinstance(md.get("cwd"), str)
                        else None,
                        theme_variables=self._theme_tokens(),
                    )
                )
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            blocks.extend(
                render_shell_result_payload(
                    payload=output_display,
                    metadata=md,
                    exit_code=exit_code,
                    theme_variables=self._theme_tokens(),
                )
            )
        elif name == "web_search" and success:
            blocks.append(Text(narrative, style=self._style("muted")))
            query = md.get("query") or args.get("query")
            results_count = md.get("results")
            provider = md.get("provider")
            summary_parts: list[str] = []
            if isinstance(query, str) and query.strip():
                summary_parts.append(f'"{query.strip()}"')
            if isinstance(results_count, int):
                summary_parts.append(
                    f"{results_count} result{'s' if results_count != 1 else ''}"
                )
            if isinstance(provider, str) and provider.strip():
                summary_parts.append(provider)
            if summary_parts:
                blocks.append(
                    Text(" • ".join(summary_parts), style=self._style("muted"))
                )
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            blocks.append(
                render_text_payload(
                    output_display,
                    success=success,
                    syntax_theme=self._syntax_theme_name(),
                    theme_variables=self._theme_tokens(),
                )
            )
        elif name == "web_fetch" and success:
            blocks.append(Text(narrative, style=self._style("muted")))
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
                blocks.append(
                    Text(" • ".join(summary_parts), style=self._style("muted"))
                )
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            blocks.append(
                render_text_payload(
                    output_display,
                    success=success,
                    syntax_theme=self._syntax_theme_name(),
                    theme_variables=self._theme_tokens(),
                )
            )
        elif name in {"list_dir", "glob", "grep"}:
            blocks.append(Text(narrative, style=self._style("muted")))
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            if name == "list_dir":
                blocks.append(
                    render_list_dir_output(
                        output_display, theme_variables=self._theme_tokens()
                    )
                )
            elif name == "grep":
                blocks.append(
                    render_grep_output(
                        output_display,
                        cwd=self.config.cwd,
                        syntax_theme=self._syntax_theme_name(),
                        theme_variables=self._theme_tokens(),
                    )
                )
            else:
                blocks.append(
                    render_text_payload(
                        output_display,
                        success=success,
                        syntax_theme=self._syntax_theme_name(),
                        theme_variables=self._theme_tokens(),
                    )
                )
        elif name == "git_diff":
            blocks.append(Text(narrative, style=self._style("muted")))
            selection = md.get("selection")
            files = md.get("files")
            diff_count = md.get("diff_count")
            summary_parts: list[str] = []
            if isinstance(selection, str) and selection.strip():
                summary_parts.append(selection.strip())
            if isinstance(diff_count, int):
                summary_parts.append(
                    f"{diff_count} file{'s' if diff_count != 1 else ''}"
                )
            if summary_parts:
                blocks.append(
                    Text(" • ".join(summary_parts), style=self._style("muted"))
                )
            if isinstance(files, list) and files:
                for entry in files[:6]:
                    if not isinstance(entry, dict):
                        continue
                    rel_path = str(entry.get("path", "")).strip()
                    stage_label = str(entry.get("stage_label", "")).strip()
                    change_type = str(entry.get("change_type", "")).strip()
                    detail = Text()
                    detail.append("• ", style=self._style("muted"))
                    detail.append(rel_path, style=self._style("fg"))
                    meta_bits = [part for part in [stage_label, change_type] if part]
                    if meta_bits:
                        detail.append("  ")
                        detail.append(" / ".join(meta_bits), style=self._style("muted"))
                    blocks.append(detail)
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            if output_display.strip().startswith(("--- ", "+++ ", "@@ ")):
                blocks.append(
                    render_numbered_unified_diff(
                        normalize_unified_diff_paths(
                            output_display,
                            cwd=self.config.cwd,
                        ),
                        self._theme_tokens(),
                    )
                )
            elif output_display.strip():
                blocks.append(
                    render_text_payload(
                        output_display,
                        success=success,
                        syntax_theme=self._syntax_theme_name(),
                        theme_variables=self._theme_tokens(),
                    )
                )
            else:
                blocks.append(Text("No diff output", style=self._style("muted")))
        elif name == "git_log" and success:
            blocks.append(Text(narrative, style=self._style("muted")))
            count = md.get("count")
            ref = md.get("ref")
            summary_parts: list[str] = []
            if isinstance(count, int):
                summary_parts.append(f"{count} commit{'s' if count != 1 else ''}")
            if isinstance(ref, str) and ref.strip():
                summary_parts.append(ref.strip())
            if summary_parts:
                blocks.append(
                    Text(" • ".join(summary_parts), style=self._style("muted"))
                )
            blocks.append(
                render_git_log_output(md, theme_variables=self._theme_tokens())
            )
        elif name == "todos" and success:
            blocks.append(Text(narrative, style=self._style("muted")))
            todo_blocks, was_truncated = render_todo_payload(
                output=payload,
                metadata=md,
                theme_variables=self._theme_tokens(),
            )
            local_truncated = local_truncated or was_truncated
            blocks.extend(todo_blocks)
        elif name == "skills":
            blocks.append(Text(narrative, style=self._style("muted")))
            blocks.append(
                render_skills_payload(
                    output=payload,
                    success=success,
                    theme_variables=self._theme_tokens(),
                )
            )
        elif name == "subagent_metrics":
            blocks.append(Text(narrative, style=self._style("muted")))
            blocks.extend(
                render_subagent_metrics_payload(
                    metadata=md,
                    output=output,
                    error=error,
                    success=success,
                    theme_variables=self._theme_tokens(),
                )
            )
        elif name in {
            "spawn_subagent",
            "spawn_subagents",
            "wait_subagent",
            "list_subagents",
            "cancel_subagent",
        }:
            blocks.append(Text(narrative, style=self._style("muted")))
            blocks.extend(
                render_subagent_runtime_payload(
                    metadata=md,
                    output=output,
                    error=error,
                    success=success,
                    collapse_completed=(name == "wait_subagent"),
                    theme_variables=self._theme_tokens(),
                )
            )
        elif name.startswith("subagent_"):
            blocks.append(Text(narrative, style=self._style("muted")))
            subagent_blocks, was_truncated = render_subagent_payload(
                output=output,
                metadata=md,
                success=success,
                error=error,
                theme_variables=self._theme_tokens(),
            )
            local_truncated = local_truncated or was_truncated
            blocks.extend(subagent_blocks)
        elif tool_kind == "mcp":
            server_name = str(md.get("mcp_server") or "").strip()
            mcp_tool_name = str(md.get("mcp_tool") or "").strip()
            identity = format_mcp_identity(
                name,
                server_name=server_name,
                mcp_tool_name=mcp_tool_name,
            )
            if identity:
                blocks.append(Text(identity, style=self._style("muted")))
            if success:
                if payload.strip():
                    summary, mcp_blocks, was_truncated = summarize_mcp_success(
                        server_name=server_name,
                        tool_name=name,
                        payload_text=payload,
                        theme_variables=self._theme_tokens(),
                    )
                    local_truncated = local_truncated or was_truncated
                    blocks.append(Text(summary, style=self._style("muted")))
                    blocks.extend(mcp_blocks)
                else:
                    blocks.append(Text("Data loaded.", style=self._style("muted")))
            else:
                summary = str(md.get("ui_summary") or "The MCP request failed.").strip()
                detail = str(md.get("ui_detail") or "").strip()
                summary_style = (
                    self._style("warning") if recoverable else self._style("error")
                )
                blocks.append(Text(summary, style=summary_style))
                if detail and detail != summary:
                    blocks.append(Text(detail, style=self._style("muted")))
                if self.config.debug:
                    output_display, was_truncated = truncate_for_tool(name, payload)
                    local_truncated = local_truncated or was_truncated
                    if output_display.strip():
                        blocks.append(
                            render_text_payload(
                                output_display,
                                success=False,
                                syntax_theme=self._syntax_theme_name(),
                                theme_variables=self._theme_tokens(),
                            )
                        )
        else:
            blocks.append(Text(narrative, style=self._style("muted")))
            output_display, was_truncated = truncate_for_tool(name, payload)
            local_truncated = local_truncated or was_truncated
            if diff:
                diff_display, diff_truncated = truncate_for_tool(name, diff)
                local_truncated = local_truncated or diff_truncated
                blocks.append(
                    Syntax(
                        diff_display,
                        "diff",
                        theme=self._syntax_theme_name(),
                        background_color=syntax_background_color(self._theme_tokens()),
                        word_wrap=True,
                    )
                )
            elif output_display.strip():
                blocks.append(
                    render_text_payload(
                        output_display,
                        success=success,
                        syntax_theme=self._syntax_theme_name(),
                        theme_variables=self._theme_tokens(),
                    )
                )
            else:
                blocks.append(Text("No output", style=self._style("muted")))

        if local_truncated or truncated:
            blocks.append(Text("... [truncated]", style=self._style("warning")))

        header = Text()
        header.append(icon, style=title_style)
        header.append("  ")
        if name == "shell":
            header.append(
                "Command finished" if success else "Command failed",
                style=title_style,
            )
        else:
            header.append(title_text, style=title_style)
        suffix = status
        if exit_code is not None:
            suffix = f"{suffix} · exit {exit_code}" if suffix else f"exit {exit_code}"
        if suffix:
            header.append(
                "  " + suffix,
                style=self._style("muted"),
            )

        card.update(Group(header, *blocks))
        card.remove_class("running")
        if success:
            card.add_class("success")
        else:
            card.add_class("error")

        if pin_after_update:
            await self._pin_activity_indicator_to_end()

    async def confirmation_callback(self, confirmation) -> bool:
        if (
            self._remote_server is not None
            and self._remote_server.is_running
            and self._remote_server.has_authenticated_clients()
            and self.agent
            and self.agent.session
        ):
            approved = await self._remote_server.request_approval(
                serialize_approval_request(
                    request_id="",
                    tool_name=str(confirmation.tool_name or "tool"),
                    description=str(confirmation.description or ""),
                    command=confirmation.command,
                    diff=confirmation.diff.to_diff() if confirmation.diff else None,
                    session_id=self._active_session_id()
                    or self.agent.session.session_id,
                )
            )
            if approved is not None:
                await self._broadcast_remote_state()
                return approved
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

            result = await self._present_plan_question_with_remote(
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
        runtime = getattr(
            getattr(self.agent, "session", None), "subagent_runtime", None
        )
        if runtime is not None and hasattr(runtime, "cancel"):
            try:
                await runtime.cancel(run_ids=None)
            except Exception:
                pass
        self._active_turn_task = None
        self._is_turn_running = False
        await self._clear_inflight_turn_ui()
        self._set_loading_state("idle", busy=False)
        await self._broadcast_remote_state()

    async def start_new_thread(self) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            return

        current_session_id = self._active_session_id()
        if self.agent.session.turn_count == 0:
            return

        reusable_empty_session_id = self._find_reusable_empty_session_id(
            exclude_session_id=current_session_id,
        )
        if reusable_empty_session_id:
            await self._activate_open_session(reusable_empty_session_id)
            return

        if (
            self.agent.session.turn_count > 0
            and not self._run_state(current_session_id).is_turn_running
        ):
            await self.auto_save()

        fresh = Session(config=self.config)
        fresh_agent = self._build_session_agent(fresh)
        await fresh_agent.__aenter__()
        self._remember_open_session(fresh, agent=fresh_agent)
        self.agent = fresh_agent
        self.refresh_header()

        conversation = self.query_one("#conversation", VerticalScroll)
        await conversation.remove_children()

        self._message_count = 0
        self._reset_session_local_ui_state()
        self._suppress_agents_recommendation_once = True
        self._refresh_empty_state()
        await self._broadcast_remote_state()

    async def close_current_thread(self) -> None:
        await self.ensure_agent()
        if not self.agent or not self.agent.session:
            return

        if len(self._open_session_order) <= 1:
            self.post_notice("Exit", "Use `/exit` or `/quit` to close iTE.")
            return

        current_session = self.agent.session
        current_session_id = self._active_session_id()
        if not current_session_id:
            return

        is_running = self._run_state(current_session_id).is_turn_running
        title = self._session_title(current_session)
        body_lines = [f"Close `{title}`?"]
        if is_running:
            body_lines.append("The current run will be stopped first.")
        body_lines.append(
            "This thread will be closed completely and removed from the open tabs."
        )
        confirmed = await self._open_modal(
            ConfirmModal(
                title="Close current thread?",
                body="\n\n".join(body_lines),
                yes_label="Close",
                no_label="Keep",
            )
        )
        if not confirmed:
            return

        if is_running:
            await self.cancel_active_turn()

        next_session_id = self._neighbor_session_id_for_close(current_session_id)
        SessionManager().delete_session(current_session_id)

        self._open_sessions.pop(current_session_id, None)
        self._open_session_workspaces.pop(current_session_id, None)
        self._open_session_order = [
            sid for sid in self._open_session_order if sid != current_session_id
        ]
        self._session_run_states.pop(current_session_id, None)
        closed_agent = self._session_agents.pop(current_session_id, None)

        if next_session_id:
            await self._activate_open_session(next_session_id)
        else:
            fresh = Session(config=self.config)
            fresh_agent = self._build_session_agent(fresh)
            await fresh_agent.__aenter__()
            self._remember_open_session(fresh, agent=fresh_agent)
            self.agent = fresh_agent
            self.refresh_header()
            conversation = self.query_one("#conversation", VerticalScroll)
            await conversation.remove_children()
            self._message_count = 0
            self._reset_session_local_ui_state()
            self._refresh_empty_state()

        if closed_agent is not None:
            try:
                await closed_agent.__aexit__(None, None, None)
            except Exception:
                pass
        await self._broadcast_remote_state()

    async def auto_save(self) -> None:
        if not self.agent or not self.agent.session:
            return

        session = self.agent.session
        if session.turn_count == 0:
            return

        if session.name is None:
            session.set_auto_name(await self.generate_session_name(session))
            self.refresh_header()
        elif session.should_refresh_auto_name():
            refreshed = await self.generate_session_name(session)
            if refreshed and refreshed.strip() and refreshed.strip() != session.name:
                session.set_auto_name(refreshed)
                self.refresh_header()

        snapshot = SessionSnapshot(
            **session.snapshot_kwargs(workspace_path=str(self.config.cwd.resolve()))
        )
        SessionManager().save_session(snapshot)

    async def generate_session_name(self, session: Session) -> str:
        first_user = ""
        try:
            context = session.name_generation_context()
            first_user = context.get("first_user", "")
            first_assistant = context.get("first_assistant", "")
            latest_user = context.get("latest_user", "")
            focus_hint = context.get("focus_hint", "")

            if not first_user:
                return "New thread"

            naming_messages = [
                {
                    "role": "user",
                    "content": (
                        "Generate a concise 3-6 word title for this conversation. "
                        "Prefer the current active work focus over the initial exploratory question if they differ. "
                        "Reply with ONLY the title text, nothing else. No quotes, no punctuation at the end.\n\n"
                        f"Initial user: {first_user}\n"
                        + (
                            f"Initial assistant: {first_assistant}\n"
                            if first_assistant
                            else ""
                        )
                        + (f"Latest user: {latest_user}\n" if latest_user else "")
                        + (f"Active focus: {focus_hint}" if focus_hint else "")
                    ),
                }
            ]

            title = ""
            async for event in session.client.chat_completion(
                naming_messages,
                tools=None,
                stream=False,
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
    if sys.stdout.isatty():
        sys.stdout.write("\n")
        sys.stdout.flush()
