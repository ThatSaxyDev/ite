"""Runtime event taxonomy for the headless session host.

Phase 0 of ``docs/headless-runtime-plan.md``. One ``RuntimeEvent`` union replaces the
three ad-hoc paths that exist today (relay ``agent_event`` broadcasts, Telegram
``handle_agent_event``, and TUI widgets).

The wire form intentionally matches ``ite.remote.protocol.serialize_agent_event`` so
the relay frame contract in ``docs/remote-relay-plan.md`` §5 does not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ite.agent.events import AgentEvent
from ite.remote.protocol import (
    REMOTE_PROTOCOL_VERSION,
    json_safe,
    serialize_agent_event,
    utc_now_iso,
)


class RuntimeEventType(str, Enum):
    """Every message the host puts on the bus."""

    # turn lifecycle
    TURN_STARTED = "turn_started"
    TURN_ENDED = "turn_ended"
    TURN_FAILED = "turn_failed"
    TURN_CANCELLED = "turn_cancelled"

    # agent passthrough (wraps AgentEvent, already serialized)
    AGENT_EVENT = "agent_event"

    # tool lifecycle
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"

    # feeds
    COMMAND_FEED_APPENDED = "command_feed_appended"
    CHANGE_FEED_APPENDED = "change_feed_appended"

    # sessions
    SESSION_OPENED = "session_opened"
    SESSION_CLOSED = "session_closed"
    SESSION_ACTIVATED = "session_activated"

    # interactive requests
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    PLAN_QUESTION_REQUESTED = "plan_question_requested"
    PLAN_QUESTION_RESOLVED = "plan_question_resolved"
    PLAN_READY_REQUESTED = "plan_ready_requested"
    PLAN_READY_RESOLVED = "plan_ready_resolved"

    # snapshot invalidation
    STATE_CHANGED = "state_changed"


@dataclass(slots=True)
class RuntimeEvent:
    """A single bus message.

    ``session_id`` and ``turn_id`` mirror the relay envelope so clients can route
    without inspecting ``data``.
    """

    type: RuntimeEventType
    session_id: str = ""
    turn_id: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    raw: Any = None

    def to_wire(self) -> dict[str, Any]:
        """Serialize to the relay-compatible frame envelope.

        ``AGENT_EVENT`` delegates to :func:`serialize_agent_event` so the existing
        ``agent_event`` frame contract is byte-for-byte preserved. In-process clients
        still receive the structured :class:`AgentEvent` on ``raw``. All other events
        use the same envelope shape with their own ``type``.
        """

        if self.type == RuntimeEventType.AGENT_EVENT and self.raw is not None:
            return serialize_agent_event(
                self.raw, session_id=self.session_id, turn_id=self.turn_id
            )
        return {
            "protocol_version": REMOTE_PROTOCOL_VERSION,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "timestamp": self.timestamp or utc_now_iso(),
            "event": {
                "type": self.type.value,
                "data": json_safe(self.data),
            },
        }

    @classmethod
    def agent_event(
        cls,
        event: AgentEvent,
        *,
        session_id: str,
        turn_id: int,
    ) -> RuntimeEvent:
        """Wrap an :class:`AgentEvent` using the canonical serializer."""

        return cls(
            type=RuntimeEventType.AGENT_EVENT,
            session_id=session_id,
            turn_id=turn_id,
            raw=event,
        )

    @classmethod
    def turn_started(cls, *, session_id: str, turn_id: int, message: str) -> RuntimeEvent:
        return cls(
            type=RuntimeEventType.TURN_STARTED,
            session_id=session_id,
            turn_id=turn_id,
            data={"message": message},
        )

    @classmethod
    def turn_ended(
        cls, *, session_id: str, turn_id: int, had_error: bool = False
    ) -> RuntimeEvent:
        return cls(
            type=RuntimeEventType.TURN_ENDED,
            session_id=session_id,
            turn_id=turn_id,
            data={"had_error": bool(had_error)},
        )

    @classmethod
    def turn_failed(
        cls, *, session_id: str, turn_id: int, error: str, recovery: dict[str, Any] | None = None
    ) -> RuntimeEvent:
        return cls(
            type=RuntimeEventType.TURN_FAILED,
            session_id=session_id,
            turn_id=turn_id,
            data={"error": error, "recovery": recovery or {}},
        )

    @classmethod
    def turn_cancelled(cls, *, session_id: str, turn_id: int) -> RuntimeEvent:
        return cls(
            type=RuntimeEventType.TURN_CANCELLED,
            session_id=session_id,
            turn_id=turn_id,
            data={},
        )

    @classmethod
    def state_changed(
        cls, *, session_id: str = "", turn_id: int = 0, reason: str = ""
    ) -> RuntimeEvent:
        return cls(
            type=RuntimeEventType.STATE_CHANGED,
            session_id=session_id,
            turn_id=turn_id,
            data={"reason": reason},
        )
