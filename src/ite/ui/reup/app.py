from __future__ import annotations

import asyncio
import contextlib
import difflib
import hashlib
import inspect
import io
import json
import os
import re
import shlex
import signal
import ssl
import subprocess
import sys
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Iterable, Literal, cast
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
from ite.model_metadata import detect_vision_from_model_name
from ite.cloud import (
    CloudAuthError,
    CloudConnectionError,
    CloudSessionState,
    clear_cloud_auth,
    ensure_cloud_auth,
    get_activity,
    get_bundled_models_result,
    get_cloud_auth_status,
    get_cloud_entitlements_result,
    get_remote_companion_access_status,
    get_usage_summary,
    has_stored_cloud_auth,
    is_cloud_api_reachable,
    is_cloud_signed_out,
    mark_cloud_signed_out,
)
from ite.cloud.services import generate_cloud_session_title
from ite.commands import build_registry
from ite.commands.aside import execute_aside, is_aside_command_text
from ite.config.config import DEFAULT_CONTEXT_WINDOW, ApprovalPolicy, Config
from ite.config.loader import (
    get_workspace_agents_recommendation,
    load_config,
    load_saved_custom_provider,
    load_theme,
    remove_saved_custom_provider,
    save_cloud_settings,
    save_global_approval_mode,
    save_onboarding_settings,
    save_saved_custom_provider,
    save_system_config,
    save_theme,
    save_voice_settings,
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
from ite.tools.builtin.shell import send_input_to_shell_run
from ite.tools.mcp.mcp_tool import MCPTool
from ite.tools.subagent import SubagentTool
from ite.ui.reup.markdown_widget import CopyableMarkdown
from ite.ui.tool_narrative import activity_title, describe_tool_activity, progress_label
from ite.update_check import (
    check_runtime_update,
    current_runtime_version,
    detect_install_method,
    get_notification_type,
    mark_update_notice_seen,
    should_show_update_notice,
)
from ite.voice import VoiceRecorder, VoiceRecorderError, transcribe_voice_file

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
    build_sandbox_command_renderable,
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
    flow_control_text,
    render_command_palette,
    render_turn_action_palette,
    send_control_text,
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
    VoiceSetupModal,
)
from .model_labels import bundled_model_display_label
from .tool_views import (
    compact_tool_preview_blocks,
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

LEGACY_BUNDLED_MODEL_ALIASES: dict[str, str] = {
    "kimi-k2.5:cloud": "moonshotai/kimi-k2.5",
    "kimi-k2.6:cloud": "moonshotai/kimi-k2.6",
    "minimax-m2.5:cloud": "minimax/minimax-m2.5",
    "minimax-m2.7:cloud": "minimax/minimax-m2.7",
    "minimax-m3:cloud": "minimax/minimax-m3",
    "glm-5:cloud": "z-ai/glm-5",
    "glm-5.1:cloud": "z-ai/glm-5.1",
}

CLOUD_NETWORK_ONLINE_PROBE_INTERVAL_SEC = 30.0
CLOUD_NETWORK_OFFLINE_FAILURE_THRESHOLD = 3

_VOICE_TRANSCRIPTION_MAX_RETRIES = 2

_MAX_PATH_LENGTH = 255  # macOS filename component limit — guard against paste-as-path


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


from ._cloud import CloudMixin
from ._panels import PanelsMixin
from ._composer import ComposerMixin
from ._threads import ThreadsMixin
from ._turn import TurnMixin
from ._streaming import StreamingMixin
from .settings import SettingsPanel
from .widgets.prompt_area import ReupPromptTextArea
from .widgets.message_row import UserMessageRow
from .widgets.state import SessionRunState, ShellSessionCardState
from .adapters.tui_adapter import ReupTUIAdapter
from .widgets.tool_cards import CompactToolCard, ShellToolCard, ToolCardStack
from .widgets.remote_bridge import RemoteBridgeCard, RemoteBridgeField, UpdateCommandBox
from .widgets.side_panels import (
    ChangeReviewSidePanel,
    CommandsSidePanel,
    GoalSidePanel,
    HooksSidePanel,
)
from .widgets.thread_switcher import ThreadSwitcherRow, ThreadSwitcherSidePanel
from .widgets.system_commands import ReupSystemCommandsProvider
from ._helpers import _is_transient_voice_error, insert_voice_text_into_widget, redact_sensitive_command_text, _skills_action_title

class ReupApp(CloudMixin, PanelsMixin, ComposerMixin, ThreadsMixin, TurnMixin, StreamingMixin, App):
    CSS_PATH: ClassVar[list[str]] = [
        "styles/base.tcss",
        "styles/workspace.tcss",
        "styles/conversation.tcss",
        "styles/modals.tcss",
        "styles/settings.tcss",
        "styles/modal_details.tcss",
        "styles/shared.tcss",
        "styles/update_required.tcss",
    ]
    TITLE = "iTE"
    BINDINGS = [
        Binding("ctrl+enter", "send", "Send"),
        Binding("ctrl+c", "interrupt_or_quit", "Interrupt", priority=True),
        Binding("ctrl+l", "clear_input", "Clear Input"),
        Binding("ctrl+s", "toggle_voice_input", "Flow"),
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
    GIT_POLL_TIMEOUT_SECONDS = 2.0

    # Re-export @on handlers from mixins so Textual's metaclass discovers them.
    # Textual only looks at cls.__dict__, not MRO, so handlers defined on
    # CloudMixin/PanelsMixin/etc. (which inherit from object) are invisible.
    on_aside_toggle_pressed = PanelsMixin.on_aside_toggle_pressed
    on_change_review_close_pressed = PanelsMixin.on_change_review_close_pressed
    on_change_review_commit = PanelsMixin.on_change_review_commit
    on_change_review_discard_all = PanelsMixin.on_change_review_discard_all
    on_change_review_discard_file = PanelsMixin.on_change_review_discard_file
    on_change_review_node_highlighted = PanelsMixin.on_change_review_node_highlighted
    on_change_review_node_selected = PanelsMixin.on_change_review_node_selected
    on_change_review_stage_all = PanelsMixin.on_change_review_stage_all
    on_change_review_stage_file = PanelsMixin.on_change_review_stage_file
    on_change_review_unstage_file = PanelsMixin.on_change_review_unstage_file
    on_changes_toggle_pressed = PanelsMixin.on_changes_toggle_pressed
    on_goal_panel_clear_requested = PanelsMixin.on_goal_panel_clear_requested
    on_goal_panel_close_requested = PanelsMixin.on_goal_panel_close_requested
    on_goal_panel_edit_requested = PanelsMixin.on_goal_panel_edit_requested
    on_goal_panel_edit_saved = PanelsMixin.on_goal_panel_edit_saved
    on_goal_panel_pause_requested = PanelsMixin.on_goal_panel_pause_requested
    on_goal_panel_resume_requested = PanelsMixin.on_goal_panel_resume_requested
    on_goal_toggle_pressed = PanelsMixin.on_goal_toggle_pressed
    on_cloud_exit_pressed = CloudMixin.on_cloud_exit_pressed
    on_cloud_sign_in_pressed = CloudMixin.on_cloud_sign_in_pressed
    on_cloud_skip_sign_in_pressed = CloudMixin.on_cloud_skip_sign_in_pressed
    on_command_palette_click = ComposerMixin.on_command_palette_click
    on_composer_flow_control_click = ComposerMixin.on_composer_flow_control_click
    on_composer_meta_line_click = ComposerMixin.on_composer_meta_line_click
    on_composer_send_control_click = ComposerMixin.on_composer_send_control_click
    on_hooks_toggle_pressed = PanelsMixin.on_hooks_toggle_pressed
    on_onboarding_continue_pressed = CloudMixin.on_onboarding_continue_pressed
    on_onboarding_input_submitted = CloudMixin.on_onboarding_input_submitted
    on_onboarding_role_select_changed = CloudMixin.on_onboarding_role_select_changed
    on_onboarding_skip_pressed = CloudMixin.on_onboarding_skip_pressed
    on_onboarding_use_case_select_changed = CloudMixin.on_onboarding_use_case_select_changed
    on_plan_badge_click = ComposerMixin.on_plan_badge_click
    on_plan_question_button_pressed = ComposerMixin.on_plan_question_button_pressed
    on_plan_question_custom_submitted = ComposerMixin.on_plan_question_custom_submitted
    on_plan_ready_implement = ComposerMixin.on_plan_ready_implement
    on_plan_ready_keep = ComposerMixin.on_plan_ready_keep
    on_prompt_changed = ComposerMixin.on_prompt_changed
    on_session_tab_pressed = TurnMixin.on_session_tab_pressed
    on_thread_switcher_open_settings = ThreadsMixin.on_thread_switcher_open_settings
    on_thread_switcher_row_selected = ThreadsMixin.on_thread_switcher_row_selected
    on_threads_toggle_pressed = PanelsMixin.on_threads_toggle_pressed
    on_update_required_exit_pressed = CloudMixin.on_update_required_exit_pressed

    @staticmethod
    def is_macos_terminal_app() -> bool:
        """True when running inside macOS Terminal.app.

        Terminal.app is the only mainstream macOS terminal that cannot
        distinguish Shift+Enter from Enter at the input layer (it sends the
        same CR byte for both). This means no TUI, including iTE, can bind
        a distinct Shift+Enter gesture inside Terminal.app.

        Other macOS terminals (iTerm2 in non-legacy mode, WezTerm, Ghostty,
        Alacritty, the VS Code integrated terminal, and the JetBrains
        terminal) do transmit a distinct Shift+Enter.
        """
        return (
            sys.platform == "darwin"
            and os.environ.get("TERM_PROGRAM", "") == "Apple_Terminal"
        )

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.title = "iTE"
        self.config = config
        self.agent: Agent | None = None
        self._session_agents: dict[str, Agent] = {}
        self._session_run_states: dict[str, SessionRunState] = {}
        self._session_name_refinements: set[str] = set()
        self._fallback_run_state = SessionRunState()
        self._macos_terminal_hint_shown: bool = False
        self._command_registry = None
        self._command_registry_ready: bool = False
        self._command_registry_loading: bool = False
        self._streaming_widget: Widget | None = None
        self._streaming_buffer: str = ""
        self._tool_widgets: dict[str, Widget] = {}
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
        self._rewriting_dropped_path: bool = False
        self._voice_recorder: VoiceRecorder | None = None
        self._voice_target: Widget | None = None
        self._voice_busy: bool = False
        self._top_busy: bool = False
        self._top_spinner_index: int = 0
        self._top_spinner_frames: tuple[str, ...] = (
            "▰▱▱▱▱",
            "▱▰▱▱▱",
            "▱▱▰▱▱",
            "▱▱▱▰▱",
            "▱▱▱▱▰",
            "▱▱▱▰▱",
            "▱▱▰▱▱",
            "▱▰▱▱▱",
        )
        self._activity_suffix_frames: tuple[str, ...] = ("", ".", "..", "...")
        self._activity_suffix_index: int = 0
        self._aside_gerund_index: int = 0
        self._top_state_text: str = ""
        self._activity_widget: Static | None = None
        self._live_compaction_card: Container | None = None
        self._live_compaction_body: Static | None = None
        self._live_compaction_active: bool = False
        self._activity_resume_timer = None
        self._activity_version: int = 0
        self._hydrating_from_snapshot: bool = (
            False  # Skip activity indicator updates during bulk hydration
        )
        self._empty_state_cached_thread_count: int = 0
        self._cloud_signed_out: bool = False
        self._cloud_auth_busy: bool = False
        self._cloud_bootstrap_busy: bool = False
        self._cloud_network_probe_in_flight: bool = False
        self._cloud_network_last_probe_at: float = 0.0
        self._cloud_network_watch_enabled: bool = False
        self._cloud_network_was_unreachable: bool = False
        self._cloud_network_unreachable_probe_count: int = 0
        self._cloud_signed_out_status_message: str = ""
        self._session_switching: bool = (
            False  # Show centered spinner during session switch
        )
        self._ensure_agent_lock = asyncio.Lock()
        self._bundled_models_cache: list[dict[str, Any]] = []
        self._bundled_access_denied: bool = False
        self._account_plan_is_pro: bool | None = None
        self._account_plan_unavailable: bool = False
        self._cloud_user_email: str | None = None
        self._cloud_user_name: str | None = None
        self._cloud_user_image: str | None = None
        self._usage_summary_cache: dict[str, Any] | None = None
        self._activity_cache: dict[str, Any] | None = None
        self._startup_active: bool = False
        self._settings_active: bool = False
        self._startup_phase_text: str = "Preparing your workspace"
        self._startup_error_text: str | None = None
        self._onboarding_active: bool = False
        self._onboarding_busy: bool = False
        self._onboarding_skip_busy: bool = False
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
        self._composer_reasoning_hitbox: tuple[int, int] = (0, 0)
        self._composer_plan_hitbox: tuple[int, int] = (0, 0)
        self._composer_branch_hitbox: tuple[int, int] = (0, 0)
        self._composer_usage_hitbox: tuple[int, int] | None = None
        self._composer_context_hitbox: tuple[int, int] = (0, 0)
        self._composer_activity_hitbox: tuple[int, int] = (0, 0)
        self._send_meta_frame: int = 0
        self._composer_flow_hitbox: tuple[int, int] = (0, 0)
        self._flow_meta_frame: int = 0
        self._usage_remaining_percent: int | None = None
        self._usage_refresh_in_flight: bool = False
        self._usage_poll_active: bool = False
        self._runtime_update_check_in_flight: bool = False
        self._required_update_notice: Any | None = None
        self._bundled_access_announced: bool = False
        self._last_bundled_access_notice_at: float | None = None
        self._remote_access_cache: tuple[Any, float] | None = None
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
        self._last_change_review_git_poll: float = 0.0
        self._change_review_refresh_in_flight: bool = False
        self._last_status_hash: str = ""
        self._last_status_cwd: Path | None = None
        self._cached_git_cwd: Path | None = None
        self._cached_is_git_repo: bool = False
        self._cached_branch_label: str = "no-git"
        self._cached_git_ts: float = 0.0
        self._head_mtime: float = 0.0
        self._suppress_pending_restore_once: bool = False
        self._open_sessions: dict[str, Session] = {}
        self._open_session_order: list[str] = []
        self._open_session_workspaces: dict[str, Path] = {}
        self._session_tabs_version: int = 0
        self._thread_switcher_panel: ThreadSwitcherSidePanel | None = None
        self._thread_switcher_dismissed_count: int = 0
        self._thread_switcher_sync_lock = asyncio.Lock()
        self._thread_nav_order: list[str] = []
        self._shutdown_started: bool = False
        self._sigint_handled: bool = False
        self._suppress_theme_prompt_sync: bool = False
        self._remote_server: RemoteRuntimeServer | None = None
        self._telegram_service: Any = None  # TelegramBotService | None (deferred import)
        self._suppress_telegram_user_echo: bool = False
        self._remote_port_preference: int = 0
        self._commands_panel: CommandsSidePanel | None = None
        self._change_review_panel: ChangeReviewSidePanel | None = None
        self._goal_panel: GoalSidePanel | None = None
        self._goal_clear_confirmation_open: bool = False
        self._hooks_panel: HooksSidePanel | None = None
        self._hooks_snapshot_key: tuple[Any, ...] | None = None
        self._hooks_panel_layout_key: tuple[Any, ...] | None = None
        self._hooks_run_widgets: dict[str, Static] = {}
        self._agents_recommendation_last_workspace_key: str | None = None
        self._agents_recommendation_current_visit: tuple[str, str] | None = None
        self._suppress_agents_recommendation_once: bool = False
        self._remote_command_feed: list[dict[str, Any]] = []
        self._remote_command_seq: int = 0
        self._remote_change_feed: list[dict[str, Any]] = []
        self._remote_change_seq: int = 0

    def _handle_exception(self, error: Exception) -> None:
        import ssl

        error_str = str(error)

        transient_markers = (
            "SSLV3_ALERT_BAD_RECORD_MAC",
            "ssl/tls alert bad record mac",
            "CERTIFICATE_VERIFY_FAILED",
            "SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC",
            "Connection reset by peer",
            "Remote end closed connection",
            "Broken pipe",
        )
        is_transient_network = any(
            marker.lower() in error_str.lower() for marker in transient_markers
        )

        if isinstance(error, (CloudConnectionError, ssl.SSLError)) or is_transient_network:
            if self._exception is None:
                self._exception = error
                self._exception_event.set()
            return

        super()._handle_exception(error)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="shell"):
            with Horizontal(id="topbar"):
                yield Button("≡", id="threads-toggle", variant="default")
                yield Static("New thread", id="title")
                with Horizontal(id="header-meta-group"):
                    yield Static("", id="plan-badge")
                    yield Button("", id="goal-toggle", variant="default")
                    yield Static("", id="header-meta")
                yield Button("/changes", id="changes-toggle", variant="default")
                yield Button("/hooks", id="hooks-toggle", variant="default")
                yield Button("/aside", id="aside-toggle", variant="default")
            with HorizontalScroll(id="session-tabs-scroll"):
                yield Horizontal(id="session-tabs")
            with Container(id="chat-panel"):
                with Horizontal(id="chat-body"):
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
                        with Container(id="session-switch-state"):
                            with Vertical(id="session-switch-stack"):
                                yield Static("", id="session-switch-spinner")
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
                        with Container(id="update-required-state"):
                            with Vertical(id="update-required-stack"):
                                yield Static(
                                    "Update required", id="update-required-title"
                                )
                                yield Static("", id="update-required-copy")
                                yield UpdateCommandBox()
                                yield Static("", id="update-required-meta")
                                with Horizontal(id="update-required-actions"):
                                    yield Button(
                                        "Exit",
                                        id="update-required-exit",
                                        variant="default",
                                    )
                        with Container(id="onboarding-state"):
                            with Vertical(id="onboarding-stack"):
                                yield Static(
                                    "Welcome to iTE",
                                    id="onboarding-title",
                                )
                                yield Static(
                                    "A quick setup before you start. Tell iTE a little about you so it can tailor the workspace.",
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
                    with Horizontal(id="prompt-row"):
                        yield ReupPromptTextArea(id="prompt", language="markdown")
                        yield Static("", id="composer-flow-control")
                        yield Static("", id="composer-send-control")
                    yield Static("", id="command-palette")
                    yield Static("", id="composer-gap")
                    yield Static("", id="composer-meta-line")
            yield SettingsPanel(id="settings-panel")
        yield Footer()

    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to clipboard.

        Warp and some other terminals don't support OSC 52 clipboard protocol.
        Use pbcopy directly on macOS as a reliable fallback.
        """
        # Try pbcopy first on macOS - this is the most reliable method
        if sys.platform == "darwin":
            try:
                import subprocess

                proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                proc.communicate(input=text.encode("utf-8"))
                if proc.returncode == 0:
                    return
            except Exception:
                pass

        # Fallback to pyperclip
        try:
            import pyperclip

            pyperclip.copy(text)
            return
        except Exception:
            pass

        # Last resort: try Textual's OSC 52
        super().copy_to_clipboard(text)

    async def on_mount(self) -> None:
        saved_theme = load_theme()
        self._suppress_theme_prompt_sync = True
        try:
            self.theme = saved_theme or detect_host_textual_theme()
        finally:
            self._suppress_theme_prompt_sync = False
        # macOS Terminal.app cannot distinguish Shift+Enter from Enter at the
        # input layer, so any Shift+Enter press there looks identical to
        # pressing Enter (which submits the prompt). Surface a one-time
        # notice telling the user to use Ctrl+J for new lines.
        if self.is_macos_terminal_app() and not self._macos_terminal_hint_shown:
            self._macos_terminal_hint_shown = True
            self.post_notice(
                "macOS Terminal",
                "Shift+Enter sends the same byte as Enter in macOS Terminal.app, "
                "so it cannot insert a newline here. Use Ctrl+J for new lines, "
                "or run iTE in iTerm2/WezTerm/Ghostty/VS Code to use Shift+Enter.",
                timeout=10,
            )
        self.query_one("#aside-toggle", Button).display = False
        self.query_one("#changes-toggle", Button).display = False
        try:
            self.query_one("#hooks-toggle", Button).display = False
        except Exception:
            pass
        try:
            self.query_one("#threads-toggle", Button).display = False
        except Exception:
            pass
        if self.config.cloud_auth_enabled:
            self._cloud_bootstrap_busy = True
        if not self.config.cloud_auth_enabled:
            self._set_local_account_plan_state(refresh=False)
        self.refresh_header()
        self._set_loading_state("idle", busy=False)
        self._refresh_empty_state()
        self._resize_composer_for_prompt()
        try:
            self.query_one("#prompt", TextArea).focus()
        except (AttributeError, NoMatches, ScreenStackError):
            pass
        self._apply_aside_panel_state()
        self._apply_change_review_panel_state()
        self._apply_hooks_panel_state()
        self.set_interval(0.15, self._tick_top_indicator)
        self.set_interval(1.0, self._tick_goal_display)
        self.set_interval(4.5, self._tick_aside_gerund)
        self.set_interval(0.35, self._tick_live_context_meter)
        self.set_interval(0.35, self._poll_hooks_panel)
        self.set_interval(1.0, self._maybe_probe_cloud_network_recovery)
        self._change_review_poll_timer = self.set_interval(
            3.0, self._poll_change_review_panel
        )
        self.set_interval(0.3, self._poll_head_change)
        self.run_worker(self._initialize_command_palette(), exclusive=False)
        self.run_worker(self._bootstrap_after_mount(), exclusive=False)
        self._install_sigint_handler()

    def on_resize(self, _event: events.Resize) -> None:
        self._update_composer_meta_line()
        self._resize_composer_for_prompt()

    def _install_sigint_handler(self) -> None:
        app = self

        def _handle_sigint(signum: int, frame: object) -> None:
            if app._sigint_handled:
                os._exit(1)
            app._sigint_handled = True
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(app._perform_quit())
                )
            except RuntimeError:
                os._exit(1)

        signal.signal(signal.SIGINT, _handle_sigint)

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
            explicitly_signed_out = await asyncio.to_thread(is_cloud_signed_out)
            if explicitly_signed_out:
                self._cloud_bootstrap_busy = False
                self._cloud_network_watch_enabled = True
                self._set_startup_state(False)
                self._set_signed_out_state(True)
                self._set_loading_state("idle", busy=False)
                self._schedule_runtime_update_check()
                return

            if self.config.cloud_auth_enabled:
                self._set_startup_phase("Checking iTE Cloud")
                has_cloud_session = await asyncio.to_thread(
                    has_stored_cloud_auth, self.config
                )
                if not has_cloud_session:
                    self._cloud_bootstrap_busy = False
                    self._cloud_network_watch_enabled = True
                    self._set_startup_state(False)
                    self._set_signed_out_state(True)
                    self._set_loading_state("idle", busy=False)
                    self._schedule_runtime_update_check()
                    return
                else:
                    self._set_signed_out_state(False)
                    self._cloud_bootstrap_busy = False
                    self._prefetch_cloud_caches()
                    # Cloud verification is on-demand; startup should not block on network reachability.

            if self._should_show_onboarding():
                self._set_startup_state(False)
                self._set_onboarding_state(True)
                self._set_loading_state("idle", busy=False)
                self._schedule_runtime_update_check()
                self.query_one("#onboarding-name", Input).focus()
                return

            self._set_startup_phase("Starting runtime")
            resumed = await self._resume_last_workspace_session_on_startup()
            if not resumed:
                await self.ensure_agent()
            self._set_startup_state(False)
            self._schedule_usage_meta_refresh()
            self._start_usage_idle_poll()
            await self._refresh_change_review_source()
            self._set_loading_state("idle", busy=False)
            self.query_one("#prompt", TextArea).focus()
            self._sync_command_palette("")
            self._schedule_runtime_update_check()
        except Exception as exc:
            self._cloud_bootstrap_busy = False
            self._set_loading_state("idle", busy=False)
            self._fail_startup(exc)


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
        from ite.ui.reup.command_views import (
            build_mcp_command_renderable,
            build_memory_command_renderable,
            build_memory_prompt_command_renderable,
            build_stats_command_renderable,
            build_subagent_command_renderable,
            build_todos_command_renderable,
            build_tools_command_renderable,
            build_workboard_command_renderable,
        )
        from ite.memory.manager import MemoryManager

        conversation = self.query_one("#conversation", VerticalScroll)
        styles = self._render_styles()
        is_light = self._prefer_terminal_safe_source_rendering()

        async def replace_card_body(
            card: Widget, body_widget: Static, body: Any
        ) -> None:
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
                    if not self.agent or not self.agent.session:
                        continue
                    session = self.agent.session
                    active_ids = {
                        skill.identifier for skill in session.get_active_skills()
                    }
                    new_body = build_skills_overview_renderable(
                        session.skill_manager.list_skills(),
                        active_ids,
                        styles=styles,
                    )
                    body_widget.update(new_body)
                except Exception:
                    pass

            # Re-render tools cards
            if child.has_class("tools"):
                try:
                    body_widget = child.query_one(".card-body", Static)
                    if not self.agent or not self.agent.session:
                        continue
                    new_body = build_tools_command_renderable(
                        self.agent.session.tool_registry.get_tools(),
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

            # Re-render sandbox cards
            if child.has_class("sandbox"):
                try:
                    body_widget = child.query_one(".card-body", Static)
                    sandbox_config = self._sandbox_render_config()
                    new_body = build_sandbox_command_renderable(
                        enabled=sandbox_config.sandbox.enabled,
                        allowed_paths=[
                            str(p) for p in sandbox_config.sandbox.allowed_paths
                        ],
                        cwd=str(sandbox_config.cwd),
                        styles=styles,
                    )
                    await replace_card_body(child, body_widget, new_body)
                except Exception:
                    pass

            # Re-render todos cards
            if child.has_class("todos"):
                try:
                    body_widget = child.query_one(".card-body", Static)
                    if not self.agent or not self.agent.session:
                        continue
                    new_body = build_todos_command_renderable(
                        self.agent.session,
                        styles=styles,
                    )
                    await replace_card_body(child, body_widget, new_body)
                except Exception:
                    pass

            # Re-render mcp cards
            if child.has_class("mcp"):
                try:
                    body_widget = child.query_one(".card-body", Static)
                    if not self.agent or not self.agent.session:
                        continue
                    new_body = build_mcp_command_renderable(
                        self.agent.session.mcp_manager.get_all_servers(),
                        styles=styles,
                    )
                    await replace_card_body(child, body_widget, new_body)
                except Exception:
                    pass

            # Re-render subagents cards
            if child.has_class("subagents"):
                try:
                    body_widget = child.query_one(".card-body", Static)
                    if not self.agent or not self.agent.session:
                        continue
                    from ite.tools.subagent import SubagentTool
                    tools = self.agent.session.tool_registry.get_tools()
                    subagent_tools = [t for t in tools if isinstance(t, SubagentTool)]
                    subagents = [t.definition for t in subagent_tools]
                    new_body = build_subagent_command_renderable(
                        subagents,
                        styles=styles,
                    )
                    await replace_card_body(child, body_widget, new_body)
                except Exception:
                    pass

            # Re-render workboard cards
            if child.has_class("workboard"):
                try:
                    body_widget = child.query_one(".card-body", Static)
                    if not self.agent or not self.agent.session:
                        continue
                    new_body = build_workboard_command_renderable(
                        self.agent.session,
                        styles=styles,
                    )
                    await replace_card_body(child, body_widget, new_body)
                except Exception:
                    pass

            # Re-render memory cards
            if child.has_class("memory"):
                try:
                    body_widget = child.query_one(".card-body", Static)
                    if not self.agent or not self.agent.session:
                        continue
                    session = self.agent.session
                    manager = MemoryManager(
                        self.config.cwd, session_id=session.session_id
                    )
                    new_body = build_memory_command_renderable(
                        session_id=session.session_id,
                        workspace=str(self.config.cwd),
                        controls=manager.load_active_controls(),
                        long_term=manager.list_entries("long_term"),
                        semantic=manager.list_entries("semantic"),
                        short_term=manager.list_entries("short_term"),
                        episodic=manager.list_episodes()[-5:],
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
        if (
            not self._change_review_panel_is_open()
            or not self._change_review_change_set
        ):
            return
        panel = self._change_review_panel
        if panel is None:
            return
        tree = panel.query_one("#change-review-tree", ChangedFilesTree)
        # Update tree styles
        tree._styles = self._render_styles()
        # Re-populate with current selection
        current_selection = self._change_review_selected_rel_path
        await self._populate_change_review_panel()

    async def _rerender_hooks_panel_for_theme(self) -> None:
        """Re-render hooks panel Rich text when theme changes."""
        if not self._hooks_panel_is_open():
            return
        await self._populate_hooks_panel(snapshot=self._active_hooks_snapshot())

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
            self.run_worker(self._rerender_assistant_cards_for_theme(), exclusive=False)
            if self._change_review_panel_is_open():
                self.run_worker(
                    self._rerender_change_review_for_theme(), exclusive=False
                )
            if self._hooks_panel_is_open():
                self.run_worker(self._rerender_hooks_panel_for_theme(), exclusive=False)

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
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        if self._voice_recorder is not None:
            await self._voice_recorder.cancel()
            self._voice_recorder = None
        await self._shutdown_remote_server()
        await self._shutdown_telegram_service()
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

        async def _close_agent(agent: Agent) -> None:
            try:
                await asyncio.wait_for(agent.__aexit__(None, None, None), timeout=2.0)
            except Exception:
                pass

        await asyncio.gather(
            *(_close_agent(agent) for agent in agents_to_close.values()),
            return_exceptions=True,
        )

        if self.agent is not None:
            self.agent = None

    async def _shutdown_remote_server(self) -> None:
        if self._remote_server is None:
            return
        remote_server = self._remote_server
        try:
            await asyncio.wait_for(remote_server.stop(), timeout=1.5)
        except Exception:
            pass
        finally:
            self._remote_server = None

    async def _shutdown_telegram_service(self) -> None:
        if self._telegram_service is None:
            return
        service = self._telegram_service
        try:
            await asyncio.wait_for(service.stop(), timeout=3)
        except Exception:
            pass
        finally:
            self._telegram_service = None


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
        await self._dedupe_activity_indicators(conversation)
        content = self._render_activity_indicator_text(label)
        widget = self._activity_widget
        mounted_new_widget = False
        if self._activity_widget is None:
            widget = Static(classes="activity-indicator")
            self._activity_widget = widget
            await conversation.mount(widget)
            mounted_new_widget = True
            self._message_count += 1
            self._refresh_empty_state()
        if (
            widget is None
            or self._activity_widget is not widget
            or (version is not None and version != self._activity_version)
        ):
            if mounted_new_widget:
                try:
                    await widget.remove()
                except Exception:
                    pass
                self._message_count = max(0, self._message_count - 1)
                self._refresh_empty_state()
                if self._activity_widget is widget:
                    self._activity_widget = None
            return
        widget.update(content)
        await self._pin_activity_indicator_to_end()

    async def _pin_activity_indicator_to_end(self) -> None:
        # Skip during bulk hydration - we'll scroll once at the end
        if self._hydrating_from_snapshot:
            return
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

    async def _dedupe_activity_indicators(
        self, conversation: VerticalScroll | None = None
    ) -> None:
        if conversation is None:
            conversation = self.query_one("#conversation", VerticalScroll)
        indicators = [
            child
            for child in list(conversation.children)
            if child.has_class("activity-indicator")
        ]
        if not indicators:
            if (
                self._activity_widget is not None
                and self._activity_widget.parent is None
            ):
                self._activity_widget = None
            return
        keep = self._activity_widget if self._activity_widget in indicators else None
        if keep is None:
            keep = indicators[-1]
            self._activity_widget = keep
        removed = 0
        for indicator in indicators:
            if indicator is keep:
                continue
            try:
                await indicator.remove()
                removed += 1
            except Exception:
                pass
        if removed:
            self._message_count = max(0, self._message_count - removed)
            self._refresh_empty_state()

    async def _hide_activity_indicator(self, version: int | None = None) -> None:
        if version is not None and version != self._activity_version:
            return
        conversation = self.query_one("#conversation", VerticalScroll)
        indicators = [
            child
            for child in list(conversation.children)
            if child.has_class("activity-indicator")
        ]
        if (
            self._activity_widget is not None
            and self._activity_widget not in indicators
        ):
            indicators.append(self._activity_widget)
        removed = 0
        for indicator in indicators:
            try:
                await indicator.remove()
                removed += 1
            except Exception:
                pass
        self._activity_widget = None
        if removed:
            self._message_count = max(0, self._message_count - removed)
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
        content = Text()
        content.append(frame, style=f"bold {styles['success']}")
        content.append(" ")
        content.append(
            (label or "Thinking").strip().title() or "Thinking",
            style=f"bold {styles['fg']}",
        )
        return content


    def action_quit(self) -> None:
        """Confirm before quitting the app."""
        self.run_worker(self._confirm_quit(), exclusive=False)


    async def _open_modal(self, screen: ModalScreen[Any]) -> Any:
        """Open a modal and await dismissal from regular event handlers safely."""
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[Any] = loop.create_future()

        def _on_dismiss(result: Any) -> None:
            if not result_future.done():
                result_future.set_result(result)

        self.push_screen(screen, callback=_on_dismiss)
        result = await result_future
        self._maybe_focus_prompt()
        return result

    async def _perform_quit(self) -> None:
        self._resolve_pending_plan_question(empty=True)
        try:
            await asyncio.wait_for(
                self.auto_save(allow_name_generation=False),
                timeout=1.0,
            )
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


# Re-exports for backwards compatibility — tests and modals.py import these from app.py
from .widgets.prompt_area import ReupPromptTextArea  # noqa: F811
from .widgets.message_row import UserMessageRow  # noqa: F811
from .widgets.side_panels import ChangeReviewSidePanel  # noqa: F811
from .widgets.tool_cards import pluralize_tool_title  # noqa: F811
from ._helpers import insert_voice_text_into_widget, redact_sensitive_command_text  # noqa: F811
from ._cloud import (
    CLOUD_NETWORK_OFFLINE_FAILURE_THRESHOLD,
    CLOUD_NETWORK_ONLINE_PROBE_INTERVAL_SEC,
    ONBOARDING_OTHER_VALUE,
)


def run_reup(config: Config) -> None:
    app = ReupApp(config)
    app.run()
    if sys.stdout.isatty():
        sys.stdout.write("\n")
        sys.stdout.flush()
