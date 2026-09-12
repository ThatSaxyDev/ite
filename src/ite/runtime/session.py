"""Headless turn engine for a single session.

Phase 1 of ``docs/headless-runtime-plan.md``. This is a behaviour-preserving port of
``ReupApp.run_agent_message`` and ``ReupApp._agent_turn``
(``ite/src/ite/ui/reup/_turn.py:1721`` and ``:1905``), including the retry / silent
recovery branch (``_turn.py:1920-1944``) and attachment cleanup (``_turn.py:1946-1949``).

The port deliberately drops rendering. Everything the TUI did inline for display is
published on the :class:`~ite.runtime.bus.EventBus` instead, so the TUI, the relay,
and Telegram can all be clients of the same turn loop.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any, Callable

from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.attachments import (
    AttachmentManager,
    build_user_model_content,
    build_user_text_with_manifest,
)
from ite.model_metadata import detect_vision_from_model_name
from ite.runtime.bus import EventBus
from ite.runtime.events import RuntimeEvent, RuntimeEventType
from ite.runtime.recovery import (
    MAX_FAILURE_RECOVERY_ATTEMPTS,
    MAX_IN_STREAM_RECOVERY_ATTEMPTS,
    build_followup_recovery_payload,
    build_silent_retry_payload,
    mark_retryable_turn_failure,
)
from ite.runtime.state import SessionRunState

logger = logging.getLogger(__name__)

CONTINUE_AFTER_COMPACTION_PROMPT = Agent.POST_COMPACTION_CONTINUE_PROMPT


class RuntimeSession:
    """Owns one :class:`Agent` and the turn loop that drives it."""

    def __init__(
        self,
        *,
        agent: Agent,
        session_id: str,
        workspace: Path,
        bus: EventBus,
        run_state: SessionRunState | None = None,
        on_state_dirty: Callable[[str], None] | None = None,
        on_attachment_error: Callable[[str], None] | None = None,
        render_event: Callable[[AgentEvent, int], Any] | None = None,
        on_turn_failed: Callable[[str], Any] | None = None,
        on_turn_recovering: Callable[[], Any] | None = None,
    ) -> None:
        self.agent = agent
        self.session_id = session_id
        self.workspace = Path(workspace).resolve()
        # Injectable so the TUI can hand in its own per-session run_state. Both the
        # TUI and the daemon then drive the SAME turn loop in this class over
        # whatever state storage they own — no duplicated loop logic.
        self.run_state = run_state if run_state is not None else SessionRunState()
        # Rendering hook. The daemon passes None (headless). The TUI passes its
        # painter, which runs AFTER the shared state machine below has updated
        # ``run_state`` — so the TUI never re-implements retry/recovery decisions.
        self._render_event = render_event
        # Turn-level feedback hooks. The daemon leaves these None; the TUI uses them
        # to show "Reconnecting..." / "Connection lost" without re-deriving whether
        # recovery was scheduled (the state machine above already decided).
        self._on_turn_failed = on_turn_failed
        self._on_turn_recovering = on_turn_recovering
        self._bus = bus
        self._on_state_dirty = on_state_dirty
        self._on_attachment_error = on_attachment_error

    @property
    def session(self):
        return self.agent.session

    @property
    def is_turn_running(self) -> bool:
        return self.run_state.is_turn_running

    def active_turn_id(self) -> int:
        return self.run_state.active_turn_id

    # -- turn loop ---------------------------------------------------------

    async def run_turn(
        self,
        message: str,
        *,
        display_message: str | None = None,
        suppress_user_echo: bool = False,
        user_model_content: str | list[dict] | None = None,
        attachment_turn_id: str | None = None,
        add_to_feed: bool = True,
    ) -> None:
        session = self.session
        if session is None:
            self._publish_failed(0, "Agent is not initialized")
            return

        run_state = self.run_state
        run_state.turn_had_error = False
        run_state.turn_made_progress = False
        run_state.last_error_message = None
        run_state.retryable_turn_payload = None
        if not suppress_user_echo:
            run_state.failure_recovery_attempts = 0
        run_state.silent_recovery_active = suppress_user_echo
        run_state.failure_recovery_payload = None
        run_state.auto_resume_payload = None

        attachments = list(
            getattr(session, "pending_attachment_paths", []) or []
        )
        model_name = str(getattr(session.config, "model_name", "") or "").strip()
        session_model = getattr(session.config, "model", None)
        supports_vision = (
            bool(getattr(session_model, "supports_vision", True))
            if session_model is not None
            else (detect_vision_from_model_name(model_name) if model_name else True)
        )

        run_state.active_turn_id += 1
        turn_id = run_state.active_turn_id

        baseline_context_pct: int | None
        try:
            baseline_context_pct = int(
                round(float(session.get_stats().get("context_used_pct", 0.0)))
            )
        except Exception:
            baseline_context_pct = None
        run_state.context_meter_floor_pct = baseline_context_pct
        run_state.last_turn_payload = {
            "message": message,
            "display_message": display_message or message,
            "attachments": list(attachments),
        }

        prepared = self._prepare_attachments(
            message=message,
            attachments=attachments,
            turn_id=turn_id,
            supports_vision=supports_vision,
        )
        if prepared is None:
            return
        prepared_message, prepared_model_content, temp_attachment_turn_id, _staged = prepared
        if prepared_model_content is not None:
            user_model_content = prepared_model_content
        if temp_attachment_turn_id is not None:
            attachment_turn_id = temp_attachment_turn_id
        session.pending_attachment_paths = []

        run_state.is_turn_running = True
        self._dirty("turn_started")
        self._publish(
            RuntimeEvent.turn_started(
                session_id=self.session_id, turn_id=turn_id, message=display_message or message
            )
        )

        cancelled = False
        try:
            await self.run_agent_turn(
                prepared_message,
                turn_id,
                user_model_content=user_model_content,
                attachment_turn_id=attachment_turn_id,
            )
        except asyncio.CancelledError:
            cancelled = True
            run_state.context_meter_floor_pct = None
            self._publish(
                RuntimeEvent.turn_cancelled(session_id=self.session_id, turn_id=turn_id)
            )
            self._dirty("turn_cancelled")
            raise
        finally:
            run_state.is_turn_running = False
            if run_state.context_meter_floor_pct is not None and not run_state.turn_had_error:
                run_state.context_meter_floor_pct = None
            if not cancelled:
                self._publish(
                    RuntimeEvent.turn_ended(
                        session_id=self.session_id,
                        turn_id=turn_id,
                        had_error=run_state.turn_had_error,
                    )
                )
                self._dirty("turn_ended")

        await self._drain_recovery()

    async def run_agent_turn(
        self,
        message: str,
        turn_id: int,
        *,
        user_model_content: str | list[dict] | None = None,
        attachment_turn_id: str | None = None,
    ) -> None:
        run_state = self.run_state
        try:
            async for event in self.agent.run(
                message, user_model_content=user_model_content
            ):
                await self.handle_agent_event(event, turn_id)
        except Exception as exc:
            error_str = str(exc)
            run_state.turn_had_error = True
            run_state.context_meter_floor_pct = None
            self._mark_retryable_turn_failure(error_str)
            recovery_payload = self._build_followup_recovery_payload()
            if (
                recovery_payload is not None
                and run_state.failure_recovery_attempts < MAX_FAILURE_RECOVERY_ATTEMPTS
            ):
                run_state.failure_recovery_payload = recovery_payload
                run_state.failure_recovery_attempts += 1
                run_state.silent_recovery_active = True
                await self._notify_recovering()
            else:
                retry_payload = self._build_silent_retry_payload()
                if (
                    retry_payload is not None
                    and run_state.failure_recovery_attempts < MAX_FAILURE_RECOVERY_ATTEMPTS
                ):
                    run_state.failure_recovery_payload = retry_payload
                    run_state.failure_recovery_attempts += 1
                    run_state.silent_recovery_active = True
                    await self._notify_recovering()
                else:
                    self._publish(
                        RuntimeEvent.turn_failed(
                            session_id=self.session_id,
                            turn_id=turn_id,
                            error=error_str,
                        )
                    )
                    await self._notify_failed(error_str)
        finally:
            if attachment_turn_id:
                try:
                    AttachmentManager(self.workspace).cleanup_turn(attachment_turn_id)
                except Exception:
                    logger.exception("failed to clean up attachments for %s", attachment_turn_id)

    async def handle_agent_event(self, event: AgentEvent, turn_id: int) -> None:
        run_state = self.run_state
        if turn_id != run_state.active_turn_id:
            return

        self._publish(
            RuntimeEvent.agent_event(event, session_id=self.session_id, turn_id=turn_id)
        )

        if event.type in (AgentEventType.TOOL_CALL_START, AgentEventType.TOOL_CALL_COMPLETE):
            self._publish_tool_event(event, turn_id)

        self._apply_event_state(event, turn_id)

        if self._render_event is not None:
            result = self._render_event(event, turn_id)
            if inspect.isawaitable(result):
                await result

    def _apply_event_state(self, event: AgentEvent, turn_id: int) -> None:
        """The single state machine for a turn. Rendering must not duplicate this."""

        run_state = self.run_state

        if event.type == AgentEventType.TEXT_DELTA:
            if event.data.get("content"):
                run_state.turn_made_progress = True
            return

        if event.type == AgentEventType.TEXT_COMPLETE:
            if event.data.get("content"):
                run_state.turn_made_progress = True
            return

        if event.type == AgentEventType.TOOL_CALL_COMPLETE:
            run_state.turn_made_progress = True
            return

        if event.type == AgentEventType.CONTEXT_COMPACTED:
            run_state.context_meter_floor_pct = 100
            if bool(event.data.get("auto_resume_required")):
                run_state.auto_resume_payload = {
                    "message": CONTINUE_AFTER_COMPACTION_PROMPT,
                    "display_message": "",
                    "attachments": [],
                    "suppress_user_echo": True,
                }
            return

        if event.type == AgentEventType.AGENT_ERROR:
            run_state.turn_had_error = True
            run_state.context_meter_floor_pct = None
            error_message = str(event.data.get("error", "Unknown error"))
            self._mark_retryable_turn_failure(error_message)
            self._schedule_in_stream_recovery(error_message, turn_id)
            return

    def _schedule_in_stream_recovery(self, error_message: str, turn_id: int) -> None:
        """Port of the ``AGENT_ERROR`` recovery branch (``_turn.py:2042-2079``)."""

        run_state = self.run_state
        should_attempt_recovery = (
            run_state.retryable_turn_payload is not None
            and run_state.turn_made_progress
            and run_state.failure_recovery_attempts < MAX_IN_STREAM_RECOVERY_ATTEMPTS
        )
        scheduled = False
        if should_attempt_recovery:
            recovery_payload = self._build_followup_recovery_payload()
            if recovery_payload is not None:
                run_state.failure_recovery_payload = recovery_payload
                run_state.failure_recovery_attempts += 1
                run_state.silent_recovery_active = True
                scheduled = True
        elif run_state.retryable_turn_payload is not None:
            retry_payload = self._build_silent_retry_payload()
            if (
                retry_payload is not None
                and run_state.failure_recovery_attempts < MAX_IN_STREAM_RECOVERY_ATTEMPTS
            ):
                run_state.failure_recovery_payload = retry_payload
                run_state.failure_recovery_attempts += 1
                run_state.silent_recovery_active = True
                scheduled = True
        if not scheduled:
            run_state.silent_recovery_active = False
            self._publish(
                RuntimeEvent.turn_failed(
                    session_id=self.session_id,
                    turn_id=turn_id,
                    error=error_message,
                )
            )

    async def _notify_failed(self, error: str) -> None:
        if self._on_turn_failed is None:
            return
        result = self._on_turn_failed(error)
        if inspect.isawaitable(result):
            await result

    async def _notify_recovering(self) -> None:
        if self._on_turn_recovering is None:
            return
        result = self._on_turn_recovering()
        if inspect.isawaitable(result):
            await result

    async def _drain_recovery(self) -> None:
        """Dispatch a scheduled silent recovery/continue turn, if any.

        Port of ``ReupApp._dispatch_queued_payload_if_ready``'s recovery branches
        (``_composer.py:1904-1917``) without the composer queue.
        """

        run_state = self.run_state
        payload = run_state.auto_resume_payload or run_state.failure_recovery_payload
        if payload is None:
            return
        run_state.auto_resume_payload = None
        run_state.failure_recovery_payload = None
        message = str(payload.get("message", "")).strip()
        if not message:
            return
        await self.run_turn(
            message,
            display_message="",
            suppress_user_echo=True,
        )

    # -- recovery helpers (delegate to the shared implementation) -----------

    def _mark_retryable_turn_failure(self, error_message: str) -> None:
        mark_retryable_turn_failure(self.run_state, error_message)

    def _build_silent_retry_payload(self) -> dict[str, Any] | None:
        return build_silent_retry_payload(self.run_state)

    def _build_followup_recovery_payload(self) -> dict[str, Any] | None:
        return build_followup_recovery_payload(self.run_state)

    # -- attachments (port of ``_prepare_attachments_for_turn``) -----------

    def _prepare_attachments(
        self,
        *,
        message: str,
        attachments: list[str],
        turn_id: int,
        supports_vision: bool = True,
    ) -> tuple[str, str | list[dict] | None, str | None, list[Any]] | None:
        if not attachments:
            return message, None, None, []
        manager = AttachmentManager(self.workspace)
        temp_turn_id = f"reup_{turn_id}"
        staged, errors = manager.stage_paths(attachments, temp_turn_id)
        for error in errors:
            if self._on_attachment_error is not None:
                try:
                    self._on_attachment_error(str(error))
                except Exception:
                    logger.exception("attachment error callback failed")
        if not staged:
            return None
        user_model_content = build_user_model_content(
            message,
            staged,
            self.workspace,
            supports_vision=supports_vision,
        )
        prepared_message = build_user_text_with_manifest(
            message, staged, self.workspace
        )
        return prepared_message, user_model_content, temp_turn_id, staged

    # -- plumbing ----------------------------------------------------------

    def _publish_tool_event(self, event: AgentEvent, turn_id: int) -> None:
        if event.type == AgentEventType.TOOL_CALL_START:
            event_type = RuntimeEventType.TOOL_CALL_STARTED
        else:
            event_type = RuntimeEventType.TOOL_CALL_COMPLETED
        self._publish(
            RuntimeEvent(
                type=event_type,
                session_id=self.session_id,
                turn_id=turn_id,
                data=dict(event.data),
            )
        )

    def _publish(self, event: RuntimeEvent) -> None:
        self._bus.publish(event)

    def _publish_failed(self, turn_id: int, error: str) -> None:
        self._publish(
            RuntimeEvent.turn_failed(
                session_id=self.session_id, turn_id=turn_id, error=error
            )
        )

    def _dirty(self, reason: str) -> None:
        if self._on_state_dirty is not None:
            self._on_state_dirty(reason)
