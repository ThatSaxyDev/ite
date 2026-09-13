from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import Awaitable
from typing import Callable

from ite.agent.agent import Agent
from ite.agent.events import AgentEvent, AgentEventType
from ite.agent.session import Session
from ite.config.config import Config
from ite.config.loader import ensure_workspace_layout, load_config
from ite.ui.tool_narrative import progress_label

from .protocol import (
    build_remote_transcript,
    serialize_agent_event,
    serialize_approval_request,
    serialize_plan_question_request,
    serialize_plan_ready_request,
)
from .server import RemoteRuntimeServer

logger = logging.getLogger(__name__)

_APPROVAL_TIMEOUT_SECONDS = 300.0
_PLAN_QUESTION_TIMEOUT_SECONDS = 600.0
_PLAN_READY_TIMEOUT_SECONDS = 600.0
_COMMAND_FEED_LIMIT = 30
_CHANGE_FEED_LIMIT = 30
_SHELL_TOOL_NAMES = {"shell", "run_shell", "bash", "terminal"}
_ACCESS_CACHE_SECONDS = 60.0


@dataclass
class HostRunState:
    active_turn_id: int = 0
    is_turn_running: bool = False
    turn_had_error: bool = False
    last_error_message: str = ""
    activity_label: str = ""
    activity_busy: bool = False


@dataclass
class HeadlessRuntimeHost:
    """Owns one agent session and exposes it to a :class:`RemoteRuntimeServer`.

    This is the no-TUI counterpart of the reup app's remote wiring: the same
    server frames, the same state payload, but driven by callbacks the mobile
    client sends over the relay. It deliberately supports a single active
    session, which matches the "attach to my runtime" model.
    """

    config: Config
    cwd: Path
    session_provider: Any = None
    access_checker: Callable[[], Awaitable[bool]] | None = None
    _session: Session | None = field(default=None, init=False)
    _agent: Agent | None = field(default=None, init=False)
    _server: RemoteRuntimeServer | None = field(default=None, init=False)
    _run_state: HostRunState = field(default_factory=HostRunState, init=False)
    _turn_task: asyncio.Task[None] | None = field(default=None, init=False)
    _command_feed: list[dict[str, Any]] = field(default_factory=list, init=False)
    _change_feed: list[dict[str, Any]] = field(default_factory=list, init=False)
    _command_seq: int = field(default=0, init=False)
    _change_seq: int = field(default=0, init=False)
    _access_cache: tuple[bool, float] | None = field(default=None, init=False)

    @classmethod
    def create(
        cls,
        *,
        cwd: Path | None = None,
        session_provider: Any = None,
        access_checker: Callable[[], Awaitable[bool]] | None = None,
    ) -> "HeadlessRuntimeHost":
        workspace = (cwd or Path.cwd()).resolve()
        ensure_workspace_layout(workspace)
        config = load_config(cwd=workspace)
        return cls(
            config=config,
            cwd=workspace,
            session_provider=session_provider,
            access_checker=access_checker,
        )

    async def start(self) -> RemoteRuntimeServer:
        if self._agent is None:
            await self._ensure_agent()
        server = RemoteRuntimeServer(
            state_provider=self.build_state,
            submit_prompt=self.submit_prompt,
            cancel_turn=self.cancel_turn,
            switch_session=self.switch_session,
            access_checker=self.access_checker or self._has_remote_access,
            transport="relay",
        )
        server.ensure_identity()
        self._server = server
        return server

    @property
    def server(self) -> RemoteRuntimeServer:
        if self._server is None:
            raise RuntimeError("Host has not been started.")
        return self._server

    @property
    def session(self) -> Session | None:
        return self._session

    async def _ensure_agent(self) -> None:
        if self._agent is not None:
            return
        session = Session(config=self.config, session_provider=self.session_provider)
        agent = Agent(
            config=self.config,
            session=session,
            confirmation_callback=self.confirmation_callback,
            plan_question_callback=self.plan_question_callback,
        )
        await agent.__aenter__()
        self._session = agent.session
        self._agent = agent

    async def _has_remote_access(self) -> bool:
        now = time.monotonic()
        if self._access_cache is not None:
            cached, checked_at = self._access_cache
            if now - checked_at < _ACCESS_CACHE_SECONDS:
                return cached
        from ite.cloud.auth import get_remote_companion_access_status

        try:
            status = await asyncio.to_thread(
                get_remote_companion_access_status, self.config
            )
            valid = bool(getattr(status, "is_valid", False))
        except Exception:
            valid = False
        self._access_cache = (valid, now)
        return valid

    # ------------------------------------------------------------------ state

    def build_state(self) -> dict[str, Any]:
        session = self._session
        transcript: list[dict[str, Any]] = []
        if session is not None and session.context_manager is not None:
            transcript_state = session.context_manager.export_transcript_state()
            transcript = build_remote_transcript(
                transcript_state.get("events", [])
                if isinstance(transcript_state, dict)
                else []
            )

        session_id = str(getattr(session, "session_id", "") or "")
        run_state = self._run_state
        return {
            "app": {"name": "iTE", "surface": "cloud"},
            "current_session": {
                "session_id": session_id,
                "title": self._session_title(),
                "workspace": str(self.cwd),
                "model": str(self.config.model_name or ""),
                "approval_mode": str(self.config.approval.value),
                "plan_mode_enabled": bool(session.plan_mode_enabled) if session else False,
                "plan_phase": str(session.plan_phase) if session else "idle",
                "active_turn_id": int(run_state.active_turn_id),
                "is_turn_running": bool(run_state.is_turn_running),
                "activity_label": str(run_state.activity_label or ""),
                "activity_busy": bool(run_state.activity_busy),
                "awaiting_shell_input": False,
                "turn_had_error": bool(run_state.turn_had_error),
                "last_error_message": str(run_state.last_error_message or ""),
            },
            "open_sessions": [
                {
                    "session_id": session_id,
                    "title": self._session_title(),
                    "turn_count": int(getattr(session, "turn_count", 0) or 0),
                    "is_active": True,
                    "workspace": str(self.cwd),
                    "is_running": bool(run_state.is_turn_running),
                }
            ]
            if session_id
            else [],
            "transcript": transcript,
            "command_feed": list(self._command_feed),
            "change_feed": list(self._change_feed),
        }

    def _session_title(self) -> str:
        session = self._session
        if session is None:
            return "iTE Cloud Runtime"
        title = str(getattr(session, "title", "") or "").strip()
        return title or self.cwd.name or "iTE Cloud Runtime"

    # ------------------------------------------------------------------- turns

    async def submit_prompt(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        await self._ensure_agent()
        if self._run_state.is_turn_running:
            # A turn is already running; queueing prompts is out of scope for now.
            logger.info("Ignoring prompt while a turn is running")
            return
        await self._start_turn(text)

    async def _start_turn(self, message: str) -> None:
        assert self._session is not None
        self._run_state.active_turn_id += 1
        turn_id = self._run_state.active_turn_id
        self._run_state.is_turn_running = True
        self._run_state.turn_had_error = False
        self._run_state.last_error_message = ""
        self._run_state.activity_busy = True
        self._run_state.activity_label = "Thinking"
        await self._publish_state()
        self._turn_task = asyncio.create_task(self._run_turn(message, turn_id))

    async def _run_turn(self, message: str, turn_id: int) -> None:
        assert self._agent is not None and self._session is not None
        session_id = str(self._session.session_id)
        pending_execute = False
        try:
            async for event in self._agent.run(message):
                await self._handle_event(event, session_id=session_id, turn_id=turn_id)
                if event.type == AgentEventType.PLAN_READY:
                    pending_execute = await self._handle_plan_ready(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._run_state.turn_had_error = True
            self._run_state.last_error_message = str(exc)
            logger.exception("Headless turn failed")
            await self._publish_event(
                {
                    "protocol_version": 1,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": {
                        "type": AgentEventType.AGENT_ERROR.value,
                        "data": {"message": str(exc)},
                    },
                }
            )
        finally:
            self._run_state.is_turn_running = False
            self._run_state.activity_busy = False
            self._run_state.activity_label = ""
            self._turn_task = None
            self._append_change_feed()
            await self._publish_state()

        if pending_execute:
            await self._start_turn(Agent.PLAN_EXECUTE_PROMPT)

    async def _handle_event(
        self, event: AgentEvent, *, session_id: str, turn_id: int
    ) -> None:
        self._track_activity(event)
        if event.type == AgentEventType.TOOL_CALL_START:
            self._on_tool_start(event)
        elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
            self._on_tool_complete(event)
        await self._publish_event(
            serialize_agent_event(event, session_id=session_id, turn_id=turn_id)
        )

    def _track_activity(self, event: AgentEvent) -> None:
        """Publish the same action wording the interactive runtime shows.

        The TUI names the specific action ("Searching code", "Running tests")
        and uses varied gerunds while reasoning. Reusing `progress_label` keeps
        the remote identical to the local experience instead of flattening every
        state to a single "Thinking".
        """
        if event.type == AgentEventType.TOOL_CALL_START:
            name = str(event.data.get("name") or "")
            arguments = event.data.get("arguments")
            self._run_state.activity_label = progress_label(
                tool_name=name,
                arguments=arguments if isinstance(arguments, dict) else None,
            )
        elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
            name = str(event.data.get("name") or "")
            metadata = event.data.get("metadata")
            self._run_state.activity_label = progress_label(
                tool_name=name,
                metadata=metadata if isinstance(metadata, dict) else None,
                phase="post_tool",
            )
        elif event.type == AgentEventType.TEXT_DELTA:
            self._run_state.activity_label = "Writing"
        elif event.type == AgentEventType.PLAN_READY:
            self._run_state.activity_label = "Plan ready"
        else:
            self._run_state.activity_label = progress_label()

    def _on_tool_start(self, event: AgentEvent) -> None:
        name = str(event.data.get("name") or "")
        arguments = event.data.get("arguments")
        command = ""
        if isinstance(arguments, dict):
            command = str(arguments.get("command") or "").strip()
        if not command or name.lower() not in _SHELL_TOOL_NAMES:
            return
        self._command_seq += 1
        self._command_feed.append(
            {
                "id": f"cmd_{self._command_seq}",
                "call_id": str(event.data.get("call_id") or ""),
                "session_id": str(getattr(self._session, "session_id", "") or ""),
                "command": command,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "running",
                "output": "",
                "metadata": {
                    "kind": "generic",
                    "command_name": command.split()[0] if command else "",
                    "args": command.split()[1:],
                },
            }
        )
        self._command_feed = self._command_feed[-_COMMAND_FEED_LIMIT:]

    def _on_tool_complete(self, event: AgentEvent) -> None:
        name = str(event.data.get("name") or "")
        if name.lower() not in _SHELL_TOOL_NAMES:
            return
        call_id = str(event.data.get("call_id") or "")
        output = str(event.data.get("output") or "").strip()
        success = bool(event.data.get("success", False))
        for entry in reversed(self._command_feed):
            if entry.get("call_id") != call_id:
                continue
            entry["status"] = "completed" if success else "failed"
            if output:
                entry["output"] = output
            break

    def _append_change_feed(self) -> None:
        session = self._session
        if session is None:
            return
        change_set = getattr(session.change_history, "last_turn_change_set", None)
        if change_set is None or not getattr(change_set, "changes", None):
            return
        try:
            from ite.ui.reup.change_views import build_change_card_payload
        except Exception:
            return
        try:
            payload = build_change_card_payload(
                change_set,
                cwd=self.cwd,
                title="Changes",
                verb="Changed",
                footer="Review in the app.",
                mode="turn",
            )
        except Exception:
            return
        self._change_seq += 1
        self._change_feed.append(
            {
                "id": f"chg_{self._change_seq}",
                "session_id": str(getattr(session, "session_id", "") or ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **payload,
            }
        )
        self._change_feed = self._change_feed[-_CHANGE_FEED_LIMIT:]

    async def cancel_turn(self) -> None:
        task = self._turn_task
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def switch_session(self, session_id: str) -> bool:
        # Single-runtime model: only the active session exists.
        return bool(session_id) and session_id == str(
            getattr(self._session, "session_id", "") or ""
        )

    async def _publish_state(self) -> None:
        if self._server is not None:
            await self._server.publish_state()

    async def _publish_event(self, payload: dict[str, Any]) -> None:
        if self._server is not None:
            await self._server.publish_event(payload)

    # -------------------------------------------------------------- approvals

    def _active_session_id(self) -> str:
        return str(getattr(self._session, "session_id", "") or "")

    async def confirmation_callback(self, confirmation: Any) -> bool:
        server = self._server
        if server is None or not server.has_authenticated_clients():
            # No mobile client to ask. Deny rather than silently running a
            # destructive tool in a headless, multi-tenant runtime.
            logger.warning(
                "Denying %s approval: no remote client attached",
                getattr(confirmation, "tool_name", "tool"),
            )
            return False

        request_id = uuid.uuid4().hex
        diff = confirmation.diff.to_diff() if getattr(confirmation, "diff", None) else None
        result = await server.request_approval(
            serialize_approval_request(
                request_id=request_id,
                tool_name=str(getattr(confirmation, "tool_name", "") or "tool"),
                description=str(getattr(confirmation, "description", "") or ""),
                command=getattr(confirmation, "command", None),
                diff=diff,
                session_id=self._active_session_id(),
            ),
            timeout=_APPROVAL_TIMEOUT_SECONDS,
        )
        await self._publish_state()
        return bool(result)

    async def plan_question_callback(self, payload: dict[str, Any]) -> dict[str, Any]:
        empty = {"selected_option": "", "free_text": "", "selected_index": None}
        server = self._server
        if server is None or not server.has_authenticated_clients():
            return empty
        session = self._session
        question_number = int(
            payload.get("question_number")
            or (
                (session.plan_questions_asked + 1)
                if session is not None
                else 1
            )
        )
        result = await server.request_plan_question(
            serialize_plan_question_request(
                request_id=uuid.uuid4().hex,
                session_id=self._active_session_id(),
                question=str(payload.get("question", "")),
                options=[str(o) for o in payload.get("options", []) if str(o).strip()],
                recommended_index=payload.get("recommended_index"),
                allow_free_text=bool(payload.get("allow_free_text", True)),
                question_number=question_number,
            ),
            timeout=_PLAN_QUESTION_TIMEOUT_SECONDS,
        )
        return result or empty

    async def _handle_plan_ready(self, event: AgentEvent) -> bool:
        """Ask the client to approve the plan; return True to auto-execute."""
        session = self._session
        if session is None:
            return False
        plan_text = str(event.data.get("plan_text") or "")
        if not plan_text.strip():
            return False

        server = self._server
        approved = False
        if server is not None and server.has_authenticated_clients():
            result = await server.request_plan_ready(
                serialize_plan_ready_request(
                    request_id=uuid.uuid4().hex,
                    session_id=self._active_session_id(),
                    plan_text=plan_text,
                    question_count=int(session.plan_questions_asked),
                ),
                timeout=_PLAN_READY_TIMEOUT_SECONDS,
            )
            approved = bool(result)

        if approved:
            session.seed_execution_todos_from_plan(session.pending_plan_text or plan_text)
            session.promote_pending_plan_to_active()
            session.set_plan_mode(False)
            session.set_plan_phase("executing")
        else:
            session.set_plan_phase("awaiting_implementation_confirmation")
        await self._publish_state()
        return approved

    async def shutdown(self) -> None:
        await self.cancel_turn()
        if self._server is not None:
            await self._server.stop()
            self._server = None
        if self._agent is not None:
            with contextlib.suppress(Exception):
                await self._agent.__aexit__(None, None, None)
            self._agent = None
            self._session = None
