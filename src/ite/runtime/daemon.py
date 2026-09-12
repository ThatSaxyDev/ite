"""Headless daemon entry point for the runtime host.

Phase 5 of ``docs/headless-runtime-plan.md``. Builds the host, resolves the stored
cloud session, wires the relay transport, and runs until SIGTERM/SIGINT.

No Textual import on this path (enforced by ``tests/test_runtime_contract.py``).
Structured logs go to stdout/journald; frame payloads are never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import uuid
from typing import Any

from ite.cloud import get_remote_companion_access_status
from ite.config.config import Config
from ite.remote.protocol import (
    serialize_approval_request,
    serialize_plan_question_request,
    serialize_plan_ready_request,
)
from ite.remote.relay import CloudRelayClient, resolve_cloud_session
from ite.remote.server import RemoteRuntimeServer
from ite.runtime.approval import ApprovalBroker
from ite.runtime.client import (
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalResolution,
    PlanQuestion,
    PlanReadyRequest,
)
from ite.runtime.events import RuntimeEvent, RuntimeEventType
from ite.runtime.host import RuntimeHost

logger = logging.getLogger("ite.runtime.daemon")


class RemoteServerClient:
    """Bus client that forwards host events to the relay ``RemoteRuntimeServer``.

    Also acts as the interactive client for approvals/plan questions, so a phone
    attached over the relay can approve destructive tool calls. ``is_interactive``
    is only true while an authenticated client is actually connected.
    """

    name = "relay"

    def __init__(self, server: RemoteRuntimeServer) -> None:
        self._server = server
        self._queue: asyncio.Queue[RuntimeEvent] | None = None
        self._worker: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._queue = asyncio.Queue()
        self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        worker = self._worker
        self._worker = None
        self._queue = None
        if worker is not None and not worker.done():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await worker

    # -- RuntimeClient -----------------------------------------------------

    def on_event(self, event: RuntimeEvent) -> None:
        if self._queue is not None:
            self._queue.put_nowait(event)

    def on_state(self, state: dict[str, Any]) -> None:
        # The server pulls state via ``state_provider``; nothing to push here.
        return None

    def is_interactive(self) -> bool:
        return bool(self._server.is_running and self._server.has_authenticated_clients())

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResolution | None:
        if not self.is_interactive():
            return None
        request_id = request.request_id or uuid.uuid4().hex
        approved = await self._server.request_approval(
            serialize_approval_request(
                request_id=request_id,
                tool_name=request.tool_name,
                description=request.description,
                command=request.command,
                diff=request.diff,
                session_id=request.session_id,
            )
        )
        if approved is None:
            return None
        return ApprovalResolution(request_id, bool(approved), "relay")

    async def request_plan_question(self, request: PlanQuestion) -> dict[str, Any] | None:
        if not self.is_interactive():
            return None
        request_id = request.request_id or uuid.uuid4().hex
        return await self._server.request_plan_question(
            serialize_plan_question_request(
                request_id=request_id,
                session_id=request.session_id,
                question=request.question,
                options=request.options,
                recommended_index=request.recommended_index,
                allow_free_text=request.allow_free_text,
                question_number=request.question_number,
            )
        )

    async def request_plan_ready(self, request: PlanReadyRequest) -> bool | None:
        if not self.is_interactive():
            return None
        request_id = request.request_id or uuid.uuid4().hex
        return await self._server.request_plan_ready(
            serialize_plan_ready_request(
                request_id=request_id,
                session_id=request.session_id,
                plan_text=request.plan_text,
                question_count=request.question_count,
            )
        )

    # -- worker ------------------------------------------------------------

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            try:
                await self._dispatch(event)
            except Exception:
                logger.exception("relay client failed dispatching %s", event.type.value)

    async def _dispatch(self, event: RuntimeEvent) -> None:
        if event.type == RuntimeEventType.AGENT_EVENT:
            if not self._server.is_running:
                return
            await self._server.publish_event(event.to_wire())
            return
        if event.type in (
            RuntimeEventType.STATE_CHANGED,
            RuntimeEventType.TURN_STARTED,
            RuntimeEventType.TURN_ENDED,
            RuntimeEventType.TURN_FAILED,
            RuntimeEventType.SESSION_OPENED,
            RuntimeEventType.SESSION_CLOSED,
            RuntimeEventType.SESSION_ACTIVATED,
            RuntimeEventType.COMMAND_FEED_APPENDED,
            RuntimeEventType.CHANGE_FEED_APPENDED,
            RuntimeEventType.APPROVAL_RESOLVED,
            RuntimeEventType.PLAN_QUESTION_RESOLVED,
            RuntimeEventType.PLAN_READY_RESOLVED,
        ):
            if not self._server.is_running:
                return
            await self._server.publish_state()


async def _has_remote_companion_access(config: Config) -> bool:
    """Headless equivalent of ``ReupApp._has_remote_companion_access``."""

    try:
        status = await asyncio.to_thread(get_remote_companion_access_status, config)
    except Exception:
        logger.exception("remote companion access check failed")
        return False
    return bool(getattr(status, "is_valid", False))


class RuntimeDaemon:
    """Owns the host, the relay transport, and the process lifecycle."""

    def __init__(
        self,
        config: Config,
        *,
        approval_policy: ApprovalPolicy = ApprovalPolicy.DENY,
        access_checker=None,
    ) -> None:
        self.config = config
        self.host = RuntimeHost(config, approval_policy=approval_policy)
        self._server: RemoteRuntimeServer | None = None
        self._relay: CloudRelayClient | None = None
        self._relay_client: RemoteServerClient | None = None
        self._access_checker = access_checker or (
            lambda: _has_remote_companion_access(config)
        )
        self._stop_event = asyncio.Event()

    async def _preflight(self) -> None:
        """Fail fast with actionable errors instead of silently retrying forever.

        The relay client retries on a fixed backoff and only logs at debug level when
        it cannot connect. That makes a misconfigured host look "started" while the
        phone shows no runtime. These checks convert the three common misconfigurations
        into immediate, readable failures.
        """

        session = await resolve_cloud_session(self.config)
        if session is None:
            raise RuntimeError(
                "Not signed in to iTE Cloud, or the stored session targets a different "
                "API URL. Run `ite` and sign in, then retry `ite remote serve`."
            )

        try:
            has_access = bool(await self._access_checker())
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            raise RuntimeError(
                f"Could not verify remote companion access: {exc}"
            ) from exc
        if not has_access:
            raise RuntimeError(
                "This account does not have remote companion access. "
                "Remote control requires bundled/Pro access."
            )

        logger.info(
            "preflight ok (cloud=%s, workspace=%s)", session.api_url, self.config.cwd
        )

    async def start(self) -> None:
        await self._preflight()
        await self.host.start()
        self._server = RemoteRuntimeServer(
            state_provider=self.host.snapshot,
            submit_prompt=self.host.submit_prompt,
            cancel_turn=self.host.cancel_turn,
            switch_session=self.host.switch_session,
            access_checker=self._access_checker,
            transport="relay",
        )
        self._relay_client = RemoteServerClient(self._server)
        self.host.subscribe(self._relay_client)
        self._relay_client.start()
        # Relay mode never binds a listening socket, so the TLS identity must be
        # loaded explicitly. Without it runtime_id is empty and the relay reports
        # "could not derive a stable runtime id", so the phone never sees this runtime.
        self._server.ensure_identity()
        runtime_id = self._server.runtime_id
        if not runtime_id:
            raise RuntimeError(
                "Runtime could not derive a runtime id; "
                "the cloud relay cannot register this runtime."
            )
        self._relay = CloudRelayClient(
            self._server,
            config=self.config,
            runtime_id=runtime_id,
            status_callback=self._on_relay_status,
        )
        await self._relay.start()
        logger.info(
            "runtime daemon started (runtime_id=%s, workspace=%s)",
            runtime_id,
            self.config.cwd,
        )

    async def stop(self) -> None:
        if self._relay is not None:
            relay = self._relay
            self._relay = None
            with contextlib.suppress(Exception):
                await asyncio.wait_for(relay.stop(), timeout=2.0)
        if self._relay_client is not None:
            client = self._relay_client
            self._relay_client = None
            with contextlib.suppress(Exception):
                await client.stop()
        if self._server is not None:
            server = self._server
            self._server = None
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server.stop(), timeout=2.0)
        with contextlib.suppress(Exception):
            await self.host.stop()
        logger.info("runtime daemon stopped")

    def request_stop(self) -> None:
        self._stop_event.set()

    async def serve_forever(self) -> None:
        loop = asyncio.get_running_loop()
        installed: list[signal.Signals] = []
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.request_stop)
                installed.append(sig)
            except (NotImplementedError, RuntimeError):
                pass
        try:
            await self._stop_event.wait()
        finally:
            for sig in installed:
                with contextlib.suppress(Exception):
                    loop.remove_signal_handler(sig)
        await self.stop()

    def _on_relay_status(self, status: str, message: str) -> None:
        logger.info("relay status=%s %s", status, message or "")


def run_daemon(
    config: Config,
    *,
    approval_policy: ApprovalPolicy = ApprovalPolicy.DENY,
) -> int:
    """Blocking entry point. Returns a process exit code."""

    async def _main() -> None:
        daemon = RuntimeDaemon(config, approval_policy=approval_policy)
        await daemon.start()
        await daemon.serve_forever()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        # Preflight and startup failures are configuration problems, not crashes.
        # Print one readable line instead of a traceback.
        logger.error("runtime daemon failed to start: %s", exc)
        return 1
    except Exception:
        logger.exception("runtime daemon crashed")
        return 1
    return 0
