from __future__ import annotations

import asyncio, contextlib, difflib, hashlib, inspect, io, json, os, re, shlex, signal, ssl
import subprocess, sys, time, uuid, webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, cast
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
from textual.command import CommandPalette
from textual.containers import Container, Horizontal, HorizontalScroll, ScrollableContainer, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Input, Select, Static, TextArea, Tree

from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.agent.session import Session
from ite.agent.session_manager import SessionManager, SessionSnapshot

from ite.attachment_refs import discover_attachable_files, extract_at_query, extract_inline_attachment_refs, resolve_inline_attachment_refs, suggest_inline_attachment_paths
from ite.attachments import MAX_ATTACHMENTS, Attachment, AttachmentManager, build_user_model_content, build_user_text_with_manifest
from ite.model_metadata import detect_vision_from_model_name
from ite.cloud import CloudAuthError, CloudConnectionError, CloudSessionState, clear_cloud_auth, ensure_cloud_auth, get_activity, get_bundled_models_result, get_cloud_auth_status, get_cloud_entitlements_result, get_remote_companion_access_status, get_usage_summary, has_stored_cloud_auth, is_cloud_api_reachable, mark_cloud_signed_out
from ite.cloud.services import generate_cloud_session_title
from ite.commands import build_registry
from ite.commands.aside import execute_aside, is_aside_command_text
from ite.config.config import DEFAULT_CONTEXT_WINDOW, ApprovalPolicy, Config
from ite.config.loader import clear_openrouter_oauth_secret, get_workspace_agents_recommendation, load_config, load_saved_custom_provider, load_theme, remove_saved_custom_provider, save_cloud_settings, save_global_approval_mode, save_onboarding_settings, save_saved_custom_provider, save_system_config, save_theme, save_voice_settings
from ite.git.branches import checkout_branch, create_and_checkout, current_branch, is_git_repo, list_local_branches
from ite.git.remotes import upsert_remote
from ite.git.working_tree import commit_changes, discard_all, discard_path, git_outbound_state, outbound_commit_subjects, push_current_branch, stage_all, stage_path, unstage_all, unstage_path, working_tree_change_set
from ite.memory import MemoryManager
from ite.remote import RemoteRuntimeServer
from ite.remote.protocol import build_remote_transcript, json_safe, serialize_agent_event, serialize_approval_request, serialize_plan_question_request, serialize_plan_ready_request
from ite.skills import build_skill_detail_renderable, build_skill_feedback_renderable, build_skills_overview_renderable
from ite.skills.manager import SkillDefinition
from ite.skills.rendering import skill_state
from ite.tools.base import Tool, ToolRiskLevel
from ite.tools.builtin.shell import send_input_to_shell_run
from ite.tools.mcp.mcp_tool import MCPTool
from ite.tools.subagent import SubagentTool
from ite.ui.reup.markdown_widget import CopyableMarkdown
from ite.ui.tool_narrative import activity_title, describe_tool_activity, progress_label
from ite.update_check import check_runtime_update, current_runtime_version, detect_install_method, get_notification_type, mark_update_notice_seen, should_show_update_notice
from ite.voice import VoiceRecorder, VoiceRecorderError, transcribe_voice_file

from .adapters.registry import StreamingCommandOutput, build_command_context
from .widgets.prompt_area import ReupPromptTextArea
from .widgets.message_row import UserMessageRow
from .widgets.state import SessionRunState, ShellSessionCardState
from .widgets.side_panels import CommandsSidePanel, HooksSidePanel, ChangeReviewSidePanel
from .widgets.thread_switcher import ThreadSwitcherRow, ThreadSwitcherSidePanel
from .widgets.tool_cards import CompactToolCard, ShellToolCard, ToolCardStack
from .widgets.remote_bridge import RemoteBridgeCard, RemoteBridgeField, UpdateCommandBox
from .widgets.system_commands import ReupSystemCommandsProvider
from .adapters.tui_adapter import ReupTUIAdapter
from .change_views import change_entry_label, build_change_card_body, build_change_card_payload
from .model_labels import bundled_model_display_label
from .modals import ApprovalPickerModal, AttachPickerModal, BranchPickerModal, CommitModal, ContextSummaryModal, ActivityModal, ModelPickerModal, ThemePickerModal, UsageSummaryModal, PushReviewModal, RemoteSetupModal, PlanQuestionModal, SessionResumeModal, VoiceSetupModal, ConfirmModal, SetupModal
from .tool_views import render_shell_running_card


class ThreadsMixin:
    """Extracted mixin for _threads."""


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


    def _session_config_for_workspace(self, workspace: Path | None = None) -> Config:
        resolved_workspace = Path(workspace or self.config.cwd).resolve()
        workspace_config = load_config(resolved_workspace)
        return workspace_config.model_copy(
            update={
                "cwd": resolved_workspace,
                "model": self.config.model.model_copy(deep=True),
                "voice": self.config.voice.model_copy(deep=True),
                "api_key": self.config.api_key,
                "base_url": self.config.base_url,
                "cloud_auth_enabled": self.config.cloud_auth_enabled,
                "cloud_api_url": self.config.cloud_api_url,
                "cloud_client_id": self.config.cloud_client_id,
                "cloud_device_name": self.config.cloud_device_name,
                "approval": self.config.approval,
                "sandbox": self.config.sandbox.model_copy(deep=True),
                "debug": self.config.debug,
                "resume_last_session": self.config.resume_last_session,
            },
            deep=False,
        )


    def _active_session_config(self) -> Config | None:
        if self.agent is None:
            return None
        session = getattr(self.agent, "session", None)
        session_config = getattr(session, "config", None)
        return session_config if isinstance(session_config, Config) else None

    @staticmethod

    def _merged_sandbox_allowed_paths(*path_groups: list[Path]) -> list[Path]:
        merged: list[Path] = []
        seen: set[Path] = set()
        for paths in path_groups:
            for path in paths:
                resolved = Path(path).expanduser().resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                merged.append(resolved)
        return merged


    def _prepare_sandbox_command_config(self) -> Config:
        session_config = self._active_session_config()
        if session_config is None or session_config is self.config:
            return self.config

        merged_allowed_paths = self._merged_sandbox_allowed_paths(
            self.config.sandbox.allowed_paths,
            session_config.sandbox.allowed_paths,
        )
        self.config.sandbox.allowed_paths = list(merged_allowed_paths)
        session_config.sandbox.allowed_paths = list(merged_allowed_paths)
        session_config.sandbox.enabled = self.config.sandbox.enabled
        return session_config


    def _sync_app_sandbox_from_active_session(self) -> None:
        session_config = self._active_session_config()
        if session_config is None or session_config is self.config:
            return
        self.config.sandbox = session_config.sandbox.model_copy(deep=True)


    def _sandbox_render_config(self) -> Config:
        return self._active_session_config() or self.config


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
        self._thread_nav_order = [
            sid for sid in self._thread_nav_order if sid != session_id
        ]
        return self._session_agents.pop(session_id, None)


    def _session_tab_label(self, session_id: str) -> str:
        session = self._open_sessions.get(session_id)
        title = self._session_title(session)
        title = re.sub(r"\s+", " ", title).strip() or "New thread"
        if self._run_state(session_id).is_turn_running:
            title = f"●●● {title}"
        return title


    def _thread_switcher_threads(self) -> list[tuple[str, str, str, str]]:
        active_session_id = self._active_session_id()
        rows_by_session_id: dict[str, tuple[str, str, str, str]] = {}
        discovered_order: list[str] = []
        hidden_session_ids: set[str] = set()
        open_session_ids: set[str] = set()
        for session_id in self._open_session_order:
            session = self._open_sessions.get(session_id)
            if session is None:
                continue
            open_session_ids.add(session_id)
            discovered_order.append(session_id)
            is_running = self._run_state(session_id).is_turn_running
            if (
                getattr(session, "turn_count", 0) == 0
                and not is_running
                and self._session_title(session) == "New thread"
            ):
                hidden_session_ids.add(session_id)
                continue
            title = self._session_title(session)
            title = re.sub(r"\s+", " ", title).strip() or "New thread"
            state = ""
            if session_id == active_session_id:
                state = "current"
            elif is_running:
                state = "running"
            rows_by_session_id[session_id] = (session_id, title, state, "open")
        sessions = SessionManager().list_sessions(
            workspace_path=self.config.cwd,
            include_legacy_unscoped=False,
        )
        for session in sessions:
            session_id = str(session.get("session_id", "") or "").strip()
            if not session_id:
                continue
            if int(session.get("turn_count", 0) or 0) <= 0:
                continue
            if session_id not in discovered_order:
                discovered_order.append(session_id)
            if session_id in open_session_ids:
                continue
            title = str(session.get("name") or "").strip()
            title = re.sub(r"\s+", " ", title).strip() or "Untitled thread"
            rows_by_session_id[session_id] = (session_id, title, "saved", "saved")
        if not self._thread_nav_order:
            self._thread_nav_order = list(discovered_order)
        else:
            available = set(rows_by_session_id) | hidden_session_ids
            self._thread_nav_order = [
                sid for sid in self._thread_nav_order if sid in available
            ]
            for session_id in discovered_order:
                if session_id not in self._thread_nav_order:
                    self._thread_nav_order.append(session_id)
        return [
            rows_by_session_id[session_id]
            for session_id in self._thread_nav_order
            if session_id in rows_by_session_id
        ]


    def _thread_switcher_should_auto_open(self) -> bool:
        return (
            len(self._open_session_order) > 1
            and not self._cloud_signed_out
            and self._thread_switcher_dismissed_count != len(self._open_session_order)
        )


    def _thread_switcher_panel_is_open(self) -> bool:
        panel = self._thread_switcher_panel
        return bool(panel is not None and panel.is_mounted)


    def _insert_thread_nav_session_at_top(self, session_id: str | None) -> None:
        if not session_id:
            return
        self._thread_nav_order = [
            sid for sid in self._thread_nav_order if sid != session_id
        ]
        self._thread_nav_order.insert(0, session_id)


    def _apply_thread_switcher_button_state(self) -> None:
        try:
            toggle = self.query_one("#threads-toggle", Button)
        except Exception:
            return
        visible = not self._cloud_signed_out
        toggle.display = visible and not self._thread_switcher_panel_is_open()
        toggle.label = "≡"


    def _queue_session_tabs_refresh(self) -> None:
        self._session_tabs_version += 1
        self._run_worker_safely(
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
        if self._cloud_signed_out:
            tabs.display = False
            tabs_scroll.display = False
            await self._hide_thread_switcher_panel(remember=False)
            return
        tabs.display = False
        tabs_scroll.display = False
        await self._sync_thread_switcher_panel()
        return


    async def _sync_thread_switcher_panel(self, *, force_open: bool = False) -> None:
        async with self._thread_switcher_sync_lock:
            if not self.is_mounted:
                return
            count = len(self._open_session_order)
            self._apply_thread_switcher_button_state()
            if self._cloud_signed_out or count <= 0 or self._commands_panel_is_open():
                if count <= 0:
                    self._thread_switcher_dismissed_count = 0
                await self._hide_thread_switcher_panel(remember=False)
                return
            if force_open:
                self._thread_switcher_dismissed_count = 0
            should_open = force_open or self._thread_switcher_should_auto_open()
            if not should_open and not self._thread_switcher_panel_is_open():
                return
            threads = self._thread_switcher_threads()
            panel = self._thread_switcher_panel
            if panel is None or not panel.is_mounted:
                panel = ThreadSwitcherSidePanel(
                    threads=threads,
                    email=self._cloud_user_email or "",
                    image=self._cloud_user_image,
                    id="thread-switcher-panel",
                )
                await self.screen.mount(panel)
                self._thread_switcher_panel = panel
            else:
                await panel.refresh_threads(threads)
                panel.refresh_account_info(
                    self._cloud_user_email or "",
                    self._cloud_user_image,
                )
            self._apply_thread_switcher_button_state()


    def _refresh_thread_switcher_account(self) -> None:
        panel = self._thread_switcher_panel
        if panel is None or not panel.is_mounted:
            return
        panel.refresh_account_info(
            self._cloud_user_email or "",
            self._cloud_user_image,
        )


    async def _hide_thread_switcher_panel(self, *, remember: bool = True) -> None:
        if remember:
            self._thread_switcher_dismissed_count = len(self._open_session_order)
        panel = self._thread_switcher_panel
        self._thread_switcher_panel = None
        if panel is not None:
            try:
                await panel.remove()
            except Exception:
                pass
        self._apply_thread_switcher_button_state()
        self._maybe_focus_prompt()


    async def _toggle_thread_switcher_panel(self) -> None:
        if self._thread_switcher_panel_is_open():
            await self._hide_thread_switcher_panel()
            return
        await self._sync_thread_switcher_panel(force_open=True)


    def refresh_header(self, *, refresh_session_tabs: bool = True) -> None:
        current_workspace_key = str(Path(self.config.cwd).resolve())
        if (
            self._agents_recommendation_last_workspace_key is not None
            and self._agents_recommendation_last_workspace_key != current_workspace_key
        ):
            self._agents_recommendation_current_visit = None
        self._agents_recommendation_last_workspace_key = current_workspace_key
        title = self.query_one("#title", Static)
        plan_badge = self.query_one("#plan-badge", Static)
        meta = self.query_one("#header-meta", Static)
        if self._cloud_signed_out:
            title.update("Sign in")
            plan_badge.display = False
            meta.update("iTE Cloud required")
        else:
            title.update(self._current_session_title())
            plan_badge.display = True
            plan_badge.update(self._plan_badge_renderable())
            cwd_name = os.path.basename(self.config.cwd) or self.config.cwd
            meta.update(f"WORKSPACE: {cwd_name}")
        self._update_composer_meta_line()
        self.run_worker(self._refresh_change_review_source(), exclusive=False)
        if refresh_session_tabs:
            self._queue_session_tabs_refresh()


    def _plan_badge_renderable(self) -> Text:
        styles = self._render_styles()
        if self._account_plan_unavailable:
            return Text(
                " Offline ",
                style=f"bold {styles['muted']} on {styles['surface']}",
                no_wrap=True,
            )
        if self._account_plan_is_pro is None:
            frame = self._top_spinner_frames[
                self._top_spinner_index % len(self._top_spinner_frames)
            ]
            return Text(
                f" {frame} ",
                style=f"bold {styles['secondary']} on {styles['surface']}",
                no_wrap=True,
            )
        label = "Pro" if self._account_plan_is_pro else "Free"
        badge_bg = styles["success"] if self._account_plan_is_pro else styles["warning"]
        badge_fg = styles["background"]
        badge_style = f"bold {badge_fg} on {badge_bg}"
        return Text(f" {label} ", style=badge_style, no_wrap=True)


    def _set_account_plan_badge_state(
        self, is_pro: bool | None, *, unavailable: bool = False
    ) -> None:
        if (
            self._account_plan_is_pro == is_pro
            and self._account_plan_unavailable == unavailable
        ):
            return
        self._account_plan_is_pro = is_pro
        self._account_plan_unavailable = unavailable
        self.refresh_header()


    def _set_local_account_plan_state(self, *, refresh: bool = True) -> None:
        self._bundled_models_cache = []
        self._usage_summary_cache = None
        self._usage_remaining_percent = None
        self._account_plan_is_pro = False
        self._account_plan_unavailable = False
        self._cloud_user_email = None
        self._cloud_user_image = None
        if refresh:
            self.refresh_header()


    @on(ThreadSwitcherRow.Selected)

    async def on_thread_switcher_row_selected(
        self, event: ThreadSwitcherRow.Selected
    ) -> None:
        session_id = event.session_id.strip()
        if not session_id:
            return

        # Show centered spinner state (clears conversation, shows centered loader)
        self._session_switching = True
        self._apply_shell_surface()

        if session_id in self._open_sessions:
            await self._activate_open_session(session_id)
            self._session_switching = False
            self._apply_shell_surface()
            return

        # Load snapshot on thread pool to avoid blocking UI
        snapshot = await asyncio.to_thread(
            lambda: SessionManager().load_session(session_id)
        )
        if snapshot is None:
            self._session_switching = False
            self._apply_shell_surface()
            self.post_system(
                "Sessions", f"Session not found: {session_id}", is_error=True
            )
            return
        await self._resume_snapshot(snapshot)
        # Clear centering spinner
        self._session_switching = False
        self._apply_shell_surface()

    async def _exit_app(self) -> None:
        await self._shutdown_remote_server()
        await self._shutdown_agents()
        self.exit()

    async def _apply_setup_result(self, result: dict[str, Any]) -> None:
        try:
            save_system_config(
                api_key=result["api_key"],
                base_url=result["base_url"],
                model_name=result["model_name"],
                context_window=int(
                    result.get("context_window") or DEFAULT_CONTEXT_WINDOW
                ),
                context_window_source=str(
                    result.get("context_window_source") or ""
                ).strip()
                or None,
                source_kind="saved",
            )
            save_saved_custom_provider(
                api_key=result["api_key"],
                base_url=result["base_url"],
                model_name=result["model_name"],
                context_window=int(
                    result.get("context_window") or DEFAULT_CONTEXT_WINDOW
                ),
                context_window_source=str(
                    result.get("context_window_source") or ""
                ).strip()
                or None,
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
        self.config.model.source_kind = "saved"
        self.config.model.supports_vision = self._resolve_model_vision_support(
            result["model_name"], source_kind="saved"
        )
        self.config.approval = ApprovalPolicy(result["approval"])
        await self._reset_active_provider_client()
        self.refresh_header(refresh_session_tabs=False)
        self.post_notice("Setup complete", "Credentials saved and applied.")

    async def _apply_openrouter_signout(self, result: dict[str, Any]) -> None:
        """Remove the OpenRouter key everywhere it is persisted.

        Clears the OAuth secret, the ``api_key`` in the system config, and the
        saved-provider profile — the profile is what the /models picker lists
        OpenRouter models from, so removing it keeps signed-out models out of
        the picker.
        """
        model_name = str(result.get("model_name") or "").strip()
        try:
            clear_openrouter_oauth_secret()
            if model_name:
                remove_saved_custom_provider(model_name=model_name)
            # Persist the removal only when the active provider is actually
            # OpenRouter; never clobber an Ollama/custom config by accident.
            if "openrouter.ai" in str(self.config.base_url or "").lower():
                save_system_config(
                    api_key="",
                    base_url=str(self.config.base_url or ""),
                    model_name=str(self.config.model_name or ""),
                    context_window=int(
                        self.config.model.context_window or DEFAULT_CONTEXT_WINDOW
                    ),
                    context_window_source=str(
                        self.config.model.context_window_source or ""
                    ).strip() or None,
                    source_kind="saved",
                )
        except Exception as exc:  # noqa: BLE001 - surface any persistence failure
            self.post_system(
                "Sign out failed", str(exc), is_error=True
            )
            return

        self.config.api_key = ""
        # If the current model belonged to the removed OpenRouter profile,
        # clear it so no OpenRouter model lingers as the active selection.
        if model_name and self.config.model.name == model_name:
            self.config.model.name = ""
            self.config.model.source_kind = ""
        await self._reset_active_provider_client()
        self.refresh_header(refresh_session_tabs=False)
        self.post_notice(
            "Signed out of OpenRouter",
            "The key was removed from this device.",
        )


    def _tick_top_indicator(self) -> None:
        flow_animating = self._voice_recorder is not None or self._voice_busy
        send_animating = self._is_turn_running
        plan_animating = (
            self._account_plan_is_pro is None
            and not self._cloud_signed_out
            and not self._account_plan_unavailable
        )
        onboarding_animating = self._onboarding_busy
        signed_out_animating = self._cloud_auth_busy or self._cloud_bootstrap_busy
        has_pending_command_spinner = any(
            pending_active
            for _card, _body_widget, _scroll_widget, _lines, pending_active, _pending_text in self._streaming_command_cards.values()
        )
        if (
            not self._top_busy
            and not self._aside_pending_widgets
            and not has_pending_command_spinner
            and not self._cloud_auth_busy
            and not self._cloud_bootstrap_busy
            and not onboarding_animating
            and not flow_animating
            and not send_animating
            and not plan_animating
            and not self._session_switching
        ):
            return
        self._top_spinner_index += 1
        if plan_animating:
            self._refresh_plan_badge_renderable()
        if send_animating:
            self._send_meta_frame += 1
            self._update_composer_send_control()
        if flow_animating:
            self._flow_meta_frame += 1
            self._update_composer_flow_control()
        if self._top_spinner_index % 3 == 0:
            self._activity_suffix_index += 1
        # Update session switch spinner (centered loader)
        if self._session_switching:
            self._update_session_switch_spinner()
        if onboarding_animating:
            try:
                self.query_one("#onboarding-status", Static).update(
                    self._onboarding_status_text()
                )
            except NoMatches:
                pass
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
        if self._cloud_signed_out or signed_out_animating:
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

        fresh = Session(config=self._session_config_for_workspace())
        fresh_agent = self._build_session_agent(fresh)
        await fresh_agent.__aenter__()
        self._remember_open_session(fresh, agent=fresh_agent)
        self._insert_thread_nav_session_at_top(self._session_id(fresh))
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
        self._thread_nav_order = [
            sid for sid in self._thread_nav_order if sid != current_session_id
        ]
        self._session_run_states.pop(current_session_id, None)
        closed_agent = self._session_agents.pop(current_session_id, None)

        if next_session_id:
            await self._activate_open_session(next_session_id)
        else:
            fresh = Session(config=self._session_config_for_workspace())
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


    async def auto_save(self, *, allow_name_generation: bool = True) -> None:
        if not self.agent or not self.agent.session:
            return

        await self._auto_save_session(
            self.agent.session,
            workspace=Path(self.config.cwd).resolve(),
            refresh_ui=True,
            allow_name_generation=allow_name_generation,
        )


    async def _auto_save_session(
        self,
        session: Session,
        *,
        workspace: Path,
        refresh_ui: bool,
        allow_name_generation: bool = True,
    ) -> None:
        if session.turn_count == 0:
            return

        if allow_name_generation and (
            session.name is None
            or session.should_refresh_auto_name()
        ):
            self._queue_session_name_refinement(
                session,
                workspace=workspace,
                refresh_ui=refresh_ui,
            )

        snapshot = SessionSnapshot(
            **session.snapshot_kwargs(workspace_path=str(workspace.resolve()))
        )
        SessionManager().save_session(snapshot)


    def _queue_session_name_refinement(
        self,
        session: Session,
        *,
        workspace: Path,
        refresh_ui: bool,
    ) -> None:
        session_id = self._session_id(session)
        if not session_id or session_id in self._session_name_refinements:
            return
        if not has_stored_cloud_auth(self.config):
            return
        self._session_name_refinements.add(session_id)
        self.run_worker(
            self._refine_session_name(
                session,
                workspace=workspace,
                refresh_ui=refresh_ui,
            ),
            exclusive=False,
        )


    async def _refine_session_name(
        self,
        session: Session,
        *,
        workspace: Path,
        refresh_ui: bool,
    ) -> None:
        session_id = self._session_id(session)
        try:
            if getattr(session, "name_locked", False):
                return
            current = str(session.name or "").strip()
            refreshed = (await self._generate_cloud_session_name(session) or "").strip()
            if refreshed and refreshed != current:
                session.set_auto_name(refreshed)
            else:
                session.mark_auto_name_attempt()
            snapshot = SessionSnapshot(
                **session.snapshot_kwargs(workspace_path=str(workspace.resolve()))
            )
            SessionManager().save_session(snapshot)
            self._refresh_session_name_ui(session, refresh_ui=refresh_ui)
        finally:
            if session_id:
                self._session_name_refinements.discard(session_id)


    def _refresh_session_name_ui(
        self,
        session: Session,
        *,
        refresh_ui: bool,
    ) -> None:
        if refresh_ui and self._session_id(session) == self._active_session_id():
            self.refresh_header()
        elif self.is_mounted:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return
            self._queue_session_tabs_refresh()


    async def generate_session_name(self, session: Session) -> str:
        cloud_title = await self._generate_cloud_session_name(session)
        return cloud_title or ""


    async def _generate_cloud_session_name(self, session: Session) -> str | None:
        try:
            context = session.name_generation_context()
            first_user = str(context.get("first_user", "") or "")

            if not first_user:
                return None
            cloud_title = await generate_cloud_session_title(self.config, context)
            if cloud_title:
                return cloud_title

        except Exception:
            pass

        return None


def run_reup(config: Config) -> None:
    app = ReupApp(config)
    app.run()
    if sys.stdout.isatty():
        sys.stdout.write("\n")
        sys.stdout.flush()
