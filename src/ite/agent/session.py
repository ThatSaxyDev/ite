from typing import Any
from ite.context.compact_artifacts import CompactArtifactManager
from ite.context.loop_detector import LoopDetector
from ite.safety.approval import ApprovalManager
from ite.context.compaction import ChatCompactor
from ite.tools.mcp.mcp_manager import MCPManager
from ite.tools.discovery import ToolDiscoveryManager
from datetime import datetime
import uuid
from ite.tools.registry import create_default_registry
from ite.tools.registry import refresh_subagent_tools
from ite.context.manager import ContextManager
from ite.client.llm_client import LLMClient
from ite.config.config import Config
from ite.hooks.hook_system import HookSystem
from ite.memory import MemoryManager, is_memory_probe, parse_explicit_memory_instruction
from ite.memory.session_memory import SessionMemoryManager
from ite.tools.builtin.memory import MemoryTool
from ite.tools.builtin.skills import SkillsTool
from ite.tools.builtin.subagent_runtime_tools import CancelSubagentTool
from ite.tools.builtin.subagent_runtime_tools import ListSubagentsTool
from ite.tools.builtin.subagent_runtime_tools import SpawnSubagentTool
from ite.tools.builtin.subagent_runtime_tools import SpawnSubagentsTool
from ite.tools.builtin.subagent_runtime_tools import SubagentMetricsTool
from ite.tools.builtin.subagent_runtime_tools import WaitSubagentTool
from ite.tools.builtin.todo import TodosTool
from ite.agent.change_history import ChangeHistory
from ite.agent.subagent_runtime import SubagentRuntime
from ite.skills import SkillDefinition
from ite.skills import SkillManager
from ite.skills import SkillTrustManager
from dataclasses import dataclass, field


@dataclass
class RuntimeIssue:
    component: str
    severity: str
    message: str
    details: str


@dataclass
class RuntimeStatus:
    degraded: bool = False
    issues: list[RuntimeIssue] = field(default_factory=list)
    disabled_capabilities: list[str] = field(default_factory=list)


class Session:
    def __init__(
        self,
        config: Config,
    ):
        self.config = config
        self.client = LLMClient(config=self.config)
        self.session_id = str(uuid.uuid4())
        self.tool_registry = create_default_registry(config)
        self.context_manager: ContextManager | None = None
        self.compact_artifact_manager = CompactArtifactManager(self.session_id)
        self.memory_manager = MemoryManager(self.config.cwd, session_id=self.session_id)
        self.session_memory_manager = SessionMemoryManager(
            self.config.cwd,
            session_id=self.session_id,
        )
        self.skill_trust_manager = SkillTrustManager()
        self.skill_manager = SkillManager(self.config.cwd, trust_manager=self.skill_trust_manager)
        self.active_skill_refs: list[str] = []
        self._sync_memory_tool_session()
        self._sync_skills_tool_session()
        self.subagent_runtime = SubagentRuntime(
            config=self.config,
            session_id=self.session_id,
            tool_registry=self.tool_registry,
        )
        self._sync_subagent_runtime_tools()
        self.discovery_manager = ToolDiscoveryManager(
            self.config,
            self.tool_registry,
        )
        self.mcp_manager = MCPManager(self.config)
        self.chat_compactor = ChatCompactor(self.client)
        self.approval_manager = ApprovalManager(
            self.config.approval,
            self.config.cwd,
        )
        self.loop_detector = LoopDetector()
        self.hook_system = HookSystem(self.config)
        self.name: str | None = None
        self.name_source: str | None = None
        self.name_locked: bool = False
        self.name_last_generated_turn: int = 0
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.plan_mode_enabled: bool = False
        self.plan_phase: str = "idle"
        self.plan_questions_asked: int = 0
        self.plan_target_questions: int = 3
        self.pending_plan_text: str | None = None
        self.active_plan_text: str | None = None
        self.todo_execution_handoff_active: bool = False
        self.show_planning_todos: bool = False
        self.planning_seed_ids: list[str] = []
        self.execution_seed_ids: list[str] = []
        self.pending_attachment_paths: list[str] = []
        self.change_history = ChangeHistory(self.config.cwd)
        self.runtime_status = RuntimeStatus()

        self._turn_count = 0

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @turn_count.setter
    def turn_count(self, value: int) -> None:
        self._turn_count = value

    async def initialize(self) -> None:
        self.runtime_status = RuntimeStatus()

        try:
            await self.mcp_manager.initialize()
            self.mcp_manager.register_tools(self.tool_registry)
            if self.mcp_manager.all_startup_servers_failed:
                self._record_runtime_issue(
                    component="mcp",
                    capability="mcp",
                    message="MCP unavailable; continuing without external MCP tools.",
                    details=(
                        f"Configured {self.mcp_manager.startup_server_count} startup server(s); "
                        f"0 connected."
                    ),
                )
        except Exception as exc:
            self._record_runtime_issue(
                component="mcp",
                capability="mcp",
                message="MCP unavailable; continuing without external MCP tools.",
                details=str(exc),
            )

        user_memory: dict | None = None
        try:
            user_memory = self._load_memory()
        except Exception as exc:
            self._record_runtime_issue(
                component="memory",
                capability="persistent_memory",
                message="Persistent memory unavailable; continuing with empty prompt memory.",
                details=str(exc),
            )

        if self.memory_manager.degraded_mode:
            self._record_runtime_issue(
                component="memory",
                capability="persistent_memory",
                message="Persistent memory unavailable; using in-memory fallback for this session.",
                details=self.memory_manager.degraded_reason or "memory manager degraded",
            )

        self.discovery_manager.discover_all()
        refresh_subagent_tools(self.tool_registry, self.config)
        self.skill_manager.discover()
        self.restore_active_skills(self.active_skill_refs)
        self.context_manager = ContextManager(
            config=self.config,
            user_memory=user_memory,
            tools=self.tool_registry.get_tools(),
            memory_provider=self._load_prompt_memory,
            session_memory_provider=self._load_session_memory,
            compact_artifact_provider=self._load_compact_artifact,
            skill_provider=self._load_skill_context,
        )
        self.context_manager.set_plan_state(self.plan_mode_enabled, self.plan_phase)

    def _load_memory(self) -> dict | None:
        return self._load_prompt_memory(None)

    def _load_prompt_memory(self, current_user_text: str | None) -> dict | None:
        return self.memory_manager.load_prompt_memory(current_user_text)

    def _load_session_memory(self) -> str | None:
        return self.session_memory_manager.get_content()

    def _load_compact_artifact(self, artifact_id: str | None) -> str | None:
        return self.compact_artifact_manager.load_summary(artifact_id)

    def _load_skill_context(self) -> dict[str, Any]:
        remaining_reference_chars = 6000
        active_entries: list[dict[str, Any]] = []
        for skill in self.get_active_skills():
            loaded_refs = self.skill_manager.load_reference_context(
                skill,
                max_chars=remaining_reference_chars,
            )
            remaining_reference_chars -= sum(len(item["content"]) for item in loaded_refs)
            active_entries.append(
                {
                    "identifier": skill.identifier,
                    "name": skill.name,
                    "description": skill.description,
                    "instructions": skill.instructions,
                    "source": skill.source,
                    "directory": str(skill.directory),
                    "skill_file": str(skill.skill_file),
                    "user_invocable": skill.user_invocable,
                    "argument_hint": skill.argument_hint or "",
                    "reference_files": list(skill.reference_files),
                    "loaded_references": loaded_refs,
                    "trusted": skill.trusted,
                }
            )
        return {
            "catalog": self.list_available_skills(),
            "active": active_entries,
        }

    def set_session_id(self, session_id: str) -> None:
        self.session_id = session_id
        self.compact_artifact_manager.set_session_id(session_id)
        self.memory_manager.set_session_id(session_id)
        self.session_memory_manager.set_session_id(session_id)
        self._sync_memory_tool_session()
        self._sync_skills_tool_session()
        self.subagent_runtime.session_id = session_id
        self._sync_subagent_runtime_tools()

    def is_degraded(self) -> bool:
        return self.runtime_status.degraded

    def runtime_summary(self) -> str:
        if not self.runtime_status.degraded:
            return ""

        parts = []
        if "persistent_memory" in self.runtime_status.disabled_capabilities:
            parts.append("persistent memory unavailable")
        if "mcp" in self.runtime_status.disabled_capabilities:
            parts.append("MCP unavailable")

        if not parts:
            parts = [issue.message.rstrip(".") for issue in self.runtime_status.issues[:2]]
        return "Running in degraded mode: " + "; ".join(parts) + "."

    def _record_runtime_issue(
        self,
        *,
        component: str,
        capability: str,
        message: str,
        details: str,
        severity: str = "warning",
    ) -> None:
        if any(
            issue.component == component and issue.message == message
            for issue in self.runtime_status.issues
        ):
            return

        self.runtime_status.degraded = True
        if capability not in self.runtime_status.disabled_capabilities:
            self.runtime_status.disabled_capabilities.append(capability)
        self.runtime_status.issues.append(
            RuntimeIssue(
                component=component,
                severity=severity,
                message=message,
                details=details,
            )
        )

    def _sync_memory_tool_session(self) -> None:
        tool = self.tool_registry.get("memory")
        if isinstance(tool, MemoryTool):
            tool.set_session_id(self.session_id)

    def _sync_skills_tool_session(self) -> None:
        tool = self.tool_registry.get("skills")
        if isinstance(tool, SkillsTool):
            tool.set_session(self)

    def _sync_subagent_runtime_tools(self) -> None:
        for name in (
            "spawn_subagent",
            "spawn_subagents",
            "wait_subagent",
            "list_subagents",
            "cancel_subagent",
            "subagent_metrics",
        ):
            tool = self.tool_registry.get(name)
            if isinstance(
                tool,
                (
                    SpawnSubagentTool,
                    SpawnSubagentsTool,
                    WaitSubagentTool,
                    ListSubagentsTool,
                    CancelSubagentTool,
                    SubagentMetricsTool,
                ),
            ):
                tool.set_runtime(self.subagent_runtime)

    def increment_turn(self) -> int:
        self._turn_count += 1
        self.updated_at = datetime.now()

        return self._turn_count

    def set_auto_name(self, name: str) -> None:
        normalized = (name or "").strip()
        if not normalized or self.name_locked:
            return
        self.name = normalized
        self.name_source = "auto"
        self.name_last_generated_turn = self.turn_count
        self.updated_at = datetime.now()

    def set_manual_name(self, name: str) -> None:
        normalized = (name or "").strip()
        if not normalized:
            return
        self.name = normalized
        self.name_source = "manual"
        self.name_locked = True
        self.updated_at = datetime.now()

    def should_refresh_auto_name(self) -> bool:
        return (
            bool(self.name)
            and self.name_source == "auto"
            and not self.name_locked
            and self.turn_count >= 3
            and self.name_last_generated_turn < 3
        )

    def name_generation_context(self) -> dict[str, str]:
        first_user = ""
        first_assistant = ""
        latest_user = ""
        if self.context_manager:
            for msg in self.context_manager.get_messages():
                if msg.get("role") == "user":
                    content = str(msg.get("content", "") or "").strip()
                    if content and not first_user:
                        first_user = content[:200]
                    if content:
                        latest_user = content[:200]
                elif msg.get("role") == "assistant" and first_user and not first_assistant:
                    content = str(msg.get("content", "") or "").strip()
                    if content:
                        first_assistant = content[:200]
        return {
            "first_user": first_user,
            "first_assistant": first_assistant,
            "latest_user": latest_user,
            "focus_hint": self._derive_current_focus()[:200],
        }

    def snapshot_kwargs(self, *, workspace_path: str) -> dict[str, Any]:
        self.session_memory_manager.refresh_from_session(self)
        return {
            "session_id": self.session_id,
            "name": self.name,
            "name_source": self.name_source,
            "name_locked": self.name_locked,
            "name_last_generated_turn": self.name_last_generated_turn,
            "workspace_path": workspace_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turn_count": self.turn_count,
            "messages": self.context_manager.get_snapshot_messages(),
            "total_usage": self.context_manager.total_usage,
            "plan_mode_enabled": self.plan_mode_enabled,
            "plan_phase": self.plan_phase,
            "plan_questions_asked": self.plan_questions_asked,
            "plan_target_questions": self.plan_target_questions,
            "pending_plan_text": self.pending_plan_text,
            "active_plan_text": self.active_plan_text,
            "active_skills": list(self.active_skill_refs),
            "todos_state": self.export_todos_state(),
            "show_planning_todos": self.show_planning_todos,
            "change_history_state": self.export_change_history_state(),
            "subagent_runtime_state": self.export_subagent_runtime_state(),
        }

    def export_subagent_runtime_state(self) -> dict[str, Any]:
        return self.subagent_runtime.export_state()

    def restore_subagent_runtime_state(self, state: dict[str, Any] | None) -> None:
        self.subagent_runtime.restore_state(state)
        self._sync_subagent_runtime_tools()

    def record_lifecycle_episode(self, summary: str, *, source: str) -> None:
        self.memory_manager.append_episode(
            summary,
            detail=summary,
            source=source,
            session_id=self.session_id,
        )

    def build_lifecycle_summary(self, event: str, focus_hint: str | None = None) -> str:
        focus = (focus_hint or "").strip() or self._derive_current_focus()
        if focus:
            return f"{event}: {focus}"
        return event

    def _derive_current_focus(self) -> str:
        plan_text = (self.current_plan_text() or "").strip()
        if plan_text:
            first = self._first_meaningful_line(plan_text)
            if first:
                return first

        todos_state = self.export_todos_state()
        execution = todos_state.get("execution", []) if isinstance(todos_state, dict) else []
        if isinstance(execution, list):
            for entry in execution:
                if not isinstance(entry, dict):
                    continue
                if not bool(entry.get("completed", False)):
                    content = str(entry.get("content", "")).strip()
                    if content:
                        return content

        recent_user = self._latest_user_message_text()
        if recent_user:
            if parse_explicit_memory_instruction(recent_user) is not None:
                return ""
            if is_memory_probe(recent_user):
                return ""
            if self._is_low_value_lifecycle_focus(recent_user):
                return ""
            return recent_user

        return ""

    def _is_low_value_lifecycle_focus(self, text: str) -> bool:
        lowered = text.strip().lower()
        if not lowered:
            return True

        low_value_prefixes = (
            "what are",
            "how do i",
            "how should you",
            "what should you",
            "what did we",
            "what phrase",
            "what is this",
            "tell me about",
        )
        if lowered.startswith(low_value_prefixes):
            return True

        low_value_fragments = (
            "responses",
            "phrase",
            "remember",
            "memory",
            "focused on right now",
            "last time",
        )
        return any(fragment in lowered for fragment in low_value_fragments)

    def _latest_user_message_text(self) -> str:
        if not self.context_manager:
            return ""
        messages = self.context_manager.get_messages()
        for message in reversed(messages):
            if message.get("role") == "user":
                content = str(message.get("content", "")).strip()
                if content:
                    return content
        return ""

    def _first_meaningful_line(self, text: str) -> str:
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            if line.startswith(("- ", "* ")):
                return line[2:].strip()
            parts = line.split(".", 1)
            if len(parts) == 2 and parts[0].isdigit():
                return parts[1].strip()
            return line
        return ""

    def set_plan_mode(self, enabled: bool) -> None:
        self.plan_mode_enabled = enabled
        if enabled:
            # Enabling plan mode always starts a fresh planning cycle.
            self.plan_questions_asked = 0
            self.plan_target_questions = 3
            if self.plan_phase == "executing":
                self.plan_phase = "idle"
        else:
            self.plan_phase = "idle"
            self.plan_questions_asked = 0
            self.plan_target_questions = 3
        if self.context_manager:
            self.context_manager.set_plan_state(self.plan_mode_enabled, self.plan_phase)

    def set_plan_phase(self, phase: str) -> None:
        self.plan_phase = phase
        if self.context_manager:
            self.context_manager.set_plan_state(self.plan_mode_enabled, self.plan_phase)

    def increment_plan_questions(self) -> None:
        self.plan_questions_asked += 1

    def set_pending_plan(self, plan_text: str) -> None:
        text = plan_text.strip()
        self.pending_plan_text = text if text else None

    def clear_pending_plan(self) -> None:
        self.pending_plan_text = None

    def has_pending_plan(self) -> bool:
        return bool(self.pending_plan_text and self.pending_plan_text.strip())

    def set_active_plan(self, plan_text: str) -> None:
        text = plan_text.strip()
        self.active_plan_text = text if text else None

    def clear_active_plan(self) -> None:
        self.active_plan_text = None

    def has_active_plan(self) -> bool:
        return bool(self.active_plan_text and self.active_plan_text.strip())

    def current_plan_text(self) -> str | None:
        if self.has_pending_plan():
            return self.pending_plan_text
        if self.has_active_plan():
            return self.active_plan_text
        return None

    def promote_pending_plan_to_active(self) -> None:
        text = (self.pending_plan_text or "").strip()
        if text:
            self.active_plan_text = text
        self.pending_plan_text = None

    def get_stats(self) -> dict[str, Any]:
        latest = self.context_manager.latest_usage
        total = self.context_manager.total_usage
        context_window = self.config.model.context_window
        context_tokens = self.context_manager.estimate_current_context_tokens()
        used_pct = (context_tokens / context_window * 100) if context_window else 0.0
        left_pct = max(0.0, 100.0 - used_pct)

        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "turn_count": self._turn_count,
            "message_count": self.context_manager.message_count,
            "token_usage": total,
            "context_window": context_window,
            "latest_tokens": context_tokens,
            "latest_cached_tokens": latest.cached_tokens,
            "context_used_pct": round(used_pct, 1),
            "context_left_pct": round(left_pct, 1),
            "compaction_count": self.context_manager.compaction_count,
            "last_compacted_at": (
                self.context_manager.last_compacted_at.isoformat()
                if self.context_manager.last_compacted_at
                else None
            ),
            "pruned_tool_msgs": self.context_manager.pruned_tool_msgs,
            "plan_mode_enabled": self.plan_mode_enabled,
            "plan_phase": self.plan_phase,
            "plan_questions_asked": self.plan_questions_asked,
            "plan_target_questions": self.plan_target_questions,
            "pending_plan_available": self.has_pending_plan(),
            "active_plan_available": self.has_active_plan(),
            "pending_attachments": len(self.pending_attachment_paths),
            "tools_enabled": len(self.tool_registry.get_tools()),
            "mcp_servers": self.mcp_manager.connected_server_count,
            "mcp_tools": self.tool_registry.mcp_tool_count,
            "mcp_failed_servers": self.mcp_manager.failed_server_count,
            "tool_discovery_errors": len(self.discovery_manager.errors),
            "available_skills": len(self.list_available_skills()),
            "active_skills": len(self.get_active_skills()),
        }

    def refresh_skills(self) -> None:
        self.skill_manager = SkillManager(self.config.cwd, trust_manager=self.skill_trust_manager)
        self.skill_manager.discover()
        self.active_skill_refs = [
            ref for ref in self.active_skill_refs if self.skill_manager.get(ref) is not None
        ]
        self._sync_skills_tool_session()

    def list_available_skills(self) -> list[dict[str, str]]:
        return self.skill_manager.summaries()

    def resolve_skill(self, reference: str) -> SkillDefinition | None:
        return self.skill_manager.get(reference)

    def get_active_skills(self) -> list[SkillDefinition]:
        active: list[SkillDefinition] = []
        seen: set[str] = set()
        for ref in self.active_skill_refs:
            skill = self.skill_manager.get(ref)
            if skill is None or skill.identifier in seen:
                continue
            active.append(skill)
            seen.add(skill.identifier)
        return active

    def activate_skill(self, reference: str) -> SkillDefinition | None:
        skill = self.resolve_skill(reference)
        if skill is None or (skill.requires_trust and not skill.trusted):
            return None
        if skill.identifier not in self.active_skill_refs:
            self.active_skill_refs.append(skill.identifier)
        return skill

    def deactivate_skill(self, reference: str) -> SkillDefinition | None:
        skill = self.resolve_skill(reference)
        if skill is None or skill.identifier not in self.active_skill_refs:
            return None
        self.active_skill_refs = [
            ref for ref in self.active_skill_refs if ref != skill.identifier
        ]
        return skill

    def clear_active_skills(self) -> None:
        self.active_skill_refs = []

    def restore_active_skills(self, skill_refs: list[str] | None) -> None:
        self.active_skill_refs = []
        for ref in skill_refs or []:
            skill = self.resolve_skill(ref)
            if (
                skill is not None
                and (not skill.requires_trust or skill.trusted)
                and skill.identifier not in self.active_skill_refs
            ):
                self.active_skill_refs.append(skill.identifier)

    def trust_skill_workspace(self) -> None:
        self.skill_trust_manager.trust_workspace(self.config.cwd)
        self.refresh_skills()

    def untrust_skill_workspace(self) -> None:
        self.skill_trust_manager.untrust_workspace(self.config.cwd)
        self.clear_active_skills()
        self.refresh_skills()

    def _get_todos_tool(self) -> TodosTool | None:
        tool = self.tool_registry.get("todos")
        if isinstance(tool, TodosTool):
            return tool
        return None

    def export_todos_state(self) -> dict[str, Any]:
        tool = self._get_todos_tool()
        if tool is None:
            return {"version": 1, "planning": [], "execution": []}
        return tool.export_state()

    def restore_todos_state(self, state: dict[str, Any] | None) -> None:
        tool = self._get_todos_tool()
        if tool is None:
            return
        tool.load_state(state)

    def export_change_history_state(self) -> dict[str, Any]:
        return self.change_history.export_state()

    def restore_change_history_state(self, state: dict[str, Any] | None) -> None:
        self.change_history.load_state(state)

    def seed_execution_todos_from_plan(self, plan_text: str | None) -> list[str]:
        tool = self._get_todos_tool()
        if tool is None:
            return []

        items: list[str] = []
        text = (plan_text or "").strip()
        for raw in text.splitlines():
            if raw.startswith((" ", "\t")):
                # Skip nested list lines; keep top-level milestones only.
                continue
            line = raw.strip()
            if not line:
                continue
            if line.startswith(("- ", "* ")):
                item = line[2:].strip()
            else:
                marker = line.split(".", 1)
                if len(marker) == 2 and marker[0].isdigit():
                    item = marker[1].strip()
                else:
                    continue
            if len(item) < 4:
                continue
            if item in items:
                continue
            items.append(item)
            if len(items) >= 6:
                break

        if not items:
            items = [
                "Implement approved plan changes",
                "Run verification and tests",
                "Summarize outcome and modified files",
            ]
        else:
            lowered = [i.lower() for i in items]
            if not any(
                ("test" in i)
                or ("lint" in i)
                or ("build" in i)
                or ("verification" in i)
                or ("validate" in i)
                for i in lowered
            ):
                items.append("Run verification checks (tests/lint/build as applicable)")
            if not any(
                ("summary" in i)
                or ("summarize" in i)
                or ("outcome" in i)
                or ("changed file" in i)
                for i in lowered
            ):
                items.append("Summarize outcome and changed files")
            items = items[:7]

        ids = tool.replace_scope_items("execution", items)
        self.execution_seed_ids = list(ids)
        return ids
