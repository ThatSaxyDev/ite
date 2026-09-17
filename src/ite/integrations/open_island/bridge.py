from __future__ import annotations

import asyncio
import atexit
import logging
from pathlib import Path
from typing import Any

from ite.agent.events import AgentEvent, AgentEventType
from ite.integrations.open_island import payloads
from ite.integrations.open_island.client import (
    OpenIslandClient,
    hooks_disabled,
)
from ite.integrations.open_island.terminal import TerminalContext, detect_terminal
from ite.ui.tool_narrative import progress_label

logger = logging.getLogger(__name__)

# Bounded queue: the bridge must never grow without limit if the socket stalls.
# Dropping events is the correct fail-open behaviour — a missed summary update
# is invisible to the user, a blocked agent turn is not.
_QUEUE_MAXSIZE = 256

# How long the interactive path waits for the worker to drain before it opens
# its own parked exchange. `PreToolUse` must reach the server first so the
# tool-use badge and the row's tool label are in place.
_QUEUE_DRAIN_TIMEOUT_SECONDS = 2.0

# Ceiling on a parked approval/question. Upstream parks indefinitely; this is
# our own resource bound, long enough that the local modal effectively decides.
_ATTENTION_TIMEOUT_SECONDS = 600.0

# How often the reasoning label is refreshed. The TUI rotates its gerund on a
# 4.5s timer (`app.py:825` -> `_panels.py:2031`); matching it keeps the island
# feeling alive instead of frozen on whichever word it first showed.
_ROTATION_INTERVAL_SECONDS = 4.5

_WORKER_IDLE_SENTINEL = object()


class OpenIslandBridge:
    """Mirrors an iTE session into Open Island's notch overlay.

    Subscribes to the ``AgentEvent`` stream and translates it into the
    Claude-shaped hook payload Open Island understands.

    Three invariants, all load-bearing:

    1. **Fail-open.** No method raises. If Open Island is absent, stopped, or
       wedged, iTE behaves exactly as it does today.
    2. **Non-blocking.** :meth:`observe` only enqueues. All socket I/O happens
       on a background worker, so the agent turn is never delayed.
    3. **No leaking.** A session is only removed from the notch by an explicit
       ``SessionEnd``, so teardown is registered at construction time.
    """

    def __init__(
        self,
        session_id: str,
        cwd: Path | str,
        *,
        enabled: bool = False,
        client: OpenIslandClient | None = None,
        model: str | None = None,
        terminal: TerminalContext | None = None,
        platform: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.cwd = str(cwd)
        self.model = model
        self._enabled = bool(enabled) and not hooks_disabled()
        self._platform = platform
        self._client = client or OpenIslandClient()

        self._terminal = terminal

        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._worker: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        self._closed = False
        self._session_announced = False
        self._atexit_registered = False
        # The island has no free-text activity field: its status line is derived
        # solely from `currentTool`. During reasoning there is no tool, so we
        # synthesise one carrying iTE's wording. That wording is refreshed on a
        # timer (see _rotate_activity) because the TUI's rotation is timer-driven
        # rather than event-driven — no event stream can reproduce it.
        self._rotation_task: asyncio.Task[None] | None = None
        self._last_activity_label: str | None = None
        # Count of tool calls that have started but not yet completed. Rotation
        # pauses while non-zero so it cannot overwrite a live tool's label.
        self._tools_in_flight = 0
        # Last known call id per tool name, so the interactive approval path can
        # carry `tool_use_id` without threading it through the safety layer.
        self._last_call_id_by_tool: dict[str, str] = {}

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _resolve_terminal(self) -> TerminalContext:
        if self._terminal is None:
            self._terminal = detect_terminal()
        return self._terminal

    def _ensure_started(self) -> None:
        """Lazily create the worker task on first observation."""
        if self._started or not self._enabled or self._closed:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Observed outside a loop; the bridge cannot work and must not
            # break the caller.
            self._enabled = False
            return

        self._loop = loop
        self._started = True

        if not self._atexit_registered:
            try:
                atexit.register(self.close)
                self._atexit_registered = True
            except Exception:  # noqa: BLE001 - teardown registration is best-effort
                logger.debug("Open Island bridge could not register teardown")

        self._worker = loop.create_task(self._run_worker())

    def observe(self, event: AgentEvent) -> None:
        """Forward an agent event. Never raises, never blocks."""
        if not self._enabled or self._closed:
            return

        try:
            self._ensure_started()
            if not self._started:
                return
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("Open Island bridge queue full; dropping event")
        except Exception as exc:  # noqa: BLE001 - fail-open is the contract
            logger.debug("Open Island bridge observe failed: %s", exc)

    async def aclose(self) -> None:
        """Flush pending events and remove the session from the notch."""
        if self._closed:
            return
        self._closed = True

        self._stop_rotation()

        if self._worker is not None and not self._worker.done():
            try:
                await asyncio.wait_for(self._queue.join(), timeout=1.5)
            except (TimeoutError, asyncio.CancelledError):
                pass

        await self._send(
            payloads.command(
                payloads.session_end(
                    self.session_id,
                    self.cwd,
                    self._terminal,
                )
            )
        )

        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown path
                logger.debug("Open Island bridge worker ended during shutdown")
            self._worker = None

    def close(self) -> None:
        """Synchronous teardown for ``atexit``. Never raises."""
        if self._closed:
            return
        self._closed = True

        if not self._enabled:
            return

        try:
            self._client.send_sync(
                payloads.command(
                    payloads.session_end(
                        self.session_id,
                        self.cwd,
                        self._terminal,
                    )
                ),
                timeout=1.5,
            )
        except Exception as exc:  # noqa: BLE001 - teardown must never raise
            logger.debug("Open Island bridge teardown failed: %s", exc)

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------

    async def _run_worker(self) -> None:
        while True:
            try:
                item = await self._queue.get()
            except asyncio.CancelledError:
                return

            try:
                if item is not _WORKER_IDLE_SENTINEL:
                    await self._handle(item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad event must not kill the worker
                logger.debug("Open Island bridge worker error: %s", exc)
            finally:
                self._queue.task_done()

    async def _send(self, command: dict[str, Any]) -> dict[str, Any] | None:
        if not self._enabled:
            return None
        try:
            return await self._client.try_send(command)
        except Exception as exc:  # noqa: BLE001 - fail-open is the contract
            logger.debug("Open Island bridge send failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # interactive (user-attention) exchanges
    #
    # These deliberately bypass the worker queue. Invariant #2 ("observe only
    # enqueues") exists so lifecycle events never delay an agent turn; here
    # delay *is* the point, and the worker must stay free to drain lifecycle
    # events while the human decides. Each method runs as its own task and
    # returns a sentinel instead of raising, so the local modal always remains
    # a valid racer.
    # ------------------------------------------------------------------

    async def _drain_queue(self) -> None:
        """Wait, bounded, for already-enqueued events to be sent.

        Ensures the `PreToolUse` emitted at `TOOL_CALL_START` reaches the server
        before the interactive `PermissionRequest`, which is what populates the
        tool-use correlation and the row's tool label.
        """
        if self._worker is None or self._worker.done():
            return
        try:
            await asyncio.wait_for(
                self._queue.join(), timeout=_QUEUE_DRAIN_TIMEOUT_SECONDS
            )
        except TimeoutError:
            logger.debug("Open Island bridge queue drain timed out")
        except asyncio.CancelledError:
            raise

    async def request_approval(
        self,
        *,
        tool_name: str,
        summary: str,
        title: str | None = None,
        affected_path: str | None = None,
        tool_use_id: str | None = None,
        timeout: float = _ATTENTION_TIMEOUT_SECONDS,
    ) -> str:
        """Park a permission request and return ``approved``/``denied``/``unavailable``.

        ``"unavailable"`` means only that the island did not answer — never that
        the operation was refused. Callers must not map it to a denial.
        """
        if not self._enabled or self._closed:
            return "unavailable"

        await self._drain_queue()
        if not self._enabled or self._closed:
            return "unavailable"

        if tool_use_id is None:
            tool_use_id = self._last_call_id_by_tool.get(tool_name)

        command = payloads.command(
            payloads.permission_request(
                self.session_id,
                self.cwd,
                title=title,
                summary=summary,
                affected_path=affected_path,
                tool_use_id=tool_use_id,
                terminal=self._resolve_terminal(),
            )
        )
        try:
            response = await self._client.send_interactive(command, timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail-open is the contract
            logger.debug("Open Island approval exchange failed: %s", exc)
            return "unavailable"

        return payloads.parse_permission_directive(response) or "unavailable"

    async def request_question(
        self,
        *,
        question: str,
        options: list[str],
        recommended_index: int | None = None,
        tool_name: str = "plan_question",
        timeout: float = _ATTENTION_TIMEOUT_SECONDS,
    ) -> dict[str, Any] | None:
        """Park a question and return the local card's result shape, or ``None``.

        ``None`` means the island did not answer; the local card stays pending.
        """
        if not self._enabled or self._closed:
            return None

        await self._drain_queue()
        if not self._enabled or self._closed:
            return None

        command = payloads.command(
            payloads.question_request(
                self.session_id,
                self.cwd,
                question=question,
                options=options,
                recommended_index=recommended_index,
                tool_use_id=self._last_call_id_by_tool.get(tool_name),
                terminal=self._resolve_terminal(),
            )
        )
        try:
            response = await self._client.send_interactive(command, timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail-open is the contract
            logger.debug("Open Island question exchange failed: %s", exc)
            return None

        return payloads.parse_question_directive(
            response, question=question, options=options
        )

    # ------------------------------------------------------------------
    # reasoning-label rotation
    # ------------------------------------------------------------------

    def _start_rotation(self) -> None:
        """Begin refreshing the reasoning label while a turn is running.

        The TUI's rotation is driven by a timer (`app.py:825` ->
        `_panels.py:2031`), not by events, so the only faithful reproduction is
        a timer here too. Without it the island freezes on whichever word it
        happened to show first, which is what made it look dead during pauses.
        """
        if self._rotation_task is not None and not self._rotation_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._rotation_task = loop.create_task(self._rotate_activity())

    def _stop_rotation(self) -> None:
        if self._rotation_task is not None:
            self._rotation_task.cancel()
            self._rotation_task = None

    async def _rotate_activity(self) -> None:
        while True:
            try:
                await asyncio.sleep(_ROTATION_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                return

            # Never overwrite a live tool's label.
            if self._tools_in_flight > 0 or self._closed:
                continue

            try:
                await self._send(
                    payloads.command(
                        payloads.activity_status(
                            self.session_id,
                            self.cwd,
                            self._next_activity_label(),
                            self._terminal,
                        )
                    )
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001 - rotation is best-effort
                logger.debug("Open Island activity rotation failed: %s", exc)

    def _next_activity_label(self) -> str:
        """Draw a fresh gerund, avoiding an immediate repeat."""
        label = self._activity_label()
        if label == self._last_activity_label:
            for _ in range(4):
                candidate = self._activity_label()
                if candidate != self._last_activity_label:
                    label = candidate
                    break
        self._last_activity_label = label
        return label

    async def _handle(self, event: AgentEvent) -> None:
        for command in self._commands_for(event):
            await self._send(payloads.command(command))

    # ------------------------------------------------------------------
    # event mapping
    # ------------------------------------------------------------------

    def _commands_for(self, event: AgentEvent) -> list[dict[str, Any]]:
        """Translate one agent event into zero or more hook payloads."""
        event_type = event.type
        data = event.data or {}

        if event_type == AgentEventType.AGENT_START:
            return self._on_agent_start(data)
        if event_type == AgentEventType.TOOL_CALL_START:
            return self._on_tool_start(data)
        if event_type == AgentEventType.TOOL_CALL_COMPLETE:
            return self._on_tool_complete(data)
        if event_type == AgentEventType.AGENT_END:
            return self._on_agent_end(data)
        if event_type == AgentEventType.AGENT_ERROR:
            return self._on_agent_error(data)
        if event_type == AgentEventType.CONTEXT_COMPACTED:
            return self._on_compacted()

        # TEXT_DELTA, TOOL_CALL_PROGRESS, PLAN_READY, USAGE_UPDATE,
        # LOOP_DETECTED and the rest are intentionally unmapped: they add
        # socket chatter without changing what the notch shows.
        return []

    def _on_agent_start(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        terminal = self._resolve_terminal()
        message = data.get("message")

        # A new turn begins: start the timer that keeps the reasoning label
        # moving, matching the TUI's rotation.
        self._start_rotation()

        # SessionStart is emitted once per iTE session. AGENT_START/AGENT_END
        # bracket a *turn*, so re-sending SessionStart each turn would churn
        # the notch entry instead of keeping one stable bubble.
        if self._session_announced:
            commands: list[dict[str, Any]] = []
        else:
            self._session_announced = True
            commands = [
                payloads.session_start(
                    self.session_id,
                    self.cwd,
                    terminal,
                    model=self.model,
                )
            ]

        if isinstance(message, str) and message.strip():
            commands.append(
                payloads.user_prompt_submit(
                    self.session_id,
                    self.cwd,
                    message,
                    terminal,
                )
            )

        # Last in the batch on purpose: `UserPromptSubmit` can clear the
        # island's `currentTool`, and this is what populates it for the
        # reasoning phase. Without it the island falls back to "Thinking"
        # while iTE's own TUI shows a specific gerund.
        commands.append(
            payloads.activity_status(
                self.session_id,
                self.cwd,
                self._activity_label(),
                terminal,
            )
        )
        return commands

    def _activity_label(self) -> str:
        """One piece of iTE's reasoning wording.

        Reuses the same `progress_label` vocabulary the TUI and the remote host
        use (`remote/host.py:377-391` already delegates to it for this reason),
        so the island shows iTE's wording rather than its generic fallback.

        Intentionally *not* cached: the TUI varies this wording as a turn
        proceeds, and the island should follow. Caching it was the earlier
        mistake — it made the island freeze on the first word it showed.
        """
        try:
            return progress_label()
        except Exception:  # noqa: BLE001 - wording must never break the bridge
            logger.debug("Open Island activity label resolution failed")
            return "Working"

    def _on_tool_start(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        name = data.get("name")
        if not isinstance(name, str) or not name:
            return []

        arguments = data.get("arguments")
        if not isinstance(arguments, dict):
            arguments = None

        call_id = data.get("call_id")
        if isinstance(call_id, str) and call_id:
            self._last_call_id_by_tool[name] = call_id

        # Rotation pauses while a tool is live so it cannot overwrite the tool's
        # own label with a gerund.
        self._tools_in_flight += 1

        return [
            payloads.pre_tool_use(
                self.session_id,
                self.cwd,
                name,
                arguments,
                data.get("call_id"),
                self._terminal,
            )
        ]

    def _on_tool_complete(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        name = data.get("name")
        if not isinstance(name, str) or not name:
            return []

        output = data.get("output")
        error = data.get("error")

        # Tool finished: rotation may resume on its next tick.
        if self._tools_in_flight > 0:
            self._tools_in_flight -= 1

        return [
            payloads.post_tool_use(
                self.session_id,
                self.cwd,
                name,
                data.get("call_id"),
                output=output if isinstance(output, str) else None,
                success=bool(data.get("success", True)),
                error=error if isinstance(error, str) else None,
                terminal=self._terminal,
            )
        ]

    def _on_agent_end(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        response = data.get("response")
        # Turn over: stop the timer so the label does not keep mutating on a
        # finished session.
        self._stop_rotation()
        return [
            payloads.stop(
                self.session_id,
                self.cwd,
                self._terminal,
                last_assistant_message=response if isinstance(response, str) else None,
            )
        ]

    def _on_agent_error(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        error = data.get("error")
        # Turn failed: stop the timer as well, so a session that never sends
        # AGENT_END does not keep rotating forever.
        self._stop_rotation()
        return [
            payloads.stop_failure(
                self.session_id,
                self.cwd,
                error if isinstance(error, str) else "Agent error",
                self._terminal,
            )
        ]

    def _on_compacted(self) -> list[dict[str, Any]]:
        return [
            payloads.pre_compact(
                self.session_id,
                self.cwd,
                self._terminal,
            ),
            # Compaction is a distinct phase with its own wording in the TUI,
            # so carry it rather than leaving the island on a stale tool label.
            payloads.activity_status(
                self.session_id,
                self.cwd,
                "Compacting context",
                self._terminal,
            ),
        ]


def build_bridge(
    session_id: str | None,
    cwd: Path | str,
    *,
    enabled: bool,
    model: str | None = None,
    client: OpenIslandClient | None = None,
) -> OpenIslandBridge | None:
    """Construct a bridge when the integration is enabled, else ``None``.

    Returning ``None`` keeps the disabled path allocation-free and makes the
    caller's wiring a single assignment.
    """
    if not enabled or not session_id:
        return None
    return OpenIslandBridge(
        session_id=session_id,
        cwd=cwd,
        enabled=True,
        client=client,
        model=model,
    )
