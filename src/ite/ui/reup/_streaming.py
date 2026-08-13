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
from ite.ui.tool_narrative import activity_title, describe_tool_activity, progress_label, tool_icon
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
from ._helpers import _skills_action_title
from .command_views import (
    build_mcp_command_renderable,
    build_memory_command_renderable,
    build_memory_prompt_command_renderable,
    build_sandbox_command_renderable,
    build_stats_command_renderable,
    build_subagent_command_renderable,
    build_todos_command_renderable,
    build_tools_command_renderable,
    build_workboard_command_renderable,
)
from .tool_views import (
    compact_tool_preview_blocks,
    display_path,
    extract_read_file_code,
    format_mcp_identity,
    guess_language,
    normalize_unified_diff_paths,
    render_args_table,
    render_git_log_output,
    render_grep_output,
    render_line_numbered_text,
    render_list_dir_output,
    render_mcp_start_payload,
    render_numbered_unified_diff,
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


class StreamingMixin:
    """Extracted mixin for _streaming."""


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
            self._streaming_widget = Container(
                CopyableMarkdown(""),
                classes="block assistant",
            )
            await conversation.mount(self._streaming_widget)
            self._message_count += 1
            self._refresh_empty_state()
        await self._update_streaming_markdown(self._streaming_buffer)
        await self._pin_activity_indicator_to_end()


    async def finalize_streaming_message(self, final_text: str | None = None) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        rendered_text = final_text if final_text is not None else self._streaming_buffer
        if self._streaming_widget is not None and rendered_text:
            if self._streaming_widget_has_copyable_markdown():
                await self._update_streaming_markdown(rendered_text)
            else:
                # Fallback for older in-flight widgets created before streaming used CopyableMarkdown.
                old_widget = self._streaming_widget
                new_widget = Container(
                    CopyableMarkdown(rendered_text),
                    classes="block assistant",
                )
                try:
                    await old_widget.remove()
                    await conversation.mount(new_widget)
                except Exception:
                    if hasattr(old_widget, "update"):
                        old_widget.update(
                            RichMarkdown(
                                rendered_text,
                                code_theme=self._syntax_theme_name(),
                            )
                        )
            await self._pin_activity_indicator_to_end()
        self._streaming_widget = None
        self._streaming_buffer = ""


    def _streaming_widget_has_copyable_markdown(self) -> bool:
        if self._streaming_widget is None:
            return False
        try:
            self._streaming_widget.query_one(CopyableMarkdown)
            return True
        except Exception:
            return False


    async def _update_streaming_markdown(self, markdown_text: str) -> None:
        if self._streaming_widget is None:
            return
        try:
            markdown_widget = self._streaming_widget.query_one(CopyableMarkdown)
        except Exception:
            if hasattr(self._streaming_widget, "update"):
                code_theme = self._syntax_theme_name()
                self._streaming_widget.update(
                    RichMarkdown(
                        markdown_text,
                        code_theme=code_theme,
                    )
                )
            return
        await markdown_widget.update(markdown_text)


    def _persist_interrupted_streaming_message(self, text: str) -> None:
        content = str(text or "")
        if not content.strip() or not self.agent or not self.agent.session:
            return
        context_manager = self.agent.session.context_manager
        if context_manager is None:
            return
        try:
            messages = context_manager.get_messages()
        except Exception:
            messages = []
        if messages:
            last = messages[-1]
            if (
                last.get("role") == "assistant"
                and str(last.get("content") or "") == content
            ):
                return
        context_manager.add_assistant_message(content)


    async def _clear_inflight_turn_ui(
        self, *, preserve_streaming_message: bool = False
    ) -> None:
        self._resolve_pending_plan_question(empty=True)
        if self._plan_question_card is not None:
            try:
                await self._plan_question_card.remove()
            except Exception:
                pass
            self._plan_question_card = None
            self._message_count = max(0, self._message_count - 1)

        if self._streaming_widget is not None:
            if preserve_streaming_message and self._streaming_buffer.strip():
                interrupted_text = self._streaming_buffer
                await self.finalize_streaming_message()
                self._persist_interrupted_streaming_message(interrupted_text)
            else:
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


    def _user_bubble_width(
        self, message: str, max_width: int = UserMessageRow.BUBBLE_MAX_WIDTH
    ) -> int:
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
        desired_width = self._user_bubble_width(message)
        row = UserMessageRow(
            bubble,
            desired_width=desired_width,
            raw_text=message,
            classes="chat-user-row",
        )
        row.refresh_bubble_width(int(getattr(conversation.size, "width", 0) or 0))
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
                        "specialists": len(sections.get("Subagent Specialists", [])),
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
                        "context_used_pct": float(stats.get("context_used_pct") or 0.0),
                        "context_left_pct": float(stats.get("context_left_pct") or 0.0),
                        "compaction_count": int(stats.get("compaction_count") or 0),
                        "last_compacted_at": str(stats.get("last_compacted_at") or ""),
                        "pruned_tool_msgs": int(stats.get("pruned_tool_msgs") or 0),
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
                        "mcp_failed_servers": int(stats.get("mcp_failed_servers") or 0),
                        "tool_discovery_errors": int(
                            stats.get("tool_discovery_errors") or 0
                        ),
                        "available_skills": int(stats.get("available_skills") or 0),
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
            active_ids = {skill.identifier for skill in session.get_active_skills()}
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
        styles = self._render_styles()
        body: Any | None = None
        css_class: str = "command"
        if command == "/tools":
            body = build_tools_command_renderable(
                session.tool_registry.get_tools(),
                styles=styles,
            )
            css_class = "tools"
        elif command == "/stats":
            body = build_stats_command_renderable(
                session.get_stats(),
                styles=styles,
            )
            css_class = "stats"
        elif command == "/workboard":
            body = build_workboard_command_renderable(
                session,
                styles=styles,
            )
            css_class = "workboard"
        elif command == "/mcp" and (not args or args[0].lower() == "list"):
            body = build_mcp_command_renderable(
                session.mcp_manager.get_all_servers(),
                styles=styles,
            )
            css_class = "mcp"
        elif command == "/todos":
            body = build_todos_command_renderable(
                session,
                styles=styles,
            )
            css_class = "todos"
        elif command == "/subagent" and (not args or args[0].lower() == "list"):
            from ite.tools.subagent import SubagentTool

            tools = session.tool_registry.get_tools()
            subagent_tools = [t for t in tools if isinstance(t, SubagentTool)]
            subagents = [t.definition for t in subagent_tools]
            body = build_subagent_command_renderable(
                subagents,
                styles=styles,
            )
            css_class = "subagents"
        elif command == "/memory":
            manager = MemoryManager(self.config.cwd, session_id=session.session_id)
            if args and args[0].lower() == "prompt":
                query = " ".join(args[1:]).strip()
                if query:
                    css_class = "memory"
                    body = build_memory_prompt_command_renderable(
                        query,
                        manager.debug_prompt_memory(query),
                    )
            else:
                css_class = "memory"
                body = build_memory_command_renderable(
                    session_id=session.session_id,
                    workspace=str(self.config.cwd),
                    controls=manager.load_active_controls(),
                    long_term=manager.list_entries("long_term"),
                    semantic=manager.list_entries("semantic"),
                    short_term=manager.list_entries("short_term"),
                    episodic=manager.list_episodes()[-5:],
                )
        elif command == "/sandbox":
            css_class = "sandbox"
            sandbox_config = self._sandbox_render_config()
            body = build_sandbox_command_renderable(
                enabled=sandbox_config.sandbox.enabled,
                allowed_paths=[str(p) for p in sandbox_config.sandbox.allowed_paths],
                cwd=str(sandbox_config.cwd),
                styles=self._render_styles(),
            )

        if body is None:
            return False

        self.run_worker(
            self.add_assistant_card(command, body, css_class=css_class),
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


    def _shell_card_icon_and_style(
        self,
        metadata: dict[str, Any] | None,
        *,
        success: bool,
    ) -> tuple[str, str]:
        if not success:
            return "❌", f"bold {self._style('error')}"
        state = shell_session_state(metadata)
        if state == "command_running":
            return "⌛", f"bold {self._style('primary')}"
        if state == "idle":
            return "💤", f"bold {self._style('muted')}"
        if state == "stopped":
            return "⏹", f"bold {self._style('muted')}"
        if state == "exited":
            return "▫️", f"bold {self._style('secondary')}"
        return "▫️", f"bold {self._style('secondary')}"


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

        return tool_icon(name), f"bold {self._style('fg')}"

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
            "read_document",
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
            "read_document": {"Parameter 'path': Field required"},
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
            "skills": {
                "Parameter '': Value error, skill is required for show, activate, and deactivate"
            },
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
        was_awaiting_shell_input = self._active_shell_input_call_id() is not None
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

        is_awaiting_shell_input = self._active_shell_input_call_id() is not None
        if is_awaiting_shell_input:
            self._set_loading_state("waiting on shell", busy=True)
        else:
            self._set_loading_state("idle", busy=False)
        if was_awaiting_shell_input != is_awaiting_shell_input:
            await self._broadcast_remote_state()


    async def _move_card_to_bottom(self, card: Widget) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        try:
            await card.remove()
        except Exception:
            pass
        await conversation.mount(card)


    async def _stack_completed_tool_card(self, card: CompactToolCard) -> None:
        if not card.stack_key:
            return
        parent = card.parent
        if isinstance(parent, Vertical) and parent.has_class("tool-stack-body"):
            stack = parent.parent
            if isinstance(stack, ToolCardStack):
                first_child = next(
                    (
                        child
                        for child in parent.children
                        if isinstance(child, CompactToolCard)
                    ),
                    None,
                )
                if first_child is card:
                    stack.refresh_title(card.plural_stack_title())
                else:
                    stack._refresh_content()
            return

        conversation = self.query_one("#conversation", VerticalScroll)
        siblings = list(conversation.children)
        try:
            index = siblings.index(card)
        except ValueError:
            return
        if index <= 0:
            return

        previous = siblings[index - 1]
        if isinstance(previous, ToolCardStack):
            if previous.stack_key != card.stack_key:
                return
            await previous.add_card(card)
            self._message_count = max(0, self._message_count - 1)
            return

        if not isinstance(previous, CompactToolCard):
            return
        if previous.stack_key != card.stack_key or not previous.has_completed_content:
            return

        stack = ToolCardStack(
            stack_key=card.stack_key,
            title=previous.plural_stack_title(),
            classes="block tool tool-stack success",
        )
        after_widget = siblings[index + 1] if index + 1 < len(siblings) else None
        await previous.remove()
        await card.remove()
        if after_widget is not None:
            await conversation.mount(stack, before=after_widget)
        else:
            await conversation.mount(stack)
        await stack.add_card(previous)
        await stack.add_card(card)
        self._message_count = max(0, self._message_count - 1)


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
            card = CompactToolCard(classes="block tool mcp-card running")
        else:
            card = CompactToolCard(classes="block tool running")
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
                    theme_variables=self._theme_tokens(),
                )
            )
        elif arguments:
            blocks.append(
                render_args_table(
                    name,
                    arguments,
                    cwd=self.config.cwd,
                    theme_variables=self._theme_tokens(),
                )
            )
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
                        theme_variables=self._theme_tokens(),
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
            header.append("⌛ ", style=f"bold {self._style('primary')}")
            header.append(title_text, style=f"bold {self._style('fg')}")
            header.append("  running", style=self._render_styles()["muted"])
            card.update(header)
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
            ""
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
        elif name in {"read_pdf", "read_document", "read_image"} and success:
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
                pdf_type = str(md.get("pdf_type") or "").strip()
                if pdf_type:
                    summary_parts.append(pdf_type)
                else:
                    quality = str(md.get("text_extraction_quality") or "").strip()
                    if quality:
                        summary_parts.append(quality)
            elif name == "read_document":
                fmt = str(md.get("format") or "").strip()
                if fmt:
                    summary_parts.append(fmt)
                text_length = md.get("text_length")
                if isinstance(text_length, int):
                    summary_parts.append(f"{text_length} chars")
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

        if isinstance(card, CompactToolCard):
            default_expanded = not success or recoverable
            expanded = card.expanded if card.has_completed_content else default_expanded
            card.stack_key = f"{tool_kind or 'builtin'}:{name}:{title_text}"
            card.set_tool_content(
                header=header,
                compact_blocks=compact_tool_preview_blocks(
                    blocks,
                    theme_variables=self._theme_tokens(),
                ),
                full_blocks=blocks,
                expanded=expanded,
            )
        else:
            card.update(Group(header, *blocks))
        card.remove_class("running")
        if success:
            card.add_class("success")
        else:
            card.add_class("error")

        if isinstance(card, CompactToolCard) and success and not recoverable:
            await self._stack_completed_tool_card(card)

        if pin_after_update:
            await self._pin_activity_indicator_to_end()

