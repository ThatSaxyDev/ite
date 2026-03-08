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


class Session:
    def __init__(
        self,
        config: Config,
    ):
        self.config = config
        self.client = LLMClient(config=self.config)
        self.tool_registry = create_default_registry(config)
        self.context_manager: ContextManager | None = None
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
        self.session_id = str(uuid.uuid4())
        self.name: str | None = None
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.plan_mode_enabled: bool = False
        self.plan_phase: str = "idle"
        self.plan_questions_asked: int = 0
        self.plan_target_questions: int = 3

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
        )
        self.context_manager.set_plan_state(self.plan_mode_enabled, self.plan_phase)

    def _load_memory(self) -> dict | None:
        from ite.tools.builtin.memory import MemoryTool

        memory = MemoryTool.load_all_memory(str(self.config.cwd))

        # Return None if all stores are empty
        has_data = (
            memory.get("long_term")
            or memory.get("short_term")
            or memory.get("episodic")
            or memory.get("semantic")
        )
        return memory if has_data else None

    def increment_turn(self) -> int:
        self._turn_count += 1
        self.updated_at = datetime.now()

        return self._turn_count

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
            "tools_enabled": len(self.tool_registry.get_tools()),
            "mcp_servers": len(self.tool_registry.connected_mcp_servers),
        }
