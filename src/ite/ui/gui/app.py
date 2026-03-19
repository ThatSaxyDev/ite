from __future__ import annotations

import asyncio
import re
import flet as ft
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Awaitable, Callable

from ite.agent.agent import Agent
from ite.attachment_refs import resolve_inline_attachment_refs
from ite.attachments import (
    Attachment,
    AttachmentManager,
    MAX_ATTACHMENTS,
    build_user_model_content,
)
from ite.commands.aside import is_aside_command_text
from ite.commands import build_registry
from ite.config.config import Config
from ite.config.loader import save_system_config
from ite.config.config import DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_MODEL_NAME
from ite.tools.base import ToolConfirmation
from ite.ui.tool_narrative import progress_label

from .builders.layout import LayoutBuilderMixin
from .builders.messages import MessageBuilderMixin
from .controllers.scroll import ScrollControllerMixin
from .controllers.workspace import WorkspaceControllerMixin
from .controllers.branch import BranchControllerMixin
from .controllers.approval import ApprovalControllerMixin
from .controllers.sessions import SessionControllerMixin
from .controllers.commands import CommandControllerMixin
from .controllers.agent_events import AgentEventControllerMixin
from .state import GUIState, GUIStateStore
from .tokens import *


class GUIApp(
    LayoutBuilderMixin,
    MessageBuilderMixin,
    ScrollControllerMixin,
    WorkspaceControllerMixin,
    BranchControllerMixin,
    ApprovalControllerMixin,
    SessionControllerMixin,
    CommandControllerMixin,
    AgentEventControllerMixin,
):
    def __init__(self, config: Config):
        self.config = config
        self.agent: Agent | None = None
        self.page: ft.Page | None = None

        self.messages_column: ft.Column | None = None
        self.empty_state_container: ft.Container | None = None
        self.empty_state_title_text: ft.Text | None = None
        self.empty_state_workspace_text: ft.Text | None = None
        self.chat_bottom_spacer: ft.Container | None = None
        self.input_field: ft.TextField | None = None
        self.send_button: ft.IconButton | None = None
        self.attach_button: ft.IconButton | None = None
        self.attachments_row: ft.Row | None = None
        self.loading_indicator: ft.ProgressRing | None = None
        self.model_selector: ft.Control | None = None
        self.model_selector_text: ft.Text | None = None
        self.model_items: list[str] = []
        self.model_picker_dialog: ft.AlertDialog | None = None
        self.empty_workspace_picker_dialog: ft.AlertDialog | None = None
        self.workspace_selector: ft.Dropdown | None = None
        self.branch_selector: ft.Control | None = None
        self.branch_selector_text: ft.Text | None = None
        self.branch_controls_row: ft.Row | None = None
        self.branch_create_button: ft.IconButton | None = None
        self.branch_dialog: ft.AlertDialog | None = None
        self.branch_name_input: ft.TextField | None = None
        self.branch_picker_dialog: ft.AlertDialog | None = None
        self.branch_picker_search: ft.TextField | None = None
        self.branch_picker_list: ft.Column | None = None
        self.branch_items: list = []
        self.current_branch_name: str | None = None
        self.branch_loading: bool = False
        self.plan_toggle_button: ft.TextButton | None = None
        self.plan_mode_badge: ft.Text | None = None
        self._plan_question_future: asyncio.Future | None = None
        self._plan_confirm_future: asyncio.Future | None = None
        self._plan_question_count: int = 0
        self._branch_workspace_key: str | None = None
        self._branch_sync_task: asyncio.Task | None = None
        self._branch_sync_running: bool = False
        self.approval_selector: ft.Dropdown | None = None
        self.header_session_text: ft.Text | None = None
        self.header_workspace_text: ft.Text | None = None
        self.current_session_title: str = "New thread"
        self.sidebar_threads_column: ft.Column | None = None
        self.sidebar_root: ft.Container | None = None
        self.sidebar_top_row: ft.Row | None = None
        self.sidebar_new_thread_container: ft.Container | None = None
        self.sidebar_body: ft.Column | None = None
        self.sidebar_toggle_button: ft.IconButton | None = None
        self.sidebar_new_thread_button: ft.TextButton | None = None
        self.sidebar_new_thread_compact: ft.IconButton | None = None
        self.sidebar_workspace_block: ft.Column | None = None
        self.sidebar_threads_label: ft.Text | None = None
        self.sidebar_footer: ft.Container | None = None
        self.sidebar_collapsed: bool = False
        self.active_session_id: str | None = None
        self.loading_session_id: str | None = None
        self._session_hydration_task: asyncio.Task | None = None
        self._hydrating_session_id: str | None = None
        self._sidebar_refresh_task: asyncio.Task | None = None
        self.sidebar_sessions_cache: list[dict] = []
        self.sidebar_sessions_by_id: dict[str, dict] = {}
        self.app_mode: str = "setup" if self.config.needs_setup else "chat"
        self.chat_shell: ft.Row | None = None
        self.chat_workboard_row: ft.Row | None = None
        self.setup_view: ft.Container | None = None
        self.setup_error_text: ft.Text | None = None
        self.setup_base_url_field: ft.TextField | None = None
        self.setup_api_key_field: ft.TextField | None = None
        self.setup_model_field: ft.TextField | None = None

        self.confirmation_dialog: ft.AlertDialog | None = None
        self.pending_confirmation: ToolConfirmation | None = None

        self.streaming_markdown: ft.Markdown | None = None
        self.streaming_container: ft.Container | None = None
        self.streaming_text: str = ""
        self._tool_call_row_indices: dict[str, int] = {}
        self._tool_args_by_call_id: dict[str, dict[str, Any]] = {}
        self._active_turn_task: asyncio.Task | None = None
        self._is_turn_running: bool = False
        self._active_turn_id: int = 0
        self._is_closing: bool = False
        self._plan_ready_prompt_open: bool = False
        self.thinking_row: ft.Row | None = None
        self.thinking_text: ft.Text | None = None
        self.thinking_spinner: ft.ProgressRing | None = None
        self._thinking_task: asyncio.Task | None = None
        self._thinking_label_base: str = "Thinking"

        self._command_registry = build_registry()
        self._auto_scroll_enabled = True
        self._scroll_request_id = 0
        self._defer_ui_updates: bool = False
        self._intent_assist_prompt: str | None = None
        self._intent_assist_kind: str | None = None
        self._intent_assist_row: ft.Control | None = None
        self._last_dispatched_message: str | None = None
        self._last_user_message_for_retry: str | None = None
        self._stop_requested_by_user: bool = False
        self._composer_history: list[str] = []
        self._composer_history_index: int | None = None
        self._composer_history_draft: str = ""
        self._composer_input_focused: bool = False
        self._pending_attachment_paths: list[str] = []
        self.workboard_container: ft.Container | None = None
        self.workboard_body: ft.Column | None = None
        self.workboard_toggle_button: ft.IconButton | None = None
        self.workboard_header_toggle_button: ft.IconButton | None = None
        self.workboard_visible: bool = True
        self.workboard_todos_column: ft.Column | None = None
        self.workboard_todos_section: ft.Container | None = None
        self.workboard_plan_markdown: ft.Markdown | None = None
        self.workboard_plan_section: ft.Container | None = None
        self.workboard_plan_wrapper: ft.Container | None = None
        self.workboard_has_content: bool = False
        self.workboard_width: float = 560.0
        self._last_workboard_todos_signature: tuple | None = None
        self._last_workboard_plan_text: str = ""
        self._last_workboard_has_content: bool = False
        self._last_workboard_visible: bool = True
        self.gui_state = GUIStateStore(initial_workspace=str(self.config.cwd.resolve()))
        self._bind_gui_state_store()

    def _bind_gui_state_store(self):
        self.gui_state.subscribe("shell", self._on_gui_shell_state_changed)
        self.gui_state.subscribe("interaction", self._on_gui_interaction_state_changed)
        self.gui_state.subscribe("session_view", self._on_gui_session_view_state_changed)
        self.gui_state.subscribe("workboard", self._on_gui_workboard_state_changed)

    def _on_gui_shell_state_changed(self, state: GUIState) -> None:
        shell = state.shell
        self.active_session_id = shell.active_session_id
        self.loading_session_id = shell.loading_session_id
        self.sidebar_collapsed = shell.sidebar_collapsed
        self.workboard_visible = shell.workboard_visible

    def _on_gui_interaction_state_changed(self, state: GUIState) -> None:
        interaction = state.interaction
        self._is_turn_running = interaction.is_turn_running
        self._apply_loading_controls()

    def _on_gui_session_view_state_changed(self, state: GUIState) -> None:
        session_view = state.session_view
        self.current_session_title = session_view.current_session_title
        if self.header_session_text:
            self.header_session_text.value = self.current_session_title
            self._safe_control_update(self.header_session_text)
        workspace_text = f"Workspace: {session_view.current_workspace}"
        if self.header_workspace_text and self.header_workspace_text.value != workspace_text:
            self.header_workspace_text.value = workspace_text
            self._safe_control_update(self.header_workspace_text)

    def _on_gui_workboard_state_changed(self, state: GUIState) -> None:
        workboard = state.workboard
        self.workboard_has_content = workboard.has_content
        if self.workboard_todos_section is not None or self.workboard_plan_section is not None:
            todos_signature = self._compute_workboard_todos_signature(
                workboard.todos_state,
                workboard.show_planning_todos,
            )
            plan_text = (workboard.plan_text or "").strip()
            should_refresh_content = (
                todos_signature != self._last_workboard_todos_signature
                or plan_text != self._last_workboard_plan_text
            )
            should_refresh_shell = (
                workboard.has_content != self._last_workboard_has_content
                or self.workboard_visible != self._last_workboard_visible
            )
            if should_refresh_content:
                self._render_workboard_todos_from_state(workboard.todos_state)
                self._set_workboard_plan_text(plan_text)
                self._last_workboard_todos_signature = todos_signature
                self._last_workboard_plan_text = plan_text
            if should_refresh_shell or should_refresh_content:
                self._apply_workboard_state(update=False)
                self._last_workboard_has_content = workboard.has_content
                self._last_workboard_visible = self.workboard_visible

    def _apply_loading_controls(self):
        is_busy = self.loading_session_id is not None
        if self.input_field:
            self.input_field.disabled = is_busy
            self._safe_control_update(self.input_field)
        if self.attach_button:
            self.attach_button.disabled = self._is_turn_running or is_busy
            self._safe_control_update(self.attach_button)
        self._refresh_action_button()

    def _has_active_turn(self) -> bool:
        if self._is_turn_running:
            return True
        task = self._active_turn_task
        return bool(task and hasattr(task, "done") and not task.done())

    def _is_plan_mode_enabled(self) -> bool:
        return bool(
            self.agent and self.agent.session and self.agent.session.plan_mode_enabled
        )

    def _clear_intent_assist_state(self):
        if self._intent_assist_row is not None:
            try:
                self._remove_chat_control(self._intent_assist_row)
            except Exception:
                pass
            self._intent_assist_row = None
        self._intent_assist_prompt = None
        self._intent_assist_kind = None
        self._safe_page_update()

    def _should_suppress_intent_detection(self, message: str, *, plan_enabled: bool) -> bool:
        text = (message or "").strip()
        # Execution intent in plan mode often comes in short imperative phrases
        # (e.g., "lets build"), so keep a lower cutoff there.
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

        # Treat collaborative "let's build/create/design ..." asks as planning-first.
        if bool(re.search(r"\b(let'?s|lets|let us)\s+(build|create|design|architect)\b", text)):
            return True

        # Product-building intent should default to planning assist.
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

        if bool(re.search(r"\b(plan|roadmap|steps)\b", text) and "implement" not in text):
            return True

        return False

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
        # Natural imperative forms should trigger even without explicit "now/this/it".
        if bool(re.search(r"\b(let'?s|lets|let us)\s+(build|built|implement|code|execute)\b", text)):
            return True
        if bool(re.search(r"\b(build|implement|start coding|execute)\b", text) and re.search(r"\b(then|next)\b", text)):
            return True
        return bool(
            re.search(r"\b(implement|build|built|code|execute|apply)\b", text)
            and re.search(r"\b(now|this|it|changes)\b", text)
        )

    def _show_intent_assist_panel(self, kind: str, prompt: str):
        if not self.messages_column:
            return

        self._intent_assist_prompt = prompt
        self._intent_assist_kind = kind

        if kind == "plan":
            title = "Enable Plan Mode?"
            body = "This prompt looks like planning. Switch to Plan mode before sending?"
            primary_label = "Enable Plan Mode"
            secondary_label = "Send Normally"
            primary_action = lambda _e: self.page.run_task(self._intent_accept_plan_mode) if self.page else None
            secondary_action = lambda _e: self.page.run_task(self._intent_send_without_switch) if self.page else None
        else:
            title = "Run In Execution Mode?"
            body = (
                "This prompt looks like execution while Plan mode is ON. "
                "Choose the execution option below or type /plan off to leave Plan mode manually."
            )
            primary_label = "Turn Off Plan Mode & Continue"
            secondary_label = "Stay in Plan Mode"
            primary_action = lambda _e: self.page.run_task(self._intent_disable_plan_mode_and_send) if self.page else None
            secondary_action = lambda _e: self.page.run_task(self._intent_send_without_switch) if self.page else None

        primary_button = ft.FilledButton(
            primary_label,
            on_click=primary_action,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.WHITE, ft.ControlState.HOVERED: "#F3F3F3"},
                color=ft.Colors.BLACK,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )
        secondary_button = ft.OutlinedButton(
            secondary_label,
            on_click=secondary_action,
            style=ft.ButtonStyle(
                side={ft.ControlState.DEFAULT: ft.BorderSide(1, BORDER_STRONG)},
                color=TEXT_SECONDARY,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )

        card = ft.Container(
            width=SPECIAL_CARD_WIDTH,
            border=ft.Border.all(1, HAIRLINE),
            border_radius=RADIUS_MD,
            bgcolor=SURFACE_ELEVATED,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            content=ft.Column(
                [
                    ft.Text(title, size=TYPE_TITLE, color=TEXT_PRIMARY, weight=ft.FontWeight.W_700),
                    ft.Text(body, size=TYPE_BODY, color=TEXT_SECONDARY),
                    ft.Text("Shortcut: Ctrl+Tab toggles Plan Mode", size=TYPE_SM, color=TEXT_MUTED),
                    ft.Row([secondary_button, primary_button], alignment=ft.MainAxisAlignment.END),
                ],
                spacing=8,
                tight=True,
            ),
        )
        row = self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        if self._intent_assist_row is not None:
            try:
                self._remove_chat_control(self._intent_assist_row)
            except Exception:
                pass
        self._intent_assist_row = row
        self._append_chat_control(row)
        self._safe_page_update()
        self._scroll_chat_to_bottom(force=True)

    async def _intent_accept_plan_mode(self):
        prompt = (self._intent_assist_prompt or "").strip()
        if not prompt:
            self._clear_intent_assist_state()
            return
        await self._run_plan_mode_toggle_flow(
            target_enabled=True,
            post_toggle_callback=lambda: self._send_pending_intent_prompt(prompt),
        )

    async def _intent_disable_plan_mode_and_send(self):
        prompt = (self._intent_assist_prompt or "").strip()
        if not prompt:
            self._clear_intent_assist_state()
            return
        await self._run_plan_mode_toggle_flow(
            target_enabled=False,
            post_toggle_callback=lambda: self._send_pending_intent_prompt(prompt),
        )

    async def _intent_send_without_switch(self):
        prompt = (self._intent_assist_prompt or "").strip()
        kind = self._intent_assist_kind
        plan_enabled = self._is_plan_mode_enabled()
        self._clear_intent_assist_state()
        if prompt:
            # If user chose to stay in plan mode from an execution-intent prompt,
            # reframe to planning so the agent quickly enters question/plan flow.
            if kind == "execute" and plan_enabled:
                self._add_assistant_card(
                    "Plan Mode",
                    ft.Text(
                        "Plan mode remains enabled. I will ask clarifying questions and produce a plan. Type /plan off whenever you want to leave Plan mode manually.",
                        color=TEXT_SECONDARY,
                    ),
                )
                prompt = (
                    f"{prompt}\n\n"
                    "Stay in plan mode. Do not execute changes yet. "
                    "Ask clarifying questions first, then provide an implementation plan."
                )
            self._dispatch_message(prompt)

    async def _send_pending_intent_prompt(self, prompt: str):
        self._clear_intent_assist_state()
        cleaned = (prompt or "").strip()
        if cleaned:
            self._dispatch_message(cleaned)

    async def _run_plan_mode_toggle_flow(
        self,
        *,
        target_enabled: bool | None = None,
        announce_shortcut_notice: bool = False,
        post_toggle_callback: Callable[[], Awaitable[None] | None] | None = None,
    ):
        self._clear_intent_assist_state()
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return
        session = self.agent.session

        current = bool(session.plan_mode_enabled)
        desired = (not current) if target_enabled is None else bool(target_enabled)

        if desired != current:
            session.set_plan_mode(desired)
            if desired:
                session.set_plan_phase("idle")
                self._plan_question_count = 0
                await self._show_plan_resume_options_if_available()
            else:
                session.plan_questions_asked = 0
                self._plan_question_count = 0
                self._plan_ready_prompt_open = False
            self._sync_plan_toggle_ui()

        if announce_shortcut_notice:
            self._show_transient_notice(
                "Plan mode enabled." if session.plan_mode_enabled else "Plan mode disabled."
            )

        if post_toggle_callback:
            maybe = post_toggle_callback()
            if asyncio.iscoroutine(maybe):
                await maybe

    def _on_keyboard_event(self, e: ft.KeyboardEvent):
        if self.app_mode != "chat":
            return
        key = str(getattr(e, "key", "") or "").lower()
        ctrl = bool(getattr(e, "ctrl", False))
        if key in {"arrow up", "arrow down"}:
            self._handle_composer_history_navigation(key)
            return
        if ctrl and key == "tab" and self.page:
            self.page.run_task(self._toggle_plan_mode_from_shortcut)

    def _on_composer_focus(self, _e=None):
        self._composer_input_focused = True

    def _on_composer_blur(self, _e=None):
        self._composer_input_focused = False
        self._composer_history_index = None
        self._composer_history_draft = ""

    def _render_attachment_chips(self):
        if not self.attachments_row:
            return
        chips: list[ft.Control] = []
        for idx, raw in enumerate(self._pending_attachment_paths):
            p = Path(raw)
            chips.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(p.name, size=TYPE_SM, color=TEXT_SECONDARY),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_size=12,
                                width=20,
                                height=20,
                                tooltip="Remove",
                                on_click=lambda _e, i=idx: self._remove_attachment_at(i),
                                style=ft.ButtonStyle(
                                    padding=0,
                                    bgcolor={ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, ft.Colors.WHITE)},
                                ),
                            ),
                        ],
                        spacing=4,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    border=ft.Border.all(1, HAIRLINE),
                    border_radius=RADIUS_SM,
                    bgcolor=SURFACE_2,
                )
            )
        self.attachments_row.controls = chips
        self.attachments_row.visible = bool(chips)
        self._safe_control_update(self.attachments_row)

    def _remove_attachment_at(self, index: int):
        if index < 0 or index >= len(self._pending_attachment_paths):
            return
        self._pending_attachment_paths.pop(index)
        self._render_attachment_chips()

    def _clear_pending_attachments(self):
        self._pending_attachment_paths = []
        self._render_attachment_chips()

    def _queue_attachments(self, paths: list[str]):
        added = 0
        for raw in paths:
            p = str(Path(raw).expanduser())
            if p in self._pending_attachment_paths:
                continue
            if len(self._pending_attachment_paths) >= MAX_ATTACHMENTS:
                self._show_transient_notice(f"Max attachments reached ({MAX_ATTACHMENTS}).")
                break
            self._pending_attachment_paths.append(p)
            added += 1
        if added:
            self._render_attachment_chips()
            self._show_transient_notice(f"Attached {added} file(s).")

    def _open_attach_picker(self, _e=None):
        if self.page:
            self.page.run_task(self._open_attach_picker_async)

    async def _open_attach_picker_async(self):
        if not self.page:
            return
        try:
            picker = ft.FilePicker()
            picked = picker.pick_files(allow_multiple=True)
            files = await picked if asyncio.iscoroutine(picked) else picked
            files = files or []
            paths = [f.path for f in files if getattr(f, "path", None)]
            if paths:
                self._queue_attachments(paths)
            return
        except Exception:
            self._show_transient_notice("File picker unavailable in this runtime.")

    def _consume_dropped_path_text(self, message: str) -> bool:
        raw_lines = [
            line.strip().strip('"').strip("'")
            for line in (message or "").splitlines()
            if line.strip()
        ]
        if not raw_lines:
            return False
        if len(raw_lines) > MAX_ATTACHMENTS:
            return False
        paths: list[str] = []
        for line in raw_lines:
            p = Path(line).expanduser()
            if not p.exists() or not p.is_file():
                return False
            paths.append(str(p))
        self._queue_attachments(paths)
        if self.input_field:
            self.input_field.value = ""
            self._safe_control_update(self.input_field)
        self._show_transient_notice("File path(s) detected and queued as attachments.")
        return True

    def _prepare_attachments_for_turn(
        self,
        message: str,
        turn_id: int,
    ) -> tuple[str, str | list[dict] | None, str | None, list[Attachment]] | None:
        if not self._pending_attachment_paths:
            return message, None, None, []

        manager = AttachmentManager(self.config.cwd)
        temp_turn_id = f"gui_{turn_id}"
        staged, errors = manager.stage_paths(self._pending_attachment_paths, temp_turn_id)
        if errors:
            self._add_assistant_card(
                "Attachments",
                ft.Column(
                    [ft.Text(err, size=TYPE_SM, color=ft.Colors.AMBER_200) for err in errors],
                    spacing=4,
                    tight=True,
                ),
            )
        if not staged:
            return None

        model_content = build_user_model_content(message, staged, self.config.cwd)
        self._clear_pending_attachments()
        return message, model_content, temp_turn_id, staged

    def _add_user_attachment_preview(self, attachments: list[Attachment]):
        if not attachments or not self.messages_column:
            return
        images = [a for a in attachments if a.kind == "image"]
        if not images:
            return
        image_fit = "cover"
        if hasattr(ft, "ImageFit"):
            try:
                image_fit = ft.ImageFit.COVER
            except Exception:
                image_fit = "cover"
        tiles: list[ft.Control] = []
        for img in images[:MAX_ATTACHMENTS]:
            tiles.append(
                ft.Container(
                    width=72,
                    height=72,
                    border=ft.Border.all(1, HAIRLINE),
                    border_radius=RADIUS_SM,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    content=ft.Image(src=img.source_path, fit=image_fit),
                )
            )
        row = ft.Row(tiles, spacing=6, alignment=ft.MainAxisAlignment.END)
        self._append_chat_control(self._wrap_in_lane(row))

    def _record_composer_history(self, message: str):
        text = (message or "").strip()
        if not text:
            return
        if self._composer_history and self._composer_history[-1] == text:
            return
        self._composer_history.append(text)
        if len(self._composer_history) > 300:
            self._composer_history = self._composer_history[-300:]

    def _handle_composer_history_navigation(self, key: str):
        if not self._composer_input_focused or not self.input_field:
            return
        if self._is_turn_running or not self._composer_history:
            return

        if key == "arrow up":
            if self._composer_history_index is None:
                self._composer_history_draft = self.input_field.value or ""
                self._composer_history_index = len(self._composer_history) - 1
            else:
                self._composer_history_index = max(0, self._composer_history_index - 1)
            self.input_field.value = self._composer_history[self._composer_history_index]
            self._safe_control_update(self.input_field)
            return

        if key == "arrow down" and self._composer_history_index is not None:
            if self._composer_history_index < len(self._composer_history) - 1:
                self._composer_history_index += 1
                self.input_field.value = self._composer_history[self._composer_history_index]
            else:
                self.input_field.value = self._composer_history_draft
                self._composer_history_index = None
                self._composer_history_draft = ""
            self._safe_control_update(self.input_field)

    async def _toggle_plan_mode_from_shortcut(self):
        if self.app_mode != "chat":
            return
        if self._intent_assist_prompt and self._intent_assist_kind == "plan":
            prompt = self._intent_assist_prompt
            await self._run_plan_mode_toggle_flow(
                target_enabled=True,
                announce_shortcut_notice=True,
                post_toggle_callback=lambda: self._send_pending_intent_prompt(prompt),
            )
            return
        if self._intent_assist_prompt and self._intent_assist_kind == "execute":
            prompt = self._intent_assist_prompt
            await self._run_plan_mode_toggle_flow(
                target_enabled=False,
                announce_shortcut_notice=True,
                post_toggle_callback=lambda: self._send_pending_intent_prompt(prompt),
            )
            return

        await self._run_plan_mode_toggle_flow(
            target_enabled=None,
            announce_shortcut_notice=True,
        )

    def _show_transient_notice(self, message: str):
        if not self.page:
            return
        snack = ft.SnackBar(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINED, size=16, color=ACCENT),
                    ft.Text(message, color=TEXT_PRIMARY, size=TYPE_MD),
                ],
                spacing=8,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE_ELEVATED,
            duration=2800,
            show_close_icon=False,
        )
        try:
            if hasattr(self.page, "show_snack_bar"):
                self.page.show_snack_bar(snack)
                return
            if hasattr(self.page, "open"):
                self.page.open(snack)
                return
            self.page.snack_bar = snack
            self.page.snack_bar.open = True
            self.page.update()
        except RuntimeError as ex:
            if "destroyed session" in str(ex).lower():
                self._is_closing = True
        except Exception:
            pass
        # Last-resort visible fallback if snack APIs are unavailable.
        self._add_assistant_card(
            "Notice",
            ft.Text(message, color=TEXT_SECONDARY),
        )

    def _is_page_alive(self) -> bool:
        if self._is_closing or not self.page:
            return False
        try:
            _ = self.page.session
            return True
        except Exception:
            return False

    def _safe_page_update(self, *controls: ft.Control) -> bool:
        if self._defer_ui_updates:
            return True
        if not self._is_page_alive() or not self.page:
            return False
        try:
            if controls:
                self.page.update(*controls)
            else:
                self.page.update()
            return True
        except RuntimeError as ex:
            if "destroyed session" in str(ex).lower():
                self._is_closing = True
            return False
        except Exception:
            return False

    def _safe_control_update(self, control: ft.Control | None) -> bool:
        if control is None or not self._is_page_alive():
            return False
        try:
            control.update()
            return True
        except RuntimeError as ex:
            if "destroyed session" in str(ex).lower():
                self._is_closing = True
            return False
        except Exception:
            return False

    def _refresh_empty_state_visibility(self):
        if not self.empty_state_container or not self.messages_column:
            return
        if self.app_mode != "chat":
            self.empty_state_container.visible = False
            self._safe_control_update(self.empty_state_container)
            return
        visible_controls = [
            c for c in self.messages_column.controls if c is not self.chat_bottom_spacer
        ]
        is_switching = getattr(self, "loading_session_id", None) is not None
        is_hydrating = getattr(self.gui_state.state.interaction, "is_hydrating_chat", False) if hasattr(self, "gui_state") else False
        should_show = (len(visible_controls) == 0) and (not self._is_turn_running) and (not is_switching) and (not is_hydrating)
        self.empty_state_container.visible = should_show
        self._safe_control_update(self.empty_state_container)

    def _refresh_empty_state_copy(self):
        if self.empty_state_title_text:
            self.empty_state_title_text.value = self._build_empty_state_title()
            self._safe_control_update(self.empty_state_title_text)
        if self.empty_state_workspace_text:
            workspace_name = Path(self.config.cwd).resolve().name or str(self.config.cwd)
            self.empty_state_workspace_text.value = workspace_name
            self._safe_control_update(self.empty_state_workspace_text)

    def _toggle_workboard(self):
        if not self.workboard_has_content:
            self._show_transient_notice("Workboard opens when a plan or checklist is available.")
            return
        self.gui_state.toggle_workboard()
        self._apply_workboard_state()

    def _apply_workboard_state(self, update: bool = True):
        show_panel = self.workboard_visible and self.workboard_has_content
        if self.workboard_container is not None:
            self.workboard_container.visible = show_panel
            self.workboard_container.width = self.workboard_width if show_panel else 0
        if self.workboard_toggle_button is not None:
            self.workboard_toggle_button.icon = (
                ft.Icons.CHEVRON_RIGHT_ROUNDED
                if show_panel
                else ft.Icons.CHEVRON_LEFT_ROUNDED
            )
            self.workboard_toggle_button.tooltip = (
                "Collapse workboard"
                if show_panel
                else ("Expand workboard" if self.workboard_has_content else "No active workboard content")
            )
            self.workboard_toggle_button.disabled = not self.workboard_has_content
            self.workboard_toggle_button.opacity = 1.0 if self.workboard_has_content else 0.45
        if self.workboard_header_toggle_button is not None:
            self.workboard_header_toggle_button.icon = (
                ft.Icons.CHEVRON_RIGHT_ROUNDED
                if show_panel
                else ft.Icons.CHEVRON_LEFT_ROUNDED
            )
            self.workboard_header_toggle_button.tooltip = (
                "Hide workboard"
                if show_panel
                else ("Show workboard" if self.workboard_has_content else "No active workboard content")
            )
            self.workboard_header_toggle_button.disabled = not self.workboard_has_content
            self.workboard_header_toggle_button.opacity = 1.0 if self.workboard_has_content else 0.45
        if update:
            if self.workboard_container is not None:
                self._safe_control_update(self.workboard_container)
            if self.workboard_toggle_button is not None:
                self._safe_control_update(self.workboard_toggle_button)
            if self.workboard_header_toggle_button is not None:
                self._safe_control_update(self.workboard_header_toggle_button)

    def _open_workboard_if_available(self):
        if not self.workboard_has_content:
            return
        if self.workboard_visible:
            return
        self.gui_state.open_workboard()
        self._apply_workboard_state(update=True)

    def _execution_todo_count(self) -> int:
        if not self.agent or not self.agent.session:
            return 0
        state = self.agent.session.export_todos_state()
        if not isinstance(state, dict):
            return 0
        execution = state.get("execution", [])
        if not isinstance(execution, list):
            return 0
        return len(execution)

    def _announce_initial_execution_todos_if_created(self, before_count: int):
        after_count = self._execution_todo_count()
        if before_count == 0 and after_count > 0:
            self._refresh_workboard_from_session()
            self._open_workboard_if_available()
            self._add_assistant_card(
                "Checklist",
                ft.Text(
                    f"Execution checklist created ({after_count} task(s)). Opened Workboard.",
                    color=TEXT_SECONDARY,
                ),
            )

    def _set_workboard_plan_text(self, plan_text: str | None):
        text = (plan_text or "").strip()
        if self.workboard_plan_markdown is not None:
            self.workboard_plan_markdown.value = text
        if self.workboard_plan_section is not None:
            self.workboard_plan_section.visible = bool(text)
        if self.workboard_plan_wrapper is not None:
            self.workboard_plan_wrapper.visible = bool(text)
        if self.workboard_plan_markdown is not None:
            self._safe_control_update(self.workboard_plan_markdown)
        if self.workboard_plan_section is not None:
            self._safe_control_update(self.workboard_plan_section)
        if self.workboard_plan_wrapper is not None:
            self._safe_control_update(self.workboard_plan_wrapper)

    def _compute_workboard_todos_signature(
        self,
        state: dict[str, Any] | None,
        show_planning_todos: bool,
    ) -> tuple:
        if not isinstance(state, dict):
            return (show_planning_todos, ())
        scopes = ["execution"]
        if show_planning_todos:
            scopes.append("planning")
        signature: list[tuple[str, tuple[tuple[str, bool], ...]]] = []
        for scope in scopes:
            entries = state.get(scope, [])
            if not isinstance(entries, list):
                entries = []
            normalized = tuple(
                (
                    str(entry.get("content", "")).strip(),
                    bool(entry.get("completed", False)),
                )
                for entry in entries
            )
            signature.append((scope, normalized))
        return (show_planning_todos, tuple(signature))

    def _render_workboard_todos_from_state(self, state: dict[str, Any] | None):
        if self.workboard_todos_column is None:
            return
        controls: list[ft.Control] = []
        if not isinstance(state, dict):
            state = {}
        scopes: list[str] = ["execution"]
        show_planning = bool(self.gui_state.state.workboard.show_planning_todos)
        if show_planning:
            scopes.append("planning")

        total_pending_all = 0
        total_completed_all = 0
        total_all = 0

        for scope in scopes:
            entries = state.get(scope, [])
            if not isinstance(entries, list):
                entries = []
            if len(entries) == 0:
                continue
            pending = [e for e in entries if not bool(e.get("completed", False))]
            done = [e for e in entries if bool(e.get("completed", False))]
            total = len(entries)
            completed = len(done)
            total_pending_all += len(pending)
            total_completed_all += completed
            total_all += total
            ratio = (completed / total) if total > 0 else 0.0

            tone = SUCCESS if scope == "execution" else ACCENT
            tone_soft = SUCCESS_SOFT if scope == "execution" else ACCENT_SOFT

            chips = ft.Row(
                [
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=13, color=tone),
                                ft.Text(
                                    f"{completed}/{total} completed",
                                    size=TYPE_SM,
                                    color=tone,
                                    weight=WEIGHT_SEMIBOLD,
                                ),
                            ],
                            spacing=6,
                            tight=True,
                        ),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                        border=ft.Border.all(1, tone_soft),
                        border_radius=RADIUS_LG,
                        bgcolor=ft.Colors.with_opacity(
                            0.08,
                            ft.Colors.GREEN_300 if scope == "execution" else ft.Colors.BLUE_300,
                        ),
                    ),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.PENDING_ROUNDED, size=13, color=WARNING),
                                ft.Text(
                                    f"{len(pending)} pending",
                                    size=TYPE_SM,
                                    color=WARNING,
                                    weight=WEIGHT_SEMIBOLD,
                                ),
                            ],
                            spacing=6,
                            tight=True,
                        ),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                        border=ft.Border.all(1, WARNING_SOFT),
                        border_radius=RADIUS_LG,
                        bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.AMBER_300),
                    ),
                ],
                spacing=8,
                wrap=True,
            )

            pending_rows: list[ft.Control] = []
            for item in pending[:6]:
                content = str(item.get("content", "")).strip()
                if content:
                    pending_rows.append(
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Icon(ft.Icons.RADIO_BUTTON_UNCHECKED_ROUNDED, size=13, color=TEXT_MUTED),
                                    ft.Text(content, size=TYPE_BODY, color=TEXT_PRIMARY, expand=True),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.START,
                            ),
                            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                            border=ft.Border.all(1, HAIRLINE),
                            border_radius=RADIUS_SM,
                            bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE),
                        )
                    )
            if len(pending) > 6:
                pending_rows.append(ft.Text(f"+{len(pending) - 6} more pending", size=TYPE_SM, color=TEXT_MUTED))

            done_rows: list[ft.Control] = []
            for item in done[:3]:
                content = str(item.get("content", "")).strip()
                if content:
                    done_rows.append(
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.CHECK_ROUNDED, size=13, color=tone),
                                ft.Text(content, size=TYPE_BODY, color=TEXT_SECONDARY, expand=True),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        )
                    )
            if len(done) > 3:
                done_rows.append(ft.Text(f"+{len(done) - 3} more completed", size=TYPE_SM, color=TEXT_MUTED))

            scope_label = "Execution checklist" if scope == "execution" else "Planning checklist"
            controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(
                                        ft.Icons.TASK_ALT_ROUNDED if scope == "execution" else ft.Icons.ROUTE_ROUNDED,
                                        size=16,
                                        color=tone,
                                    ),
                                    ft.Text(
                                        scope_label,
                                        size=TYPE_TITLE,
                                        color=TEXT_PRIMARY,
                                        weight=WEIGHT_BOLD,
                                    ),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            chips,
                            ft.ProgressBar(
                                value=ratio,
                                color=tone,
                                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.WHITE),
                                bar_height=7,
                            ),
                            ft.Text("Up next", size=TYPE_SM, color=TEXT_MUTED, weight=WEIGHT_SEMIBOLD),
                            ft.Column(pending_rows, spacing=6, tight=True)
                            if pending_rows
                            else ft.Text("No pending tasks.", size=TYPE_SM, color=TEXT_MUTED),
                            ft.Text("Done", size=TYPE_SM, color=TEXT_MUTED, weight=WEIGHT_SEMIBOLD)
                            if done_rows
                            else ft.Container(),
                            ft.Column(done_rows, spacing=5, tight=True) if done_rows else ft.Container(),
                        ],
                        spacing=8,
                        tight=True,
                    ),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=12),
                    border=ft.Border.all(1, BORDER),
                    border_radius=RADIUS_MD,
                    bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
                )
            )
        if total_all > 0:
            controls.insert(
                0,
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.INSIGHTS_ROUNDED, size=15, color=ACCENT),
                            ft.Text(
                                f"Overall: {total_completed_all}/{total_all} completed · {total_pending_all} pending",
                                size=TYPE_SM,
                                color=TEXT_SECONDARY,
                                weight=WEIGHT_SEMIBOLD,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                    border=ft.Border.all(1, HAIRLINE),
                    border_radius=RADIUS_SM,
                    bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.WHITE),
                ),
            )
        self.workboard_todos_column.controls = controls
        self._safe_control_update(self.workboard_todos_column)
        if self.workboard_todos_section is not None:
            self.workboard_todos_section.visible = bool(controls)
            self._safe_control_update(self.workboard_todos_section)

    def _refresh_workboard_from_session(self):
        if not self.agent or not self.agent.session:
            self.gui_state.set_workboard_content(
                plan_text="",
                todos_state=None,
                show_planning_todos=False,
                has_content=False,
            )
            return
        session = self.agent.session
        todos_state = session.export_todos_state()
        plan_text = (session.current_plan_text() or "").strip()
        show_planning = bool(session.show_planning_todos)
        has_todos = False
        if isinstance(todos_state, dict):
            visible_scopes = ["execution"]
            if show_planning:
                visible_scopes.append("planning")
            for scope in visible_scopes:
                entries = todos_state.get(scope, [])
                if isinstance(entries, list) and entries:
                    has_todos = True
                    break
        self.gui_state.set_workboard_content(
            plan_text=plan_text,
            todos_state=todos_state,
            show_planning_todos=show_planning,
            has_content=bool(has_todos or plan_text),
        )

    def _build_empty_state_title(self) -> str:
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

        thread_count = len(self.sidebar_sessions_cache or [])
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

    def _ensure_chat_bottom_spacer(self):
        if not self.messages_column:
            return
        if self.chat_bottom_spacer is None:
            self.chat_bottom_spacer = ft.Container(key="chat-bottom-anchor", height=16)
        controls = self.messages_column.controls
        if self.chat_bottom_spacer in controls:
            controls.remove(self.chat_bottom_spacer)
        controls.append(self.chat_bottom_spacer)

    def _append_chat_control(self, control: ft.Control) -> int | None:
        if not self.messages_column:
            return None
        self._ensure_chat_bottom_spacer()
        controls = self.messages_column.controls
        if controls and controls[-1] is self.chat_bottom_spacer:
            controls.insert(len(controls) - 1, control)
            self._refresh_empty_state_visibility()
            return len(controls) - 2
        controls.append(control)
        self._ensure_chat_bottom_spacer()
        self._refresh_empty_state_visibility()
        return len(self.messages_column.controls) - 2

    def _clear_chat_controls(self):
        if not self.messages_column:
            return
        self.messages_column.controls.clear()
        self._ensure_chat_bottom_spacer()
        self._refresh_empty_state_visibility()

    def _remove_chat_control(self, control: ft.Control):
        if not self.messages_column:
            return
        if control in self.messages_column.controls:
            self.messages_column.controls.remove(control)
        self._ensure_chat_bottom_spacer()
        self._refresh_empty_state_visibility()

    async def _run_agent(
        self,
        message: str,
        turn_id: int,
        user_model_content: str | list[dict] | None = None,
        temp_attachment_turn_id: str | None = None,
        display_message: str | None = None,
        staged_attachments: list[Attachment] | None = None,
    ):
        try:
            if turn_id != self._active_turn_id:
                return
            self.gui_state.set_turn_running(True)
            self._set_loading(True)
            self._add_user_attachment_preview(staged_attachments or [])
            self._add_message("user", (display_message if display_message is not None else message))
            self._show_thinking_indicator(
                progress_label(
                    plan_mode=bool(
                        self.agent
                        and self.agent.session
                        and self.agent.session.plan_mode_enabled
                    )
                )
            )
            await self._ensure_agent()

            if not self.agent:
                self._add_message("system", "Error: agent not initialized", is_error=True)
                return

            async for event in self.agent.run(message, user_model_content=user_model_content):
                if turn_id != self._active_turn_id:
                    return
                await self._handle_agent_event(event)
                if turn_id != self._active_turn_id:
                    return
            await self._auto_save()
        except asyncio.CancelledError:
            if turn_id == self._active_turn_id:
                if self._stop_requested_by_user:
                    self._add_assistant_card(
                        "Interrupted",
                        ft.Text("Stopped current turn.", color=ft.Colors.with_opacity(0.85, ft.Colors.AMBER_300)),
                    )
                else:
                    self._show_recovery_actions_card("Run interrupted unexpectedly.")
                await self._auto_save()
        except Exception as e:
            if turn_id == self._active_turn_id:
                self._add_message("system", f"Error: {str(e)}", is_error=True)
        finally:
            if temp_attachment_turn_id:
                AttachmentManager(self.config.cwd).cleanup_turn(temp_attachment_turn_id)
            if turn_id == self._active_turn_id:
                self._stop_requested_by_user = False
                self.gui_state.set_turn_running(False)
                self._active_turn_task = None
                self._hide_thinking_indicator()
                self._set_loading(False)
                self._refresh_empty_state_visibility()

    async def _ensure_agent(self) -> None:
        if self.agent is not None:
            return

        self.agent = Agent(
            config=self.config,
            confirmation_callback=self._gui_confirmation_callback,
            plan_question_callback=self._gui_plan_question_callback,
        )
        await self.agent.__aenter__()
        if self.agent.session:
            self.gui_state.session_loaded(
                session_id=self.agent.session.session_id,
                title=self.agent.session.name,
                workspace=self.config.cwd,
                visible_transcript_messages=[],
                transcript_truncated=False,
                pending_transcript_load=False,
            )
            self._set_current_session_title(self.agent.session.name)
            self._sync_plan_toggle_ui()
            self._refresh_workboard_from_session()

    def _on_send(self, e):
        current_text = self.input_field.value.strip() if self.input_field else ""
        if self._is_turn_running and not is_aside_command_text(current_text):
            if self.page:
                self._stop_requested_by_user = True
                self.page.run_task(self._stop_active_turn)
            return

        if not self.input_field or not self.page:
            return

        message = current_text
        if not message:
            return
        if not message.startswith("/") and self._consume_dropped_path_text(message):
            return

        normalized = self._normalize_plan_execution_request(message)
        if normalized is None:
            return
        message = normalized
        self._last_user_message_for_retry = message

        if self.loading_session_id is not None:
            self._add_assistant_card(
                "Threads",
                ft.Text("Thread is still loading. Send once loading completes.", color=TEXT_MUTED),
            )
            return

        if not message.startswith("/"):
            resolution = resolve_inline_attachment_refs(
                message,
                cwd=self.config.cwd,
                existing_paths=self._pending_attachment_paths,
            )
            if resolution.errors:
                for error in resolution.errors:
                    self._show_transient_notice(error)
                return
            self._pending_attachment_paths = resolution.queued_paths
            self._render_attachment_chips()
            message = resolution.message
            plan_enabled = self._is_plan_mode_enabled()
            if self._should_suppress_intent_detection(message, plan_enabled=plan_enabled):
                self._dispatch_message(message)
                return
            if not plan_enabled and self._detect_plan_intent(message):
                self._show_intent_assist_panel("plan", message)
                return
            if plan_enabled and self._detect_execution_intent(message):
                self._show_intent_assist_panel("execute", message)
                return
        self._dispatch_message(message)

    def _dispatch_message(self, message: str):
        if not self.page:
            return

        # A new send should always anchor the viewport at the latest chat content.
        self._auto_scroll_enabled = True
        self._scroll_chat_to_bottom(animate=False, force=True)
        self._last_dispatched_message = message
        self._record_composer_history(message)
        self._composer_history_index = None
        self._composer_history_draft = ""

        self.input_field.value = ""
        self._safe_control_update(self.input_field)

        try:
            if message.startswith("/"):
                self.page.run_task(self._run_command, message)
            else:
                self._active_turn_id += 1
                turn_id = self._active_turn_id
                prepared = self._prepare_attachments_for_turn(message, turn_id)
                if prepared is None:
                    return
                prepared_message, user_model_content, temp_turn_id, staged = prepared
                self._active_turn_task = self.page.run_task(
                    self._run_agent,
                    prepared_message,
                    turn_id,
                    user_model_content,
                    temp_turn_id,
                    message,
                    staged,
                )
        except Exception as ex:
            if "temp_turn_id" in locals() and temp_turn_id:
                AttachmentManager(self.config.cwd).cleanup_turn(temp_turn_id)
            self._add_message(
                "system",
                f"Error: failed to start agent task: {ex}",
                is_error=True,
            )

    def _build_recovery_followup_prompt(self) -> str:
        return (
            "Continue from the last successful step only. "
            "Do not repeat completed work. "
            "Fix the remaining failure, run one final verification, and summarize changed files."
        )

    def _show_recovery_actions_card(self, reason: str):
        if not self.page:
            return
        continue_button = ft.FilledButton(
            "Continue From Last Step",
            on_click=lambda _e: self.page.run_task(self._recovery_continue_from_last_step),
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.WHITE, ft.ControlState.HOVERED: "#F3F3F3"},
                color=ft.Colors.BLACK,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )
        retry_button = ft.OutlinedButton(
            "Retry Last Prompt",
            on_click=lambda _e: self.page.run_task(self._recovery_retry_last_prompt),
            style=ft.ButtonStyle(
                side={ft.ControlState.DEFAULT: ft.BorderSide(1, BORDER_STRONG)},
                color=TEXT_SECONDARY,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )
        self._add_assistant_card(
            "Recovery",
            ft.Column(
                [
                    ft.Text(reason, size=TYPE_BODY, color=TEXT_SECONDARY),
                    ft.Text(
                        "Use one of the recovery actions below.",
                        size=TYPE_SM,
                        color=TEXT_MUTED,
                    ),
                    ft.Row([retry_button, continue_button], alignment=ft.MainAxisAlignment.END),
                ],
                spacing=8,
                tight=True,
            ),
        )

    async def _recovery_continue_from_last_step(self):
        self._dispatch_message(self._build_recovery_followup_prompt())

    async def _recovery_retry_last_prompt(self):
        prompt = (self._last_user_message_for_retry or "").strip()
        if not prompt:
            self._show_transient_notice("No previous prompt to retry.")
            return
        self._dispatch_message(prompt)

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
            self._plan_ready_prompt_open = False
            before_count = self._execution_todo_count()
            session.seed_execution_todos_from_plan(session.pending_plan_text)
            session.promote_pending_plan_to_active()
            session.set_plan_mode(False)
            session.set_plan_phase("idle")
            self._sync_plan_toggle_ui()
            self._announce_initial_execution_todos_if_created(before_count)
            return Agent.PLAN_EXECUTE_PROMPT

        self._add_assistant_card(
            "Plan Mode",
            ft.Text(
                "No pending plan is waiting for approval. Ask for a plan first, then approve implementation.",
                color=TEXT_SECONDARY,
            ),
        )
        return None

    async def _stop_active_turn(self):
        await self._cancel_active_turn_and_wait()

    async def _cancel_active_turn_and_wait(self, timeout_seconds: float = 2.0):
        task = self._active_turn_task
        if not task:
            if self._is_turn_running:
                self._active_turn_id += 1
                self.gui_state.set_turn_running(False)
                self._hide_thinking_indicator()
                self._set_loading(False)
            return
        timed_out = False
        try:
            if hasattr(task, "done") and hasattr(task, "cancel") and not task.done():
                task.cancel()
            if hasattr(task, "done") and not task.done():
                await asyncio.wait_for(task, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            self._add_message(
                "system",
                f"Error stopping turn: {ex}",
                is_error=True,
            )
        finally:
            # If cancellation stalls, invalidate this turn so stale events cannot mutate UI.
            if timed_out:
                self._active_turn_id += 1
                self.gui_state.set_turn_running(False)
                self._hide_thinking_indicator()
                self._set_loading(False)
            self._active_turn_task = None

    def _reset_turn_ui_state(self):
        self._active_turn_task = None
        self.gui_state.set_turn_running(False)
        self._clear_intent_assist_state()
        self._hide_thinking_indicator()
        self._set_loading(False)

    def _show_thinking_indicator(self, label: str | None = None):
        if not self.messages_column or not self._is_page_alive():
            return
        self._thinking_label_base = (label or "Thinking").strip() or "Thinking"
        if self.thinking_row:
            if self.thinking_text is not None:
                self.thinking_text.value = self._thinking_label_base
            try:
                self._remove_chat_control(self.thinking_row)
            except Exception:
                pass
            self._append_chat_control(self.thinking_row)
            self._safe_page_update()
            self._scroll_chat_to_bottom(animate=False, force=True)
            return

        self.thinking_spinner = ft.ProgressRing(
            width=10,
            height=10,
            stroke_width=1.8,
            color=TEXT_SECONDARY,
        )
        self.thinking_text = ft.Text(
            self._thinking_label_base,
            size=TYPE_BODY,
            color=TEXT_SECONDARY,
            weight=WEIGHT_SEMIBOLD,
        )
        bubble = ft.Container(
            content=ft.Row(
                [self.thinking_spinner, self.thinking_text],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE_ELEVATED,
            border_radius=RADIUS_SM,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            width=220,
        )
        self.thinking_row = ft.Row([bubble], alignment=ft.MainAxisAlignment.START)
        self.thinking_row = self._wrap_in_lane(self.thinking_row)
        self._append_chat_control(self.thinking_row)
        self._safe_page_update()
        self._scroll_chat_to_bottom(animate=False, force=True)
        if self.page:
            self._thinking_task = self.page.run_task(self._animate_thinking_text)

    async def _animate_thinking_text(self):
        suffixes = ["", ".", "..", "..."]
        i = 0
        try:
            while self._is_turn_running and self.thinking_text and self._is_page_alive():
                base = self._thinking_label_base or "Thinking"
                self.thinking_text.value = f"{base}{suffixes[i % len(suffixes)]}"
                if not self._safe_control_update(self.thinking_text):
                    return
                i += 1
                await asyncio.sleep(0.36)
        except asyncio.CancelledError:
            return

    def _hide_thinking_indicator(self):
        if self._thinking_task and hasattr(self._thinking_task, "done"):
            if not self._thinking_task.done():
                self._thinking_task.cancel()
        self._thinking_task = None

        if not self.messages_column or not self.thinking_row:
            self.thinking_row = None
            self.thinking_text = None
            self.thinking_spinner = None
            return

        try:
            self._remove_chat_control(self.thinking_row)
        except Exception:
            pass
        self.thinking_row = None
        self.thinking_text = None
        self.thinking_spinner = None
        self._thinking_label_base = "Thinking"
        self._safe_page_update()

    def _on_close(self, e):
        self._is_closing = True
        self._stop_branch_sync_watcher()
        if self._thinking_task and hasattr(self._thinking_task, "cancel"):
            self._thinking_task.cancel()
        if self.page:
            self.page.run_task(self._shutdown_agent)

    def _is_valid_base_url(self, base_url: str) -> bool:
        parsed = urlparse(base_url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    async def _open_setup_view(self):
        if self.setup_base_url_field:
            self.setup_base_url_field.value = self.config.base_url or DEFAULT_BASE_URL
        if self.setup_api_key_field:
            self.setup_api_key_field.value = self.config.api_key or DEFAULT_API_KEY
        if self.setup_model_field:
            self.setup_model_field.value = self.config.model_name or DEFAULT_MODEL_NAME
        if self.approval_selector:
            self.approval_selector.value = self.config.approval.value
        if self.setup_error_text:
            self.setup_error_text.value = ""
            self.setup_error_text.visible = False
        self.app_mode = "setup"
        self._apply_app_mode()

    async def _cancel_setup_view(self):
        if self.config.needs_setup:
            await self._close_gui_window()
            return
        self.app_mode = "chat"
        self._apply_app_mode()

    async def _submit_setup_view(self):
        if not self.setup_base_url_field or not self.setup_api_key_field or not self.setup_model_field:
            return
        base_url = self.setup_base_url_field.value.strip() or DEFAULT_BASE_URL
        api_key = self.setup_api_key_field.value.strip() or DEFAULT_API_KEY
        model_name = self.setup_model_field.value.strip() or self.config.model.name or DEFAULT_MODEL_NAME

        if not self._is_valid_base_url(base_url):
            if self.setup_error_text:
                self.setup_error_text.value = "Base URL must be a valid http/https URL."
                self.setup_error_text.visible = True
            self._safe_page_update()
            return

        try:
            save_system_config(
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
            )
        except Exception as exc:
            if self.setup_error_text:
                self.setup_error_text.value = f"Failed to save setup: {exc}"
                self.setup_error_text.visible = True
            self._safe_page_update()
            return

        self.config.api_key = api_key
        self.config.base_url = base_url
        self.config.model.name = model_name
        if self.model_selector_text:
            self.model_selector_text.value = self.config.model_name
            self._safe_control_update(self.model_selector_text)
        if self.config.model_name not in self.model_items:
            self.model_items.insert(0, self.config.model_name)

        if self.agent is not None:
            await self._shutdown_agent()

        if self.header_workspace_text:
            self.header_workspace_text.value = f"Workspace: {self.config.cwd}"
            self._safe_control_update(self.header_workspace_text)

        self.app_mode = "chat"
        self._apply_app_mode()
        self._add_assistant_card(
            "Setup Complete",
            ft.Text("Credentials saved and applied.", color=ft.Colors.with_opacity(0.8, ft.Colors.GREEN_300)),
        )

    def _apply_app_mode(self):
        if not self.page:
            return
        if self.chat_shell:
            self.chat_shell.visible = self.app_mode == "chat"
        if self.setup_view:
            self.setup_view.visible = self.app_mode == "setup"
        self._safe_page_update()

    async def _shutdown_agent(self):
        if self.agent is None:
            return
        await self._cancel_active_turn_and_wait()
        try:
            await self.agent.__aexit__(None, None, None)
        finally:
            self.agent = None

    def _sync_plan_toggle_ui(self):
        enabled = bool(
            self.agent and self.agent.session and self.agent.session.plan_mode_enabled
        )
        if self.plan_toggle_button:
            label = "✓ Plan" if enabled else "Plan"
            self.plan_toggle_button.content = ft.Row(
                [
                    ft.Icon(
                        ft.Icons.TUNE if enabled else ft.Icons.TUNE_OUTLINED,
                        size=13,
                        color="#8FC3FF" if enabled else TEXT_MUTED,
                    ),
                    ft.Text(
                        label,
                        size=TYPE_BODY,
                        color="#8FC3FF" if enabled else TEXT_SECONDARY,
                        weight=ft.FontWeight.W_600 if enabled else ft.FontWeight.W_500,
                    ),
                ],
                spacing=6,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            self._safe_control_update(self.plan_toggle_button)

    async def _toggle_plan_mode(self):
        await self._run_plan_mode_toggle_flow(target_enabled=None)
        after = self._is_plan_mode_enabled()
        self._add_assistant_card(
            "Plan Mode",
            ft.Text(
                f"Plan mode {'enabled' if after else 'disabled'}.",
                color=TEXT_SECONDARY,
            ),
        )

    async def _show_plan_resume_options_if_available(self) -> None:
        if not self.page:
            return
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return
        session = self.agent.session
        if not session.has_pending_plan():
            return

        status = ft.Text("", size=TYPE_BODY, color=TEXT_MUTED)
        refine_button = ft.OutlinedButton("Refine old plan")
        accept_button = ft.FilledButton("Accept and implement")
        new_button = ft.TextButton("Generate new plan")
        actions = [refine_button, accept_button, new_button]

        async def handle(choice: str):
            for button in actions:
                button.disabled = True
            if choice == "accept":
                session.set_plan_mode(True)
                session.set_plan_phase("awaiting_implementation_confirmation")
                self._sync_plan_toggle_ui()
                status.value = "Reusing saved plan. Confirm implementation below."
                status.color = SUCCESS
                if self.page:
                    self._safe_page_update()
                await self._render_plan_ready_prompt()
                return
            if choice == "refine":
                session.set_plan_mode(True)
                session.set_plan_phase("asking_questions")
                self._sync_plan_toggle_ui()
                status.value = "Old plan loaded. Send follow-up guidance to refine it."
                status.color = TEXT_MUTED
                if self.page:
                    self._safe_page_update()
                return

            session.clear_pending_plan()
            session.set_plan_mode(True)
            session.set_plan_phase("idle")
            self._sync_plan_toggle_ui()
            status.value = "Saved plan discarded. Next prompt will generate a new plan."
            status.color = TEXT_MUTED
            self._safe_page_update()

        refine_button.on_click = lambda _e: self.page.run_task(handle, "refine") if self.page else None
        accept_button.on_click = lambda _e: self.page.run_task(handle, "accept") if self.page else None
        new_button.on_click = lambda _e: self.page.run_task(handle, "new") if self.page else None

        preview_lines = (session.pending_plan_text or "").strip().splitlines()
        preview_text = "\n".join(preview_lines[:6]).strip() or "Saved plan available."
        if len(preview_lines) > 6:
            preview_text += "\n..."

        self._add_assistant_card(
            "Saved Plan Found",
            ft.Column(
                [
                    ft.Text(
                        "A previously generated plan is available. Choose what to do next.",
                        color=TEXT_SECONDARY,
                    ),
                    ft.Container(
                        content=ft.Text(
                            preview_text,
                            style=ft.TextStyle(font_family="JetBrains Mono", size=TYPE_SM, color=TEXT_PRIMARY),
                            selectable=True,
                        ),
                        border=ft.Border.all(1, HAIRLINE),
                        border_radius=RADIUS_SM,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        bgcolor=SURFACE_2,
                    ),
                    ft.Row(actions, alignment=ft.MainAxisAlignment.END),
                    status,
                ],
                spacing=8,
                tight=True,
            ),
        )

    async def _gui_plan_question_callback(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.page or not self.messages_column:
            return {"selected_option": "", "free_text": "", "selected_index": None}
        self._hide_thinking_indicator()

        question = str(payload.get("question", "")).strip()
        options = [str(o) for o in payload.get("options", []) if str(o).strip()]
        recommended_index = payload.get("recommended_index")
        allow_free_text = bool(payload.get("allow_free_text", True))

        loop = asyncio.get_running_loop()
        self._plan_question_future = loop.create_future()
        self._plan_question_count += 1
        status_icon = ft.Icon(
            ft.Icons.CHECK_CIRCLE_ROUNDED,
            size=12,
            color=SUCCESS,
            visible=False,
        )
        status_text = ft.Text(
            "Answered",
            size=TYPE_MD,
            color=SUCCESS,
            weight=ft.FontWeight.W_600,
            visible=False,
        )
        status_row = ft.Row([status_icon, status_text], spacing=6, visible=False)

        choices: list[ft.OutlinedButton] = []
        option_labels: list[str] = []
        for idx, option in enumerate(options):
            recommended = idx == recommended_index
            label = f"{idx + 1}. {option}" + ("  (Recommended)" if recommended else "")
            option_labels.append(label)
            button = ft.OutlinedButton(
                content=ft.Text(
                    label,
                    size=TYPE_MD,
                    color=TEXT_PRIMARY,
                ),
                on_click=lambda _e, i=idx, o=option: self._resolve_plan_question(
                    i,
                    o,
                    "",
                    status_text=status_text,
                    status_icon=status_icon,
                    status_row=status_row,
                    option_buttons=choices,
                    option_labels=option_labels,
                    options_column=options_column,
                    custom_option_container=custom_option_container,
                    custom_option_index=len(options),
                    custom_option_text="",
                    custom_selected=False,
                    free_input=free_text_input,
                    free_submit=free_submit,
                ),
                style=ft.ButtonStyle(
                    side=ft.BorderSide(1, BORDER_STRONG),
                    color=TEXT_PRIMARY,
                    bgcolor={
                        ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                    },
                    shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                ),
            )
            choices.append(button)
        options_column = ft.Column(choices, spacing=6, tight=True)
        custom_option_container = ft.Container(visible=False)

        def _submit_custom_answer(_e=None):
            custom_value = free_text_input.value.strip() if free_text_input else ""
            if not custom_value:
                return
            self._resolve_plan_question(
                None,
                "",
                custom_value,
                status_text=status_text,
                status_icon=status_icon,
                status_row=status_row,
                option_buttons=choices,
                option_labels=option_labels,
                options_column=options_column,
                custom_option_container=custom_option_container,
                custom_option_index=len(options) + 1,
                custom_option_text=custom_value,
                custom_selected=True,
                free_input=free_text_input,
                free_submit=free_submit,
            )

        free_text_input = ft.TextField(
            hint_text="Other answer",
            border_radius=RADIUS_SM,
            border_color=BORDER,
            focused_border_color=BORDER,
            bgcolor=SURFACE_2,
            color=TEXT_PRIMARY,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            width=SPECIAL_CARD_WIDTH - 40,
            multiline=True,
            shift_enter=True,
            min_lines=1,
            max_lines=3,
            text_size=TYPE_MD,
            on_submit=_submit_custom_answer,
            visible=allow_free_text,
        )
        free_submit = ft.TextButton(
            "Submit",
            on_click=_submit_custom_answer,
            visible=allow_free_text,
        )

        card = ft.Container(
            width=SPECIAL_CARD_WIDTH,
            border=ft.Border.all(1, ACCENT_SOFT),
            border_radius=RADIUS_MD,
            bgcolor=SURFACE_ELEVATED,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            content=ft.Column(
                [
                    ft.Text(
                        f"Asking questions · {self._plan_question_count}",
                        size=TYPE_SM,
                        color=TEXT_MUTED,
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(question, size=TYPE_MD, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600),
                    options_column,
                    custom_option_container,
                    free_text_input,
                    free_submit,
                    status_row,
                ],
                spacing=8,
                tight=True,
            ),
        )
        self._append_chat_control(
            self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        )
        self._safe_page_update()
        self._scroll_chat_to_bottom(force=True)

        result = await self._plan_question_future
        self._plan_question_future = None
        return result

    def _resolve_plan_question(
        self,
        selected_index: int | None,
        selected_option: str,
        free_text: str,
        *,
        status_text: ft.Text | None = None,
        status_icon: ft.Icon | None = None,
        status_row: ft.Row | None = None,
        option_buttons: list[ft.OutlinedButton] | None = None,
        option_labels: list[str] | None = None,
        options_column: ft.Column | None = None,
        custom_option_container: ft.Container | None = None,
        custom_option_index: int = 0,
        custom_option_text: str = "",
        custom_selected: bool = False,
        free_input: ft.TextField | None = None,
        free_submit: ft.TextButton | None = None,
    ) -> None:
        if not self._plan_question_future or self._plan_question_future.done():
            return
        free_text_clean = free_text.strip()
        result = {
            "selected_index": selected_index,
            "selected_option": selected_option,
            "free_text": free_text_clean,
        }

        for idx, control in enumerate(option_buttons or []):
            label = (
                option_labels[idx]
                if option_labels and idx < len(option_labels)
                else f"{idx + 1}. Option"
            )
            is_selected = selected_index is not None and idx == selected_index
            control.disabled = True
            control.content = ft.Text(
                f"✓ {label}" if is_selected else label,
                size=TYPE_MD,
                color=TEXT_PRIMARY if is_selected else TEXT_MUTED,
                weight=ft.FontWeight.W_600 if is_selected else ft.FontWeight.W_500,
            )
            control.style = ft.ButtonStyle(
                side=ft.BorderSide(1, ft.Colors.with_opacity(0.45, ft.Colors.WHITE) if is_selected else BORDER_STRONG),
                bgcolor={
                    ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.08, ft.Colors.WHITE) if is_selected else ft.Colors.TRANSPARENT,
                },
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            )

        if custom_option_container is not None:
            custom_option_container.visible = custom_selected and bool(free_text_clean)
            if custom_selected and free_text_clean:
                custom_option_container.content = ft.OutlinedButton(
                    disabled=True,
                    content=ft.Text(
                        f"✓ {custom_option_index}. {custom_option_text}",
                        size=TYPE_MD,
                        color=TEXT_PRIMARY,
                        weight=ft.FontWeight.W_600,
                    ),
                    style=ft.ButtonStyle(
                        side=ft.BorderSide(1, ft.Colors.with_opacity(0.45, ft.Colors.WHITE)),
                        bgcolor={ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.08, ft.Colors.WHITE)},
                        shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                    ),
                )

        if free_input:
            free_input.disabled = True
            free_input.visible = False
        if free_submit:
            free_submit.disabled = True
            free_submit.visible = False
        if status_text:
            status_text.value = "Answered by user" if custom_selected else "Answered"
            status_text.visible = True
        if status_icon:
            status_icon.visible = True
        if status_row:
            status_row.visible = True
        self._safe_page_update()
        self._show_thinking_indicator()
        loop = self._plan_question_future.get_loop()
        loop.call_soon_threadsafe(self._plan_question_future.set_result, result)

    async def _render_plan_ready_prompt(self):
        if not self.page or not self.messages_column:
            return
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return
        if self._plan_ready_prompt_open:
            return
        self._plan_ready_prompt_open = True

        status = ft.Text("", size=TYPE_SM, color=TEXT_MUTED)
        no_button = ft.TextButton("No")
        yes_button = ft.FilledButton(
            "Yes, implement plan",
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ACCENT},
                color=ft.Colors.BLACK,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            ),
        )

        def on_approve(_e):
            if self.page:
                self.page.run_task(
                    self._handle_plan_ready_decision,
                    True,
                    status,
                    [no_button, yes_button],
                    actions_wrap,
                )

        def on_decline(_e):
            if self.page:
                self.page.run_task(
                    self._handle_plan_ready_decision,
                    False,
                    status,
                    [no_button, yes_button],
                    actions_wrap,
                )

        no_button.on_click = on_decline
        yes_button.on_click = on_approve

        actions = ft.Row(
            [
                no_button,
                yes_button,
            ],
            alignment=ft.MainAxisAlignment.END,
        )
        actions_wrap = ft.Container(content=actions)

        card = ft.Container(
            width=SPECIAL_CARD_WIDTH,
            border=ft.Border.all(1, ACCENT_SOFT),
            border_radius=RADIUS_MD,
            bgcolor=SURFACE_ELEVATED,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            content=ft.Column(
                [
                    ft.Text(
                        "Implement this plan?",
                        size=TYPE_TITLE,
                        color=TEXT_PRIMARY,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        "Execution is blocked until you approve.",
                        size=TYPE_BODY,
                        color=TEXT_SECONDARY,
                    ),
                    ft.Text(
                        f"Asked {self.agent.session.plan_questions_asked} questions",
                        size=TYPE_BODY,
                        color=TEXT_MUTED,
                    ),
                    actions_wrap,
                    status,
                ],
                spacing=8,
                tight=True,
            ),
        )
        self._append_chat_control(
            self._wrap_in_lane(ft.Row([card], alignment=ft.MainAxisAlignment.START))
        )
        self._safe_page_update()
        self._scroll_chat_to_bottom(force=True)

    async def _handle_plan_ready_decision(
        self,
        approved: bool,
        status_text: ft.Text,
        action_buttons: list[ft.Control] | None = None,
        actions_container: ft.Container | None = None,
    ):
        await self._ensure_agent()
        if not self.agent or not self.agent.session:
            return
        for control in action_buttons or []:
            control.disabled = True
        if actions_container is not None:
            actions_container.visible = False

        if approved:
            # Approving exits plan mode and starts execution.
            before_count = self._execution_todo_count()
            self.agent.session.seed_execution_todos_from_plan(
                self.agent.session.pending_plan_text
            )
            self.agent.session.set_plan_mode(False)
            self.agent.session.set_plan_phase("idle")
            self.agent.session.promote_pending_plan_to_active()
            self.agent.session.plan_questions_asked = 0
            self._plan_question_count = 0
            self._plan_ready_prompt_open = False
            self._sync_plan_toggle_ui()
            self._announce_initial_execution_todos_if_created(before_count)
            status_text.value = "Approved. Plan mode off. Starting implementation."
            status_text.color = SUCCESS
            self._safe_page_update()
            self._add_assistant_card(
                "Plan Mode",
                ft.Column(
                    [
                        ft.Text(
                            "Implementation started.",
                            size=TYPE_TITLE,
                            color=TEXT_PRIMARY,
                            weight=ft.FontWeight.W_600,
                        ),
                        ft.Text(
                            "Plan mode has been turned off for this run.",
                            size=TYPE_BODY,
                            color=TEXT_SECONDARY,
                        ),
                    ],
                    spacing=4,
                    tight=True,
                ),
            )
            self._active_turn_id += 1
            turn_id = self._active_turn_id
            self._active_turn_task = self.page.run_task(
                self._run_agent,
                Agent.PLAN_EXECUTE_PROMPT,
                turn_id,
            )
            return

        # Declining keeps plan mode enabled and the plan in pending-approval state.
        self.agent.session.set_plan_mode(True)
        self.agent.session.set_plan_phase("awaiting_implementation_confirmation")
        self._plan_ready_prompt_open = False
        self._sync_plan_toggle_ui()
        status_text.value = "Not implemented. Plan remains pending."
        status_text.color = TEXT_MUTED
        self._add_assistant_card(
            "Plan Mode",
            ft.Column(
                [
                    ft.Text(
                        "Plan mode remains enabled.",
                        size=TYPE_TITLE,
                        color=TEXT_PRIMARY,
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(
                        "Next: send follow-up guidance to refine this plan.",
                        size=TYPE_BODY,
                        color=TEXT_SECONDARY,
                    ),
                    ft.Text(
                        "Or type 'implement plan' later to execute this exact plan, or type /plan off to leave Plan mode manually.",
                        size=TYPE_MD,
                        color=TEXT_MUTED,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
        )
        self._safe_page_update()


def create_gui_app(config: Config):
    gui = GUIApp(config)
    return gui.run


def run_gui(config: Config):
    import flet

    def create_page(page: ft.Page):
        gui = GUIApp(config)
        gui.run(page)

    assets_dir = str((Path(__file__).resolve().parent / "assets"))
    flet.run(main=create_page, view=ft.AppView.FLET_APP, assets_dir=assets_dir)
