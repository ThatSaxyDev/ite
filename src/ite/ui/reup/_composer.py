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

from ite.attachment_refs import discover_attachable_files, extract_at_query, extract_inline_attachment_refs, parse_dropped_file_paths, resolve_inline_attachment_refs, suggest_inline_attachment_paths
from ite.attachments import MAX_ATTACHMENTS, Attachment, AttachmentManager, build_user_model_content, build_user_text_with_manifest
from ite.model_metadata import detect_vision_from_model_name
from ite.cloud import CloudAuthError, CloudConnectionError, CloudSessionState, clear_cloud_auth, ensure_cloud_auth, get_activity, get_bundled_models_result, get_cloud_auth_status, get_cloud_entitlements_result, get_remote_companion_access_status, get_usage_summary, has_stored_cloud_auth, is_cloud_api_reachable, mark_cloud_signed_out
from ite.cloud.services import generate_cloud_session_title
from ite.commands import build_registry
from ite.commands.aside import execute_aside, is_aside_command_text
from ite.config.config import DEFAULT_CONTEXT_WINDOW, ApprovalPolicy, Config
from ite.config.loader import get_workspace_agents_recommendation, load_config, load_saved_custom_provider, load_theme, remove_saved_custom_provider, save_cloud_settings, save_global_approval_mode, save_onboarding_settings, save_saved_custom_provider, save_system_config, save_theme, save_voice_settings
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

_VOICE_TRANSCRIPTION_MAX_RETRIES = 2

from ._helpers import _is_transient_voice_error, insert_voice_text_into_widget, redact_sensitive_command_text

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


class ComposerMixin:
    """Extracted mixin for _composer."""


    def _update_composer_meta_line(self) -> None:
        try:
            composer_meta_line = self.query_one("#composer-meta-line", Static)
        except Exception:
            return
        composer_meta_line.update(self._composer_meta_text())
        self._update_composer_flow_control()
        self._update_composer_send_control()


    def _refresh_plan_badge_renderable(self) -> None:
        if self._cloud_signed_out:
            return
        try:
            self.query_one("#plan-badge", Static).update(self._plan_badge_renderable())
        except Exception:
            return


    def _update_composer_send_control(self) -> None:
        try:
            send_control = self.query_one("#composer-send-control", Static)
        except Exception:
            return
        send_control.update(
            send_control_text(
                turn_running=self._is_turn_running,
                send_frame=self._send_meta_frame,
                styles=self._render_styles(),
            )
        )


    def _update_composer_flow_control(self) -> None:
        try:
            flow_control = self.query_one("#composer-flow-control", Static)
        except Exception:
            return
        text = flow_control_text(
            flow_enabled=bool(self.config.voice.enabled),
            flow_state=self._flow_meta_state(),
            flow_frame=self._flow_meta_frame,
            styles=self._render_styles(),
        )
        flow_control.display = bool(text.plain)
        flow_control.update(text)


    def _composer_meta_text(self) -> Text:
        plan_enabled = bool(
            self.agent and self.agent.session and self.agent.session.plan_mode_enabled
        )
        context_used_percent: int | None = None
        branch_label = "no-git"
        try:
            cwd = Path(self.config.cwd).resolve()
            now = time.monotonic()
            # Prefer the freshly-polled branch from git_outbound_state
            # (updated every 1-3s by _refresh_change_review_source)
            if self._git_outbound_state is not None and getattr(
                self._git_outbound_state, "branch", None
            ):
                branch_label = self._git_outbound_state.branch
            elif self._cached_git_cwd == cwd and now - self._cached_git_ts < 30.0:
                if self._cached_is_git_repo:
                    branch_label = self._cached_branch_label
            else:
                in_repo = is_git_repo(cwd)
                self._cached_git_cwd = cwd
                self._cached_is_git_repo = in_repo
                self._cached_git_ts = now
                if in_repo:
                    self._cached_branch_label = current_branch(cwd)
                    branch_label = self._cached_branch_label
                else:
                    self._cached_branch_label = "no-git"
        except Exception:
            pass
        model_display_name = self._model_display_name()
        if (
            model_display_name != "select model"
            and self.agent
            and self.agent.session
            and self.agent.session.context_manager
        ):
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
        available_width: int | None = None
        try:
            meta_line = self.query_one("#composer-meta-line", Static)
            width = int(getattr(meta_line.size, "width", 0) or 0)
            if width > 0:
                available_width = width
        except Exception:
            pass
        (
            text,
            attach_hitbox,
            model_hitbox,
            branch_hitbox,
            plan_hitbox,
            usage_hitbox,
            context_hitbox,
            activity_hitbox,
            flow_hitbox,
        ) = composer_meta_text(
            cwd=Path(self.config.cwd),
            model_name=model_display_name,
            plan_enabled=plan_enabled,
            branch_label=branch_label,
            usage_remaining_percent=self._usage_remaining_percent,
            context_used_percent=context_used_percent,
            styles=self._render_styles(),
            show_usage=self._is_bundled_model(),
            show_context=model_display_name != "select model",
            available_width=available_width,
        )
        self._composer_attach_hitbox = attach_hitbox
        self._composer_model_hitbox = model_hitbox
        self._composer_branch_hitbox = branch_hitbox
        self._composer_plan_hitbox = plan_hitbox
        self._composer_usage_hitbox = usage_hitbox
        self._composer_context_hitbox = context_hitbox
        self._composer_activity_hitbox = activity_hitbox
        self._composer_flow_hitbox = flow_hitbox
        return text


    def _flow_meta_state(
        self,
    ) -> Literal["idle", "recording", "transcribing", "missing_key"]:
        if self._voice_recorder is not None:
            return "recording"
        if self._voice_busy:
            return "transcribing"
        if self.config.voice.enabled and not self._voice_has_provider():
            return "missing_key"
        return "idle"


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
            limit=10000,
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
        name = path.expanduser().resolve().name
        if any(ch.isspace() for ch in name):
            return f'@"{name}"'
        return f"@{name}"


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


    @staticmethod
    def _is_path_like_probe(candidate: str) -> bool:
        probe = candidate.strip().strip("\"'")
        return (
            probe.startswith(("/", "~"))
            or probe.lower().startswith("file://")
            or bool(re.match(r"^[A-Za-z]:[\\/]", probe))
        )


    @staticmethod
    def _drop_candidate_starts(tail: str) -> list[int]:
        """Indexes in ``tail`` where a dropped path could begin.

        Covers the start of the line, each whitespace-delimited token, and any
        path boundary embedded *inside* a token (``/``, ``~``, ``file://``,
        drive letters). The latter is what a path looks like when the terminal
        types the drop straight into the caret after an existing word.
        """
        starts = {0}
        lowered = tail.lower()
        for index, char in enumerate(tail):
            if char.isspace():
                starts.add(index + 1)
            if char in "/~" or lowered.startswith("file://", index):
                starts.add(index)
            elif re.match(r"[A-Za-z]:[\\/]", tail[index : index + 3]):
                starts.add(index)
        return sorted(start for start in starts if start < len(tail))


    def _rewrite_trailing_dropped_path(self, text: str) -> tuple[str, list[str]] | None:
        """Replace a trailing dropped absolute path with an @name ref.

        Terminals such as macOS Terminal.app deliver drag-and-dropped files as
        typed keystrokes rather than a bracketed paste, so the raw path
        (leading slash and all) lands directly in the composer and is mistaken
        for a slash command. Because the path is typed at the caret, it can be
        glued to whatever the user last typed (``look at this/Users/…``); when
        that happens we insert a separator space so the drop becomes a clean
        ``@name`` token. Returns ``(text, paths)`` or ``None`` when there is
        nothing to rewrite.
        """
        if not text:
            return None
        newline = text.rfind("\n")
        head, tail = text[: newline + 1], text[newline + 1 :]
        if not tail:
            return None
        for start in self._drop_candidate_starts(tail):
            candidate = tail[start:]
            if not self._is_path_like_probe(candidate):
                continue
            parsed = parse_dropped_file_paths(candidate)
            if not parsed.paths:
                continue
            refs = " ".join(
                self._attachment_ref_for_path(Path(path)) for path in parsed.paths
            )
            prefix = tail[:start]
            separator = "" if not prefix or prefix[-1].isspace() else " "
            return f"{head}{prefix}{separator}{refs}", parsed.paths
        return None


    def _normalize_dropped_path_message(self, message: str) -> str | None:
        """Rewrite a dropped/pasted absolute-path payload into @name refs.

        Terminals deliver drag-and-dropped files as raw absolute paths (e.g.
        "/Users/…/image.png"), whose leading slash would otherwise be read as a
        slash command. When the message is purely path-like, stage the files as
        attachments and return "@name" refs so the drop sends exactly like an
        @-mention attachment. Returns None to swallow the send when the payload
        is path-like but no file resolved (errors are posted as notes).
        """
        result = parse_dropped_file_paths(message)
        if result.path_like_count == 0 or result.prose_count > 0:
            return message

        session = getattr(getattr(self, "agent", None), "session", None)
        if result.paths and session is not None:
            pending = list(session.pending_attachment_paths)
            for path in result.paths:
                if path not in pending:
                    pending.append(path)
            session.pending_attachment_paths = pending[:MAX_ATTACHMENTS]

        for error in result.errors:
            self.post_attachment_note(error)

        if not result.paths:
            return None
        return " ".join(self._attachment_ref_for_path(Path(p)) for p in result.paths)


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
        if start <= event.x < end:
            self.run_worker(self._toggle_plan_mode_from_meta(), exclusive=False)
            event.stop()

    @on(events.Click, "#composer-flow-control")

    def on_composer_flow_control_click(self, event: events.Click) -> None:
        self.action_toggle_voice_input()
        event.stop()

    @on(events.Click, "#plan-badge")

    def on_plan_badge_click(self, event: events.Click) -> None:
        event.stop()
        if self._account_plan_unavailable:
            self.post_notice(
                "iTE Cloud",
                "Plan status is unavailable right now. Try again later.",
                timeout=5,
            )
            return
        if self._account_plan_is_pro is None:
            return
        if self._account_plan_is_pro:
            return
        opened = webbrowser.open("https://ite.kiishi.space/pricing")
        if opened:
            self.post_notice("Pricing", "Opened iTE Pro pricing in your browser.")
        else:
            self.post_notice(
                "Pricing",
                "Open https://ite.kiishi.space/pricing to start iTE Pro.",
            )

    @on(events.Click, "#composer-send-control")

    def on_composer_send_control_click(self, event: events.Click) -> None:
        self.run_worker(self._activate_send_stop_control(), exclusive=False)
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


    def action_command_palette(self) -> None:
        """Open the command palette while preserving Reup system command order."""
        if not CommandPalette.is_open(self):
            self.push_screen(
                CommandPalette(
                    providers=[ReupSystemCommandsProvider],
                    id="--command-palette",
                ),
                callback=lambda _: self._maybe_focus_prompt(),
            )


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
        if not re.search(r"\bplans?\b|\bplanning\b", text):
            return False

        strong_phrases = (
            "make a plan",
            "make plans",
            "implementation plan",
            "implementation planning",
            "before coding",
            "plan this",
            "create a plan",
            "draft a plan",
            "what is the plan",
            "outline the plan",
            "planning first",
            "plan before",
        )
        if any(p in text for p in strong_phrases):
            return True

        plan_context_markers = (
            "let's",
            "lets",
            "let us",
            "need",
            "needs",
            "should",
            "before",
            "first",
            "outline",
            "draft",
            "create",
            "make",
            "write",
            "implementation",
            "approach",
        )
        if any(marker in text for marker in plan_context_markers):
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
                    body="This prompt mentions planning. Use Plan mode or send normally?",
                    yes_label="Use plan mode",
                    no_label="Send normally",
                    primary="no",
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
        newline_hint = (
            "On macOS Terminal.app, Shift+Enter cannot insert a newline "
            "(the terminal does not distinguish it from Enter). "
            "Use Ctrl+J to insert a newline. Shift+Enter works normally "
            "in iTerm2, WezTerm, Ghostty, VS Code, and JetBrains terminals."
            if self.is_macos_terminal_app()
            else "Use Shift+Enter to insert a newline, or Ctrl+J as a fallback."
        )
        self.post_system(
            "Help",
            "Enter text and use Ctrl+Enter to send.\n"
            f"{newline_hint}\n"
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


    async def _activate_send_stop_control(self) -> None:
        if self._is_turn_running:
            await self.cancel_active_turn()
            return
        await self.handle_send()


    def action_toggle_voice_input(self) -> None:
        self.run_worker(self._toggle_voice_input(), exclusive=False)


    async def _toggle_voice_input(self) -> None:
        if self._voice_busy:
            return
        if self._voice_recorder is not None:
            await self._stop_voice_input()
            return
        await self._start_voice_input()


    async def _start_voice_input(self) -> None:
        if not self.config.voice.enabled:
            self.post_notice(
                "Flow",
                "Enable flow with `/flow on` before recording.",
                timeout=6,
            )
            return
        if not self._voice_has_provider():
            self.post_notice(
                "Flow",
                "Sign in to iTE Cloud or add a Groq API key with `/flow setup` before recording.",
                timeout=6,
            )
            return

        target = self.focused
        if not isinstance(target, Input | TextArea):
            self.post_notice(
                "Flow",
                "Place your cursor in a text field, then press Ctrl+S.",
            )
            return

        recorder = VoiceRecorder()
        try:
            await recorder.start()
        except VoiceRecorderError:
            self.post_notice("Flow", "An error occurred, please try again.", timeout=8)
            return

        self._voice_recorder = recorder
        self._voice_target = target
        self._flow_meta_frame = 0
        self._update_composer_meta_line()


    async def _stop_voice_input(self) -> None:
        recorder = self._voice_recorder
        target = self._voice_target
        if recorder is None:
            return

        self._voice_recorder = None
        self._voice_target = None
        self._voice_busy = True
        self._flow_meta_frame = 0
        self._update_composer_meta_line()
        audio_path: Path | None = None
        try:
            audio_path = await recorder.stop()
            result = None
            for attempt in range(_VOICE_TRANSCRIPTION_MAX_RETRIES + 1):
                try:
                    result = await transcribe_voice_file(self.config, audio_path)
                    break
                except Exception as exc:
                    if not _is_transient_voice_error(exc) or attempt >= _VOICE_TRANSCRIPTION_MAX_RETRIES:
                        raise
                    await asyncio.sleep(min(2**attempt, 4))
            assert result is not None, "transcription result must be set"
            transcript = result.transcript.strip()
            if not transcript:
                self.post_notice("Flow", "No speech detected.")
                return

            insert_target = target
            if insert_target is None or not getattr(insert_target, "is_mounted", True):
                focused = self.focused
                insert_target = (
                    focused if isinstance(focused, Input | TextArea) else None
                )
            if insert_target is None or not insert_voice_text_into_widget(
                insert_target,
                transcript,
            ):
                self.post_notice(
                    "Flow",
                    "Choose where the transcript should go, then try again.",
                )
                return
            insert_target.focus()
            if isinstance(insert_target, TextArea) and insert_target.id == "prompt":
                self._sync_command_palette(insert_target.text)
                self._resize_composer_for_prompt()
        except Exception:
            self.post_notice("Flow", "An error occurred, please try again.", timeout=8)
        finally:
            self._voice_busy = False
            self._flow_meta_frame = 0
            self._update_composer_meta_line()
            if audio_path is not None:
                with contextlib.suppress(OSError):
                    audio_path.unlink(missing_ok=True)


    async def _run_voice_command_native(self, args: list[str]) -> None:
        action = (args[0] if args else "status").strip().lower()
        if action == "status":
            status = "Ready" if self.config.voice.enabled else "Not enabled"
            if str(self.config.voice.groq_api_key or "").strip():
                key_status = "local Groq key ready"
            elif has_stored_cloud_auth(self.config):
                key_status = "cloud voice ready"
            else:
                key_status = "voice provider missing"
            self.post_notice(
                "Flow",
                f"{status}. {key_status}. Press Ctrl+S in any text field.",
                timeout=5,
            )
            return
        if action == "setup":
            if len(args) > 1:
                self.post_notice(
                    "Flow",
                    "For security, run `/flow setup` without pasting the key into the command.",
                    timeout=8,
                )
                return
            key = await self._open_modal(VoiceSetupModal())
            if not key:
                return
            save_voice_settings(enabled=True, groq_api_key=key)
            self.config.voice.enabled = True
            self.config.voice.groq_api_key = key
            self._update_composer_meta_line()
            return
        if action in {"on", "enable"}:
            save_voice_settings(enabled=True)
            self.config.voice.enabled = True
            self._update_composer_meta_line()
            return
        if action in {"off", "disable"}:
            save_voice_settings(enabled=False)
            self.config.voice.enabled = False
            if self._voice_recorder is not None:
                await self._voice_recorder.cancel()
                self._voice_recorder = None
                self._voice_target = None
            self._voice_busy = False
            self._flow_meta_frame = 0
            self._update_composer_meta_line()
            return
        self.post_notice(
            "Flow",
            "Use `/flow setup`, `/flow status`, `/flow on`, or `/flow off`.",
            timeout=6,
        )

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
        prompt = self.query_one("#prompt", TextArea)
        if not self._rewriting_dropped_path:
            rewrite = self._rewrite_trailing_dropped_path(prompt.text)
            if rewrite is not None:
                updated, paths = rewrite
                self._rewriting_dropped_path = True
                try:
                    prompt.load_text(updated)
                    if hasattr(prompt, "action_cursor_document_end"):
                        prompt.action_cursor_document_end()
                    if self.agent and self.agent.session:
                        pending = list(self.agent.session.pending_attachment_paths)
                        for path in paths:
                            if path not in pending:
                                pending.append(path)
                        self.agent.session.pending_attachment_paths = pending[
                            :MAX_ATTACHMENTS
                        ]
                finally:
                    self._rewriting_dropped_path = False
                self._sync_command_palette(updated)
                self._resize_composer_for_prompt()
                return
        self._sync_command_palette(prompt.text)
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
                if key == "enter":
                    top.action_accept()
                    event.stop()
                    if hasattr(event, "prevent_default"):
                        event.prevent_default()
                    return
                if key == "y":
                    top.action_yes()
                    event.stop()
                    if hasattr(event, "prevent_default"):
                        event.prevent_default()
                    return
                if key == "2":
                    top.action_option_2()
                    event.stop()
                    if hasattr(event, "prevent_default"):
                        event.prevent_default()
                    return
                if key == "1":
                    top.action_option_1()
                    event.stop()
                    if hasattr(event, "prevent_default"):
                        event.prevent_default()
                    return
                if key in {"n", "escape", "ctrl+c"}:
                    top.action_no()
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
        prompt_row = self.query_one("#prompt-row", Horizontal)
        prompt_container = self.query_one("#prompt-container", Container)
        composer = self.query_one("#composer", Horizontal)

        # Use the wrapped document height so soft-wrapped lines (long single
        # lines that wrap visually) expand the composer. Counting only "\n"
        # underestimates the visual row count when a long line wraps.
        try:
            line_count = max(1, int(prompt.wrapped_document.height))
        except Exception:
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
        prompt_row.styles.height = prompt_height
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
            or "could not reach ite bundled inference" in text
            or "incomplete chunked read" in text
            or "peer closed connection" in text
            or "ssl/tls alert bad record mac" in text
            or "sslv3_alert_bad_record_mac" in text
            or "ssl: decryption_failed_or_bad_record_mac" in text
            or "remote end closed connection" in text
            or "connection reset by peer" in text
            or "connection lost" in text
            or "could not reach ite cloud api" in text
            or "connection error" in text
            or "ssl error" in text
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


    def _build_silent_retry_payload(self, session_id: str) -> dict[str, Any] | None:
        run_state = self._run_state(session_id)
        payload = run_state.retryable_turn_payload or run_state.last_turn_payload
        if payload is None:
            return None
        retry_payload = dict(payload)
        retry_payload["suppress_user_echo"] = True
        retry_payload["display_message"] = ""
        return retry_payload


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


    async def _post_no_model_selected_guidance(self) -> None:
        body = (
            "- Subscribe to [iTE Pro](https://ite.kiishi.space/pricing) to use bundled cloud models when your plan includes them.\n"
            "- Run `/setup` to add local Ollama, OpenRouter, or another OpenAI-compatible provider."
        )
        await self.add_assistant_card(
            "Select a model",
            CopyableMarkdown(body),
            css_class="system",
        )


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
        workspace: Path,
        supports_vision: bool = True,
    ) -> tuple[str, str | list[dict] | None, str | None, list[Attachment]] | None:
        if not attachments:
            return message, None, None, []
        manager = AttachmentManager(workspace)
        temp_turn_id = f"reup_{turn_id}"
        staged, errors = manager.stage_paths(attachments, temp_turn_id)
        if errors:
            for error in errors:
                self.post_attachment_note(error)
        if not staged:
            return None
        user_model_content = build_user_model_content(
            message, staged, workspace, supports_vision=supports_vision,
        )
        prepared_message = build_user_text_with_manifest(message, staged, workspace)
        return prepared_message, user_model_content, temp_turn_id, staged


    def _clear_composer_after_submit(self, *, clear_attachments: bool = False) -> None:
        prompt = self.query_one("#prompt", TextArea)
        self._record_composer_history(redact_sensitive_command_text(prompt.text))
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
        session_id = self._active_session_id()

        normalized = self._normalize_plan_execution_request(message)
        if normalized is None:
            return
        message = normalized

        # A message that parses as one or more existing file paths (e.g. a
        # drag-and-dropped "/Users/..." path or a "file://..." URI delivered
        # by the terminal) is an attachment, never a slash command.
        drop = parse_dropped_file_paths(message)
        is_drop_payload = bool(drop.paths) and drop.prose_count == 0
        if is_drop_payload:
            attachments = list(
                dict.fromkeys([*attachments, *drop.paths])
            )[:MAX_ATTACHMENTS]
            if self.agent and self.agent.session:
                self.agent.session.pending_attachment_paths = list(attachments)

        if message.startswith("/") and not is_drop_payload:
            await self.run_command(message)
            return  # Command handlers may open modals; prevent fallthrough to agent send

        if not self._has_selected_model():
            self._restore_payload_to_composer(payload)
            await self._post_no_model_selected_guidance()
            return

        if not suppress_user_echo:
            await self.add_user_message(display_message or message)
            if (
                self._telegram_service is not None
                and self._telegram_service.running
                and not self._suppress_telegram_user_echo
            ):
                await self._telegram_service.send_user_message(
                    display_message or message
                )
            self._is_turn_running = True
            self._update_composer_send_control()

        coro = self._handle_agent_send_with_intent(
            message,
            display_message=display_message or message,
            suppress_user_echo=suppress_user_echo,
            session_id=session_id,
        )
        self.call_after_refresh(self.run_worker, coro, exclusive=False)


    async def _resolve_active_turn_send(self, payload: dict[str, Any]) -> bool:
        replacing_queue = self._queued_turn_payload is not None
        self._show_turn_action_palette(payload, replacing_queue=replacing_queue)
        return True


    def _active_shell_input_call_id(self) -> str | None:
        run_state = self._run_state()
        for call_id in reversed(list(self._live_shell_call_state.keys())):
            if call_id not in run_state.running_shell_call_ids:
                continue
            state = self._live_shell_call_state.get(call_id)
            md = state.metadata if state is not None else {}
            if md.get("input_capable") is True and md.get("awaiting_input") is True:
                return call_id
        return None


    async def _send_active_shell_input(
        self,
        text: str,
        *,
        clear_composer: bool = True,
    ) -> bool:
        call_id = self._active_shell_input_call_id()
        if not call_id:
            return False
        sent = await send_input_to_shell_run(call_id, text, append_newline=True)
        if not sent:
            return False
        if clear_composer:
            prompt = self.query_one("#prompt", TextArea)
            prompt.text = ""
            self._resize_composer_for_prompt()
        state = self._live_shell_call_state.get(call_id)
        if state is not None:
            was_awaiting_shell_input = self._active_shell_input_call_id() is not None
            state.metadata = dict(state.metadata)
            state.metadata["awaiting_input"] = False
            is_awaiting_shell_input = self._active_shell_input_call_id() is not None
            if was_awaiting_shell_input != is_awaiting_shell_input:
                await self._broadcast_remote_state()
        self._set_loading_state("waiting on shell", busy=True)
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
            payload = dict(run_state.failure_recovery_payload)
            run_state.failure_recovery_payload = None
            payload["suppress_user_echo"] = True
            payload["display_message"] = ""
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
        if self._is_turn_running and await self._send_active_shell_input(message):
            return
        normalized = self._normalize_dropped_path_message(message)
        if normalized is None:
            return
        message = normalized
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

        self._clear_composer_after_submit()
        await self._dispatch_payload(payload)


    async def _handle_agent_send_with_intent(
        self,
        message: str,
        *,
        display_message: str | None = None,
        suppress_user_echo: bool = False,
        session_id: str | None = None,
    ) -> None:
        try:
            if session_id and session_id != self._active_session_id():
                assisted = message
            else:
                assisted = await self._apply_intent_assist(message)
            if assisted is None:
                return
            await self.run_agent_message(
                assisted,
                display_message=display_message or message,
                suppress_user_echo=suppress_user_echo,
                session_id=session_id,
                add_to_feed=False,
            )
        finally:
            if self._is_turn_running and not suppress_user_echo:
                self._is_turn_running = False
                self._update_composer_send_control()


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
        telegram_task: asyncio.Task[dict[str, Any] | None] | None = None
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
        if (
            self._telegram_service is not None
            and self._telegram_service.running
            and self.agent
            and self.agent.session
        ):
            tg_req_id = str(uuid.uuid4()) if not request_id else request_id
            telegram_task = asyncio.create_task(
                self._telegram_service.request_plan_question(
                    dict(
                        question_number=tg_req_id,
                        question=question,
                        options=options,
                        recommended_index=recommended_index,
                        allow_free_text=allow_free_text,
                    )
                )
            )

        tasks_to_cleanup: list[asyncio.Task[Any]] = [local_task]
        if remote_task is not None:
            tasks_to_cleanup.append(remote_task)
        if telegram_task is not None:
            tasks_to_cleanup.append(telegram_task)
        try:
            pending: set[asyncio.Task[Any]] = {local_task}
            if remote_task is not None:
                pending.add(remote_task)
            if telegram_task is not None:
                pending.add(telegram_task)
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
                    if task is telegram_task and result is None:
                        continue
                    winner = task
                    answer = result
                    break
                if winner is not None:
                    break

            if not isinstance(answer, dict):
                answer = {
                    "selected_option": "",
                    "free_text": "",
                    "selected_index": None,
                }

            selected_index = answer.get("selected_index")
            if not isinstance(selected_index, int):
                selected_index = None
            selected_option = str(answer.get("selected_option") or "")
            free_text = str(answer.get("free_text") or "")

            if winner is local_task and remote_task is not None and request_id:
                assert self._remote_server is not None
                await self._remote_server.resolve_plan_question_request(
                    request_id, answer
                )
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
            elif winner is telegram_task:
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
        finally:
            for task in tasks_to_cleanup:
                if not task.done():
                    task.cancel()


    def _reset_plan_question_state(self) -> None:
        self._plan_question_future = None
        self._plan_question_options = []
        self._plan_question_number = 0
        self._plan_question_prompt = ""
        self._plan_question_option_buttons = []
        self._plan_question_custom_input = None
        self._plan_question_custom_submit = None
        self._plan_question_status = None
        self._plan_question_recommended_index = None


    def _resolve_pending_plan_question(self, *, empty: bool) -> None:
        future = self._plan_question_future
        if future is None:
            self._reset_plan_question_state()
            return
        if not future.done():
            result = {"selected_option": "", "free_text": "", "selected_index": None}
            if empty:
                future.set_result(result)
            else:
                future.cancel()
        self._reset_plan_question_state()


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
        self._reset_plan_question_state()

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

