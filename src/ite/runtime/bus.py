"""In-process event bus for the runtime host.

Phase 0 of ``docs/headless-runtime-plan.md``. The host publishes to the bus; the TUI,
relay, and Telegram become subscribers. Publish is synchronous and isolates client
failures so one broken client cannot take down a turn.
"""

from __future__ import annotations

import logging
from typing import Any

from ite.runtime.client import RuntimeClient
from ite.runtime.events import RuntimeEvent

logger = logging.getLogger(__name__)


class EventBus:
    """Fan-out for :class:`RuntimeEvent` and state snapshots."""

    def __init__(self) -> None:
        self._clients: list[RuntimeClient] = []

    @property
    def clients(self) -> list[RuntimeClient]:
        return list(self._clients)

    def subscribe(self, client: RuntimeClient) -> None:
        if client not in self._clients:
            self._clients.append(client)

    def unsubscribe(self, client: RuntimeClient) -> None:
        try:
            self._clients.remove(client)
        except ValueError:
            pass

    def clear(self) -> None:
        self._clients.clear()

    def publish(self, event: RuntimeEvent) -> None:
        for client in list(self._clients):
            try:
                client.on_event(event)
            except Exception:
                logger.exception(
                    "runtime client %r failed handling event %s",
                    getattr(client, "name", client),
                    event.type.value,
                )

    def publish_state(self, state: dict[str, Any]) -> None:
        for client in list(self._clients):
            try:
                client.on_state(state)
            except Exception:
                logger.exception(
                    "runtime client %r failed handling state",
                    getattr(client, "name", client),
                )

    def interactive_clients(self) -> list[RuntimeClient]:
        return [client for client in self._clients if _is_interactive(client)]


def _is_interactive(client: RuntimeClient) -> bool:
    checker = getattr(client, "is_interactive", None)
    if checker is None:
        return False
    try:
        return bool(checker())
    except Exception:
        return False
