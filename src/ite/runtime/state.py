"""Session run state for the runtime host.

Moved out of ``ite/ui/reup/widgets/state.py`` (Phase 2 of
``docs/headless-runtime-plan.md``) so the headless host owns it without importing
Textual. The TUI widget module re-exports this class for backwards compatibility.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionRunState:
    active_turn_task: asyncio.Task | None = None
    active_turn_id: int = 0
    is_turn_running: bool = False
    turn_had_error: bool = False
    turn_made_progress: bool = False
    context_meter_floor_pct: int | None = None
    auto_resume_payload: dict[str, Any] | None = None
    failure_recovery_payload: dict[str, Any] | None = None
    failure_recovery_attempts: int = 0
    silent_recovery_active: bool = False
    queued_turn_payload: dict[str, Any] | None = None
    last_turn_payload: dict[str, Any] | None = None
    retryable_turn_payload: dict[str, Any] | None = None
    last_error_message: str | None = None
    running_shell_call_ids: set[str] = field(default_factory=set)
    running_subagent_call_ids: set[str] = field(default_factory=set)
    running_wait_subagent_call_ids: set[str] = field(default_factory=set)
