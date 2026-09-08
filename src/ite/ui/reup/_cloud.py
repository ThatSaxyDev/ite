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
from .composer_views import build_signed_out_state_renderable
from .model_labels import bundled_model_display_label

LEGACY_BUNDLED_MODEL_ALIASES: dict[str, str] = {
    "kimi-k2.5:cloud": "moonshotai/kimi-k2.5",
    "kimi-k2.6:cloud": "moonshotai/kimi-k2.6",
    "minimax-m2.5:cloud": "minimax/minimax-m2.5",
    "minimax-m2.7:cloud": "minimax/minimax-m2.7",
    "minimax-m3:cloud": "minimax/minimax-m3",
    "glm-5:cloud": "z-ai/glm-5",
    "glm-5.1:cloud": "z-ai/glm-5.1",
}

BUNDLED_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-5-20250929": 200_000,
}

CLOUD_NETWORK_ONLINE_PROBE_INTERVAL_SEC = 30.0
CLOUD_NETWORK_OFFLINE_FAILURE_THRESHOLD = 3

ONBOARDING_OTHER_VALUE = "__other__"

from .modals import ApprovalPickerModal, AttachPickerModal, BranchPickerModal, CommitModal, ContextSummaryModal, ActivityModal, ModelPickerModal, ThemePickerModal, UsageSummaryModal, PushReviewModal, RemoteSetupModal, PlanQuestionModal, SessionResumeModal, VoiceSetupModal, ConfirmModal, SetupModal


class CloudMixin:
    """Extracted mixin for _cloud."""


    def _should_show_onboarding(self) -> bool:
        return not bool(self.config.onboarding_completed)


    def _latest_workspace_session_snapshot(self) -> SessionSnapshot | None:
        if not bool(getattr(self.config, "resume_last_session", False)):
            return None

        manager = SessionManager()
        sessions = manager.list_sessions(
            workspace_path=self.config.cwd,
            include_legacy_unscoped=False,
        )
        for session in sessions:
            if int(session.get("turn_count", 0) or 0) <= 0:
                continue
            session_id = str(session.get("session_id", "") or "").strip()
            if not session_id:
                continue
            try:
                snapshot = manager.load_session(session_id)
            except Exception:
                continue
            if snapshot is not None and snapshot.turn_count > 0:
                return snapshot
        return None


    async def _resume_last_workspace_session_on_startup(self) -> bool:
        snapshot = self._latest_workspace_session_snapshot()
        if snapshot is None:
            return False

        try:
            self._set_startup_phase("Restoring last thread")
            await self._resume_snapshot(snapshot)
            return True
        except Exception:
            return False

    # REMOVED: _verify_cloud_auth_after_startup()
    # Background timer-based auth checks removed.
    # Cloud auth is now handled on-demand via ensure_cloud_auth() before cloud API calls.


    def _voice_has_provider(self) -> bool:
        if str(self.config.voice.groq_api_key or "").strip():
            return True
        return has_stored_cloud_auth(self.config)


    def _has_selected_model(self) -> bool:
        return bool(str(self.config.model_name or "").strip()) and (
            self._model_display_name() != "select model"
        )


    def _setup_required_for_model_selection(self) -> bool:
        if self._has_active_user_provider_credentials():
            return False
        if load_saved_custom_provider():
            return False
        if str(getattr(self.config.model, "source_kind", "") or "").strip().lower() in {
            "bundled",
            "saved",
            "custom",
        }:
            return False
        if self._bundled_models_cache:
            return False
        if has_stored_cloud_auth(self.config):
            return False
        return True


    def _has_active_user_provider_credentials(self) -> bool:
        return bool(
            str(self.config.api_key or "").strip()
            and str(self.config.base_url or "").strip()
        )


    def _model_display_name(self) -> str:
        current_model = str(self.config.model_name or "").strip()
        if not current_model:
            return "select model"
        persisted_source_kind = (
            str(getattr(self.config.model, "source_kind", "") or "").strip().lower()
        )
        saved_providers = load_saved_custom_provider()
        if persisted_source_kind == "bundled":
            if self._bundled_access_denied:
                return "select model"
            for item in self._bundled_models_cache:
                model_name = str(item.get("model_name") or "").strip()
                if model_name == current_model and bool(item.get("available", True)):
                    return bundled_model_display_label(
                        model_name,
                        str(item.get("label") or model_name).strip(),
                    )
            return "select model"
        if persisted_source_kind in {"saved", "custom"}:
            if self._setup_required_for_model_selection():
                return "/setup"
            return current_model.removesuffix(":cloud")
        for item in self._bundled_models_cache:
            model_name = str(item.get("model_name") or "").strip()
            if model_name == current_model:
                return bundled_model_display_label(
                    model_name,
                    str(item.get("label") or model_name).strip(),
                )
        if (
            persisted_source_kind not in {"bundled", "saved", "custom"}
            and current_model not in saved_providers
            and not self._has_active_user_provider_credentials()
        ):
            return "select model"
        if self._setup_required_for_model_selection():
            return "/setup"
        return current_model.removesuffix(":cloud")


    def _schedule_usage_meta_refresh(self) -> None:
        if self._usage_refresh_in_flight or self._cloud_signed_out:
            return
        self.run_worker(self._refresh_usage_meta(), exclusive=False)


    def _canonical_bundled_model_name(self, model_name: str) -> str:
        normalized = str(model_name or "").strip()
        return LEGACY_BUNDLED_MODEL_ALIASES.get(normalized, normalized)


    def _is_bundled_model(self) -> bool:
        """Check if current model is a bundled (backend-provided) model.

        Returns False for user keys (Ollama, OpenRouter, custom providers).
        """
        model = str(self.config.model_name or "").strip()
        persisted_source_kind = (
            str(getattr(self.config.model, "source_kind", "") or "").strip().lower()
        )
        if self._bundled_access_denied:
            return False
        if persisted_source_kind == "bundled":
            return any(
                str(item.get("model_name") or "").strip() == model
                and bool(item.get("available", True))
                for item in self._bundled_models_cache
            )
        if persisted_source_kind in {"saved", "custom"}:
            return False
        if not model or self._has_active_user_provider_credentials():
            return False
        saved_providers = load_saved_custom_provider()
        if model in saved_providers:
            return False
        bundled_models = {
            str(item.get("model_name") or "").strip()
            for item in self._bundled_models_cache
        }
        return model in bundled_models


    def _resolve_model_vision_support(self, model_name: str, source_kind: str | None = None) -> bool:
        """Return whether *model_name* supports vision/image inputs.

        For bundled models, check the capabilities reported by the cloud API.
        For all others, fall back to the name-based heuristic.
        """
        if source_kind == "bundled" and self._bundled_models_cache:
            for item in self._bundled_models_cache:
                if str(item.get("model_name") or "").strip() == model_name:
                    caps = item.get("capabilities")
                    if isinstance(caps, list) and "image" in caps:
                        return True
                    return False
        return detect_vision_from_model_name(model_name)


    def _apply_cloud_auth_status(
        self,
        auth: Any,
        *,
        context: str = "iTE Cloud",
        interactive: bool = False,
    ) -> bool:
        state = str(getattr(auth, "state", "") or "")
        message = str(getattr(auth, "message", "") or "").strip()
        if state == CloudSessionState.VALID:
            if self._cloud_signed_out:
                self._set_signed_out_state(False)
            return True
        if state == CloudSessionState.NO_ENTITLEMENT:
            self._bundled_access_denied = True
            if interactive:
                self._maybe_post_bundled_access_notice(message)
            return False
        if state == CloudSessionState.NETWORK_ERROR:
            if interactive:
                self.post_system(
                    context,
                    message
                    or "iTE Cloud is unreachable right now. Your stored session was kept.",
                    is_error=True,
                )
            return False
        if state == CloudSessionState.CREDENTIAL_ERROR:
            self._cloud_bootstrap_busy = False
            self._set_signed_out_state(False)
            if interactive:
                self.post_system(
                    context,
                    (
                        message
                        or "Could not read iTE Cloud credentials from the OS credential store."
                    )
                    + " Unlock Keychain Access if needed, then try again. If that keeps failing, run `/cloud login`.",
                    is_error=True,
                )
            return False
        stored_session = getattr(auth, "session", None)
        if state in {CloudSessionState.SIGNED_OUT, CloudSessionState.INVALID}:
            if state == CloudSessionState.INVALID and stored_session is None:
                clear_cloud_auth(revoke_remote=False)
            self._cloud_bootstrap_busy = False
            if stored_session is not None:
                self._set_signed_out_state(False)
            else:
                self._set_signed_out_state(True)
            if interactive:
                self.post_system(
                    context,
                    message or "Sign in with `/login` to continue.",
                    is_error=True,
                )
            return False
        if interactive:
            self.post_system(
                context,
                message or "iTE Cloud is not available right now.",
                is_error=True,
            )
        return False


    def _maybe_post_bundled_access_notice(self, message: str = "") -> None:
        now = time.monotonic()
        if (
            self._last_bundled_access_notice_at is not None
            and now - self._last_bundled_access_notice_at < 3600
        ):
            return
        self._last_bundled_access_notice_at = now
        self.post_notice(
            "iTE Pro",
            message or "Bundled cloud models are available with iTE Pro.",
            timeout=5,
        )


    async def _refresh_bundled_models_cache(self) -> None:
        try:
            result = await asyncio.to_thread(get_bundled_models_result, self.config)
        except Exception:
            return
        if not self._apply_cloud_auth_status(
            result.auth,
            context="Bundled models",
            interactive=False,
        ):
            if (
                str(getattr(result.auth, "state", "") or "")
                == CloudSessionState.NO_ENTITLEMENT
            ):
                self._bundled_models_cache = []
                self._usage_summary_cache = None
                self._usage_remaining_percent = None
                self._account_plan_is_pro = False
                self._account_plan_unavailable = False
                self.refresh_header()
            return
        self._bundled_access_denied = False
        self._bundled_models_cache = result.models
        self._migrate_legacy_bundled_selection_if_needed()
        self._sync_bundled_context_window()
        self.refresh_header()
        if self._is_bundled_model():
            self.run_worker(self._refresh_usage_summary_cache(), exclusive=False)


    def _sync_bundled_context_window(self) -> None:
        """Update config context_window from the bundled API cache for the current model."""
        if not self._bundled_models_cache or not self._is_bundled_model():
            return
        current_model = str(self.config.model_name or "").strip()
        for item in self._bundled_models_cache:
            if str(item.get("model_name") or "").strip() == current_model:
                api_window = item.get("context_window")
                if isinstance(api_window, int) and api_window > 0:
                    context_window_source = (
                        str(item.get("context_window_source") or "")
                        or "bundled_provider_api"
                    )
                    if self.config.model.context_window != api_window:
                        self.config.model.context_window = api_window
                    if self.config.model.context_window_source != context_window_source:
                        self.config.model.context_window_source = context_window_source
                    if self.agent and self.agent.session:
                        session_config = getattr(self.agent.session, "config", None)
                        if (
                            session_config is not None
                            and str(session_config.model_name or "").strip()
                            == current_model
                        ):
                            session_config.model.context_window = api_window
                            session_config.model.context_window_source = (
                                context_window_source
                            )
                break


    def _set_usage_summary_cache(self, summary: dict[str, Any] | None) -> None:
        self._usage_summary_cache = summary
        remaining = (
            self._five_hour_usage_remaining_percent(summary) if summary else None
        )
        if remaining != self._usage_remaining_percent:
            self._usage_remaining_percent = remaining
            self.refresh_header()


    async def _refresh_usage_summary_cache(self) -> dict[str, Any] | None:
        try:
            summary = await asyncio.to_thread(get_usage_summary, self.config)
        except Exception:
            self._set_usage_summary_cache(None)
            return None
        self._set_usage_summary_cache(summary)
        return summary

    @staticmethod

    def _five_hour_usage_remaining_percent(summary: dict[str, Any]) -> int:
        quotas = summary.get("quotas") or {}
        five_hour = quotas.get("fiveHour") or {}
        used = float(five_hour.get("usedUsdCents") or 0)
        cap = max(1.0, float(five_hour.get("capUsdCents") or 1))
        return max(0, min(100, int(((cap - used) / cap) * 100)))


    async def _refresh_usage_modal(self, modal: UsageSummaryModal) -> None:
        summary = await self._refresh_usage_summary_cache()
        if summary:
            modal.update_summary(summary)
        else:
            modal.mark_unavailable()


    async def _refresh_activity_cache(self) -> None:
        try:
            payload = await asyncio.to_thread(get_activity, self.config)
        except Exception:
            return
        self._activity_cache = payload


    async def _refresh_account_plan_badge(self) -> None:
        if not self.config.cloud_auth_enabled:
            self._set_local_account_plan_state()
            return
        try:
            result = await asyncio.to_thread(get_cloud_entitlements_result, self.config)
        except Exception:
            if (
                self._account_plan_is_pro is not None
                and not self._account_plan_unavailable
            ):
                self._cloud_network_watch_enabled = True
                return
            self._set_account_plan_badge_state(None, unavailable=True)
            return
        state = str(getattr(result.auth, "state", "") or "")
        if state == CloudSessionState.NO_ENTITLEMENT:
            self._set_account_plan_badge_state(False)
            self._set_cloud_user_profile(result.user)
            return
        if state == CloudSessionState.NETWORK_ERROR:
            if (
                self._account_plan_is_pro is not None
                and not self._account_plan_unavailable
            ):
                self._cloud_network_watch_enabled = True
                return
            self._set_account_plan_badge_state(None, unavailable=True)
            return
        if not result.auth.is_valid:
            self._set_account_plan_badge_state(None, unavailable=True)
            return
        entitlements = result.entitlements
        pro = bool(
            entitlements.get("proAccess")
            or entitlements.get("remoteCompanion")
            or entitlements.get("bundledInference")
        )
        self._set_account_plan_badge_state(pro)
        self._set_cloud_user_profile(result.user)


    def _set_cloud_user_profile(self, user: dict[str, Any] | None) -> None:
        email = ""
        image: str | None = None
        if isinstance(user, dict):
            email = str(user.get("email") or "").strip()
            raw_image = user.get("image")
            image = str(raw_image) if raw_image else None
        if email == self._cloud_user_email and image == self._cloud_user_image:
            return
        self._cloud_user_email = email or None
        self._cloud_user_image = image
        self._refresh_thread_switcher_account()


    def _prefetch_cloud_caches(self) -> None:
        self.run_worker(self._refresh_account_plan_badge(), exclusive=False)
        self.run_worker(self._refresh_bundled_models_cache(), exclusive=False)
        self.run_worker(self._refresh_activity_cache(), exclusive=False)
        if self._is_bundled_model():
            self.run_worker(self._refresh_usage_summary_cache(), exclusive=False)


    def _cloud_network_recovery_probe_interval(self) -> float:
        if self._cloud_signed_out or self._account_plan_unavailable:
            return 2.0
        if (
            not self._cloud_signed_out
            and not self._account_plan_unavailable
            and self._account_plan_is_pro is not None
        ):
            return CLOUD_NETWORK_ONLINE_PROBE_INTERVAL_SEC
        return 2.0


    def _should_probe_cloud_network_recovery(self) -> bool:
        if not self.config.cloud_auth_enabled:
            return False
        if self._cloud_auth_busy or self._cloud_bootstrap_busy:
            return False
        if self._cloud_network_probe_in_flight:
            return False
        if self._cloud_signed_out:
            return self._cloud_network_watch_enabled
        if self._account_plan_is_pro is not None:
            return True
        return self._account_plan_unavailable


    def _maybe_probe_cloud_network_recovery(self) -> None:
        if not self._should_probe_cloud_network_recovery():
            return
        now = time.monotonic()
        if (
            now - self._cloud_network_last_probe_at
            < self._cloud_network_recovery_probe_interval()
        ):
            return
        self._cloud_network_last_probe_at = now
        self._cloud_network_probe_in_flight = True
        self.run_worker(self._probe_cloud_network_recovery(), exclusive=False)


    async def _probe_cloud_network_recovery(self) -> None:
        try:
            if self._cloud_signed_out:
                reachable = await asyncio.to_thread(
                    is_cloud_api_reachable,
                    self.config,
                )
                if reachable:
                    self._handle_cloud_network_reachable()
                else:
                    self._handle_cloud_network_unreachable()
                return

            if not self._account_plan_unavailable:
                reachable = await asyncio.to_thread(
                    is_cloud_api_reachable,
                    self.config,
                )
                if reachable:
                    self._handle_cloud_network_reachable()
                else:
                    self._handle_cloud_network_unreachable()
                return

            auth = await asyncio.to_thread(get_cloud_auth_status, self.config)
            if auth.state == CloudSessionState.NETWORK_ERROR:
                self._handle_cloud_network_unreachable()
                return
            if auth.state == CloudSessionState.VALID:
                self._handle_cloud_network_reachable(auth)
                return
            self._apply_cloud_auth_status(
                auth,
                context="iTE Cloud",
                interactive=False,
            )
        except Exception:
            self._handle_cloud_network_unreachable()
        finally:
            self._cloud_network_probe_in_flight = False


    def _handle_cloud_network_unreachable(self) -> None:
        if self._cloud_signed_out:
            self._cloud_network_was_unreachable = True
            self._cloud_network_watch_enabled = True
            self._cloud_signed_out_status_message = (
                "Waiting for iTE Cloud to come online..."
            )
            self._refresh_signed_out_status()
            return
        self._cloud_network_unreachable_probe_count += 1
        if (
            not self._account_plan_unavailable
            and self._cloud_network_unreachable_probe_count
            < CLOUD_NETWORK_OFFLINE_FAILURE_THRESHOLD
        ):
            return
        self._cloud_network_was_unreachable = True
        was_unavailable = self._account_plan_unavailable
        self._set_account_plan_badge_state(None, unavailable=True)
        if not was_unavailable:
            self.post_notice(
                "iTE Cloud",
                "Offline. Cloud features will reconnect automatically.",
            )


    def _handle_cloud_network_reachable(self, auth: Any | None = None) -> None:
        recovered = (
            self._cloud_network_was_unreachable or self._account_plan_unavailable
        )
        self._cloud_network_unreachable_probe_count = 0
        self._cloud_network_was_unreachable = False
        self._cloud_network_watch_enabled = False
        if auth is not None:
            self._apply_cloud_auth_status(auth, context="iTE Cloud", interactive=False)
            if not recovered:
                return
            self._set_account_plan_badge_state(None, unavailable=False)
            self._prefetch_cloud_caches()
            self.post_notice(
                "iTE Cloud",
                "Back online. Cloud features are available.",
            )
            return
        self._cloud_signed_out_status_message = (
            "iTE Cloud is reachable. Sign in to continue."
        )
        self._refresh_signed_out_status()
        if recovered:
            self.post_notice("iTE Cloud", "Back online. You can sign in now.")


    def _refresh_signed_out_status(self) -> None:
        if not self.is_mounted:
            return
        try:
            self.query_one("#signed-out-status", Static).update(
                self._signed_out_status_text()
            )
        except (NoMatches, ScreenStackError):
            pass


    def _schedule_runtime_update_check(self) -> None:
        if not self.is_mounted or self._runtime_update_check_in_flight:
            return
        self.run_worker(self._refresh_runtime_update_notice(), exclusive=False)


    async def _refresh_runtime_update_notice(self) -> None:
        if self._runtime_update_check_in_flight:
            return
        self._runtime_update_check_in_flight = True
        try:
            notice = await asyncio.to_thread(check_runtime_update, self.config)
            if notice is None:
                return
            should_show = await asyncio.to_thread(should_show_update_notice, notice)
            if not should_show:
                return
            if notice.update_required:
                self._set_required_update_notice(notice)
            else:
                # Determine notification type: toast (1-3 times) or feed (4+ times)
                notif_type = await asyncio.to_thread(get_notification_type, notice)
                title, message = self._runtime_update_notice_copy(notice)
                if notif_type == "feed":
                    title, body = self._runtime_update_notice_feed_card(notice)
                    await self.add_assistant_card(
                        title, CopyableMarkdown(body), css_class="system"
                    )
                else:
                    self.post_notice(title, message, timeout=8)
                await asyncio.to_thread(mark_update_notice_seen, notice)
        finally:
            self._runtime_update_check_in_flight = False


    def _upgrade_command_for_notice(self, notice: Any) -> str:
        install_method = detect_install_method()
        if install_method == "installer":
            command = (
                str(getattr(notice, "installer_command", "") or "").strip()
                or "curl -fsSL https://ite.kiishi.space/install.sh | bash"
            )
        elif install_method == "uv":
            command = (
                str(getattr(notice, "upgrade_command", "") or "").strip()
                or "uv tool upgrade ite-agent"
            )
        else:
            command = (
                str(getattr(notice, "upgrade_command", "") or "").strip()
                or "pipx upgrade ite-agent"
            )
        return command


    def _runtime_update_notice_copy(
        self, notice: Any, *, include_command: bool = True
    ) -> tuple[str, str]:
        latest = str(getattr(notice, "latest_version", "") or "").strip()
        command = self._upgrade_command_for_notice(notice)
        title = str(getattr(notice, "title", "") or "").strip() or "Update available"
        message = str(getattr(notice, "message", "") or "").strip()
        if not message:
            target = latest or "a newer version"
            if include_command:
                message = (
                    f"Version {target} is available. Exit iTE, run: {command}, "
                    "then reopen it."
                )
            else:
                message = (
                    f"Version {target} is available. Exit iTE, run the command below, "
                    "then reopen it."
                )
        message = message.replace("Run below", "Run the command below")
        message = message.replace(
            "Run the command below, then reopen iTE",
            "Exit iTE, run the command below, then reopen it",
        )
        instruction = (
            f"Exit iTE, run: {command}, then reopen it."
            if include_command
            else "Exit iTE, run the command below, then reopen it."
        )
        message = self._append_update_instruction(message, instruction)
        release_url = str(getattr(notice, "release_url", "") or "").strip()
        if release_url and release_url not in message:
            message = f"{message} {release_url}"
        return title, message


    def _runtime_update_notice_feed_card(self, notice: Any) -> tuple[str, str]:
        title, message = self._runtime_update_notice_copy(notice, include_command=False)
        command = self._upgrade_command_for_notice(notice)
        body = f"{message}\n\n```bash\n{command}\n```"
        return title, body

    @staticmethod

    def _append_update_instruction(message: str, instruction: str) -> str:
        normalized = message.lower()
        has_instruction = (
            ("exit" in normalized or "quit" in normalized)
            and "run" in normalized
            and ("reopen" in normalized or "restart" in normalized)
        )
        if has_instruction:
            return message
        separator = "" if not message else " "
        return (
            f"{message.rstrip('.')}.{separator}{instruction}"
            if message
            else instruction
        )


    def _migrate_legacy_bundled_selection_if_needed(self) -> None:
        current_model = str(self.config.model_name or "").strip()
        canonical_model = self._canonical_bundled_model_name(current_model)
        if not current_model or canonical_model == current_model:
            return
        bundled_model_names = {
            str(item.get("model_name") or "").strip()
            for item in self._bundled_models_cache
        }
        if canonical_model not in bundled_model_names:
            return
        if self._has_active_user_provider_credentials():
            return
        saved_providers = load_saved_custom_provider()
        if current_model in saved_providers or canonical_model in saved_providers:
            return
        try:
            api_window = None
            for item in self._bundled_models_cache:
                if str(item.get("model_name") or "").strip() == canonical_model:
                    window = item.get("context_window")
                    if isinstance(window, int) and window > 0:
                        api_window = window
                    break
            save_system_config(
                api_key=self.config.api_key or "",
                base_url=self.config.base_url or "",
                model_name=canonical_model,
                context_window=api_window
                or int(self.config.model.context_window or DEFAULT_CONTEXT_WINDOW),
                context_window_source=(
                    "bundled_provider_api"
                    if api_window
                    else str(
                        getattr(self.config.model, "context_window_source", "") or ""
                    ).strip()
                    or "fallback_default"
                ),
                source_kind="bundled",
                cloud_auth_enabled=self.config.cloud_auth_enabled,
                cloud_api_url=self.config.cloud_api_url,
                cloud_client_id=self.config.cloud_client_id,
            )
        except Exception:
            return
        self.config.model.name = canonical_model
        self.config.model.source_kind = "bundled"
        self.config.model.supports_vision = self._resolve_model_vision_support(
            canonical_model, source_kind="bundled"
        )
        if api_window is not None:
            self.config.model.context_window = api_window
            self.config.model.context_window_source = "bundled_provider_api"


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
            self._set_usage_summary_cache(summary)
        except Exception:
            self._set_usage_summary_cache(None)
        finally:
            self._usage_refresh_in_flight = False


    def _start_usage_idle_poll(self) -> None:
        if self._usage_poll_active:
            return
        if not self._is_bundled_model():
            return
        self._usage_poll_active = True
        self.set_timer(30.0, self._on_usage_poll_tick)


    def _cancel_usage_idle_poll(self) -> None:
        self._usage_poll_active = False


    def _on_usage_poll_tick(self) -> None:
        self._usage_poll_active = False
        if self._is_turn_running:
            return
        if not self._is_bundled_model():
            return
        self._schedule_usage_meta_refresh()
        self._start_usage_idle_poll()


    def _set_signed_out_state(self, enabled: bool) -> None:
        was_enabled = self._cloud_signed_out
        self._cloud_signed_out = enabled
        if enabled:
            if not was_enabled:
                self._cloud_signed_out_status_message = ""
            self._onboarding_active = False
            self._bundled_models_cache = []
            self._bundled_access_denied = True
            self._usage_summary_cache = None
            self._usage_remaining_percent = None
            self._account_plan_is_pro = False
            self._account_plan_unavailable = False
            self._cloud_user_email = None
            self._cloud_user_image = None
        else:
            self._cloud_signed_out_status_message = ""
            self._cloud_network_watch_enabled = False
            self._cloud_network_was_unreachable = False
            self._cloud_network_unreachable_probe_count = 0
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


    def _set_required_update_notice(self, notice: Any | None) -> None:
        self._required_update_notice = notice
        self._apply_shell_surface()


    def _apply_shell_surface(self) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        empty = self.query_one("#empty-state", Static)
        startup = self.query_one("#startup-state", Container)
        signed_out = self.query_one("#signed-out-state", Container)
        update_required = self.query_one("#update-required-state", Container)
        onboarding = self.query_one("#onboarding-state", Container)
        session_switch = self.query_one("#session-switch-state", Container)
        settings_panel = self.query_one("#settings-panel", Widget)
        composer = self.query_one("#composer", Horizontal)
        topbar = self.query_one("#topbar", Horizontal)
        chat_body = self.query_one("#chat-body", Horizontal)
        prompt = self.query_one("#prompt", TextArea)
        session_tabs = self.query_one("#session-tabs-scroll", HorizontalScroll)
        sign_in = self.query_one("#cloud-sign-in", Button)
        footer = self.query_one(Footer)
        header = self.query_one(Header)

        in_startup = self._startup_active
        in_bootstrap = self._cloud_bootstrap_busy
        in_required_update = (
            not in_startup
        ) and self._required_update_notice is not None
        in_signed_out = (
            (not in_startup) and (not in_required_update) and self._cloud_signed_out
        )
        in_onboarding = (
            (not in_required_update) and (not in_signed_out) and self._onboarding_active
        )
        in_session_switch = (
            (not in_startup)
            and (not in_required_update)
            and (not in_signed_out)
            and (not in_onboarding)
            and self._session_switching
        )
        in_settings = (
            (not in_startup)
            and (not in_required_update)
            and (not in_signed_out)
            and (not in_onboarding)
            and (not in_bootstrap)
            and (not in_session_switch)
            and self._settings_active
        )
        in_chat = (
            (not in_startup)
            and (not in_required_update)
            and (not in_signed_out)
            and (not in_onboarding)
            and (not in_bootstrap)
            and (not in_session_switch)
            and (not in_settings)
        )
        if in_signed_out or in_bootstrap:
            self.clear_notifications()

        startup.display = in_startup
        update_required.display = in_required_update
        signed_out.display = in_signed_out
        onboarding.display = in_onboarding
        session_switch.display = in_session_switch
        settings_panel.display = in_settings
        conversation.display = in_chat
        empty.display = False if not in_chat else empty.display
        composer.display = in_chat or in_session_switch
        topbar.display = in_chat or in_session_switch
        session_tabs.display = False
        footer.display = in_chat or in_settings
        header.display = in_chat or in_session_switch or in_settings
        chat_body.styles.padding = (
            (0, 0, 0, 0)
            if (
                in_startup
                or in_required_update
                or in_signed_out
                or in_onboarding
                or in_bootstrap
                or in_session_switch
                or in_settings
            )
            else (0, 2, 0, 2)
        )
        prompt.disabled = not in_chat and not in_session_switch
        sign_in.disabled = self._cloud_auth_busy
        sign_in.label = "Sign in"
        self.query_one("#startup-status", Static).update(self._startup_status_text())
        self._update_session_switch_spinner()
        self.query_one("#signed-out-copy", Static).update(
            build_signed_out_state_renderable(styles=self._render_styles())
        )
        self.query_one("#signed-out-status", Static).update(
            self._signed_out_status_text()
        )
        if in_required_update:
            self._refresh_required_update_state()
        if in_onboarding:
            self.query_one("#onboarding-status", Static).update(
                self._onboarding_status_text()
            )
        if in_chat:
            self._refresh_empty_state()
            prompt.focus()
        self._apply_aside_panel_state()
        self._apply_change_review_panel_state()
        self._apply_thread_switcher_button_state()
        self.refresh_header()


    def _refresh_required_update_state(self) -> None:
        notice = self._required_update_notice
        if notice is None:
            return
        latest = str(getattr(notice, "latest_version", "") or "").strip()
        current = (
            str(getattr(notice, "current_version", "") or "").strip()
            or current_runtime_version()
        )
        command = self._upgrade_command_for_notice(notice)
        message = str(getattr(notice, "message", "") or "").strip()
        if not message:
            target = latest or "the latest version"
            message = (
                f"Version {target} is required before you can continue. "
                "Exit iTE, run the command below, then reopen it."
            )
        message = message.replace("Run below", "Run the command below")
        message = message.replace(
            "Run the command below, then reopen iTE",
            "Exit iTE, run the command below, then reopen it",
        )
        message = self._append_update_instruction(
            message,
            "Exit iTE, run the command below, then reopen it.",
        )
        self.query_one("#update-required-copy", Static).update(message)
        self.query_one(UpdateCommandBox).set_command(command)
        meta_parts = []
        if latest:
            meta_parts.append(f"Latest {latest}")
        if current:
            meta_parts.append(f"Your version {current}")
        release_url = str(getattr(notice, "release_url", "") or "").strip()
        if release_url:
            meta_parts.append(release_url)
        self.query_one("#update-required-meta", Static).update("  •  ".join(meta_parts))


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


    def _update_session_switch_spinner(self) -> None:
        """Update the centered spinner during session switch (no text)."""
        spinner = self.query_one("#session-switch-spinner", Static)
        frame = self._top_spinner_frames[
            self._top_spinner_index % len(self._top_spinner_frames)
        ]
        spinner.update(Text(frame, justify="center"))


    def _onboarding_status_text(self) -> Text:
        status = Text(justify="center")
        if self._onboarding_busy:
            frame = self._top_spinner_frames[
                self._top_spinner_index % len(self._top_spinner_frames)
            ]
            message = (
                "Skipping first-run setup"
                if self._onboarding_skip_busy
                else "Saving your first-run setup"
            )
            status.append(
                f"{frame} {message}",
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
        elif self._cloud_signed_out_status_message:
            status.append(
                self._cloud_signed_out_status_message,
                style=f"bold {self._render_styles()['muted']}",
            )
        else:
            status.append(" ", style=self._render_styles()["muted"])
        return status


    async def _run_cloud_login_flow(self) -> None:
        if self._cloud_auth_busy:
            return
        auth = await asyncio.to_thread(get_cloud_auth_status, self.config)
        auth_state = auth.state if auth else CloudSessionState.SIGNED_OUT
        if auth_state == CloudSessionState.VALID:
            self._apply_cloud_auth_status(auth)
            self._prefetch_cloud_caches()
            if self._should_show_onboarding():
                self._set_onboarding_state(True)
                self.query_one("#onboarding-name", Input).focus()
                return
            await self.ensure_agent()
            self._refresh_empty_state()
            self.query_one("#prompt", TextArea).focus()
            self.post_notice("iTE Cloud", "Already signed in.")
            return
        if auth_state == CloudSessionState.NETWORK_ERROR:
            self._apply_cloud_auth_status(
                auth,
                context="iTE Cloud",
                interactive=True,
            )
            return
        if auth_state == CloudSessionState.INVALID:
            stored_session = getattr(auth, "session", None)
            if stored_session is not None:
                self._apply_cloud_auth_status(
                    auth,
                    context="iTE Cloud",
                    interactive=True,
                )
                return
            clear_cloud_auth(revoke_remote=False)
        if auth_state == CloudSessionState.SIGNED_OUT:
            stored_session = getattr(auth, "session", None)
            if stored_session is not None:
                self._apply_cloud_auth_status(
                    auth,
                    context="iTE Cloud",
                    interactive=True,
                )
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
            self._cloud_network_watch_enabled = True
            self._cloud_network_was_unreachable = True
            self._cloud_signed_out_status_message = f"Cloud API unreachable: {exc}"
            self.query_one("#signed-out-status", Static).update(
                Text(
                    self._cloud_signed_out_status_message,
                    style="bold #ffcf92",
                    justify="center",
                )
            )
            return
        except CloudAuthError as exc:
            self._cloud_auth_busy = False
            self._set_signed_out_state(True)
            self._cloud_network_watch_enabled = False
            self._cloud_signed_out_status_message = f"Sign-in failed: {exc}"
            self.query_one("#signed-out-status", Static).update(
                Text(
                    self._cloud_signed_out_status_message,
                    style="bold #ffcf92",
                    justify="center",
                )
            )
            return

        self._cloud_auth_busy = False
        self._set_signed_out_state(False)
        self._prefetch_cloud_caches()
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


    async def _continue_without_cloud_sign_in(self) -> None:
        if self._cloud_auth_busy:
            return
        self._cloud_auth_busy = True
        self._cloud_bootstrap_busy = False
        self._set_signed_out_state(True)
        try:
            await asyncio.to_thread(save_cloud_settings, enabled=False)
            self.config.cloud_auth_enabled = False
            self._set_local_account_plan_state(refresh=False)
        except Exception as exc:
            self._cloud_auth_busy = False
            self._apply_shell_surface()
            self.query_one("#signed-out-status", Static).update(
                Text(
                    f"Could not skip sign-in: {exc}",
                    style="bold #ffcf92",
                    justify="center",
                )
            )
            return

        self._cloud_auth_busy = False
        self._set_signed_out_state(False)
        if self._should_show_onboarding():
            self._set_onboarding_state(True)
            self.query_one("#onboarding-name", Input).focus()
            return
        if self.config.needs_setup:
            await self._open_setup_modal(exit_on_cancel=False)
            await self._reset_active_provider_client()
            if self.config.needs_setup:
                self._apply_shell_surface()
                return
            self.agent = None
        await self.ensure_agent()
        self._refresh_empty_state()
        self.query_one("#prompt", TextArea).focus()


    async def _reset_runtime_after_cloud_logout(self) -> None:
        if self._is_turn_running:
            await self.cancel_active_turn()
        if self.agent and self.agent.session and self.agent.session.turn_count > 0:
            await self.auto_save()

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
        self.agent = None
        self._session_agents.clear()
        self._open_sessions.clear()
        self._open_session_order.clear()
        self._open_session_workspaces.clear()
        self._thread_nav_order.clear()
        self._session_run_states.clear()
        self._bundled_models_cache = []
        self._account_plan_is_pro = False
        self._account_plan_unavailable = False
        self._usage_summary_cache = None
        self._activity_cache = None
        self._usage_remaining_percent = None
        if self.is_mounted:
            conversation = self.query_one("#conversation", VerticalScroll)
            await conversation.remove_children()
            self._message_count = 0
            self._reset_session_local_ui_state()


    async def _run_cloud_logout_flow(self) -> None:
        await self._reset_runtime_after_cloud_logout()
        clear_cloud_auth()
        mark_cloud_signed_out()
        self._set_signed_out_state(True)


    async def _run_cloud_status_flow(self) -> None:
        auth = await asyncio.to_thread(get_cloud_auth_status, self.config)
        if auth.state == CloudSessionState.VALID:
            self._apply_cloud_auth_status(auth)
            self._prefetch_cloud_caches()
            self.post_notice("iTE Cloud", "Signed in.")
            return
        if auth.state in {CloudSessionState.SIGNED_OUT, CloudSessionState.INVALID}:
            self._apply_cloud_auth_status(
                auth,
                context="iTE Cloud",
                interactive=(auth.state == CloudSessionState.INVALID),
            )
            if auth.state == CloudSessionState.SIGNED_OUT:
                self.post_notice("iTE Cloud", "Signed out. Use `/login` to sign in.")
            return
        self._apply_cloud_auth_status(auth, context="iTE Cloud", interactive=True)


    async def _run_refresh_flow(self) -> None:
        if self._cloud_signed_out:
            self.post_notice(
                "iTE Cloud",
                "Not signed in. Use `/login` to sign in first.",
            )
            return
        if self._cloud_auth_busy or self._cloud_bootstrap_busy:
            self.post_notice(
                "iTE Cloud",
                "Another cloud operation is in progress. Please wait.",
            )
            return
        self._prefetch_cloud_caches()
        self.post_notice(
            "iTE Cloud",
            "Refreshing...",
        )


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
        self._onboarding_skip_busy = skip
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
            self._onboarding_skip_busy = False
            if self._onboarding_active:
                self._apply_shell_surface()

        self._set_onboarding_state(False)
        if self.config.needs_setup:
            self.post_notice(
                "Model setup",
                "Run /setup to use local Ollama models, OpenRouter, or your own OpenAI-compatible provider.",
                timeout=8,
            )
        # Ensure agent is created after onboarding completes.
        # This was previously skipped because onboarding blocked the initial ensure_agent() call.
        await self.ensure_agent()
        # Sync the dismissed count to prevent unintended thread nav auto-open.
        # After onboarding, user has just one session, so they shouldn't see the nav.
        self._thread_switcher_dismissed_count = len(self._open_session_order)
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


    @on(Button.Pressed, "#cloud-sign-in")

    def on_cloud_sign_in_pressed(self, _event: Button.Pressed) -> None:
        self.run_worker(self._run_cloud_login_flow(), exclusive=False)

    @on(Button.Pressed, "#cloud-skip-sign-in")

    def on_cloud_skip_sign_in_pressed(self, _event: Button.Pressed) -> None:
        self.run_worker(self._continue_without_cloud_sign_in(), exclusive=False)

    @on(Button.Pressed, "#cloud-exit")

    def on_cloud_exit_pressed(self, _event: Button.Pressed) -> None:
        self.run_worker(self._exit_app(), exclusive=False)

    @on(Button.Pressed, "#update-required-exit")

    def on_update_required_exit_pressed(self, _event: Button.Pressed) -> None:
        self.run_worker(self._exit_app(), exclusive=False)


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

    async def _open_setup_modal(self, *, exit_on_cancel: bool = False) -> bool:
        result = await self._open_modal(SetupModal(self.config))
        if not result:
            if exit_on_cancel and self.config.needs_setup:
                self.exit()
            return False
        await self._apply_setup_result(result)
        return True


    async def _reset_active_provider_client(self) -> None:
        if not self.agent or not self.agent.session:
            return
        session_config = getattr(self.agent.session, "config", None)
        if session_config is not None:
            session_config.api_key = self.config.api_key
            session_config.base_url = self.config.base_url
            session_config.model.name = self.config.model.name
            session_config.model.context_window = self.config.model.context_window
            session_config.model.context_window_source = (
                self.config.model.context_window_source
            )
            session_config.model.source_kind = self.config.model.source_kind
            session_config.model.supports_vision = self.config.model.supports_vision
        if not getattr(self.agent.session, "client", None):
            return
        try:
            await self.agent.session.client.close()
        except Exception:
            pass
