"""Headless runtime host package.

See ``docs/headless-runtime-plan.md``. This package must stay importable without
Textual installed; the import-guard test enforces that.

Phase 0 exposes the host contract: the event taxonomy, the client protocol, the event
bus, and the approval broker. Phases 1-2 add the turn engine and the host itself.
"""

from .approval import ApprovalBroker
from .bus import EventBus
from .client import (
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalResolution,
    PlanQuestion,
    PlanReadyRequest,
    RuntimeClient,
)
from .events import RuntimeEvent, RuntimeEventType
from .host import RuntimeHost
from .session import RuntimeSession
from .state import SessionRunState

__all__ = [
    "ApprovalBroker",
    "ApprovalPolicy",
    "ApprovalRequest",
    "ApprovalResolution",
    "EventBus",
    "PlanQuestion",
    "PlanReadyRequest",
    "RuntimeClient",
    "RuntimeEvent",
    "RuntimeEventType",
    "RuntimeHost",
    "RuntimeSession",
    "SessionRunState",
]
