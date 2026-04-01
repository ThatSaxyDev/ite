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
from typing import Callable


@dataclass
class MessageItem:
    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_ui: dict[str, Any] | None = None
    subtype: str | None = None
    metadata: dict[str, Any] | None = None
    token_count: int | None = None
    pruned_at: datetime | None = None

    def to_dict(
        self,
        *,
        include_tool_ui: bool = False,
        include_internal_metadata: bool = False,
    ) -> dict[str, Any]:
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

        if include_tool_ui and self.tool_ui and self.role == "tool":
            result["tool_ui"] = self.tool_ui

        if include_internal_metadata:
            if self.subtype:
                result["subtype"] = self.subtype
            if self.metadata:
                result["metadata"] = self.metadata

        return result


class ContextManager:
    PRUNE_PROTECT_TOKENS = 40_000
    PRUNE_MINIMUM_TOKENS = 10_000
    COMPACTION_MIN_MESSAGES = 8
    COMPACTION_TRIGGER_RATIO = 0.65
    COMPACTION_MIN_RESERVE_TOKENS = 12_000
    COMPACTION_PRESERVE_MAX_MESSAGES = 10

    def __init__(
        self,
        config: Config,
        user_memory: dict | None = None,
        tools: list[Tool] | None = None,
        memory_provider: Callable[[str | None], dict | None] | None = None,
        session_memory_provider: Callable[[], str | None] | None = None,
        compact_artifact_provider: Callable[[str | None], str | None] | None = None,
        skill_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self._user_memory = user_memory
        self._tools = tools
        self._memory_provider = memory_provider
        self._session_memory_provider = session_memory_provider
        self._compact_artifact_provider = compact_artifact_provider
        self._skill_provider = skill_provider
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
        skip_restore_triplet = False
        for msg in messages:
            if skip_restore_triplet:
                content = str(msg.get("content", "") or "")
                role = str(msg.get("role", "") or "")
                if role == "assistant" and content.startswith(
                    "I've reviewed the context from the previous session."
                ):
                    continue
                if role == "user" and content.startswith(
                    "Continue with the REMAINING work only."
                ):
                    skip_restore_triplet = False
                    continue
                skip_restore_triplet = False

            if msg.get("role") == "system" and msg.get("subtype") != "compact_boundary":
                continue
            if (
                msg.get("role") == "user"
                and str(msg.get("content", "") or "").startswith(
                    "# Context Restoration (Previous Session Compacted)"
                )
                and self._messages
                and self._messages[-1].role == "system"
                and self._messages[-1].subtype == "compact_boundary"
            ):
                metadata = self._messages[-1].metadata or {}
                artifact_id = str(metadata.get("summary_artifact_id", "")).strip() or None
                artifact_content = (
                    self._compact_artifact_provider(artifact_id)
                    if self._compact_artifact_provider
                    else None
                )
                if artifact_content:
                    self._messages.append(
                        MessageItem(
                            role="system",
                            subtype="compact_artifact",
                            content=(
                                "Compaction summary artifact loaded for session restore.\n\n"
                                + artifact_content
                            ),
                            metadata={"summary_artifact_id": artifact_id},
                            token_count=count_tokens(artifact_content, self._model_name),
                        )
                    )
                    skip_restore_triplet = True
                    continue
            self._messages.append(
                MessageItem(
                    role=msg["role"],
                    content=msg.get("content", ""),
                    tool_call_id=msg.get("tool_call_id"),
                    tool_calls=msg.get("tool_calls", []),
                    tool_ui=msg.get("tool_ui")
                    if isinstance(msg.get("tool_ui"), dict)
                    else None,
                    subtype=str(msg.get("subtype", "")).strip() or None,
                    metadata=msg.get("metadata")
                    if isinstance(msg.get("metadata"), dict)
                    else None,
                    token_count=count_tokens(msg.get("content", ""), self._model_name),
                )
            )
        self._drop_unresolved_tool_calls()

    def set_plan_state(self, enabled: bool, phase: str) -> None:
        self._plan_mode_enabled = enabled
        self._plan_phase = phase

    def add_user_message(self, content: str) -> None:
        # If the previous turn was interrupted mid tool-calling, remove dangling
        # assistant tool-call messages that have no matching tool result(s).
        self._drop_unresolved_tool_calls()

        item = MessageItem(
            role="user",
            content=content,
            token_count=count_tokens(
                content,
                self._model_name,
            ),
        )

        self._messages.append(item)

    def add_system_message(
        self,
        content: str,
        *,
        subtype: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        item = MessageItem(
            role="system",
            content=content,
            subtype=subtype,
            metadata=metadata if isinstance(metadata, dict) else None,
            token_count=count_tokens(
                content,
                self._model_name,
            ),
        )
        self._messages.append(item)

    def _drop_unresolved_tool_calls(self) -> int:
        if not self._messages:
            return 0

        kept: list[MessageItem] = []
        dropped = 0
        i = 0
        n = len(self._messages)

        while i < n:
            msg = self._messages[i]
            if msg.role != "assistant" or not msg.tool_calls:
                kept.append(msg)
                i += 1
                continue

            expected_ids = {
                str(tc.get("id", "")).strip()
                for tc in msg.tool_calls
                if isinstance(tc, dict) and str(tc.get("id", "")).strip()
            }

            j = i + 1
            seen_ids: set[str] = set()
            while j < n and self._messages[j].role == "tool":
                tool_id = (self._messages[j].tool_call_id or "").strip()
                if tool_id:
                    seen_ids.add(tool_id)
                j += 1

            unresolved = bool(expected_ids) and not expected_ids.issubset(seen_ids)
            if unresolved:
                dropped += 1
                if msg.content.strip():
                    msg.tool_calls = []
                    msg.token_count = count_tokens(msg.content, self._model_name)
                    kept.append(msg)
            else:
                kept.append(msg)
            i += 1

        if dropped:
            self._messages = kept
        return dropped

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

    def add_tool_result(
        self,
        tool_call_id: str,
        content: str,
        *,
        tool_ui: dict[str, Any] | None = None,
    ) -> None:
        item = MessageItem(
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            tool_ui=tool_ui,
            token_count=count_tokens(
                content,
                self._model_name,
            ),
        )

        self._messages.append(item)

    def get_messages(self) -> list(dict[str, Any]):
        messages = []

        user_memory = self._user_memory
        if self._memory_provider:
            user_memory = self._memory_provider(self._latest_user_message_text())
        session_memory = (
            self._session_memory_provider() if self._session_memory_provider else None
        )
        skill_context = self._skill_provider() if self._skill_provider else None

        system_prompt = get_system_prompt(
            self.config,
            user_memory,
            tools=self._tools,
            session_memory=session_memory,
            plan_mode_enabled=self._plan_mode_enabled,
            plan_phase=self._plan_phase,
            skill_context=skill_context,
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

    def get_snapshot_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in self._messages:
            if item.role == "system" and item.subtype != "compact_boundary":
                continue
            messages.append(
                item.to_dict(
                    include_tool_ui=True,
                    include_internal_metadata=True,
                )
            )
        return messages

    def _latest_user_message_text(self) -> str | None:
        for item in reversed(self._messages):
            if item.role == "user" and item.content.strip():
                return item.content
        return None

    def get_compaction_status(self) -> dict[str, int | bool]:
        context_limit = self.config.model.context_window
        current_tokens = self.estimate_current_context_tokens()
        ratio_trigger = int(context_limit * self.COMPACTION_TRIGGER_RATIO)
        reserve_trigger = max(
            0,
            context_limit - self.COMPACTION_MIN_RESERVE_TOKENS,
        )
        trigger_at = min(ratio_trigger, reserve_trigger)
        return {
            "message_count": self.message_count,
            "min_messages": self.COMPACTION_MIN_MESSAGES,
            "current_tokens": current_tokens,
            "context_limit": context_limit,
            "ratio_trigger": ratio_trigger,
            "reserve_trigger": reserve_trigger,
            "trigger_at": trigger_at,
            "eligible_by_messages": self.message_count >= self.COMPACTION_MIN_MESSAGES,
            "needs_compression": bool(
                trigger_at > 0
                and self.message_count >= self.COMPACTION_MIN_MESSAGES
                and current_tokens >= trigger_at
            ),
        }

    def needs_compression(self) -> bool:
        status = self.get_compaction_status()
        return bool(status["needs_compression"])

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

    def select_compaction_tail(self, *, max_messages: int | None = None) -> list[dict[str, Any]]:
        non_system = [item for item in self._messages if item.role != "system"]
        if not non_system:
            return []

        limit = max_messages or self.COMPACTION_PRESERVE_MAX_MESSAGES
        start = max(0, len(non_system) - max(1, limit))

        while start > 0 and non_system[start].role == "tool":
            start -= 1

        # Ensure any preserved tool results still have their originating assistant
        # tool-call message in the preserved window.
        while start > 0:
            preserved = non_system[start:]
            expected_ids: set[str] = set()
            seen_ids: set[str] = set()

            for item in preserved:
                if item.role == "assistant" and item.tool_calls:
                    for tool_call in item.tool_calls:
                        if not isinstance(tool_call, dict):
                            continue
                        call_id = str(tool_call.get("id", "")).strip()
                        if call_id:
                            expected_ids.add(call_id)
                elif item.role == "tool":
                    tool_id = str(item.tool_call_id or "").strip()
                    if tool_id:
                        seen_ids.add(tool_id)

            unresolved = bool(seen_ids - expected_ids)
            if not unresolved:
                break
            start -= 1

        return [
            item.to_dict(include_tool_ui=True, include_internal_metadata=True)
            for item in non_system[start:]
        ]

    def replace_with_summary(
        self,
        summary: str,
        *,
        boundary_metadata: dict[str, Any] | None = None,
        preserved_messages: list[dict[str, Any]] | None = None,
    ) -> None:
        self._messages = []
        self._compaction_count += 1
        self._last_compacted_at = datetime.now()
        artifact_id = None

        if boundary_metadata:
            artifact_id = str(boundary_metadata.get("summary_artifact_id", "")).strip() or None
            self.add_system_message(
                "Context compacted; earlier history replaced with continuation summary.",
                subtype="compact_boundary",
                metadata=boundary_metadata,
            )

        if artifact_id:
            self.add_system_message(
                "Compaction summary artifact loaded for live continuation.\n\n" + summary,
                subtype="compact_artifact",
                metadata={"summary_artifact_id": artifact_id},
            )
        else:
            continuation_content = f"""# Context Restoration (Previous Session Compacted)

            The previous conversation was compacted due to context length limits. Below is a detailed summary of the work done so far. 

            **CRITICAL: Actions listed under "COMPLETED ACTIONS" are already done. DO NOT repeat them.**
            **CRITICAL: Do NOT perform git write actions (`git add`, `git commit`, `git push`, tagging, rebasing, or similar) unless the user explicitly asked for that workflow in this thread.**
            **CRITICAL: If the next step appears to be staging, committing, or pushing based only on the summary, stop after implementation/verification and wait for user confirmation instead.**

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

        for msg in preserved_messages or []:
            role = str(msg.get("role", "")).strip()
            if role not in {"user", "assistant", "tool"}:
                continue
            self._messages.append(
                MessageItem(
                    role=role,
                    content=str(msg.get("content", "") or ""),
                    tool_call_id=msg.get("tool_call_id"),
                    tool_calls=list(msg.get("tool_calls") or []),
                    tool_ui=msg.get("tool_ui")
                    if isinstance(msg.get("tool_ui"), dict)
                    else None,
                    subtype=str(msg.get("subtype", "")).strip() or None,
                    metadata=msg.get("metadata")
                    if isinstance(msg.get("metadata"), dict)
                    else None,
                    token_count=count_tokens(
                        str(msg.get("content", "") or ""),
                        self._model_name,
                    ),
                )
            )

        if not artifact_id:
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
