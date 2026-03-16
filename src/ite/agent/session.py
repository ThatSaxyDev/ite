from typing import Any
from ite.context.loop_detector import LoopDetector
from ite.safety.approval import ApprovalManager
from ite.context.compaction import ChatCompactor
from ite.tools.mcp.mcp_manager import MCPManager
from ite.tools.discovery import ToolDiscoveryManager
from datetime import datetime
import uuid
from ite.tools.registry import create_default_registry
from ite.context.manager import ContextManager
from ite.client.llm_client import LLMClient
from ite.config.config import Config
from ite.hooks.hook_system import HookSystem
from ite.memory import MemoryManager, is_memory_probe, parse_explicit_memory_instruction
from ite.tools.builtin.memory import MemoryTool
from ite.tools.builtin.todo import TodosTool


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
        self.memory_manager = MemoryManager(self.config.cwd, session_id=self.session_id)
        self._sync_memory_tool_session()
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

        self._turn_count = 0

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @turn_count.setter
    def turn_count(self, value: int) -> None:
        self._turn_count = value

    async def initialize(self) -> None:
        await self.mcp_manager.initialize()
        self.mcp_manager.register_tools(self.tool_registry)
        self.discovery_manager.discover_all()
        self.context_manager = ContextManager(
            config=self.config,
            user_memory=self._load_memory(),
            tools=self.tool_registry.get_tools(),
            memory_provider=self._load_prompt_memory,
        )
        self.context_manager.set_plan_state(self.plan_mode_enabled, self.plan_phase)

    def _load_memory(self) -> dict | None:
        return self._load_prompt_memory(None)

    def _load_prompt_memory(self, current_user_text: str | None) -> dict | None:
        return self.memory_manager.load_prompt_memory(current_user_text)

    def set_session_id(self, session_id: str) -> None:
        self.session_id = session_id
        self.memory_manager.set_session_id(session_id)
        self._sync_memory_tool_session()

    def _sync_memory_tool_session(self) -> None:
        tool = self.tool_registry.get("memory")
        if isinstance(tool, MemoryTool):
            tool.set_session_id(self.session_id)

    def increment_turn(self) -> int:
        self._turn_count += 1
        self.updated_at = datetime.now()

        return self._turn_count

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
            "mcp_servers": len(self.tool_registry.connected_mcp_servers),
            "tool_discovery_errors": len(self.discovery_manager.errors),
        }

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
