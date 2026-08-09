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
from ite.ui.tool_narrative import activity_title, describe_tool_activity, progress_label, _random_gerund
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
from .change_tree import ChangedFilesTree
from .composer_views import build_empty_state_renderable, build_signed_out_state_renderable
from .model_labels import bundled_model_display_label
from .modals import ApprovalPickerModal, AttachPickerModal, BranchPickerModal, CommitModal, ContextSummaryModal, ActivityModal, ModelPickerModal, ThemePickerModal, UsageSummaryModal, PushReviewModal, RemoteSetupModal, PlanQuestionModal, SessionResumeModal, VoiceSetupModal, ConfirmModal, SetupModal


class PanelsMixin:
    """Extracted mixin for _panels."""


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
        while True:
            current_model = self.config.model_name
            bundled_items = (
                [] if self._bundled_access_denied else self._bundled_models_cache
            )
            model_options, current_entry_id, bundled_model_names, saved_providers = (
                self._build_model_options(bundled_items, current_model)
            )

            modal = ModelPickerModal(
                current_model,
                model_options,
                current_entry_id=current_entry_id,
            )
            refresh_task = (
                asyncio.create_task(
                    self._refresh_model_picker_data(modal, current_model)
                )
                if self.config.cloud_auth_enabled
                else None
            )
            result = await self._open_modal(modal)
            if refresh_task is not None:
                refresh_task.cancel()
                try:
                    await refresh_task
                except asyncio.CancelledError:
                    pass

            if not result:
                return

            action = str(result.get("action") or "").strip().lower()
            selected_entry_id = str(result.get("entry_id") or "").strip()
            selected_source_kind = str(result.get("source_kind") or "").strip().lower()
            selected = str(result.get("model_name") or "").strip()
            if not selected_entry_id and selected_source_kind and selected:
                selected_entry_id = f"{selected_source_kind}:{selected}"
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
                if (
                    selected in saved_providers
                    and self._has_active_user_provider_credentials()
                ):
                    selected_entry_id = f"saved:{selected}"
                elif selected in bundled_model_names:
                    selected_entry_id = f"bundled:{selected}"
                elif selected in saved_providers:
                    selected_entry_id = f"saved:{selected}"
                else:
                    selected_entry_id = f"custom:{selected}"
            if not selected:
                return
            if not any(
                str(item.get("entry_id") or "").strip() == selected_entry_id
                for item in model_options
            ):
                (
                    model_options,
                    current_entry_id,
                    bundled_model_names,
                    saved_providers,
                ) = self._build_model_options(
                    [] if self._bundled_access_denied else self._bundled_models_cache,
                    self.config.model_name,
                )

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
        selected_item_source_kind = (
            str(selected_item.get("source_kind") or "").strip().lower()
            if selected_item
            else ""
        )
        selecting_bundled_model = selected_source_kind == "bundled" or (
            bool(selected_item)
            and not bool(selected_item.get("saved_profile"))
            and selected_item_source_kind == "bundled"
        )
        next_api_key = (
            str(restored_profile.get("api_key") or "")
            if restored_profile
            else ("" if selecting_bundled_model else (self.config.api_key or ""))
        )
        next_base_url = (
            str(restored_profile.get("base_url") or "")
            if restored_profile
            else ("" if selecting_bundled_model else (self.config.base_url or ""))
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
        next_source_kind = selected_item_source_kind or selected_source_kind

        try:
            save_system_config(
                api_key=next_api_key,
                base_url=next_base_url,
                model_name=selected,
                context_window=next_context_window,
                context_window_source=next_context_window_source,
                source_kind=next_source_kind or None,
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
        self.config.model.source_kind = next_source_kind or None
        self.config.model.supports_vision = self._resolve_model_vision_support(
            selected, source_kind=next_source_kind
        )
        await self._reset_active_provider_client()
        self.refresh_header()


    def _build_model_options(
        self, bundled_items: list[dict[str, Any]], current_model: str
    ) -> tuple[list[dict[str, Any]], str, set[str], dict[str, Any]]:
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
            persisted_source_kind = (
                str(getattr(self.config.model, "source_kind", "") or "").strip().lower()
            )
            if persisted_source_kind in {"bundled", "saved", "custom"}:
                return f"{persisted_source_kind}:{normalized_current}"
            if self._has_active_user_provider_credentials():
                if normalized_current in saved_providers:
                    return f"saved:{normalized_current}"
                return f"custom:{normalized_current}"
            if normalized_current in bundled_model_names:
                return f"bundled:{normalized_current}"
            if normalized_current in saved_providers:
                return f"saved:{normalized_current}"
            return ""

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
            capabilities: list[str] | None = None,
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
                "capabilities": capabilities,
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
                context_window_source=str(
                    profile.get("context_window_source") or ""
                ).strip()
                or None,
                saved_profile=True,
            )

        if (
            current_model
            and current_model not in bundled_model_names
            and current_model not in saved_providers
            and (
                self._has_active_user_provider_credentials()
                or str(getattr(self.config.model, "source_kind", "") or "")
                .strip()
                .lower()
                == "custom"
            )
            and not (
                self._bundled_access_denied
                and str(getattr(self.config.model, "source_kind", "") or "")
                .strip()
                .lower()
                == "bundled"
            )
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
            model_name = str(item.get("model_name") or "")
            _append(
                "bundled",
                model_name,
                bundled_model_display_label(
                    model_name,
                    str(item.get("label") or item.get("model_name") or ""),
                ),
                "Bundled",
                context_window=(
                    int(item.get("context_window"))
                    if isinstance(item.get("context_window"), int)
                    else None
                ),
                context_window_source=str(
                    item.get("context_window_source") or ""
                ).strip()
                or None,
                capabilities=(
                    item.get("capabilities")
                    if isinstance(item.get("capabilities"), list)
                    else None
                ),
                available=bool(item.get("available", True)),
                unavailable_reason=str(item.get("unavailable_reason") or ""),
            )

        current_entry_id = _current_entry_id()
        return model_options, current_entry_id, bundled_model_names, saved_providers


    async def _refresh_model_picker_data(self, modal: Any, current_model: str) -> None:
        if not self.config.cloud_auth_enabled:
            return
        try:
            result = await asyncio.to_thread(get_bundled_models_result, self.config)
        except Exception:
            return
        bundled_items = result.models
        if not self._apply_cloud_auth_status(
            result.auth,
            context="Bundled models",
            interactive=False,
        ):
            if str(result.auth.state) in {
                CloudSessionState.SIGNED_OUT,
                CloudSessionState.INVALID,
                CloudSessionState.NO_ENTITLEMENT,
            }:
                if str(result.auth.state) == CloudSessionState.NO_ENTITLEMENT:
                    self._bundled_models_cache = []
                return
        else:
            self._bundled_access_denied = False
        self._bundled_models_cache = bundled_items
        model_options, current_entry_id, _, _ = self._build_model_options(
            bundled_items, current_model
        )
        if model_options:
            modal.update_models(model_options, current_entry_id=current_entry_id)


    async def _open_theme_picker_from_meta(self) -> None:
        old_theme = str(self.theme or "textual-dark")
        selected = await self._open_modal(ThemePickerModal(old_theme))
        if not selected or selected == self.theme:
            return
        self.theme = selected
        save_theme(selected)
        self.refresh_header()
        self._sync_command_palette(self.query_one("#prompt", TextArea).text)
        self.call_after_refresh(
            lambda: self.post_notice("Theme", f"{old_theme} → {selected}")
        )


    def action_change_theme(self) -> None:
        """Route Textual's built-in theme action through the Reup theme modal."""
        self.run_worker(self._open_theme_picker_from_meta(), exclusive=False)


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
        await self._hide_thread_switcher_panel(remember=False)
        await self._hide_hooks_panel()
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
        await self._sync_thread_switcher_panel()
        self._maybe_focus_prompt()


    def _hooks_panel_is_open(self) -> bool:
        panel = self._hooks_panel
        return bool(panel is not None and panel.is_mounted)


    async def _toggle_hooks_panel(self) -> None:
        if self._hooks_panel_is_open():
            await self._hide_hooks_panel()
            return
        await self._show_hooks_panel()


    async def _show_hooks_panel(self) -> None:
        await self._hide_commands_panel()
        await self._hide_thread_switcher_panel(remember=False)
        await self._hide_change_review_panel()
        self.screen.query("HelpPanel").remove()
        panel = HooksSidePanel(id="hooks-panel")
        self._hooks_panel = panel
        await self.screen.mount(panel)
        await self._populate_hooks_panel(force=True)
        self._apply_hooks_panel_state()


    async def _hide_hooks_panel(self) -> None:
        panel = self._hooks_panel
        self._hooks_panel = None
        self._hooks_panel_layout_key = None
        self._hooks_run_widgets = {}
        if panel is None:
            return
        try:
            await panel.remove()
        except Exception:
            pass
        self._apply_hooks_panel_state()
        self._maybe_focus_prompt()


    def _change_review_panel_is_open(self) -> bool:
        return self._change_review_panel is not None


    def _get_change_review_widget(
        self, id: str, widget_type: type[Widget]
    ) -> Widget | None:
        panel = self._change_review_panel
        if panel is None:
            return None
        try:
            return panel.query_one(f"#{id}", widget_type)
        except NoMatches:
            return None


    async def _show_change_review_panel(self) -> None:
        await self._hide_hooks_panel()
        await self._refresh_change_review_source(force=True)
        if not self._change_review_change_set or not getattr(
            self._change_review_change_set, "changes", None
        ):
            return
        self._change_review_visible = True
        self._set_change_review_poll_interval(1.0)
        panel = ChangeReviewSidePanel(id="change-review-panel")
        self._change_review_panel = panel
        await self.screen.mount(panel)
        await self._populate_change_review_panel()


    async def _hide_change_review_panel(self) -> None:
        panel = self._change_review_panel
        self._change_review_panel = None
        self._change_review_visible = False
        self._set_change_review_poll_interval(3.0)
        if panel is None:
            return
        try:
            await panel.remove()
        except Exception:
            pass
        self._apply_change_review_panel_state()
        self._maybe_focus_prompt()


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
        modal = UsageSummaryModal(self._usage_summary_cache, loading=True)
        self.run_worker(self._refresh_usage_modal(modal), exclusive=False)
        await self._open_modal(modal)


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
        self._sync_bundled_context_window()
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
        payload = self._activity_cache
        if payload is None:
            payload = await asyncio.to_thread(get_activity, self.config)
        else:
            self.run_worker(self._refresh_activity_cache(), exclusive=False)
        if not payload:
            self.post_system(
                "Activity",
                "Usage analytics are not available right now.",
                is_error=True,
            )
            return
        self._activity_cache = payload
        await self._open_modal(ActivityModal(payload))


    async def _open_attach_picker_from_meta(self) -> None:
        await self.ensure_agent()
        if not self.agent:
            return
        cwd = Path(self.config.cwd).resolve()
        selected = await self._open_modal(AttachPickerModal(cwd, []))
        if selected is None:
            return
        self._insert_attachment_refs_into_prompt(
            list(selected)[:MAX_ATTACHMENTS]
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

        if self.agent and self.agent.session:
            pending = list(self.agent.session.pending_attachment_paths)
            for p in paths:
                if p not in pending:
                    pending.append(p)
            self.agent.session.pending_attachment_paths = pending[:MAX_ATTACHMENTS]

        self._insert_attachment_refs_into_prompt(paths[:MAX_ATTACHMENTS])
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
        if (
            self._cloud_signed_out
            or self._startup_active
            or self._onboarding_active
            or self._cloud_bootstrap_busy
        ):
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
        if not self._workspace_agents_recommendation_surface_ready():
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


    def _workspace_agents_recommendation_surface_ready(self) -> bool:
        return not (
            self._startup_active
            or self._cloud_signed_out
            or self._onboarding_active
            or self._cloud_bootstrap_busy
            or self._session_switching
            or self._required_update_notice is not None
        )


    def _run_worker_safely(
        self,
        work: Any,
        *,
        exclusive: bool = False,
        group: str | None = None,
    ) -> None:
        if self._shutdown_started:
            if inspect.iscoroutine(work):
                work.close()
            return
        kwargs: dict[str, Any] = {"exclusive": exclusive}
        if group is not None:
            kwargs["group"] = group
        try:
            self.run_worker(work, **kwargs)
        except RuntimeError as exc:
            if "App is not running" not in str(exc):
                raise
            if inspect.iscoroutine(work):
                work.close()


    def _set_loading_state(self, state: str, busy: bool) -> None:
        self._top_state_text = state
        self._top_busy = busy
        self._activity_version += 1
        version = self._activity_version
        self._run_worker_safely(self._broadcast_remote_state(), exclusive=False)
        if busy:
            self._run_worker_safely(
                self._show_activity_indicator(state, version), exclusive=False
            )
        else:
            self._run_worker_safely(
                self._hide_activity_indicator(version), exclusive=False
            )

        try:
            prompt = self.query_one("#prompt", TextArea)
        except (NoMatches, ScreenStackError):
            return
        prompt.disabled = (
            self._cloud_signed_out
            or self._startup_active
            or self._onboarding_active
            or self._required_update_notice is not None
        )
        self._refresh_empty_state()


    def _maybe_focus_prompt(self) -> None:
        if self._cloud_signed_out or self._startup_active or self._onboarding_active:
            return
        try:
            self.query_one("#prompt", TextArea).focus()
        except (NoMatches, ScreenStackError):
            pass


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
        toggle = self.query_one("#changes-toggle", Button)
        has_content = bool(
            self._change_review_change_set
            and getattr(self._change_review_change_set, "changes", None)
        )
        has_outgoing = bool(
            self._git_outbound_state and self._git_outbound_state.needs_attention
        )
        wants_publish = bool(
            self._git_outbound_state and self._git_outbound_state.needs_publish
        )
        is_panel_open = self._change_review_panel_is_open()
        toggle.display = (
            (has_content or has_outgoing)
            and not is_panel_open
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


    def _active_hooks_snapshot(self) -> dict[str, Any]:
        session = self.agent.session if self.agent and self.agent.session else None
        if session is not None:
            return session.hook_system.snapshot()
        return {
            "enabled": bool(self.config.hooks_enabled),
            "configured": [
                {
                    "name": hook.name,
                    "trigger": hook.trigger.value,
                    "command": hook.command or "<inline script>",
                    "timeout_sec": hook.timeout_sec,
                    "enabled": hook.enabled,
                }
                for hook in self.config.hooks
            ],
            "runs": [],
        }


    def _hooks_snapshot_signature(self, snapshot: dict[str, Any]) -> tuple[Any, ...]:
        configured = tuple(
            (
                str(item.get("name", "")),
                str(item.get("trigger", "")),
                bool(item.get("enabled", True)),
            )
            for item in snapshot.get("configured", [])
            if isinstance(item, dict)
        )
        runs = tuple(
            (
                str(item.get("id", "")),
                str(item.get("status", "")),
                item.get("duration_ms"),
                item.get("exit_code"),
            )
            for item in snapshot.get("runs", [])
            if isinstance(item, dict)
        )
        return (bool(snapshot.get("enabled")), configured, runs)


    def _hooks_panel_layout_signature(
        self, snapshot: dict[str, Any]
    ) -> tuple[Any, ...]:
        configured = tuple(
            (
                str(item.get("name", "")),
                str(item.get("trigger", "")),
                bool(item.get("enabled", True)),
            )
            for item in snapshot.get("configured", [])
            if isinstance(item, dict)
        )
        return (bool(snapshot.get("enabled")), configured)


    def _apply_hooks_panel_state(self) -> None:
        try:
            toggle = self.query_one("#hooks-toggle", Button)
        except Exception:
            return
        snapshot = self._active_hooks_snapshot()
        configured = [
            item for item in snapshot.get("configured", []) if isinstance(item, dict)
        ]
        runs = [item for item in snapshot.get("runs", []) if isinstance(item, dict)]
        has_failed = any(
            str(item.get("status", "")).lower() in {"failed", "timed_out"}
            for item in runs[-20:]
        )
        has_running = any(
            str(item.get("status", "")).lower() == "running" for item in runs
        )
        is_enabled = bool(snapshot.get("enabled"))
        toggle.display = (
            not self._cloud_signed_out
            and not self._hooks_panel_is_open()
            and is_enabled
            and (bool(configured) or bool(runs))
        )
        if has_failed:
            toggle.label = "/hooks !"
        elif has_running:
            toggle.label = "/hooks *"
        else:
            toggle.label = "/hooks"


    def _poll_hooks_panel(self) -> None:
        self.run_worker(
            self._sync_hooks_panel_state(),
            exclusive=True,
            group="hooks-panel-sync",
        )


    async def _sync_hooks_panel_state(self) -> None:
        snapshot = self._active_hooks_snapshot()
        signature = self._hooks_snapshot_signature(snapshot)
        if signature == self._hooks_snapshot_key:
            self._apply_hooks_panel_state()
            return
        self._hooks_snapshot_key = signature
        if self._hooks_panel_is_open():
            layout_signature = self._hooks_panel_layout_signature(snapshot)
            if layout_signature == self._hooks_panel_layout_key:
                await self._refresh_hooks_panel_rows(snapshot)
            else:
                await self._populate_hooks_panel(snapshot=snapshot)
        self._apply_hooks_panel_state()


    def _hook_status_style(self, status: str) -> str:
        normalized = str(status or "").strip().lower()
        if normalized == "running":
            return self._style("warning")
        if normalized == "completed":
            return self._style("success")
        if normalized in {"failed", "timed_out"}:
            return self._style("error")
        return self._style("muted")


    def _hook_trigger_order(self) -> tuple[str, ...]:
        return (
            "before_agent",
            "before_tool",
            "after_tool",
            "after_agent",
            "on_error",
        )


    def _hook_trigger_title(self, trigger: str) -> str:
        titles = {
            "before_agent": "Turn starts",
            "before_tool": "Before tools",
            "after_tool": "After tools",
            "after_agent": "Turn finishes",
            "on_error": "Errors",
        }
        return titles.get(str(trigger or "").strip(), str(trigger or "Other"))


    def _group_hooks_by_trigger(
        self, items: list[dict[str, Any]]
    ) -> list[tuple[str, list[dict[str, Any]]]]:
        by_trigger: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            trigger = str(item.get("trigger") or "other").strip() or "other"
            by_trigger.setdefault(trigger, []).append(item)
        ordered: list[tuple[str, list[dict[str, Any]]]] = []
        for trigger in self._hook_trigger_order():
            if trigger in by_trigger:
                ordered.append((trigger, by_trigger.pop(trigger)))
        for trigger in sorted(by_trigger):
            ordered.append((trigger, by_trigger[trigger]))
        return ordered


    def _hook_run_text(self, run: dict[str, Any]) -> Text:
        status = str(run.get("status") or "unknown")
        trigger = str(run.get("trigger") or "").strip()
        name = str(run.get("name") or "hook")
        tool_name = str(run.get("tool_name") or "").strip()
        duration = run.get("duration_ms")
        exit_code = run.get("exit_code")
        status_label = status.replace("_", " ")
        text = Text()
        marker = "●" if status == "running" else "●"
        text.append(marker, style=self._hook_status_style(status))
        text.append(" ")
        if trigger:
            text.append(self._hook_trigger_title(trigger), style=self._style("muted"))
            text.append(" · ", style=self._style("muted"))
        text.append(name, style=self._style("fg"))
        if tool_name:
            text.append(f" · {tool_name}", style=self._style("muted"))
        text.append("  ")
        text.append(status_label, style=self._hook_status_style(status))
        if isinstance(duration, int):
            text.append(f" · {duration}ms", style=self._style("muted"))
        if exit_code not in (None, 0):
            text.append(f" · exit {exit_code}", style=self._style("error"))
        error = str(run.get("error") or "").strip()
        if error:
            text.append(f"\n  {error}", style=self._style("error"))
        stderr = str(run.get("stderr") or "").strip()
        if stderr:
            text.append("\n  stderr: ", style=self._style("muted"))
            text.append(stderr[:500], style=self._style("error"))
        stdout = str(run.get("stdout") or "").strip()
        if stdout and status != "completed":
            text.append("\n  stdout: ", style=self._style("muted"))
            text.append(stdout[:500], style=self._style("muted"))
        return text


    def _hook_run_classes(self, run: dict[str, Any]) -> str:
        status = str(run.get("status") or "").strip().lower()
        classes = "hooks-run-row"
        if status:
            classes += f" {status}"
        return classes


    def _sync_hook_row_classes(self, widget: Static, classes: str) -> None:
        for class_name in (
            "running",
            "completed",
            "failed",
            "timed_out",
            "idle",
        ):
            widget.remove_class(class_name)
        for class_name in classes.split():
            if class_name != "hooks-run-row":
                widget.add_class(class_name)


    async def _refresh_hooks_panel_rows(self, snapshot: dict[str, Any]) -> None:
        panel = self._hooks_panel
        if panel is None:
            return
        try:
            summary = panel.query_one("#hooks-panel-summary", Static)
            run_list = panel.query_one("#hooks-runs-list", Vertical)
        except NoMatches:
            return
        configured = [
            item for item in snapshot.get("configured", []) if isinstance(item, dict)
        ]
        runs = [item for item in snapshot.get("runs", []) if isinstance(item, dict)]
        enabled_count = len([item for item in configured if item.get("enabled", True)])
        running_count = len(
            [item for item in runs if str(item.get("status", "")).lower() == "running"]
        )
        failed_count = len(
            [
                item
                for item in runs
                if str(item.get("status", "")).lower() in {"failed", "timed_out"}
            ]
        )
        state = "enabled" if snapshot.get("enabled") else "disabled"
        summary.update(
            f"{state} · {enabled_count}/{len(configured)} active hooks · "
            f"{len(runs)} runs · {running_count} running · {failed_count} attention"
        )
        visible_runs = list(reversed(runs))
        visible_ids = {
            str(run.get("id") or "") for run in visible_runs if str(run.get("id") or "")
        }
        for run_id, widget in list(self._hooks_run_widgets.items()):
            if run_id not in visible_ids:
                try:
                    await widget.remove()
                except Exception:
                    pass
                self._hooks_run_widgets.pop(run_id, None)

        if not visible_runs:
            empty = self._hooks_run_widgets.get("__empty__")
            if empty is None:
                empty = Static(
                    Text("waiting for hook activity", style=self._style("muted")),
                    classes="hooks-run-row idle",
                )
                self._hooks_run_widgets["__empty__"] = empty
                await run_list.mount(empty)
            else:
                empty.display = True
            return

        empty = self._hooks_run_widgets.pop("__empty__", None)
        if empty is not None:
            try:
                await empty.remove()
            except Exception:
                pass

        for index, run in enumerate(visible_runs):
            run_id = str(run.get("id") or "")
            widget = self._hooks_run_widgets.get(run_id)
            if widget is None:
                widget = Static(
                    self._hook_run_text(run),
                    classes=self._hook_run_classes(run),
                )
                self._hooks_run_widgets[run_id] = widget
                before = (
                    run_list.children[index] if index < len(run_list.children) else None
                )
                await run_list.mount(widget, before=before)
            else:
                widget.update(self._hook_run_text(run))
                self._sync_hook_row_classes(widget, self._hook_run_classes(run))
                if widget.parent is run_list and index < len(run_list.children):
                    target = run_list.children[index]
                    if target is not widget:
                        run_list.move_child(widget, before=target)


    async def _populate_hooks_panel(
        self,
        *,
        snapshot: dict[str, Any] | None = None,
        force: bool = False,
    ) -> None:
        panel = self._hooks_panel
        if panel is None:
            return
        snapshot = snapshot or self._active_hooks_snapshot()
        if force:
            self._hooks_snapshot_key = self._hooks_snapshot_signature(snapshot)
        self._hooks_panel_layout_key = self._hooks_panel_layout_signature(snapshot)
        try:
            summary = panel.query_one("#hooks-panel-summary", Static)
            body = panel.query_one("#hooks-panel-body", VerticalScroll)
        except NoMatches:
            return
        configured = [
            item for item in snapshot.get("configured", []) if isinstance(item, dict)
        ]
        runs = [item for item in snapshot.get("runs", []) if isinstance(item, dict)]
        enabled_count = len([item for item in configured if item.get("enabled", True)])
        running_count = len(
            [item for item in runs if str(item.get("status", "")).lower() == "running"]
        )
        failed_count = len(
            [
                item
                for item in runs
                if str(item.get("status", "")).lower() in {"failed", "timed_out"}
            ]
        )
        state = "enabled" if snapshot.get("enabled") else "disabled"
        summary.update(
            f"{state} · {enabled_count}/{len(configured)} active hooks · "
            f"{len(runs)} runs · {running_count} running · {failed_count} attention"
        )
        await body.remove_children()
        self._hooks_run_widgets = {}
        if configured:
            await body.mount(Static("Configured", classes="hooks-section-title"))
            for trigger, hook_group in self._group_hooks_by_trigger(configured):
                await body.mount(
                    Static(
                        self._hook_trigger_title(trigger),
                        classes="hooks-trigger-title",
                    )
                )
                for hook in hook_group:
                    classes = "hooks-config-row"
                    if not hook.get("enabled", True):
                        classes += " disabled"
                    label = Text()
                    label.append(
                        str(hook.get("name") or "hook"), style=self._style("fg")
                    )
                    timeout = hook.get("timeout_sec")
                    if timeout is not None:
                        label.append(f" · {timeout:g}s", style=self._style("muted"))
                    if hook.get("blocking", False):
                        label.append(" · blocking", style=self._style("warning"))
                    else:
                        label.append(" · async", style=self._style("muted"))
                    if not hook.get("enabled", True):
                        label.append(" · off", style=self._style("muted"))
                    await body.mount(Static(label, classes=classes))
        else:
            await body.mount(
                Static(
                    "No hooks configured. Add [[hooks]] entries to .ite/config.toml.",
                    classes="hooks-empty",
                )
            )

        await body.mount(Static("Latest runs", classes="hooks-section-title"))
        await body.mount(Vertical(id="hooks-runs-list", classes="hooks-runs-list"))
        await self._refresh_hooks_panel_rows(snapshot)


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
        panel = self._change_review_panel
        if panel is None:
            return
        try:
            stage_file = panel.query_one("#change-review-stage-file", Static)
            unstage_file = panel.query_one("#change-review-unstage-file", Static)
            discard_file = panel.query_one("#change-review-discard-file", Static)
            stage_all_button = panel.query_one("#change-review-stage-all", Static)
            discard_all_button = panel.query_one("#change-review-discard-all", Static)
            commit_button = panel.query_one("#change-review-commit", Static)
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
            self._change_review_bulk_action = "stage"
            stage_all_button.update(panel.bulk_action_label("stage"))
            stage_all_button.disabled = False
        elif has_any_staged:
            self._change_review_bulk_action = "unstage"
            stage_all_button.update(panel.bulk_action_label("unstage"))
            stage_all_button.disabled = False
        else:
            self._change_review_bulk_action = "stage"
            stage_all_button.update(panel.bulk_action_label("stage"))
            stage_all_button.disabled = True
        discard_all_button.disabled = not bool(
            self._change_review_source == "git" and has_content
        )
        commit_button.disabled = not bool(
            self._change_review_source == "git"
            and (has_any_staged or (has_any_unstaged and has_content))
        )


    async def _refresh_change_review_source(
        self, *, prefer_git_only: bool = False, force: bool = False
    ) -> None:
        if self._change_review_refresh_in_flight:
            return
        self._change_review_refresh_in_flight = True
        try:
            await self._refresh_change_review_source_once(
                prefer_git_only=prefer_git_only,
                force=force,
            )
        finally:
            self._change_review_refresh_in_flight = False


    async def _refresh_change_review_source_once(
        self, *, prefer_git_only: bool = False, force: bool = False
    ) -> None:
        now = time.monotonic()
        if not force and now - self._last_change_review_git_poll < 1.0:
            return
        self._last_change_review_git_poll = now
        cwd = Path(self.config.cwd).resolve()
        if await asyncio.to_thread(is_git_repo, cwd):
            # Hash git status output + file mtimes to detect content changes
            # (git status --porcelain alone doesn't change when a tracked
            #  file is modified but not staged, so we include mtimes.)
            try:
                status_result = await asyncio.to_thread(
                    subprocess.run,
                    ["git", "-C", str(cwd), "status", "--porcelain", "-z"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    start_new_session=True,
                    timeout=self.GIT_POLL_TIMEOUT_SECONDS,
                )
                if status_result.returncode != 0:
                    self._apply_change_review_panel_state()
                    return
                status_payload = (status_result.stdout or "").encode()
                # Append mtimes so that content edits to tracked files
                # produce a different hash even when status codes are unchanged.
                mtime_buf = bytearray()
                for entry in (status_result.stdout or "").split("\0"):
                    if len(entry) >= 4:
                        # entry format is "XY path" — 2 status chars + space + path
                        file_path = entry[3:]
                        try:
                            mtime = os.path.getmtime(os.path.join(cwd, file_path))
                            mtime_buf += f"{file_path}:{mtime}\0".encode()
                        except OSError:
                            pass
                status_hash = hashlib.sha256(
                    status_payload + bytes(mtime_buf)
                ).hexdigest()
                # Also hash HEAD so branch switches and new commits
                # invalidate the short-circuit even when the working
                # tree is clean.
                try:
                    head_result = await asyncio.to_thread(
                        subprocess.run,
                        ["git", "-C", str(cwd), "rev-parse", "HEAD"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                        start_new_session=True,
                        timeout=self.GIT_POLL_TIMEOUT_SECONDS,
                    )
                    head_ref = (head_result.stdout or "").strip()
                    if head_ref:
                        status_hash = hashlib.sha256(
                            status_hash.encode() + head_ref.encode()
                        ).hexdigest()
                except Exception:
                    pass
            except Exception:
                self._apply_change_review_panel_state()
                return
            outbound_state = await asyncio.to_thread(
                git_outbound_state,
                cwd,
                timeout=self.GIT_POLL_TIMEOUT_SECONDS,
            )
            if outbound_state is not None or self._git_outbound_state is None:
                self._git_outbound_state = outbound_state
            if (
                not force
                and status_hash
                and status_hash == self._last_status_hash
                and self._last_status_cwd == cwd
                and self._git_outbound_state is not None
            ):
                self._apply_change_review_panel_state()
                return
            self._last_status_hash = status_hash
            self._last_status_cwd = cwd
            change_set = await asyncio.to_thread(
                working_tree_change_set,
                cwd,
                timeout=self.GIT_POLL_TIMEOUT_SECONDS,
            )
            if status_payload and change_set is None:
                self._apply_change_review_panel_state()
                return
            if change_set is not None:
                source = "git"
                title = (
                    f"Working tree  {change_set.staged_count} staged"
                    f"  {change_set.unstaged_count} unstaged"
                )
                mode = "changed"
            else:
                source = "git"
                title = "Working tree"
                mode = "changed"
        else:
            self._git_outbound_state = None
            change_set = None
            source = "git"
            title = "Working tree"
            mode = "changed"
            self._last_status_hash = ""
            self._last_status_cwd = None
        self._change_review_source = source
        self._change_review_change_set = change_set
        self._change_review_title = title
        self._change_review_mode = mode
        if change_set is None:
            self._change_review_visible = False
            self._change_review_snapshot_key = None
        self._apply_change_review_panel_state()
        self._update_composer_meta_line()


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
        panel = self._change_review_panel
        if panel is None:
            return
        tree = panel.query_one("#change-review-tree", ChangedFilesTree)
        preview = panel.query_one("#change-review-preview", ScrollableContainer)
        await preview.remove_children()
        title = panel.query_one("#change-review-title", Static)
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

        previous_selection = self._change_review_selected_rel_path
        self._change_review_selected_rel_path = first_rel
        initial_diff = (
            self._change_review_diff_lookup.get(first_rel) if first_rel else first_diff
        )
        # Preserve previously selected file across auto-updates
        if previous_selection and previous_selection in self._change_review_diff_lookup:
            initial_diff = self._change_review_diff_lookup[previous_selection]
            self._change_review_selected_rel_path = previous_selection
        elif first_rel:
            self._change_review_selected_rel_path = first_rel
        else:
            self._change_review_selected_rel_path = None
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
            await self._refresh_change_review_source(force=True)
            if self._change_review_change_set and getattr(
                self._change_review_change_set, "changes", None
            ):
                self._change_review_visible = True
                self._set_change_review_poll_interval(1.0)
                await self._populate_change_review_panel()
            return
        self._change_review_change_set = change_set
        self._change_review_title = title
        self._change_review_mode = mode
        self._change_review_visible = True
        self._set_change_review_poll_interval(1.0)
        await self._populate_change_review_panel()


    async def _toggle_change_review_panel(self) -> None:
        if self._change_review_panel_is_open():
            await self._hide_change_review_panel()
            return
        await self._show_change_review_panel()


    async def _poll_head_change(self) -> None:
        """Watch .git/HEAD mtime for instant branch-switch detection."""
        try:
            cwd = Path(self.config.cwd).resolve()
            head_path = cwd / ".git" / "HEAD"
            mtime = os.path.getmtime(head_path)
            if mtime != self._head_mtime:
                self._head_mtime = mtime
                if await asyncio.to_thread(is_git_repo, cwd):
                    self._git_outbound_state = await asyncio.to_thread(
                        git_outbound_state,
                        cwd,
                        timeout=self.GIT_POLL_TIMEOUT_SECONDS,
                    )
                    self._update_composer_meta_line()
                    # Also trigger a full refresh for the change review panel
                    self.run_worker(
                        self._refresh_change_review_source(force=True),
                        exclusive=True,
                        group="change-review-sync",
                    )
        except Exception:
            pass


    def _poll_change_review_panel(self) -> None:
        self.run_worker(
            self._sync_change_review_panel_state(),
            exclusive=True,
            group="change-review-sync",
        )


    def _set_change_review_poll_interval(self, seconds: float) -> None:
        if self._change_review_poll_timer is not None:
            try:
                self._change_review_poll_timer.stop()
            except Exception:
                pass
        self._change_review_poll_timer = self.set_interval(
            seconds, self._poll_change_review_panel
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
        text = Text(_random_gerund(), style=f"{self._style('success')} italic")
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

    @on(Button.Pressed, "#threads-toggle")

    async def on_threads_toggle_pressed(self, _event: Button.Pressed) -> None:
        await self._toggle_thread_switcher_panel()

    @on(Button.Pressed, "#hooks-toggle")

    async def on_hooks_toggle_pressed(self, _event: Button.Pressed) -> None:
        await self._toggle_hooks_panel()

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
        await self._refresh_change_review_source(prefer_git_only=True, force=True)
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
            await self._refresh_change_review_source(prefer_git_only=True, force=True)
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
        await self._refresh_change_review_source(prefer_git_only=True, force=True)
        if not result.ok:
            self.post_system("Git", result.message, is_error=True)
            return
        self.post_notice("Git", result.message)

    @on(Button.Pressed, "#change-review-close")

    def on_change_review_close_pressed(self, _event: Button.Pressed) -> None:
        self._change_review_visible = False
        self._apply_change_review_panel_state()
        self._maybe_focus_prompt()


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
            prefer_git_only=self._change_review_source == "git", force=True
        )
        change_set = self._change_review_change_set
        if not change_set or not getattr(change_set, "changes", None):
            self._change_review_selected_rel_path = None
            await self._hide_change_review_panel()
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
        widget = self._get_change_review_widget("change-review-stage-file", Static)
        if not widget or widget.disabled:
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
        widget = self._get_change_review_widget("change-review-unstage-file", Static)
        if not widget or widget.disabled:
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
        widget = self._get_change_review_widget("change-review-discard-file", Static)
        if not widget or widget.disabled:
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
        stage_all_chip = self._get_change_review_widget(
            "change-review-stage-all", Static
        )
        if not stage_all_chip or stage_all_chip.disabled:
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
        commit_chip = self._get_change_review_widget("change-review-commit", Static)
        if not commit_chip or commit_chip.disabled:
            return
        result = await self._open_commit_modal()
        if not result:
            return
        action = str(result.get("action", "commit")).strip().lower()
        include_unstaged = bool(result.get("include_unstaged"))
        message = str(result.get("message", ""))
        await self._hide_change_review_panel()
        commit_result = await asyncio.to_thread(
            commit_changes,
            Path(self.config.cwd).resolve(),
            message=message,
            include_unstaged=include_unstaged,
            push=action == "commit_push",
        )
        if not commit_result.ok:
            self.post_system("Git", commit_result.message, is_error=True)
            return
        self.post_notice("Git", commit_result.message)
        await self._refresh_change_review_source(
            prefer_git_only=self._change_review_source == "git", force=True
        )

    @on(events.Click, "#change-review-commit")

    def on_change_review_commit(self, event: events.Click) -> None:
        event.stop()
        self.run_worker(self._run_change_review_commit(), exclusive=False)


    async def _run_change_review_discard_all(self) -> None:
        widget = self._get_change_review_widget("change-review-discard-all", Static)
        if not widget or widget.disabled:
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

