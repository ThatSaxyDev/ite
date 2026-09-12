"""Runtime host: the single writable source of truth for sessions and turns.

Delivers the Phase 0 public surface from ``docs/headless-runtime-plan.md`` §5 —
``start``, ``stop``, ``open_session``, ``activate_session``, ``close_session``,
``submit_prompt``, ``cancel_turn``, ``switch_session``, ``snapshot``, ``subscribe`` —
and the Phase 2 state/feed ownership.

The host has no Textual dependency. The TUI, the relay, and Telegram attach as
:class:`~ite.runtime.client.RuntimeClient` subscribers.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

from ite.agent.agent import Agent
from ite.agent.session import Session
from ite.config.config import Config
from ite.config.loader import load_config
from ite.remote.protocol import build_remote_transcript, utc_now_iso
from ite.runtime.approval import ApprovalBroker
from ite.runtime.bus import EventBus
from ite.runtime.client import (
    ApprovalPolicy,
    ApprovalRequest,
    PlanQuestion,
    RuntimeClient,
)
from ite.runtime.events import RuntimeEvent, RuntimeEventType
from ite.runtime.session import RuntimeSession

logger = logging.getLogger(__name__)

MAX_REMOTE_COMMAND_FEED = 200
MAX_REMOTE_CHANGE_FEED = 200

_BROKER_EVENT_TYPES = {
    "approval_requested": RuntimeEventType.APPROVAL_REQUESTED,
    "approval_resolved": RuntimeEventType.APPROVAL_RESOLVED,
    "plan_question_requested": RuntimeEventType.PLAN_QUESTION_REQUESTED,
    "plan_question_resolved": RuntimeEventType.PLAN_QUESTION_RESOLVED,
    "plan_ready_requested": RuntimeEventType.PLAN_READY_REQUESTED,
    "plan_ready_resolved": RuntimeEventType.PLAN_READY_RESOLVED,
}


class RuntimeHost:
    """Owns agent lifecycle, sessions, turns, feeds, and state."""

    def __init__(
        self,
        config: Config,
        *,
        bus: EventBus | None = None,
        approval_policy: ApprovalPolicy = ApprovalPolicy.DENY,
    ) -> None:
        self.config = config
        self.bus = bus or EventBus()
        self._sessions: dict[str, RuntimeSession] = {}
        self._order: list[str] = []
        self._active_session_id: str | None = None
        self._ensure_agent_lock = asyncio.Lock()
        self._started = False
        self._remote_command_feed: list[dict[str, Any]] = []
        self._remote_command_seq = 0
        self._remote_change_feed: list[dict[str, Any]] = []

        self._broker = ApprovalBroker(
            policy=approval_policy,
            publish=self._publish_broker_event,
        )

        # Optional hooks. The TUI client installs these so the snapshot carries the
        # same activity fields as the pre-extraction ``_build_remote_runtime_state``.
        # Headless leaves them as neutral defaults.
        self.activity_provider: Callable[[], str] | None = None
        self.activity_busy_provider: Callable[[], bool] | None = None
        self.awaiting_shell_input_provider: Callable[[], bool] | None = None

        # Optional factories. The TUI installs these so the host builds sessions and
        # agents exactly the way the TUI does (its own callbacks, credentials, and
        # workspace config). Headless falls back to the built-in path below.
        self.session_factory: Callable[[Path], Session] | None = None
        self.agent_factory: Callable[[Session], Agent] | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        await self.ensure_agent()

    async def stop(self) -> None:
        self._started = False
        for session in list(self._sessions.values()):
            await self.cancel_turn(session.session_id)
        for session_id in list(self._order):
            await self.close_session(session_id)
        self.bus.clear()

    # -- client subscription ----------------------------------------------

    def subscribe(self, client: RuntimeClient) -> None:
        self.bus.subscribe(client)
        client.on_state(self.snapshot())

    def unsubscribe(self, client: RuntimeClient) -> None:
        self.bus.unsubscribe(client)

    async def publish_state(self) -> None:
        self.bus.publish_state(self.snapshot())

    # -- session registry --------------------------------------------------

    @property
    def active_session_id(self) -> str | None:
        return self._active_session_id

    @property
    def agent(self) -> Agent | None:
        session = self._active_session()
        return session.agent if session is not None else None

    @property
    def open_session_ids(self) -> list[str]:
        return list(self._order)

    @property
    def is_turn_running(self) -> bool:
        session = self._active_session()
        return bool(session and session.is_turn_running)

    def get_session(self, session_id: str | None = None) -> RuntimeSession | None:
        if session_id:
            return self._sessions.get(session_id)
        return self._active_session()

    def _active_session(self) -> RuntimeSession | None:
        if self._active_session_id is None:
            return None
        return self._sessions.get(self._active_session_id)

    async def open_session(self, workspace: Path | None = None) -> str:
        resolved_workspace = Path(workspace or self.config.cwd).resolve()
        if self.session_factory is not None:
            session = self.session_factory(resolved_workspace)
        else:
            session = Session(config=self.session_config_for_workspace(resolved_workspace))
        agent = (
            self.agent_factory(session)
            if self.agent_factory is not None
            else self.build_session_agent(session)
        )
        await agent.__aenter__()
        return await self._register_runtime_session(
            agent=agent, workspace=resolved_workspace
        )

    async def register_session(
        self,
        *,
        agent: Agent,
        workspace: Path | None = None,
        run_state: SessionRunState | None = None,
        activate: bool = False,
    ) -> str:
        """Adopt an already-built agent (e.g. a resumed or TUI-created session).

        The TUI builds agents with its own callbacks; the daemon builds them via
        :meth:`open_session`. Either way the resulting :class:`RuntimeSession` runs the
        same turn loop.
        """

        return await self._register_runtime_session(
            agent=agent,
            workspace=Path(workspace or self.config.cwd).resolve(),
            run_state=run_state,
            activate=activate,
        )

    async def _register_runtime_session(
        self,
        *,
        agent: Agent,
        workspace: Path,
        run_state: SessionRunState | None = None,
        activate: bool = False,
    ) -> str:
        session_id = self._session_id(agent.session) or ""
        if not session_id:
            raise RuntimeError("session has no session_id")
        existing = self._sessions.get(session_id)
        if existing is not None:
            if activate:
                await self.activate_session(session_id)
            return session_id
        runtime_session = RuntimeSession(
            agent=agent,
            session_id=session_id,
            workspace=workspace,
            bus=self.bus,
            run_state=run_state,
            on_state_dirty=self._on_session_state_dirty,
        )
        self._sessions[session_id] = runtime_session
        if session_id not in self._order:
            self._order.append(session_id)
        if activate or self._active_session_id is None:
            self._active_session_id = session_id
        self._publish_event(
            RuntimeEvent(
                type=RuntimeEventType.SESSION_OPENED,
                session_id=session_id,
                data={"workspace": str(workspace)},
            )
        )
        await self.publish_state()
        return session_id

    async def ensure_agent(self) -> RuntimeSession | None:
        async with self._ensure_agent_lock:
            existing = self._active_session()
            if existing is not None and existing.session is not None:
                return existing
            await self.open_session()
            return self._active_session()

    async def activate_session(self, session_id: str) -> bool:
        if not session_id or session_id not in self._sessions:
            return False
        if self._active_session_id == session_id:
            return True
        self._active_session_id = session_id
        self._publish_event(
            RuntimeEvent(type=RuntimeEventType.SESSION_ACTIVATED, session_id=session_id)
        )
        await self.publish_state()
        return True

    async def switch_session(self, session_id: str) -> bool:
        return await self.activate_session(session_id)

    async def close_session(self, session_id: str) -> bool:
        runtime_session = self._sessions.get(session_id)
        if runtime_session is None:
            return False
        await self.cancel_turn(session_id)
        try:
            await runtime_session.agent.__aexit__(None, None, None)
        except Exception:
            logger.exception("error closing session %s", session_id)
        self._sessions.pop(session_id, None)
        self._order = [sid for sid in self._order if sid != session_id]
        if self._active_session_id == session_id:
            self._active_session_id = self._order[0] if self._order else None
        self._publish_event(
            RuntimeEvent(type=RuntimeEventType.SESSION_CLOSED, session_id=session_id)
        )
        await self.publish_state()
        return True

    # -- turns -------------------------------------------------------------

    @property
    def command_runner(self) -> Any:
        """Lazily built slash-command dispatcher (no Textual)."""

        runner = getattr(self, "_command_runner", None)
        if runner is None:
            from ite.runtime.commands import RuntimeCommandRunner

            runner = RuntimeCommandRunner(self)
            self._command_runner = runner
        return runner

    async def submit_prompt(
        self,
        message: str,
        *,
        display_message: str | None = None,
        suppress_user_echo: bool = False,
        session_id: str | None = None,
        add_to_feed: bool = True,
    ) -> None:
        target = self._sessions.get(session_id) if session_id else self._active_session()
        if target is None:
            target = await self.ensure_agent()
        if target is None:
            return

        # A leading "/" is a command, not a prompt — matching the TUI
        # (``_composer.py:1804``). Never route a dropped file path to the registry.
        from ite.runtime.commands import is_slash_command_line

        if (
            not suppress_user_echo
            and is_slash_command_line(message)
        ):
            if add_to_feed and target.session_id == self._active_session_id:
                await self.command_runner.run(message, target.session_id)
            else:
                await self.command_runner.run(message, target.session_id)
            return

        task = asyncio.create_task(
            target.run_turn(
                message,
                display_message=display_message,
                suppress_user_echo=suppress_user_echo,
                add_to_feed=add_to_feed,
            )
        )
        target.run_state.active_turn_task = task
        try:
            await task
        finally:
            if target.run_state.active_turn_task is task:
                target.run_state.active_turn_task = None

    async def cancel_turn(self, session_id: str | None = None) -> None:
        target = self._sessions.get(session_id) if session_id else self._active_session()
        if target is None:
            return
        task = target.run_state.active_turn_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("error cancelling turn for %s", target.session_id)
        target.run_state.active_turn_task = None
        target.run_state.is_turn_running = False
        runtime = getattr(getattr(target.agent, "session", None), "subagent_runtime", None)
        if runtime is not None and hasattr(runtime, "cancel"):
            try:
                await runtime.cancel(run_ids=None)
            except Exception:
                logger.exception("error cancelling subagent runtime")
        self._dirty(target.session_id, "turn_cancelled")

    # -- feeds -------------------------------------------------------------

    def append_command_feed(self, entry: dict[str, Any]) -> None:
        self._remote_command_feed.append(entry)
        if len(self._remote_command_feed) > MAX_REMOTE_COMMAND_FEED:
            del self._remote_command_feed[:-MAX_REMOTE_COMMAND_FEED]
        self._publish_event(
            RuntimeEvent(
                type=RuntimeEventType.COMMAND_FEED_APPENDED,
                session_id=self._active_session_id or "",
                data=dict(entry),
            )
        )

    def start_command_feed_entry(self, command_line: str) -> str:
        """Begin a command-feed entry, matching the TUI's entry shape."""

        self._remote_command_seq += 1
        command_id = f"cmd_{self._remote_command_seq}"
        parts = str(command_line or "").split()
        command_name = parts[0].lower() if parts else ""
        entry = {
            "id": command_id,
            "session_id": self._active_session_id or "",
            "command": str(command_line).strip(),
            "timestamp": utc_now_iso(),
            "status": "running",
            "output": "",
            "metadata": {
                "kind": "generic",
                "command_name": command_name,
                "args": parts[1:],
            },
        }
        self._remote_command_feed.append(entry)
        if len(self._remote_command_feed) > MAX_REMOTE_COMMAND_FEED:
            del self._remote_command_feed[:-MAX_REMOTE_COMMAND_FEED]
        return command_id

    def finish_command_feed_entry(
        self, command_id: str, *, status: str, output: str
    ) -> None:
        for entry in self._remote_command_feed:
            if entry.get("id") != command_id:
                continue
            entry["status"] = status
            final_output = str(output or "").strip()
            if final_output:
                entry["output"] = final_output
            break
        self._publish_event(
            RuntimeEvent(
                type=RuntimeEventType.COMMAND_FEED_APPENDED,
                session_id=self._active_session_id or "",
                data={"id": command_id, "status": status, "output": str(output or "")},
            )
        )

    def append_change_feed(self, entry: dict[str, Any]) -> None:
        self._remote_change_feed.append(entry)
        if len(self._remote_change_feed) > MAX_REMOTE_CHANGE_FEED:
            del self._remote_change_feed[:-MAX_REMOTE_CHANGE_FEED]
        self._publish_event(
            RuntimeEvent(
                type=RuntimeEventType.CHANGE_FEED_APPENDED,
                session_id=self._active_session_id or "",
                data=dict(entry),
            )
        )

    # -- snapshot (port of ``_build_remote_runtime_state``) ----------------

    def snapshot(self) -> dict[str, Any]:
        active = self._active_session()
        session = active.session if active is not None else None
        run_state = active.run_state if active is not None else None
        active_session_id = self._active_session_id

        transcript: list[dict[str, Any]] = []
        if session is not None and session.context_manager is not None:
            try:
                transcript_state = session.context_manager.export_transcript_state()
            except Exception:
                transcript_state = {}
            transcript = build_remote_transcript(
                transcript_state.get("events", [])
                if isinstance(transcript_state, dict)
                else []
            )

        open_sessions: list[dict[str, Any]] = []
        for session_id in self._order:
            runtime_session = self._sessions.get(session_id)
            if runtime_session is None:
                continue
            open_sessions.append(
                {
                    "session_id": session_id,
                    "title": self._session_title(runtime_session.session),
                    "turn_count": int(
                        getattr(runtime_session.session, "turn_count", 0) or 0
                    ),
                    "is_active": session_id == active_session_id,
                    "workspace": str(runtime_session.workspace),
                    "is_running": bool(runtime_session.is_turn_running),
                }
            )

        return {
            "app": {"name": "iTE", "surface": "runtime"},
            "current_session": {
                "session_id": active_session_id or "",
                "title": self._session_title(session),
                "workspace": str(self.config.cwd.resolve()),
                "model": str(self.config.model_name or ""),
                "approval_mode": str(self.config.approval.value),
                "plan_mode_enabled": bool(session.plan_mode_enabled) if session else False,
                "plan_phase": str(session.plan_phase) if session else "idle",
                "active_turn_id": int(run_state.active_turn_id) if run_state else 0,
                "is_turn_running": bool(run_state.is_turn_running) if run_state else False,
                "activity_label": self._activity_label(),
                "activity_busy": self._activity_busy(),
                "awaiting_shell_input": self._awaiting_shell_input(),
                "turn_had_error": bool(run_state.turn_had_error) if run_state else False,
                "last_error_message": str(run_state.last_error_message or "")
                if run_state
                else "",
            },
            "open_sessions": open_sessions,
            "transcript": transcript,
            "command_feed": list(self._remote_command_feed),
            "change_feed": list(self._remote_change_feed),
        }

    # -- agent construction ------------------------------------------------

    def build_session_agent(self, session: Session) -> Agent:
        session_id = self._session_id(session) or ""

        async def _confirm(confirmation, sid: str = session_id) -> bool:
            return await self._handle_confirmation(sid, confirmation)

        async def _plan_question(
            payload: dict[str, Any], sid: str = session_id
        ) -> dict[str, Any]:
            return await self._handle_plan_question(sid, payload)

        agent_config = getattr(session, "config", None) or self.config
        return Agent(
            config=agent_config,
            session=session,
            confirmation_callback=_confirm,
            plan_question_callback=_plan_question,
        )

    async def _handle_confirmation(self, session_id: str, confirmation) -> bool:
        if session_id and session_id != self._active_session_id:
            await self.activate_session(session_id)
        self._broker.set_interactive_clients(self.bus.interactive_clients())
        diff = getattr(confirmation, "diff", None)
        request = ApprovalRequest(
            request_id="",
            session_id=session_id,
            tool_name=str(getattr(confirmation, "tool_name", "") or "tool"),
            description=str(getattr(confirmation, "description", "") or ""),
            command=getattr(confirmation, "command", None),
            diff=diff.to_diff() if diff is not None else None,
        )
        approved = await self._broker.request_approval(request)
        await self.publish_state()
        return bool(approved)

    async def _handle_plan_question(
        self, session_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if session_id and session_id != self._active_session_id:
            await self.activate_session(session_id)
        self._broker.set_interactive_clients(self.bus.interactive_clients())
        runtime_session = self._sessions.get(session_id)
        session = runtime_session.session if runtime_session is not None else None
        question_number = int(
            payload.get("question_number")
            or (
                (getattr(session, "plan_questions_asked", 0) + 1)
                if session is not None
                else 1
            )
        )
        request = PlanQuestion(
            request_id="",
            session_id=session_id,
            question=str(payload.get("question", "")).strip(),
            options=[str(o) for o in payload.get("options", []) if str(o).strip()],
            recommended_index=payload.get("recommended_index"),
            allow_free_text=bool(payload.get("allow_free_text", True)),
            question_number=question_number,
        )
        return await self._broker.request_plan_question(request)

    # -- config ------------------------------------------------------------

    def session_config_for_workspace(self, workspace: Path | None = None) -> Config:
        resolved_workspace = Path(workspace or self.config.cwd).resolve()
        workspace_config = load_config(resolved_workspace)
        return workspace_config.model_copy(
            update={
                "cwd": resolved_workspace,
                "model": self.config.model.model_copy(deep=True),
                "voice": self.config.voice.model_copy(deep=True),
                "api_key": self.config.api_key,
                "base_url": self.config.base_url,
                "cloud_auth_enabled": self.config.cloud_auth_enabled,
                "cloud_api_url": self.config.cloud_api_url,
                "cloud_client_id": self.config.cloud_client_id,
                "cloud_device_name": self.config.cloud_device_name,
                "approval": self.config.approval,
                "sandbox": self.config.sandbox.model_copy(deep=True),
                "debug": self.config.debug,
                "resume_last_session": self.config.resume_last_session,
            },
            deep=False,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _session_id(session: Session | None) -> str | None:
        if session is None:
            return None
        session_id = str(getattr(session, "session_id", "") or "").strip()
        return session_id or None

    @staticmethod
    def _session_title(session: Session | None) -> str:
        if session is None:
            return "New thread"
        name = getattr(session, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()
        if int(getattr(session, "turn_count", 0) or 0) > 0:
            return "Untitled thread"
        return "New thread"

    def _activity_label(self) -> str:
        if self.activity_provider is None:
            return ""
        try:
            return str(self.activity_provider() or "")
        except Exception:
            return ""

    def _activity_busy(self) -> bool:
        if self.activity_busy_provider is None:
            return False
        try:
            return bool(self.activity_busy_provider())
        except Exception:
            return False

    def _awaiting_shell_input(self) -> bool:
        if self.awaiting_shell_input_provider is None:
            return False
        try:
            return bool(self.awaiting_shell_input_provider())
        except Exception:
            return False

    def _publish_event(self, event: RuntimeEvent) -> None:
        self.bus.publish(event)

    def _publish_broker_event(self, event_type: str, data: dict[str, Any]) -> None:
        mapped = _BROKER_EVENT_TYPES.get(event_type)
        if mapped is None:
            return
        self.bus.publish(
            RuntimeEvent(
                type=mapped,
                session_id=str(data.get("session_id", "") or ""),
                data=dict(data),
            )
        )

    def _on_session_state_dirty(self, reason: str) -> None:
        self._dirty(self._active_session_id or "", reason)

    def _dirty(self, session_id: str, reason: str) -> None:
        self.bus.publish(RuntimeEvent.state_changed(session_id=session_id, reason=reason))
