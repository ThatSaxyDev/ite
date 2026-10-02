"""Short transport budgets for background status checks, scoped to one call."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, TypeVar, cast

T = TypeVar("T")


@dataclass(frozen=True)
class RequestBudget:
    deadline: float
    timeout: float = 2.0
    retries: int = 0
    cancelled: threading.Event | None = None


_request_budget: ContextVar[RequestBudget | None] = ContextVar(
    "cloud_request_budget", default=None
)


def http_settings(default_timeout: float, default_retries: int) -> tuple[float, int]:
    budget = _request_budget.get()
    if budget is None:
        return default_timeout, default_retries
    if budget.cancelled is not None and budget.cancelled.is_set():
        raise TimeoutError("Cloud status request was cancelled")
    remaining = budget.deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Cloud status request exceeded its deadline")
    return min(budget.timeout, remaining), budget.retries


def run_status_request(function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    token = _request_budget.set(RequestBudget(deadline=time.monotonic() + 5.0))
    try:
        return function(*args, **kwargs)
    finally:
        _request_budget.reset(token)


async def run_status_request_async(
    function: Callable[..., T], *args: Any, **kwargs: Any
) -> T:
    """Run disposable status reads without holding Python's executor open on exit.

    Cancelling an asyncio task cannot interrupt urllib or DNS in a worker thread.
    A daemon worker lets shutdown proceed; the cancellation flag prevents it from
    starting another HTTP request if its current transport later returns.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()
    cancelled = threading.Event()

    def deliver(result: T | None, error: Exception | None) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(cast(T, result))

    def work() -> None:
        token = _request_budget.set(
            RequestBudget(deadline=time.monotonic() + 5.0, cancelled=cancelled)
        )
        result = None
        error = None
        try:
            result = function(*args, **kwargs)
        except Exception as exception:
            error = exception
        finally:
            _request_budget.reset(token)
        if not cancelled.is_set():
            try:
                loop.call_soon_threadsafe(deliver, result, error)
            except RuntimeError:
                # The event loop may have closed between the check and delivery.
                pass

    threading.Thread(target=work, name="ite-cloud-status", daemon=True).start()
    try:
        return await future
    finally:
        cancelled.set()
