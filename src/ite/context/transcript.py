from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


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
            result["tool_calls"] = _json_safe(self.tool_calls)

        if self.role == "tool":
            result["content"] = self.content or ""
        elif self.content or self.tool_calls:
            result["content"] = self.content or ""

        if include_tool_ui and self.tool_ui and self.role == "tool":
            result["tool_ui"] = _json_safe(self.tool_ui)

        if include_internal_metadata:
            if self.subtype:
                result["subtype"] = self.subtype
            if self.metadata:
                result["metadata"] = _json_safe(self.metadata)

        return result

@dataclass
class TranscriptEvent:
    kind: str
    message: MessageItem
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "kind": self.kind,
            "role": self.message.role,
            "created_at": self.created_at.isoformat(),
        }
        if self.message.subtype:
            result["subtype"] = self.message.subtype
        if self.message.metadata:
            result["metadata"] = _json_safe(self.message.metadata)
        return result


class ConversationLog:
    """Append-only transcript event store used by ContextManager."""

    def __init__(self) -> None:
        self._events: list[TranscriptEvent] = []
        self._active_start: int = 0

    def clear(self) -> None:
        self._events = []
        self._active_start = 0

    def append(self, item: MessageItem) -> TranscriptEvent:
        event = TranscriptEvent(
            kind=self._infer_kind(item),
            message=item,
        )
        self._events.append(event)
        return event

    def replace_messages(self, items: list[MessageItem]) -> None:
        self.clear()
        for item in items:
            self.append(item)
        self._active_start = 0

    def iter_events(self, *, active_only: bool = False) -> list[TranscriptEvent]:
        if active_only:
            return list(self._events[self._active_start :])
        return list(self._events)

    def iter_messages(self, *, active_only: bool = True) -> list[MessageItem]:
        events = self.iter_events(active_only=active_only)
        return [event.message for event in events]

    def active_start(self) -> int:
        return self._active_start

    def set_active_start(self, index: int) -> None:
        bounded = max(0, min(index, len(self._events)))
        self._active_start = bounded

    def event_count(self) -> int:
        return len(self._events)

    @staticmethod
    def _infer_kind(item: MessageItem) -> str:
        if item.role == "system":
            if item.subtype == "compact_boundary":
                return "compact_boundary"
            if item.subtype == "compact_artifact":
                return "compact_artifact"
            return "system_event"
        if item.role == "user":
            return "user_message"
        if item.role == "assistant":
            return "assistant_message"
        if item.role == "tool":
            return "tool_result"
        return "message"
