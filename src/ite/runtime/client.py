"""Client contract for the headless session host.

Phase 0 of ``docs/headless-runtime-plan.md`` §4.1. The host owns exactly one writable
source of truth; clients are read-only subscribers plus command-issuing handles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from ite.runtime.events import RuntimeEvent


class ApprovalPolicy(str, Enum):
    """What the host does when an approval is needed and no interactive client answers.

    Explicit, never implicit: a headless runtime must not hang forever waiting for a
    human that is not there.
    """

    DENY = "deny"
    ALLOW = "allow"
    HOLD = "hold"


@dataclass(slots=True)
class ApprovalRequest:
    request_id: str
    session_id: str
    tool_name: str
    description: str = ""
    command: str | None = None
    diff: str | None = None
    timeout: float = 120.0


@dataclass(slots=True)
class ApprovalResolution:
    request_id: str
    approved: bool
    reason: str = ""


@dataclass(slots=True)
class PlanQuestion:
    request_id: str
    session_id: str
    question: str
    options: list[str] = field(default_factory=list)
    recommended_index: int | None = None
    allow_free_text: bool = True
    question_number: int = 1
    timeout: float = 300.0


@dataclass(slots=True)
class PlanReadyRequest:
    request_id: str
    session_id: str
    plan_text: str
    question_count: int = 0
    timeout: float = 300.0


@runtime_checkable
class RuntimeClient(Protocol):
    """A consumer of host events and, optionally, a responder to interactive requests.

    Implementations are expected to be cheap and non-blocking in ``on_event`` /
    ``on_state``; the host fans out synchronously and must not be stalled by a slow
    client. Clients that need async work should enqueue and return.
    """

    name: str

    def on_event(self, event: RuntimeEvent) -> None: ...

    def on_state(self, state: dict[str, Any]) -> None: ...

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResolution | None: ...

    async def request_plan_question(self, request: PlanQuestion) -> dict[str, Any] | None: ...

    async def request_plan_ready(self, request: PlanReadyRequest) -> bool | None: ...

    def is_interactive(self) -> bool:
        """True if this client can answer approvals/questions without a human absent.

        The daemon has no interactive client; the TUI and phone do.
        """
        ...
