import json
from datetime import datetime
from ite.client.response import TokenUsage
from ite.tools.base import Tool
from ite.config.config import Config
from typing import Any
from ite.utils.text import count_tokens
from ite.prompts.system import get_system_prompt
from typing import Callable
from ite.context.transcript import ConversationLog, MessageItem


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
        self._conversation_log = ConversationLog()
        self._latest_usage = TokenUsage()
        self._total_usage = TokenUsage()
        self._compaction_count = 0
        self._last_compacted_at: datetime | None = None
        self._pruned_tool_msgs = 0
        self._plan_mode_enabled = False
        self._plan_phase = "idle"

    @property
    def message_count(self) -> int:
        return len(self._message_items())

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
        restored_items: list[MessageItem] = []
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
                and restored_items
                and restored_items[-1].role == "system"
                and restored_items[-1].subtype == "compact_boundary"
            ):
                metadata = restored_items[-1].metadata or {}
                artifact_id = str(metadata.get("summary_artifact_id", "")).strip() or None
                artifact_content = (
                    self._compact_artifact_provider(artifact_id)
                    if self._compact_artifact_provider
                    else None
                )
                if artifact_content:
                    restored_items.append(
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
            restored_items.append(
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
        self._conversation_log.replace_messages(restored_items)
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

        self._conversation_log.append(item)

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
        self._conversation_log.append(item)

    def _drop_unresolved_tool_calls(self) -> int:
        message_items = self._message_items()
        if not message_items:
            return 0

        kept: list[MessageItem] = []
        dropped = 0
        i = 0
        n = len(message_items)

        while i < n:
            msg = message_items[i]
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
            while j < n and message_items[j].role == "tool":
                tool_id = (message_items[j].tool_call_id or "").strip()
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
            self._conversation_log.replace_messages(kept)
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

        self._conversation_log.append(item)

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

        self._conversation_log.append(item)

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

        for item in self._message_items():
            messages.append(item.to_dict())

        return messages

    def get_snapshot_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in self._message_items():
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
        for item in reversed(self._message_items()):
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
        non_system = [item for item in self._message_items() if item.role != "system"]
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
        pre_compaction_events = self._conversation_log.event_count()
        replacement_items: list[MessageItem] = []
        self._compaction_count += 1
        self._last_compacted_at = datetime.now()
        artifact_id = None

        if boundary_metadata:
            artifact_id = str(boundary_metadata.get("summary_artifact_id", "")).strip() or None
            boundary_metadata = dict(boundary_metadata)
            boundary_metadata.setdefault(
                "preserved_tail_messages",
                len(preserved_messages or []),
            )
            boundary_metadata.setdefault(
                "compacted_at",
                self._last_compacted_at.isoformat(),
            )
            boundary_metadata.setdefault(
                "pre_compaction_event_count",
                pre_compaction_events,
            )
            replacement_items.append(
                MessageItem(
                    role="system",
                    content="Context compacted; earlier history replaced with continuation summary.",
                    subtype="compact_boundary",
                    metadata=boundary_metadata,
                    token_count=count_tokens(
                        "Context compacted; earlier history replaced with continuation summary.",
                        self._model_name,
                    ),
                )
            )

        artifact_content = self._build_compact_artifact_content(summary)
        artifact_metadata: dict[str, Any] = {}
        if artifact_id:
            artifact_metadata["summary_artifact_id"] = artifact_id
        else:
            artifact_metadata["inline_summary"] = True
        replacement_items.append(
            MessageItem(
                role="system",
                content=artifact_content,
                subtype="compact_artifact",
                metadata=artifact_metadata,
                token_count=count_tokens(artifact_content, self._model_name),
            )
        )

        for msg in preserved_messages or []:
            role = str(msg.get("role", "")).strip()
            if role not in {"user", "assistant", "tool"}:
                continue
            replacement_items.append(
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

        active_start = self._conversation_log.event_count()
        for item in replacement_items:
            self._conversation_log.append(item)
        self._conversation_log.set_active_start(active_start)

    def prune_tool_outputs(self) -> int:
        message_items = self._message_items()
        user_message_count = sum(1 for msg in message_items if msg.role == "user")

        if user_message_count < 2:
            return 0

        total_tokens = 0
        pruned_tokens = 0
        to_prune: list[MessageItem] = []

        for msg in reversed(message_items):
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
        self._conversation_log.clear()

    def get_transcript_events(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._conversation_log.iter_events()]

    def export_transcript_state(self) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        for event in self._conversation_log.iter_events():
            message = event.message.to_dict(
                include_tool_ui=True,
                include_internal_metadata=True,
            )
            events.append(
                {
                    "kind": event.kind,
                    "created_at": event.created_at.isoformat(),
                    "message": message,
                }
            )
        return {
            "active_start": self._conversation_log.active_start(),
            "events": events,
        }

    def restore_transcript_state(self, state: dict[str, Any] | None) -> None:
        if not isinstance(state, dict):
            return
        raw_events = state.get("events")
        if not isinstance(raw_events, list):
            return

        items: list[MessageItem] = []
        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            message = raw.get("message")
            if not isinstance(message, dict):
                continue
            role = str(message.get("role", "")).strip()
            if not role:
                continue
            items.append(
                MessageItem(
                    role=role,
                    content=str(message.get("content", "") or ""),
                    tool_call_id=message.get("tool_call_id"),
                    tool_calls=list(message.get("tool_calls") or []),
                    tool_ui=message.get("tool_ui")
                    if isinstance(message.get("tool_ui"), dict)
                    else None,
                    subtype=str(message.get("subtype", "")).strip() or None,
                    metadata=message.get("metadata")
                    if isinstance(message.get("metadata"), dict)
                    else None,
                    token_count=count_tokens(
                        str(message.get("content", "") or ""),
                        self._model_name,
                    ),
                )
            )

        self._conversation_log.replace_messages(items)
        active_start = state.get("active_start")
        if isinstance(active_start, int):
            self._conversation_log.set_active_start(active_start)
        self._drop_unresolved_tool_calls()

    def _message_items(self) -> list[MessageItem]:
        return self._conversation_log.iter_messages()

    @staticmethod
    def _build_compact_artifact_content(summary: str) -> str:
        return (
            "Compaction summary artifact loaded for live continuation.\n\n"
            "The previous conversation was compacted due to context length limits.\n"
            "Actions listed under completed work are already done and must not be repeated.\n"
            "Do not perform git write actions unless the user explicitly asked for them in this thread.\n"
            "If the next step appears to be staging, committing, or pushing based only on the summary, stop after implementation/verification and wait for user confirmation instead.\n\n"
            "---\n\n"
            f"{summary.strip()}\n\n"
            "---\n\n"
            "Resume from the remaining work only."
        )

    def transcript_event_count(self) -> int:
        return self._conversation_log.event_count()
