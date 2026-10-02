"""Short transport budgets for background status checks, scoped to one call."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RequestBudget:
    deadline: float
    timeout: float = 2.0
    retries: int = 0


_request_budget: ContextVar[RequestBudget | None] = ContextVar(
    "cloud_request_budget", default=None
)


def http_settings(default_timeout: float, default_retries: int) -> tuple[float, int]:
    budget = _request_budget.get()
    if budget is None:
        return default_timeout, default_retries
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
