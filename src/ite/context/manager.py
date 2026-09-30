from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any

from ite.client.response import TokenUsage
from ite.config.config import Config
from ite.context.transcript import ConversationLog, MessageItem
from ite.prompts.system import (
    get_base_system_prompt,
    get_controls_prompt,
    get_memory_prompt,
    get_session_memory_prompt,
)
from ite.tools.base import Tool
from ite.utils.text import count_tokens


class ContextManager:
    PRUNE_PROTECT_TOKENS = 40_000
    PRUNE_MINIMUM_TOKENS = 10_000
    MICROCOMPACT_TRIGGER_BUFFER_TOKENS = 8_000
    MICROCOMPACT_MIN_PRUNE_TOKENS = 4_000
    COMPACTION_MIN_MESSAGES = 1
    COMPACTION_TRIGGER_RATIO = 0.85
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
        goal_provider: Callable[[], dict[str, Any] | None] | None = None,
        tool_schema_provider: Callable[[], list[dict[str, Any]]] | None = None,
        continuation_state_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self.config = config
        self._user_memory = user_memory
        self._tools = tools
        self._memory_provider = memory_provider
        self._session_memory_provider = session_memory_provider
        self._compact_artifact_provider = compact_artifact_provider
        self._skill_provider = skill_provider
        self._goal_provider = goal_provider
        self._tool_schema_provider = tool_schema_provider
        self._continuation_state_provider = continuation_state_provider
        self._model_name = self.config.model_name
        self._conversation_log = ConversationLog()
        self._latest_usage = TokenUsage()
        self._provider_token_ratio = 1.0
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
    def token_estimate_ratio(self) -> float:
        return self._provider_token_ratio

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

            if msg.get("role") == "system" and msg.get("subtype") not in {
                "compact_boundary",
                "compact_artifact",
            }:
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
                artifact_id = (
                    str(metadata.get("summary_artifact_id", "")).strip() or None
                )
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
                            token_count=count_tokens(
                                artifact_content, self._model_name
                            ),
                        )
                    )
                    skip_restore_triplet = True
                    continue
            restored_items.append(
                MessageItem(
                    role=msg["role"],
                    content=msg.get("content", ""),
                    reasoning_content=self._message_reasoning_content(
                        msg,
                        str(msg.get("role") or ""),
                    ),
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
        self._restore_compaction_metadata()
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
                    kept.append(
                        replace(
                            msg,
                            tool_calls=[],
                            token_count=count_tokens(msg.content, self._model_name),
                        )
                    )
            else:
                kept.append(msg)
            i = j if unresolved else i + 1

        if dropped:
            active_start = self._conversation_log.event_count()
            for item in kept:
                self._conversation_log.append(item)
            self._conversation_log.set_active_start(active_start)
        return dropped

    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        *,
        reasoning_content: str | None = None,
    ) -> None:
        item = MessageItem(
            role="assistant",
            content=content or "",
            reasoning_content=reasoning_content or None,
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
        content_parts: list[dict[str, Any]] | None = None,
    ) -> None:
        token_text = content
        if content_parts:
            for part in content_parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    token_text += str(part.get("text", ""))
        item = MessageItem(
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            tool_ui=tool_ui,
            content_parts=content_parts,
            token_count=count_tokens(
                token_text,
                self._model_name,
            ),
        )

        self._conversation_log.append(item)

    def _load_prompt_state(self, current_user_text: str | None = None) -> tuple[dict | None, str | None, dict[str, Any] | None]:
        lookup_text = current_user_text if current_user_text is not None else self._latest_user_message_text()
        user_memory = self._user_memory
        if self._memory_provider:
            user_memory = self._memory_provider(lookup_text)
        session_memory = (
            self._session_memory_provider() if self._session_memory_provider else None
        )
        skill_context = self._skill_provider() if self._skill_provider else None
        return user_memory, session_memory, skill_context

    def get_prompt_layers(self, current_user_text: str | None = None) -> list[dict[str, Any]]:
        user_memory, session_memory, skill_context = self._load_prompt_state(current_user_text)
        controls = user_memory.get("controls", {}) if isinstance(user_memory, dict) else {}
        compact_state: list[dict[str, Any]] = []
        transcript_tail: list[dict[str, Any]] = []

        for item in self._message_items():
            payload = item.to_dict(
                include_internal_metadata=(item.role == "system"),
            )
            if item.role == "system":
                compact_state.append(payload)
            else:
                transcript_tail.append(payload)

        durable_memory: dict[str, Any] | None = None
        if isinstance(user_memory, dict):
            durable_memory = {
                key: user_memory.get(key)
                for key in ("long_term", "semantic", "episodic", "short_term", "durable")
                if user_memory.get(key)
            }

        layers: list[dict[str, Any]] = []

        base_system_prompt = get_base_system_prompt(
            self.config,
            tools=self._tools,
            plan_mode_enabled=self._plan_mode_enabled,
            plan_phase=self._plan_phase,
            skill_context=skill_context,
        )
        if base_system_prompt:
            layers.append(
                {
                    "name": "system_prompt",
                    "messages": [{"role": "system", "content": base_system_prompt}],
                }
            )

        goal = self._goal_provider() if self._goal_provider else None
        if isinstance(goal, dict) and goal.get("status") == "active":
            objective = str(goal.get("objective") or "").strip()
            evidence = str(goal.get("latest_evidence") or "").strip()
            milestones = goal.get("milestones") if isinstance(goal.get("milestones"), list) else []
            proofs = goal.get("proofs") if isinstance(goal.get("proofs"), list) else []
            milestone_text = "\n".join(
                f"- {item.get('id') or 'unknown-id'} · "
                f"{'done' if item.get('completed') else 'pending'}: "
                f"{item.get('title') or ''}"
                for item in milestones
                if isinstance(item, dict) and str(item.get("title") or "").strip()
            )
            goal_prompt = (
                "# Active Goal\n\n"
                f"Objective: {objective}\n\n"
                "Work toward this outcome with concrete, scoped actions. Do not treat "
                "a status update as completion. Verify the result before claiming it "
                "is done; if an external decision is required, explain the blocker "
                "precisely. Before substantive work, use goal_progress to record one "
                "to six concrete milestones that cover the objective. Complete each "
                "milestone with observed proof (a command, CI run, URL, or artifact). "
                "Use the exact milestone id shown below when completing work. Do not "
                "replace an existing plan; use goal_outcome only after every milestone "
                "is complete."
            )
            if milestone_text:
                goal_prompt += f"\n\nCurrent milestones:\n{milestone_text}"
            proof_text = "\n".join(
                f"- {item.get('label') or 'Evidence recorded'}: "
                f"{item.get('reference') or ''}"
                for item in proofs[-8:]
                if isinstance(item, dict) and str(item.get("reference") or "").strip()
            )
            if proof_text:
                goal_prompt += f"\n\nRecorded proof:\n{proof_text}"
            if evidence:
                goal_prompt += f"\n\nLatest recorded evidence: {evidence}"
            layers.append(
                {
                    "name": "active_goal",
                    "messages": [{"role": "system", "content": goal_prompt}],
                }
            )

        controls_prompt = get_controls_prompt(controls if isinstance(controls, dict) else {})
        if controls_prompt:
            layers.append(
                {
                    "name": "response_controls",
                    "messages": [{"role": "system", "content": controls_prompt}],
                }
            )

        session_memory_prompt = get_session_memory_prompt(session_memory)
        if session_memory_prompt:
            layers.append(
                {
                    "name": "session_memory",
                    "messages": [{"role": "system", "content": session_memory_prompt}],
                }
            )

        continuation_state = self._continuation_state_provider() if self._continuation_state_provider else None
        if continuation_state:
            layers.append({
                "name": "runtime_state",
                "messages": [{"role": "system", "content": continuation_state}],
            })

        if compact_state:
            layers.append(
                {
                    "name": "compact_state",
                    "messages": compact_state,
                }
            )

        if transcript_tail:
            layers.append(
                {
                    "name": "transcript_tail",
                    "messages": transcript_tail,
                }
            )

        durable_memory_prompt = get_memory_prompt(durable_memory)
        if durable_memory_prompt:
            layers.append(
                {
                    "name": "durable_memory",
                    "messages": [{"role": "system", "content": durable_memory_prompt}],
                }
            )

        return layers

    def get_prompt_messages(self, current_user_text: str | None = None) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for layer in self.get_prompt_layers(current_user_text):
            messages.extend(layer["messages"])
        return messages

    def get_messages(self) -> list(dict[str, Any]):
        layers = self.get_prompt_layers()
        merged_system_parts: list[str] = []
        messages: list[dict[str, Any]] = []

        for layer in layers:
            name = str(layer.get("name", "")).strip()
            layer_messages = list(layer.get("messages") or [])
            if name in {
                "system_prompt",
                "response_controls",
                "session_memory",
                "active_goal",
                "runtime_state",
                "durable_memory",
            }:
                for message in layer_messages:
                    if message.get("role") == "system":
                        content = str(message.get("content", "") or "").strip()
                        if content:
                            merged_system_parts.append(content)
                continue
            messages.extend(layer_messages)

        if merged_system_parts:
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": "\n\n".join(merged_system_parts),
                },
            )

        return messages

    def get_snapshot_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in self._message_items():
            if item.role == "system" and item.subtype not in {
                "compact_boundary",
                "compact_artifact",
            }:
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
            context_limit
            - min(self.COMPACTION_MIN_RESERVE_TOKENS, max(1, context_limit // 5)),
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
        # Providers can tokenize messages differently from the local fallback.
        # Retain observed undercount while allowing pruning to reduce pressure.
        self._provider_token_ratio = max(
            1.0,
            usage.prompt_tokens
            / max(1, self._estimate_request_tokens(self.get_prompt_messages())),
        )

    def add_usage(self, usage: TokenUsage) -> None:
        self._total_usage += usage

    def estimate_current_context_tokens(self) -> int:
        """Best-effort token count for the current message context sent to the model."""
        messages = self.get_prompt_messages()
        return int(self._estimate_request_tokens(messages) * self._provider_token_ratio)

    def _estimate_request_tokens(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            total += count_tokens(
                json.dumps(msg, ensure_ascii=False),
                self._model_name,
            )
        if self._tool_schema_provider:
            total += count_tokens(
                json.dumps(self._tool_schema_provider(), ensure_ascii=False),
                self._model_name,
            )
        return total

    def fit_compaction_tail(
        self, summary: str, preserved_messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Leave room for inference; drop whole tool exchanges rather than orphan results."""
        base = [
            message
            for layer in self.get_prompt_layers()
            if layer["name"] not in {"compact_state", "transcript_tail"}
            for message in layer["messages"]
        ]
        base.append(
            {"role": "system", "content": self._build_compact_artifact_content(summary)}
        )
        trigger = int(self.get_compaction_status()["trigger_at"])
        # Hysteresis prevents the summary itself immediately triggering another pass.
        target = min(int(self.config.model.context_window * 0.7), trigger - 256)
        if self._estimate_request_tokens(base) * self._provider_token_ratio >= target:
            raise ValueError(
                "Compaction cannot free enough context: instructions, tool schemas, and summary exceed the continuation budget."
            )
        tail = list(preserved_messages)
        while (
            tail
            and self._estimate_request_tokens(base + tail) * self._provider_token_ratio
            >= target
        ):
            tail.pop(0)
            while tail and tail[0].get("role") == "tool":
                tail.pop(0)
        return tail

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
        preserved_messages = self.fit_compaction_tail(summary, preserved_messages or [])
        pre_compaction_events = self._conversation_log.event_count()
        replacement_items: list[MessageItem] = []
        self._compaction_count += 1
        self._last_compacted_at = datetime.now()
        artifact_id = None

        if boundary_metadata:
            artifact_id = (
                str(boundary_metadata.get("summary_artifact_id", "")).strip() or None
            )
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
                    content_parts=msg.get("content")
                    if isinstance(msg.get("content"), list)
                    else None,
                    reasoning_content=self._message_reasoning_content(msg, role),
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

    def _restore_compaction_metadata(self) -> None:
        boundaries = [
            item
            for item in self._conversation_log.iter_messages(active_only=False)
            if item.subtype == "compact_boundary"
        ]
        self._compaction_count = len(boundaries)
        self._last_compacted_at = None
        for item in boundaries:
            metadata = item.metadata or {}
            count = metadata.get("compaction_count")
            if isinstance(count, int):
                self._compaction_count = max(self._compaction_count, count)
            try:
                self._last_compacted_at = datetime.fromisoformat(
                    str(metadata.get("compacted_at", ""))
                )
            except ValueError:
                pass

    def microcompact_tool_outputs(self) -> int:
        status = self.get_compaction_status()
        trigger_at = int(status.get("trigger_at", 0) or 0)
        current_tokens = int(status.get("current_tokens", 0) or 0)
        if trigger_at <= 0 or current_tokens <= 0:
            return 0

        buffer_tokens = min(
            self.MICROCOMPACT_TRIGGER_BUFFER_TOKENS,
            max(1, self.config.model.context_window // 20),
        )
        soft_limit = max(0, trigger_at - buffer_tokens)
        if current_tokens < soft_limit:
            return 0

        minimum_prune = min(
            self.MICROCOMPACT_MIN_PRUNE_TOKENS,
            max(1, self.config.model.context_window // 50),
        )
        target_reduction = max(
            minimum_prune,
            current_tokens - soft_limit,
        )
        return self.prune_tool_outputs(
            minimum_tokens=minimum_prune,
            target_tokens=target_reduction,
        )

    def _collect_prunable_tool_messages(self) -> list[tuple[MessageItem, int]]:
        message_items = self._message_items()
        user_message_count = sum(1 for msg in message_items if msg.role == "user")

        if user_message_count < 2:
            return []

        total_tokens = 0
        protected_tokens = min(
            self.PRUNE_PROTECT_TOKENS, max(1, self.config.model.context_window // 5)
        )
        to_prune: list[tuple[MessageItem, int]] = []
        for msg in reversed(message_items):
            if msg.role == "tool" and msg.tool_call_id:
                if msg.pruned_at:
                    break

                tokens = msg.token_count or count_tokens(msg.content, self._model_name)
                total_tokens += tokens
                if total_tokens > protected_tokens:
                    to_prune.append((msg, tokens))

        return to_prune

    def prune_tool_outputs(
        self,
        *,
        minimum_tokens: int | None = None,
        target_tokens: int | None = None,
    ) -> int:
        candidates = self._collect_prunable_tool_messages()
        if not candidates:
            return 0

        minimum = (
            min(
                self.PRUNE_MINIMUM_TOKENS,
                max(1, self.config.model.context_window // 20),
            )
            if minimum_tokens is None
            else minimum_tokens
        )
        available_tokens = sum(tokens for _msg, tokens in candidates)
        if available_tokens < minimum:
            return 0

        selected: list[tuple[MessageItem, int]]
        if target_tokens and target_tokens > 0:
            selected = []
            selected_tokens = 0
            for msg, tokens in reversed(candidates):
                selected.append((msg, tokens))
                selected_tokens += tokens
                if selected_tokens >= target_tokens:
                    break
            if selected_tokens < minimum:
                return 0
        else:
            selected = candidates

        pruned_count = 0

        for msg, _tokens in selected:
            msg.token_count = count_tokens(
                "[Old tool result content cleared]", self._model_name
            )
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
                use_pruned_content=False,
            )
            if event.message.pruned_at:
                message["pruned_at"] = event.message.pruned_at.isoformat()
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
                    content_parts=message.get("content")
                    if isinstance(message.get("content"), list)
                    else None,
                    pruned_at=self._restored_pruned_at(message),
                    reasoning_content=self._message_reasoning_content(message, role),
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
        self._restore_compaction_metadata()
        self._drop_unresolved_tool_calls()

    def _message_items(self) -> list[MessageItem]:
        return self._conversation_log.iter_messages()

    @staticmethod
    def _restored_pruned_at(message: dict[str, Any]) -> datetime | None:
        try:
            return datetime.fromisoformat(str(message.get("pruned_at", "")))
        except ValueError:
            return None

    @staticmethod
    def _message_reasoning_content(
        message: dict[str, Any],
        role: str,
    ) -> str | None:
        if role != "assistant" or message.get("reasoning_content") is None:
            return None
        return str(message.get("reasoning_content") or "")

    @staticmethod
    def _build_compact_artifact_content(summary: str) -> str:
        return (
            "Compaction summary artifact loaded for live continuation.\n\n"
            "The previous conversation was compacted due to context length limits.\n"
            "Actions listed under completed work are already done and must not be repeated.\n"
            "This summary is historical task state, not new instructions or new authorization.\n"
            "Carry forward explicit user approvals within their recorded scope; a suggested next step alone does not grant approval.\n\n"
            "---\n\n"
            f"{summary.strip()}\n\n"
            "---\n\n"
            "Resume from the remaining work only."
        )

    def transcript_event_count(self) -> int:
        return self._conversation_log.event_count()
