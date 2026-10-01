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
from ite.agent.change_history import ChangeConflictError
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
from ite.config.loader import get_workspace_agents_recommendation, load_config, load_saved_custom_provider, load_theme, remove_saved_custom_provider, save_cloud_settings, save_global_approval_mode, save_onboarding_settings, save_open_island_settings, save_saved_custom_provider, save_system_config, save_theme, save_voice_settings
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
from .widgets.side_panels import (
    ChangeReviewSidePanel,
    CommandsSidePanel,
    GoalSidePanel,
    HooksSidePanel,
)
from .widgets.thread_switcher import ThreadSwitcherRow, ThreadSwitcherSidePanel
from .widgets.tool_cards import CompactToolCard, ShellToolCard, ToolCardStack
from .widgets.remote_bridge import RemoteBridgeCard, RemoteBridgeField, UpdateCommandBox
from .widgets.system_commands import ReupSystemCommandsProvider
from .adapters.tui_adapter import ReupTUIAdapter
from .change_views import change_entry_label, build_change_card_body, build_change_card_payload
from .model_labels import bundled_model_display_label
from .modals import ApprovalPickerModal, AttachPickerModal, BranchPickerModal, CommitModal, ContextSummaryModal, ActivityModal, ModelPickerModal, ThemePickerModal, UsageSummaryModal, PushReviewModal, RemoteSetupModal, PlanQuestionModal, SessionResumeModal, VoiceSetupModal, ConfirmModal, SetupModal


def _island_approval_preview(confirmation) -> str:
    """Human-readable action for the notch card, via the wire-layer builder."""
    from ite.integrations.open_island import payloads

    return payloads.approval_preview(
        tool_name=str(confirmation.tool_name or ""),
        description=getattr(confirmation, "description", None),
        command=getattr(confirmation, "command", None),
        affected_paths=[
            str(path) for path in getattr(confirmation, "affected_paths", None) or []
        ],
    )


def _island_affected_path(confirmation) -> str | None:
    paths = getattr(confirmation, "affected_paths", None) or []
    return str(paths[0]) if paths else None


class TurnMixin:
    """Extracted mixin for _turn."""


    async def _has_remote_companion_access(self, *, refresh: bool = False) -> bool:
        status = await self._remote_companion_access_status(refresh=refresh)
        return bool(getattr(status, "is_valid", False))


    async def _remote_companion_access_status(self, *, refresh: bool = False) -> Any:
        now = time.monotonic()
        if not refresh and self._remote_access_cache is not None:
            status, checked_at = self._remote_access_cache
            if now - checked_at < 60:
                return status
        status = await asyncio.to_thread(
            get_remote_companion_access_status,
            self.config,
        )
        self._remote_access_cache = (status, now)
        return status


    def _remote_access_error_message(self, status: Any) -> str:
        state = str(getattr(status, "state", "") or "")
        message = str(getattr(status, "message", "") or "").strip()
        if state == CloudSessionState.CREDENTIAL_ERROR:
            return (
                (
                    message
                    or "Could not read iTE Cloud credentials from the OS credential store."
                )
                + " Unlock Keychain Access if needed, then try `/remote on` again. If that keeps failing, run `/login` to refresh the stored credential."
            )
        if state == CloudSessionState.NETWORK_ERROR:
            return (
                message
                or "iTE Cloud is unreachable right now. Your stored session was kept."
            )
        if state == CloudSessionState.SIGNED_OUT:
            return "Sign in with `/login`, then try `/remote on` again."
        if state == CloudSessionState.INVALID:
            return (
                message or "Stored iTE Cloud session is expired or revoked."
            ) + " Run `/login` to sign in again."
        return (
            message
            or "Remote companion requires bundled access. Sign in with `/login` using an account with bundled access, or manage your plan, then try `/remote on` again."
        )


    async def _require_remote_companion_access(self, *, refresh: bool = True) -> bool:
        status = await self._remote_companion_access_status(refresh=refresh)
        if bool(getattr(status, "is_valid", False)):
            return True
        self.post_system(
            "Remote",
            self._remote_access_error_message(status),
            is_error=True,
        )
        return False


    async def _ensure_remote_server(
        self,
        *,
        port: int | None = None,
        lan: bool = True,
    ) -> dict[str, Any]:
        if not await self._require_remote_companion_access(refresh=False):
            raise PermissionError("Remote companion requires bundled access.")
        if self._remote_server is None:
            self._remote_server = RemoteRuntimeServer(
                state_provider=self._build_remote_runtime_state,
                submit_prompt=self._submit_remote_prompt,
                cancel_turn=self._cancel_remote_turn,
                switch_session=self._switch_remote_session,
                access_checker=self._has_remote_companion_access,
            )
        selected_port = (
            int(port)
            if isinstance(port, int) and port >= 0
            else int(self._remote_port_preference or 0)
        )
        bind_host = "0.0.0.0" if lan else "127.0.0.1"
        if self._remote_server.is_running and self._remote_server.connection_info().get(
            "exposure_mode"
        ) != ("lan" if lan else "local"):
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
                "goal": session.export_goal_state() if session else None,
                "active_turn_id": int(run_state.active_turn_id),
                "is_turn_running": bool(run_state.is_turn_running),
                "activity_label": str(self._top_state_text or ""),
                "activity_busy": bool(self._top_busy),
                "awaiting_shell_input": self._active_shell_input_call_id() is not None,
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
        if self._is_turn_running and await self._send_active_shell_input(
            message,
            clear_composer=False,
        ):
            return
        self._suppress_telegram_user_echo = True
        try:
            payload = self._build_turn_payload(message)
            await self._dispatch_payload(payload)
        finally:
            self._suppress_telegram_user_echo = False


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
            if not await self._require_remote_companion_access():
                return
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
                intro="Mobile bridge ready."
                if lan
                else "Remote bridge ready for local-only mode.",
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
            if not await self._require_remote_companion_access():
                return
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
            connected_clients = self._remote_server.authenticated_client_count
            await self._shutdown_remote_server()
            self.post_system(
                "Remote",
                "Remote bridge stopped."
                if connected_clients == 0
                else f"Remote bridge stopped. Disconnected {connected_clients} mobile client{'s' if connected_clients != 1 else ''}.",
            )
            return

        self.post_system(
            "Remote",
            "Usage: /remote\n/remote on [port]\n/remote on [port] --local\n/remote status\n/remote code\n/remote devices\n/remote revoke <device-id-prefix>\n/remote revoke-all\n/remote off",
            is_error=True,
        )


    async def _run_telegram_command_native(self, args: list[str]) -> None:
        action = args[0].lower() if args else ""

        if action in {"on", "start"}:
            try:
                from ite.telegram.bot import TelegramBotService, _DEFAULT_TELEGRAM_BOT_TOKEN
            except ImportError:
                self.post_system(
                    "Telegram",
                    "python-telegram-bot is not installed. Run: pip install python-telegram-bot[job-queue]",
                    is_error=True,
                )
                return

            if (
                self._telegram_service is not None
                and self._telegram_service.running
            ):
                self.post_system(
                    "Telegram",
                    "Telegram bot is already running. Use /telegram off to stop.",
                )
                return

            self._telegram_service = TelegramBotService(
                on_submit_prompt=self._submit_remote_prompt,
                on_cancel_turn=self._cancel_remote_turn,
            )
            await self._telegram_service.start(bot_token=_DEFAULT_TELEGRAM_BOT_TOKEN)
            self.post_system(
                "Telegram",
                "Telegram bot polling started. Send /start to your bot on Telegram.",
            )
            return

        if action in {"off", "stop"}:
            if self._telegram_service is None or not self._telegram_service.running:
                self.post_system("Telegram", "Telegram bot is not running.")
                return
            await self._telegram_service.stop()
            self._telegram_service = None
            self.post_system("Telegram", "Telegram bot stopped.")
            return

        self.post_system(
            "Telegram",
            "Usage: /telegram on\n/telegram off",
            is_error=True,
        )


    async def ensure_agent(self) -> None:
        async with self._ensure_agent_lock:
            if self.agent is not None:
                if self.agent.session is not None:
                    self._remember_open_session(self.agent.session, agent=self.agent)
                    await self._broadcast_remote_state()
                return
            fresh = Session(config=self._session_config_for_workspace())
            agent = self._build_session_agent(fresh)
            await agent.__aenter__()
            self.agent = agent
            # The bundled-model catalog can return while agent startup is
            # awaiting. At that point the catalog updates app config, but this
            # freshly-created session still has the earlier context window.
            self._sync_bundled_context_window()
            self._update_composer_meta_line()
            if agent.session is not None:
                self._remember_open_session(agent.session, agent=agent)
            await self._broadcast_remote_state()


    def _build_session_agent(self, session: Session) -> Agent:
        session_id = self._session_id(session) or ""

        async def _confirm(confirmation, sid: str = session_id) -> bool:
            return await self._confirmation_callback_for_session(sid, confirmation)

        async def _plan_question(
            payload: dict[str, Any], sid: str = session_id
        ) -> dict[str, Any]:
            return await self._plan_question_callback_for_session(sid, payload)

        agent_config = (
            getattr(
                session,
                "config",
                None,
            )
            or self._session_config_for_workspace()
        )
        return Agent(
            config=agent_config,
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
            # Save in background — don't block session switch
            self.run_worker(self.auto_save(), exclusive=False)

        workspace = self._workspace_for_session_id(session_id)
        self.config.cwd = workspace
        self.agent = target_agent
        self._remember_open_session(target, workspace=workspace, agent=target_agent)
        self.refresh_header()
        await self._hydrate_chat_from_snapshot(
            target.context_manager.get_messages() if target.context_manager else [],
            show_loading=False,  # In-memory switch — no loading delay
        )
        if self._is_turn_running:
            self._set_loading_state(self._progress_state_label(), busy=True)
        else:
            self._set_loading_state("idle", busy=False)
        if announce:
            self.post_notice("Thread", announce)
        await self._broadcast_remote_state()
        return True


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
            self._maybe_focus_prompt()
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
        target_workspace = (
            Path(snapshot.workspace_path).resolve()
            if snapshot.workspace_path
            else Path(self.config.cwd).resolve()
        )
        if target_workspace != self.config.cwd.resolve():
            self.config.cwd = target_workspace
            self.refresh_header()

        resumed = Session(config=self._session_config_for_workspace(target_workspace))
        if hasattr(resumed, "set_session_id"):
            resumed.set_session_id(snapshot.session_id)
        else:
            resumed.session_id = snapshot.session_id
        resumed.name = snapshot.name
        resumed.name_source = snapshot.name_source
        resumed.name_locked = snapshot.name_locked
        resumed.name_last_generated_turn = snapshot.name_last_generated_turn
        resumed.name_last_attempt_turn = snapshot.name_last_attempt_turn
        resumed.name_failed_attempts = snapshot.name_failed_attempts
        resumed.name_context_hash = snapshot.name_context_hash
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
        resumed.restore_goal_state(snapshot.goal_state, snapshot.goal_history)
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
            workspace=target_workspace,
            agent=resumed_agent,
        )
        self.agent = resumed_agent
        self._sync_bundled_context_window()
        self.refresh_header()
        await self._hydrate_chat_from_snapshot(restored_messages)
        self._set_loading_state("idle", busy=False)
        await self._broadcast_remote_state()
        await self._remove_cards_by_title({"Session Loaded"})
        if dropped_agent is not None:
            try:
                await dropped_agent.__aexit__(None, None, None)
            except Exception:
                pass


    async def _hydrate_chat_from_snapshot(
        self, messages: list[dict[str, Any]], show_loading: bool = True
    ) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        await conversation.remove_children()
        self._message_count = 0
        self._reset_session_local_ui_state()

        # Show loading indicator during hydration
        loading_widget: Static | None = None
        if show_loading:
            loading_widget = Static(
                "Loading conversation...",
                classes="chat-loading-indicator",
            )
            await conversation.mount(loading_widget)

        # Skip activity indicator updates during bulk hydration
        self._hydrating_from_snapshot = True

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

        # Clean up hydration state
        self._hydrating_from_snapshot = False

        # Remove loading indicator if it exists and scroll to end once
        if loading_widget is not None:
            try:
                await loading_widget.remove()
            except Exception:
                pass
        conversation.scroll_end(animate=False)

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
        if parts and parts[0].lower() == "/init":
            worker = self._init_command_worker
            if worker is not None and not worker.is_finished:
                self.post_notice("Initialization", "Already running. Press Ctrl+C to cancel.")
                return
            self._init_command_worker = self.run_worker(
                self._run_init_command(command_line), group="init-command",
                exclusive=False, exit_on_error=False,
            )
            return
        await self._run_command_inline(command_line)

    async def _run_init_command(self, command_line: str) -> None:
        try:
            await self._run_command_inline(command_line)
        except asyncio.CancelledError:
            # Cancellation can arrive during ensure_agent(), before the handler
            # has a context or card to finalize.
            pending = next((
                entry for entry in reversed(self._remote_command_feed)
                if entry.get("command") == command_line and entry.get("status") == "running"
            ), None)
            if pending is not None:
                self._finish_remote_command_feed_entry(
                    pending["id"], status="cancelled", output="Initialization cancelled.",
                )
                self.post_notice("Initialization", "Cancelled")
            raise
        finally:
            self._init_command_worker = None

    async def _run_command_inline(self, command_line: str) -> None:
        parts = command_line.split()
        command = parts[0].lower()
        args = parts[1:]
        command_feed_id: str | None = None

        if command in {"/exit", "/quit"}:
            self.run_worker(self._confirm_quit(), exclusive=False)
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

        if command == "/goal":
            await self._run_goal_command_native(args)
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

        if command == "/hooks":
            if args and args[0].lower() in {"on", "off"}:
                # Handle on/off - persist and notify
                await self._run_hooks_command_native(args)
                return
            # No args - just toggle the panel
            await self._toggle_hooks_panel()
            return

        if command == "/oi":
            await self._run_open_island_command_native(args)
            return

        if command == "/publish":
            await self._run_publish_command_native(args)
            return

        if command == "/remote":
            await self._run_remote_command_native(args)
            return

        if command == "/telegram":
            await self._run_telegram_command_native(args)
            return

        if command in {"/voice", "/flow"}:
            if args and args[0].strip().lower() == "setup":
                self.run_worker(self._run_voice_command_native(args), exclusive=False)
                return
            await self._run_voice_command_native(args)
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

        if command == "/login":
            await self._run_cloud_login_flow()
            return

        if command == "/branch" and not args:
            await self._open_branch_picker_from_meta()
            return

        if command == "/attach" and not args:
            await self._open_attach_picker_from_meta()
            return

        if command == "/models":
            await self._open_model_picker_from_meta()
            return

        if command == "/status":
            await self._run_cloud_status_flow()
            return

        if command == "/refresh":
            await self._run_refresh_flow()
            return

        if command == "/logout":
            await self._run_cloud_logout_flow()
            return

        if command == "/usage":
            await self._open_usage_modal_from_meta()
            return

        if command == "/settings":
            await self._open_settings_screen()
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

        command_config = (
            self._prepare_sandbox_command_config()
            if command == "/sandbox"
            else self.config
        )
        live_stream_command = command in {"/init"} or (
            command == "/mcp" and args and args[0].lower() == "start"
        )
        live_stream_command = live_stream_command and (
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
            config=command_config,
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
            if command == "/sandbox":
                self._sync_app_sandbox_from_active_session()
        except SystemExit:
            self.exit()
            return
        except asyncio.CancelledError:
            if command_feed_id is not None:
                self._finish_remote_command_feed_entry(
                    command_feed_id, status="cancelled",
                    output=ctx.result or "Command cancelled",
                )
            raise
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
        rendered = output.getvalue().strip() or ctx.result
        command_metadata = self._build_remote_command_feed_metadata(
            command,
            args,
            rendered,
        )
        if command in {
            "/branch",
            "/attach",
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
                    status=ctx.outcome,
                    output=rendered,
                    metadata=command_metadata,
                )
            return
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
        await self._refresh_change_review_source(force=True)
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


    async def _run_goal_command_native(self, args: list[str]) -> None:
        await self.ensure_agent()
        session = self.agent.session if self.agent and self.agent.session else None
        if session is None:
            self.post_system("Goal", "No active session.", is_error=True)
            return

        if not args:
            if session.goal_state is None:
                self.post_system(
                    "Goal",
                    "No goal is active. Use `/goal <objective>` to start one.",
                )
                return
            await self._show_goal_panel()
            return

        action = args[0].lower()
        if action == "pause" and len(args) == 1:
            await self._pause_goal_from_ui()
            return
        if action == "resume" and len(args) == 1:
            if await self._resume_goal_from_ui():
                self.post_notice("Goal", "Goal resumed.")
            return
        if action == "clear" and len(args) == 1:
            await self._clear_goal_from_ui()
            return
        if action == "edit":
            objective = " ".join(args[1:]).strip()
            if not objective:
                self.post_system("Goal", "Use `/goal edit <objective>`.", is_error=True)
                return
            if not await self._pause_goal_from_ui(reason="Paused to edit the goal."):
                return
            try:
                session.edit_goal(objective)
            except ValueError as exc:
                self.post_system("Goal", str(exc), is_error=True)
                return
            await self._persist_goal_state()
            await self._refresh_goal_surfaces()
            self.post_notice("Goal", "Goal updated and paused. Use `/goal resume` to continue.")
            return

        if session.goal_state is not None:
            self.post_system(
                "Goal",
                "A goal already exists. Use `/goal edit` or `/goal clear`.",
                is_error=True,
            )
            return

        objective = " ".join(args).strip()
        try:
            session.create_goal(objective)
        except ValueError as exc:
            self.post_system("Goal", str(exc), is_error=True)
            return
        await self._persist_goal_state()
        await self._refresh_goal_surfaces()
        await self._show_goal_panel()
        self.post_notice("Goal", "Goal created. Starting work.")
        await self._dispatch_payload(
            {
                "message": (
                    "Work toward the active goal below. First use goal_progress to "
                    "record a concise plan of concrete milestones. Then make progress, "
                    "record observed proof for each completed milestone, and do not "
                    "claim completion until every milestone is complete. Keep the first "
                    "plan stable, and use its returned milestone IDs exactly.\n\n"
                    f"Goal: {objective}"
                ),
                "display_message": "",
                "attachments": [],
                "suppress_user_echo": True,
            }
        )


    async def _run_hooks_command_native(self, args: list[str]) -> None:
        """Handle /hooks on|off - persist and notify, don't open panel."""
        arg = args[0].lower()
        if arg not in {"on", "off"}:
            self.post_system("Hooks", "Use `/hooks on` or `/hooks off`.", is_error=True)
            return

        enable = arg == "on"
        old_state = self.config.hooks_enabled

        # Update in-memory config (this should propagate to session's hook_system)
        self.config.hooks_enabled = enable

        # Persist to workspace config
        from ite.config.loader import save_workspace_hooks_enabled

        saved_path = save_workspace_hooks_enabled(self.config.cwd, enable)

        # Update session hook system - reload hooks based on current config
        if self.agent and self.agent.session:
            session = self.agent.session
            # Update the config reference in hook_system
            session.hook_system.config = self.config
            # Reload enabled hooks
            session.hook_system.hooks = (
                [hook for hook in self.config.hooks if hook.enabled] if enable else []
            )

        # Refresh the toggle button visibility by forcing a poll
        self._hooks_snapshot_key = None  # Force refresh
        await self._sync_hooks_panel_state()

        # Notify user via toast notification (not chat feed)
        mode = "ENABLED" if enable else "DISABLED"
        self.post_notice(
            f"Hooks {mode}",
            f"Hooks {mode.lower()} and saved to {saved_path.name}",
        )

    async def _run_open_island_command_native(self, args: list[str]) -> None:
        """Handle `/oi`, `/oi on`, and `/oi off` in the running UI."""
        action = (args[0] if args else "status").strip().lower()
        if action in {"status", "info"}:
            self.post_notice("Open Island", self._open_island_status_text())
            return
        if action not in {"on", "off"}:
            self.post_system(
                "Open Island",
                "Use `/oi`, `/oi on`, or `/oi off`.",
                is_error=True,
            )
            return

        enabled = action == "on"
        await self._set_open_island_enabled(enabled)
        if enabled:
            self.post_notice("Open Island enabled", self._open_island_status_text())
        else:
            self.post_notice("Open Island disabled", self._open_island_status_text())

    def _live_agents(self) -> list[Agent]:
        """Return each active session agent once, including non-tabbed startup."""
        candidates = list(self._session_agents.values())
        if self.agent is not None:
            candidates.append(self.agent)
        seen: set[int] = set()
        live: list[Agent] = []
        for agent in candidates:
            identity = id(agent)
            if identity not in seen:
                seen.add(identity)
                live.append(agent)
        return live

    async def _set_open_island_enabled(self, enabled: bool) -> None:
        """Persist the preference and update all live sessions immediately."""
        await asyncio.to_thread(save_open_island_settings, enabled=enabled)
        self.config.integrations.open_island.enabled = enabled

        for agent in self._live_agents():
            agent.config.integrations.open_island.enabled = enabled
            session = getattr(agent, "session", None)
            session_config = getattr(session, "config", None)
            if session_config is not None:
                session_config.integrations.open_island.enabled = enabled
            await agent.set_open_island_enabled(enabled)

        self._refresh_open_island_settings()

    def _open_island_status_text(self) -> str:
        if not self.config.integrations.open_island.enabled:
            return "Notifications are off. Use `/oi on` to mirror iTE activity."
        if sys.platform != "darwin":
            return "Notifications are on, but Open Island is available on macOS only."
        connected = sum(
            1
            for agent in self._live_agents()
            if getattr(getattr(agent, "open_island_bridge", None), "enabled", False)
        )
        if connected:
            plural = "session" if connected == 1 else "sessions"
            return f"Notifications are on for {connected} active {plural}."
        return "Notifications are on and will connect when a session starts."

    def _refresh_open_island_settings(self) -> None:
        """Refresh the mounted Settings control after a slash-command change."""
        try:
            panel = self.query_one("#settings-panel")
        except NoMatches:
            return
        refresh = getattr(panel, "refresh_open_island_state", None)
        if callable(refresh):
            refresh()


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
                        "plan_mode_enabled": bool(
                            workboard_payload["plan_mode_enabled"]
                        ),
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
            normalized_entries = [item for item in entries if isinstance(item, dict)]
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
        session_id: str | None = None,
        add_to_feed: bool = True,
    ) -> None:
        rendered_message = display_message or message
        await self.ensure_agent()
        target_session_id = session_id or self._active_session_id()
        active_agent = (
            self._session_agents.get(target_session_id or "")
            if target_session_id
            else self.agent
        )
        if active_agent is None:
            active_agent = self.agent
        if not active_agent or not active_agent.session:
            self.post_system("Error", "Agent is not initialized", is_error=True)
            return

        session_id = self._session_id(active_agent.session) or target_session_id
        if not session_id:
            self.post_system("Error", "No active thread.", is_error=True)
            return
        workspace = self._workspace_for_session_id(session_id)
        is_visible_session = self._active_session_id() == session_id
        if add_to_feed and not suppress_user_echo and is_visible_session:
            await self.add_user_message(rendered_message)
            await self._broadcast_remote_state()
        if not suppress_user_echo and not active_agent.session.name:
            # Give the thread a usable title the moment the first message is sent,
            # so it is never shown as "Untitled thread" while the model works.
            self._apply_fallback_session_name(active_agent.session, message)
            self._refresh_session_name_ui(
                active_agent.session,
                refresh_ui=is_visible_session,
            )
        run_state = self._run_state(session_id)
        if is_visible_session:
            self._last_rendered_plan_text = None
        run_state.turn_had_error = False
        run_state.turn_made_progress = False
        run_state.goal_turn_had_tool_progress = False
        run_state.last_error_message = None
        run_state.retryable_turn_payload = None
        if not suppress_user_echo:
            run_state.failure_recovery_attempts = 0
        run_state.silent_recovery_active = suppress_user_echo
        run_state.failure_recovery_payload = None
        run_state.auto_resume_payload = None
        attachments = list(
            getattr(active_agent.session, "pending_attachment_paths", [])
        )
        model_name = str(getattr(active_agent.session.config, "model_name", "") or "").strip()
        session_model = getattr(active_agent.session.config, "model", None)
        supports_vision = (
            bool(getattr(session_model, "supports_vision", True))
            if session_model is not None
            else (detect_vision_from_model_name(model_name) if model_name else True)
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
            workspace=workspace,
            supports_vision=supports_vision,
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
        goal = getattr(active_agent.session, "goal_state", None)
        if goal is not None and goal.status.value == "active":
            run_state.goal_turn_started_at_monotonic = time.monotonic()
        self._cancel_usage_idle_poll()
        if self._active_session_id() == session_id:
            self._send_meta_frame = 0
        if self._active_session_id() == session_id:
            self._set_loading_state(self._progress_state_label(), busy=True)
            self.refresh_header()
        else:
            self._queue_session_tabs_refresh()
        await self._broadcast_remote_state()
        completed_normally = False

        try:
            await run_state.active_turn_task
            self._settle_goal_turn_work(session_id)
            run_state.active_turn_task = None
            run_state.is_turn_running = False
            if self._active_session_id() == session_id:
                self._send_meta_frame = 0
            run_state.context_meter_floor_pct = None
            if self._active_session_id() == session_id:
                self.refresh_header()
            else:
                self._queue_session_tabs_refresh()
            if (
                self._active_session_id() == session_id
                and run_state.auto_resume_payload is None
            ):
                self._set_loading_state("idle", busy=False)
            if self._active_session_id() == session_id:
                await self.auto_save()
            else:
                await self._auto_save_session(
                    active_agent.session,
                    workspace=workspace,
                    refresh_ui=False,
                )
            await self._broadcast_remote_state()
            completed_normally = not run_state.turn_had_error
        except asyncio.CancelledError:
            self._settle_goal_turn_work(session_id)
            if self._active_session_id() == session_id:
                run_state.active_turn_task = None
                run_state.is_turn_running = False
                self._send_meta_frame = 0
                run_state.context_meter_floor_pct = None
                self.refresh_header()
                self._set_loading_state("idle", busy=False)
                await self.auto_save()
                await self._broadcast_remote_state()
            return
        finally:
            self._settle_goal_turn_work(session_id)
            run_state.active_turn_task = None
            run_state.is_turn_running = False
            if self._active_session_id() == session_id:
                self._send_meta_frame = 0
            if run_state.context_meter_floor_pct is not None and not completed_normally:
                run_state.context_meter_floor_pct = None
            if self._active_session_id() == session_id:
                self.refresh_header()
            else:
                self._queue_session_tabs_refresh()
            if (
                self._active_session_id() == session_id
                and run_state.auto_resume_payload is None
            ):
                self._set_loading_state("idle", busy=False)
            await self._broadcast_remote_state()

        if completed_normally and self._active_session_id() == session_id:
            if self._is_bundled_model() and not self._bundled_access_announced:
                # self.post_notice(
                #     "Bundled Access",
                #     "You're now using bundled access.",
                # )
                self._bundled_access_announced = True
            if not self._cloud_signed_out:
                self._prefetch_cloud_caches()
            run_state.failure_recovery_payload = None
            await self._queue_goal_continuation_if_ready(session_id)
            await self._dispatch_queued_payload_if_ready()
        elif (
            self._active_session_id() == session_id
            and run_state.failure_recovery_payload is not None
        ):
            await self._clear_inflight_turn_ui(
                preserve_streaming_message=run_state.silent_recovery_active
            )
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
        except Exception as exc:
            error_str = str(exc)
            run_state = self._run_state(session_id)
            run_state.turn_had_error = True
            run_state.context_meter_floor_pct = None
            self._mark_retryable_turn_failure(session_id, error_str)
            recovery_payload = self._build_followup_recovery_payload(session_id)
            if recovery_payload is not None and run_state.failure_recovery_attempts < 3:
                run_state.failure_recovery_payload = recovery_payload
                run_state.failure_recovery_attempts += 1
                run_state.silent_recovery_active = True
                self._set_loading_state("Reconnecting...", busy=True)
            else:
                retry_payload = self._build_silent_retry_payload(session_id)
                if retry_payload is not None and run_state.failure_recovery_attempts < 3:
                    run_state.failure_recovery_payload = retry_payload
                    run_state.failure_recovery_attempts += 1
                    run_state.silent_recovery_active = True
                    self._set_loading_state("Reconnecting...", busy=True)
                else:
                    self.post_system(
                        "Connection lost",
                        error_str,
                        is_error=True,
                    )
        finally:
            if attachment_turn_id:
                AttachmentManager(
                    self._workspace_for_session_id(session_id)
                ).cleanup_turn(attachment_turn_id)


    def _goal_session_for_id(self, session_id: str) -> Session | None:
        session = self._open_sessions.get(session_id)
        if session is not None:
            return session
        if self.agent and self.agent.session and self.agent.session.session_id == session_id:
            return self.agent.session
        return None


    def _settle_goal_turn_work(self, session_id: str) -> None:
        run_state = self._run_state(session_id)
        started_at = run_state.goal_turn_started_at_monotonic
        run_state.goal_turn_started_at_monotonic = None
        if started_at is None:
            return
        session = self._goal_session_for_id(session_id)
        goal = getattr(session, "goal_state", None)
        if goal is None:
            return
        goal.metrics.work_elapsed_seconds += max(0.0, time.monotonic() - started_at)


    def _record_goal_event_metrics(self, session_id: str, event: AgentEvent) -> None:
        session = self._goal_session_for_id(session_id)
        goal = getattr(session, "goal_state", None)
        if goal is None:
            return
        if event.type == AgentEventType.TEXT_COMPLETE and event.data.get("final", True):
            goal.metrics.model_rounds += 1
        elif event.type == AgentEventType.TOOL_CALL_START:
            goal.metrics.tool_calls_started += 1
        elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
            is_verification = self._is_goal_verification_event(event)
            if is_verification:
                goal.metrics.verification_attempts += 1
            if event.data.get("success", False):
                goal.metrics.tool_calls_succeeded += 1
                if is_verification:
                    goal.metrics.verification_passes += 1
                self._run_state(session_id).goal_turn_had_tool_progress = True
            else:
                goal.metrics.tool_calls_failed += 1

    def _is_goal_verification_event(self, event: AgentEvent) -> bool:
        name = str(event.data.get("name") or "").strip().lower()
        if name in {"run_tests", "run_linter", "run_typecheck"}:
            return True
        if name not in {"shell", "shell_start"}:
            return False
        call_id = str(event.data.get("call_id") or "")
        arguments = self._tool_args_by_call_id.get(call_id, {})
        command = str(arguments.get("command") or "").lower()
        return bool(
            re.search(
                r"\b(pytest|unittest|ruff|mypy|pyright|nox|tox)\b"
                r"|\b(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b",
                command,
            )
        )

    def _goal_usage_limit_details(self, error_message: str) -> dict[str, Any] | None:
        """Recognize a definitive provider-quota stop, not transient throttling."""
        normalized = str(error_message or "").lower()
        quota_markers = (
            "quota_exhausted",
            "request_blocked_quota",
            "bundled usage is unavailable",
            "usage limit exhausted",
            "usage quota exceeded",
            "insufficient credits",
        )
        if not any(marker in normalized for marker in quota_markers):
            return None
        return {"reason": str(error_message).strip(), "provider": "current"}

    async def _limit_goal_for_usage_error(
        self, session_id: str, error_message: str
    ) -> bool:
        details = self._goal_usage_limit_details(error_message)
        if details is None:
            return False
        session = self._goal_session_for_id(session_id)
        goal = getattr(session, "goal_state", None)
        if goal is None or goal.status.value != "active":
            return False
        session.limit_goal_budget(details)
        await self._persist_goal_state()
        await self._refresh_goal_surfaces()
        return True

    async def _queue_goal_continuation_if_ready(self, session_id: str) -> None:
        session = self._goal_session_for_id(session_id)
        goal = getattr(session, "goal_state", None)
        run_state = self._run_state(session_id)
        if (
            goal is None
            or goal.status.value != "active"
            or run_state.goal_pause_requested
            or run_state.is_turn_running
            or run_state.auto_resume_payload is not None
            or run_state.failure_recovery_payload is not None
            or self._queued_turn_payload is not None
        ):
            return
        if not run_state.goal_turn_had_tool_progress:
            session.block_goal(
                "iTE stopped without a successful tool result. Review the latest "
                "response and resume when there is a concrete next action."
            )
            await self._persist_goal_state()
            await self._refresh_goal_surfaces()
            return
        goal.metrics.continuation_count += 1
        self._queued_turn_payload = {
            "message": (
                "Continue the active goal. Take the next highest-value scoped "
                "action, update goal_progress with milestones and proof, and use "
                "goal_outcome only for evidence, a blocker, or final completion."
            ),
            "display_message": "",
            "attachments": [],
            "suppress_user_echo": True,
        }


    async def handle_agent_event(
        self, event: AgentEvent, session_id: str, turn_id: int
    ) -> None:
        run_state = self._run_state(session_id)
        if turn_id != run_state.active_turn_id:
            return
        await self._broadcast_remote_agent_event(session_id, turn_id, event)
        self._record_goal_event_metrics(session_id, event)
        if self._telegram_service is not None and self._telegram_service.running:
            self._telegram_service.set_plan_only(self._is_plan_only_phase())
            self._telegram_service.handle_agent_event(event, session_id, turn_id)
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
            self._start_usage_idle_poll()
            return

        if event.type == AgentEventType.USAGE_UPDATE:
            summary = event.data.get("summary")
            if isinstance(summary, dict):
                self._set_usage_summary_cache(summary)
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
            goal_stopped_for_usage = await self._limit_goal_for_usage_error(
                session_id, error_message
            )
            self._mark_retryable_turn_failure(session_id, error_message)
            scheduled_recovery = False
            should_attempt_recovery = (
                not goal_stopped_for_usage
                and
                run_state.retryable_turn_payload is not None
                and run_state.turn_made_progress
                and run_state.failure_recovery_attempts < 1
            )
            if should_attempt_recovery:
                recovery_payload = self._build_followup_recovery_payload(session_id)
                if recovery_payload is not None:
                    run_state.failure_recovery_payload = recovery_payload
                    run_state.failure_recovery_attempts += 1
                    run_state.silent_recovery_active = True
                    scheduled_recovery = True
                    self._set_loading_state("continuing", busy=True)
                else:
                    retry_payload = self._build_silent_retry_payload(session_id)
                    if retry_payload is not None:
                        run_state.failure_recovery_payload = retry_payload
                        run_state.failure_recovery_attempts += 1
                        run_state.silent_recovery_active = True
                        scheduled_recovery = True
                        self._set_loading_state("continuing", busy=True)
            elif not goal_stopped_for_usage:
                if run_state.retryable_turn_payload is not None:
                    retry_payload = self._build_silent_retry_payload(session_id)
                    if (
                        retry_payload is not None
                        and run_state.failure_recovery_attempts < 1
                    ):
                        run_state.failure_recovery_payload = retry_payload
                        run_state.failure_recovery_attempts += 1
                        run_state.silent_recovery_active = True
                        scheduled_recovery = True
                        self._set_loading_state("continuing", busy=True)
            if not scheduled_recovery:
                if run_state.silent_recovery_active:
                    run_state.silent_recovery_active = False
                    self._set_loading_state("idle", busy=False)
                self.post_system("Error", error_message, is_error=True)
            self.refresh_header()
            self._schedule_usage_meta_refresh_for_cloud_model()
            self._start_usage_idle_poll()
            return

        if event.type == AgentEventType.CONTEXT_COMPACTING:
            self._cancel_activity_resume_timer()
            self._activity_version += 1
            await self._hide_activity_indicator(self._activity_version)
            await self._start_live_compaction_card("Compacting context")
            return

        if event.type == AgentEventType.CONTEXT_COMPACTED:
            auto_resume_required = bool(event.data.get("auto_resume_required", False))
            run_state.context_meter_floor_pct = 100 if auto_resume_required else None
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
        # Mirror the change card to Telegram
        if self._telegram_service is not None and self._telegram_service.running:
            await self._telegram_service.send_turn_change_summary(
                change_set, cwd=self.config.cwd
            )


    async def confirmation_callback(self, confirmation) -> bool:
        body = confirmation.description
        if confirmation.command:
            body += f"\n\n$ {confirmation.command}"
        if confirmation.diff:
            body += f"\n\n{confirmation.diff.to_diff()}"

        modal = ConfirmModal(
            title=f"Approval required: {confirmation.tool_name}",
            body=body,
            yes_label="Approve",
            no_label="Deny",
        )

        remote_server = self._remote_server
        telegram_service = self._telegram_service
        bridge = getattr(self.agent, "open_island_bridge", None)
        should_request_island = bridge is not None and bridge.enabled
        should_request_remote = (
            remote_server is not None
            and remote_server.is_running
            and remote_server.has_authenticated_clients()
            and self.agent
            and self.agent.session
        )
        should_request_telegram = (
            telegram_service is not None
            and telegram_service.running
            and self.agent
            and self.agent.session
        )

        if (
            not should_request_remote
            and not should_request_telegram
            and not should_request_island
        ):
            approved = await self._open_modal(modal)
            return bool(approved)

        request_id = uuid.uuid4().hex
        tasks: list[asyncio.Task[Any]] = [asyncio.create_task(self._open_modal(modal))]
        local_task = tasks[0]

        remote_task = None
        if should_request_remote:
            remote_task = asyncio.create_task(
                remote_server.request_approval(
                    serialize_approval_request(
                        request_id=request_id,
                        tool_name=str(confirmation.tool_name or "tool"),
                        description=str(confirmation.description or ""),
                        command=confirmation.command,
                        diff=confirmation.diff.to_diff() if confirmation.diff else None,
                        session_id=self._active_session_id()
                        or self.agent.session.session_id,
                    )
                )
            )
            tasks.append(remote_task)

        telegram_task = None
        if should_request_telegram:
            async def _telegram_approval():
                try:
                    return await telegram_service.request_confirmation(confirmation)
                except Exception:
                    return None
            telegram_task = asyncio.create_task(_telegram_approval())
            tasks.append(telegram_task)

        island_task = None
        island_bridge = bridge if should_request_island else None
        if island_bridge is not None:
            island_task = asyncio.create_task(
                island_bridge.request_approval(
                    tool_name=str(confirmation.tool_name or "tool"),
                    preview=_island_approval_preview(confirmation),
                    affected_path=_island_affected_path(confirmation),
                )
            )
            tasks.append(island_task)

        def _island_verdict(task: asyncio.Task[Any]) -> bool | None:
            """Normalise the island's tri-state result. None = no answer."""
            try:
                value = task.result()
            except Exception:
                return None
            if value == "approved":
                return True
            if value == "denied":
                return False
            return None

        try:
            pending: set[asyncio.Task[Any]] = set(tasks)
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )

                if local_task in done:
                    approved = bool(local_task.result())
                    if remote_task:
                        await remote_server.resolve_approval_request(
                            request_id, approved
                        )
                        with contextlib.suppress(asyncio.TimeoutError):
                            await asyncio.wait_for(remote_task, timeout=0.5)
                    await self._broadcast_remote_state()
                    return approved

                # A non-local racer answered. The island's "unavailable" is not
                # an answer, so keep waiting for one that is.
                winner: asyncio.Task[Any] | None = None
                approved_external = False
                for task in done:
                    if task is island_task:
                        verdict = _island_verdict(task)
                        if verdict is None:
                            continue
                        winner, approved_external = task, verdict
                        break
                    result = task.result()
                    if result is None:
                        continue
                    winner, approved_external = task, bool(result)
                    break

                if winner is not None:
                    if remote_task is not None and winner is not remote_task:
                        await remote_server.resolve_approval_request(
                            request_id, approved_external
                        )
                    if not local_task.done():
                        modal.dismiss(approved_external)
                        with contextlib.suppress(asyncio.TimeoutError):
                            await asyncio.wait_for(local_task, timeout=0.5)
                    await self._broadcast_remote_state()
                    return approved_external

            # Every external racer declined to answer (island unavailable,
            # remote/Telegram returned None): the local modal decides, exactly
            # as it would with no external racers present.
            return bool(await local_task)
        except Exception:
            if not local_task.done():
                return bool(await local_task)
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()


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
        self._resolve_pending_plan_question(empty=True)
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
        self._send_meta_frame = 0
        await self._clear_inflight_turn_ui(preserve_streaming_message=True)
        self._set_loading_state("idle", busy=False)
        await self._broadcast_remote_state()
