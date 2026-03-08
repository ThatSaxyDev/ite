import json
from datetime import datetime
from ite.client.response import TokenUsage
from ite.tools.base import Tool
from ite.config.config import Config
from dataclasses import field
from typing import Any
from ite.utils.text import count_tokens
from ite.prompts.system import get_system_prompt
from dataclasses import dataclass


@dataclass
class MessageItem:
    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    token_count: int | None = None
    pruned_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"role": self.role}

        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id

        if self.tool_calls:
            result["tool_calls"] = self.tool_calls

        if self.role == "tool":
            # API requires content on tool messages, even if empty
            result["content"] = self.content or ""
        elif self.content or self.tool_calls:
            result["content"] = self.content or ""

        return result


class ContextManager:
    PRUNE_PROTECT_TOKENS = 40_000
    PRUNE_MINIMUM_TOKENS = 10_000
    COMPACTION_MIN_MESSAGES = 8

    def __init__(
        self,
        config: Config,
        user_memory: dict | None = None,
        tools: list[Tool] | None = None,
    ) -> None:
        self.config = config
        self._user_memory = user_memory
        self._tools = tools
        self._model_name = self.config.model_name
        self._messages: list(MessageItem) = []
        self._latest_usage = TokenUsage()
        self._total_usage = TokenUsage()
        self._compaction_count = 0
        self._last_compacted_at: datetime | None = None
        self._pruned_tool_msgs = 0
        self._plan_mode_enabled = False
        self._plan_phase = "idle"

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def total_usage(self) -> TokenUsage:
        return self._total_usage

    @property
    def latest_usage(self) -> TokenUsage:
        return self._latest_usage

    @property
    def compaction_count(self) -> int:
        return self._compaction_count

    @property
    def last_compacted_at(self) -> datetime | None:
        return self._last_compacted_at

    @property
    def pruned_tool_msgs(self) -> int:
        return self._pruned_tool_msgs

    @total_usage.setter
    def total_usage(self, value: TokenUsage) -> None:
        self._total_usage = value

    def set_messages(self, messages: list[dict]) -> None:
        """Restore messages from a saved session snapshot."""
        self._messages = []
        for msg in messages:
            if msg.get("role") == "system":
                continue
            self._messages.append(
                MessageItem(
                    role=msg["role"],
                    content=msg.get("content", ""),
                    tool_call_id=msg.get("tool_call_id"),
                    tool_calls=msg.get("tool_calls", []),
                    token_count=count_tokens(msg.get("content", ""), self._model_name),
                )
            )

    def set_plan_state(self, enabled: bool, phase: str) -> None:
        self._plan_mode_enabled = enabled
        self._plan_phase = phase

    def add_user_message(self, content: str) -> None:
        item = MessageItem(
            role="user",
            content=content,
            token_count=count_tokens(
                content,
                self._model_name,
            ),
        )

        self._messages.append(item)

    def add_assistant_message(
        self, content: str, tool_calls: list[dict[str, Any]] | None = None
    ) -> None:
        item = MessageItem(
            role="assistant",
            content=content or "",
            token_count=count_tokens(
                content or "",
                self._model_name,
            ),
            tool_calls=tool_calls or [],
        )

        self._messages.append(item)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        item = MessageItem(
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            token_count=count_tokens(
                content,
                self._model_name,
            ),
        )

        self._messages.append(item)

    def get_messages(self) -> list(dict[str, Any]):
        messages = []

        system_prompt = get_system_prompt(
            self.config,
            self._user_memory,
            self._tools,
            plan_mode_enabled=self._plan_mode_enabled,
            plan_phase=self._plan_phase,
        )
        if system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        for item in self._messages:
            messages.append(item.to_dict())

        return messages

    def needs_compression(self) -> bool:
        if self.message_count < self.COMPACTION_MIN_MESSAGES:
            return False
        context_limit = self.config.model.context_window
        current_tokens = self.estimate_current_context_tokens()
        return current_tokens > (context_limit * 0.8)

    def set_latest_usage(self, usage: TokenUsage) -> None:
        self._latest_usage = usage

    def add_usage(self, usage: TokenUsage) -> None:
        self._total_usage += usage

    def estimate_current_context_tokens(self) -> int:
        """Best-effort token count for the current message context sent to the model."""
        messages = self.get_messages()
        total = 0
        for msg in messages:
            total += count_tokens(
                json.dumps(msg, ensure_ascii=False),
                self._model_name,
            )
        return total

    def replace_with_summary(self, summary: str) -> None:
        self._messages = []
        self._compaction_count += 1
        self._last_compacted_at = datetime.now()

        continuation_content = f"""# Context Restoration (Previous Session Compacted)

        The previous conversation was compacted due to context length limits. Below is a detailed summary of the work done so far. 

        **CRITICAL: Actions listed under "COMPLETED ACTIONS" are already done. DO NOT repeat them.**

        ---

        {summary}

        ---

        Resume work from where we left off. Focus ONLY on the remaining tasks."""

        summary_item = MessageItem(
            role="user",
            content=continuation_content,
            token_count=count_tokens(continuation_content, self._model_name),
        )
        self._messages.append(summary_item)

        ack_content = """I've reviewed the context from the previous session. I understand:
- The original goal and what was requested
- Which actions are ALREADY COMPLETED (I will NOT repeat these)
- The current state of the project
- What still needs to be done

I'll continue with the REMAINING tasks only, starting from where we left off."""
        ack_item = MessageItem(
            role="assistant",
            content=ack_content,
            token_count=count_tokens(ack_content, self._model_name),
        )
        self._messages.append(ack_item)

        continue_content = (
            "Continue with the REMAINING work only. Do NOT repeat any completed actions. "
            "Proceed with the next step as described in the context above."
        )

        continue_item = MessageItem(
            role="user",
            content=continue_content,
            token_count=count_tokens(continue_content, self._model_name),
        )
        self._messages.append(continue_item)

    def prune_tool_outputs(self) -> int:
        user_message_count = sum(1 for msg in self._messages if msg.role == "user")

        if user_message_count < 2:
            return 0

        total_tokens = 0
        pruned_tokens = 0
        to_prune: list[MessageItem] = []

        for msg in reversed(self._messages):
            if msg.role == "tool" and msg.tool_call_id:
                if msg.pruned_at:
                    break

                tokens = msg.token_count or count_tokens(msg.content, self._model_name)
                total_tokens += tokens

                if total_tokens > self.PRUNE_PROTECT_TOKENS:
                    pruned_tokens += tokens
                    to_prune.append(msg)

        if pruned_tokens < self.PRUNE_MINIMUM_TOKENS:
            return 0

        pruned_count = 0

        for msg in to_prune:
            msg.content = "[Old tool result content cleared]"
            msg.token_count = count_tokens(msg.content, self._model_name)
            msg.pruned_at = datetime.now()
            pruned_count += 1

        self._pruned_tool_msgs += pruned_count
        return pruned_count

    def clear(self) -> None:
        self._messages = []
