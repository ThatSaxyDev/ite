"""A display clock for live assistant text, independent of network chunk timing."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable


class AssistantTypingBuffer:
    """Accept text immediately, then reveal it until starved, finished, or canceled."""

    def __init__(
        self, render: Callable[[str], Awaitable[None]], *, interval: float = 0.01
    ) -> None:
        self.render = render
        self.interval = interval
        self.received = ""
        self.revealed = 0
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._finished = False
        self._finish_batch = 1

    def append(self, text: str) -> None:
        if self._finished:
            raise RuntimeError("Cannot append to a completed typing buffer.")
        if not text:
            return
        self.received += text
        self._wake.set()
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def finish(self) -> None:
        self._finished = True
        pending = len(self.received) - self.revealed
        # Long replies should not keep the completed turn waiting for a slow animation.
        if pending > 300:
            self._finish_batch = max(1, math.ceil(pending * self.interval))
        self._wake.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                # Removing an outgoing thread's widget only cancels its display clock.
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    raise

    async def cancel(self) -> None:
        self._finished = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            pending = len(self.received) - self.revealed
            if not pending:
                if self._finished:
                    return
                self._wake.clear()
                await self._wake.wait()
                continue
            # Short replies type letter by letter; large backlogs catch up gradually.
            count = max(1, math.ceil(pending / 500), self._finish_batch)
            fragment = self.received[self.revealed : self.revealed + count]
            await self.render(fragment)
            self.revealed += len(fragment)
            await asyncio.sleep(self.interval)
