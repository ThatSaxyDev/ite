"""Approval broker for the runtime host.

Phase 3 of ``docs/headless-runtime-plan.md``, implemented against the Phase 0 contract
so the turn engine can depend on it without knowing about the TUI, relay, or Telegram.

Routing rules:

- If an interactive client is attached, ask it. First answer wins.
- If no interactive client is attached, apply the configured :class:`ApprovalPolicy`
  (deny by default, or hold until a client appears / the timeout expires).
- Timeouts always resolve as ``approved=False`` with ``reason="timeout"``. Never hang.

:func:`race_first_decision` is the single race implementation. The headless broker and
the TUI approval path both use it, so "first answer wins, losers are cancelled, a
timeout never hangs" is defined once.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from ite.runtime.client import (
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalResolution,
    PlanQuestion,
    PlanReadyRequest,
)

logger = logging.getLogger(__name__)

# A channel is any async callable that may produce a decision. Returning ``None``
# means "this channel has no answer" and the race keeps waiting on the others.
ApprovalChannel = Callable[[], Awaitable[Any]]

WinnerCallback = Callable[[int, Any], Any]


def _completed_value(task: asyncio.Task[Any]) -> Any:
    """Return a task's value, or ``None`` if it was cancelled or raised."""

    if task.cancelled():
        return None
    exc = task.exception()
    if exc is not None:
        logger.debug("approval channel failed: %r", exc)
        return None
    return task.result()


async def race_first_decision(
    channels: Sequence[ApprovalChannel],
    *,
    timeout: float | None = None,
    on_winner: WinnerCallback | None = None,
) -> tuple[int, Any] | None:
    """Race decision channels; the first non-``None`` value wins.

    Returns ``(channel_index, value)``, or ``None`` when every channel declined or the
    timeout elapsed. Losing channels are always cancelled before returning.

    ``None`` from a channel means "no decision" and is not a win — the race keeps
    waiting on the remaining channels, which is what makes the local TUI modal the
    fallback when a remote client times out.

    ``on_winner`` runs before the losers are cancelled, so callers can mirror the
    decision (dismiss a modal, resolve a remote request) while the other channels are
    still live.
    """

    if not channels:
        return None

    tasks: list[asyncio.Task[Any]] = [asyncio.create_task(channel()) for channel in channels]
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout

    try:
        pending: set[asyncio.Task[Any]] = set(tasks)
        while pending:
            remaining: float | None = None
            if deadline is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return None
            done, pending = await asyncio.wait(
                pending,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                return None
            for task in done:
                value = _completed_value(task)
                if value is None:
                    continue
                index = tasks.index(task)
                if on_winner is not None:
                    outcome = on_winner(index, value)
                    if inspect.isawaitable(outcome):
                        await outcome
                return (index, value)
        return None
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()


class ApprovalBroker:
    """Routes interactive requests to attached clients or an explicit fallback policy."""

    def __init__(
        self,
        *,
        policy: ApprovalPolicy = ApprovalPolicy.DENY,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._policy = policy
        self._publish = publish
        self._interactive: list[Any] = []
        self._pending: dict[str, asyncio.Future[ApprovalResolution]] = {}
        self._pending_questions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_plan_ready: dict[str, asyncio.Future[bool]] = {}

    @property
    def policy(self) -> ApprovalPolicy:
        return self._policy

    def set_interactive_clients(self, clients: list[Any]) -> None:
        self._interactive = list(clients)

    # -- approvals ---------------------------------------------------------

    async def request_approval(self, request: ApprovalRequest) -> bool:
        request_id = request.request_id or uuid.uuid4().hex
        self._emit(
            "approval_requested",
            {
                "request_id": request_id,
                "session_id": request.session_id,
                "tool_name": request.tool_name,
                "description": request.description,
                "command": request.command,
                "diff": request.diff,
            },
        )

        clients = self._interactive_clients()
        if not clients:
            approved = self._policy is ApprovalPolicy.ALLOW
            reason = "policy_allow" if approved else "policy_deny"
            if self._policy is ApprovalPolicy.HOLD and request.timeout > 0:
                approved, reason = await self._hold_for_approval(request_id, request)
            self._emit_resolved(request_id, approved, reason)
            return approved

        result = await self._race_approval(clients, request_id, request)
        self._emit_resolved(request_id, result.approved, result.reason)
        return result.approved

    def resolve_approval(
        self, request_id: str, approved: bool, *, reason: str = "client"
    ) -> bool:
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(ApprovalResolution(request_id, bool(approved), reason))
        return True

    async def _race_approval(
        self,
        clients: list[Any],
        request_id: str,
        request: ApprovalRequest,
    ) -> ApprovalResolution:
        channels: list[ApprovalChannel] = [
            (lambda client=client: self._ask_client(client, request)) for client in clients
        ]
        timeout = request.timeout if request.timeout > 0 else None
        result = await race_first_decision(channels, timeout=timeout)
        if result is None:
            return ApprovalResolution(request_id, False, "timeout")
        _index, resolution = result
        if isinstance(resolution, ApprovalResolution):
            return resolution
        return ApprovalResolution(request_id, bool(resolution), "client")

    async def _ask_client(self, client: Any, request: ApprovalRequest) -> ApprovalResolution | None:
        try:
            return await client.request_approval(request)
        except Exception:
            return None

    async def _hold_for_approval(
        self, request_id: str, request: ApprovalRequest
    ) -> tuple[bool, str]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalResolution] = loop.create_future()
        self._pending[request_id] = future
        try:
            resolution = await asyncio.wait_for(future, timeout=request.timeout)
            return resolution.approved, resolution.reason
        except asyncio.TimeoutError:
            return False, "timeout"
        finally:
            self._pending.pop(request_id, None)

    # -- plan questions ----------------------------------------------------

    async def request_plan_question(self, request: PlanQuestion) -> dict[str, Any]:
        request_id = request.request_id or uuid.uuid4().hex
        empty = {"selected_option": "", "free_text": "", "selected_index": None}
        self._emit(
            "plan_question_requested",
            {
                "request_id": request_id,
                "session_id": request.session_id,
                "question": request.question,
                "options": list(request.options),
                "recommended_index": request.recommended_index,
                "allow_free_text": request.allow_free_text,
                "question_number": request.question_number,
            },
        )
        clients = self._interactive_clients()
        if not clients:
            self._emit(
                "plan_question_resolved",
                {"request_id": request_id, "answered": False, "answer": empty},
            )
            return dict(empty)

        answer = await self._race_plan_question(clients, request)
        if answer is None:
            self._emit(
                "plan_question_resolved",
                {"request_id": request_id, "answered": False, "answer": empty},
            )
            return dict(empty)
        self._emit(
            "plan_question_resolved",
            {"request_id": request_id, "answered": True, "answer": answer},
        )
        return answer

    async def _race_plan_question(
        self, clients: list[Any], request: PlanQuestion
    ) -> dict[str, Any] | None:
        channels: list[ApprovalChannel] = [
            (lambda client=client: self._ask_question(client, request)) for client in clients
        ]
        timeout = request.timeout if request.timeout > 0 else None
        result = await race_first_decision(channels, timeout=timeout)
        if result is None:
            return None
        _index, answer = result
        if not isinstance(answer, dict):
            return None
        return answer

    async def _ask_question(self, client: Any, request: PlanQuestion) -> dict[str, Any] | None:
        try:
            return await client.request_plan_question(request)
        except Exception:
            return None

    def resolve_plan_question(self, request_id: str, answer: dict[str, Any]) -> bool:
        future = self._pending_questions.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(answer)
        return True

    # -- plan ready --------------------------------------------------------

    async def request_plan_ready(self, request: PlanReadyRequest) -> bool:
        request_id = request.request_id or uuid.uuid4().hex
        self._emit(
            "plan_ready_requested",
            {
                "request_id": request_id,
                "session_id": request.session_id,
                "plan_text": request.plan_text,
                "question_count": request.question_count,
            },
        )
        clients = self._interactive_clients()
        if not clients:
            self._emit(
                "plan_ready_resolved",
                {"request_id": request_id, "approved": False},
            )
            return False

        approved = await self._race_plan_ready(clients, request)
        self._emit(
            "plan_ready_resolved",
            {"request_id": request_id, "approved": bool(approved)},
        )
        return bool(approved)

    async def _race_plan_ready(
        self, clients: list[Any], request: PlanReadyRequest
    ) -> bool:
        channels: list[ApprovalChannel] = [
            (lambda client=client: self._ask_plan_ready(client, request)) for client in clients
        ]
        timeout = request.timeout if request.timeout > 0 else None
        result = await race_first_decision(channels, timeout=timeout)
        if result is None:
            return False
        _index, approved = result
        return bool(approved)

    async def _ask_plan_ready(self, client: Any, request: PlanReadyRequest) -> bool | None:
        try:
            return await client.request_plan_ready(request)
        except Exception:
            return None

    def resolve_plan_ready(self, request_id: str, approved: bool) -> bool:
        future = self._pending_plan_ready.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(bool(approved))
        return True

    # -- helpers -----------------------------------------------------------

    def _interactive_clients(self) -> list[Any]:
        return [
            client
            for client in self._interactive
            if _client_is_interactive(client)
        ]

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._publish is not None:
            with contextlib.suppress(Exception):
                self._publish(event_type, data)

    def _emit_resolved(self, request_id: str, approved: bool, reason: str) -> None:
        self._emit(
            "approval_resolved",
            {"request_id": request_id, "approved": bool(approved), "reason": reason},
        )


def _client_is_interactive(client: Any) -> bool:
    checker = getattr(client, "is_interactive", None)
    if checker is None:
        return True
    try:
        return bool(checker())
    except Exception:
        return False
