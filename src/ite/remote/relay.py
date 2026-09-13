from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from .server import RemoteRuntimeServer

logger = logging.getLogger(__name__)

_RECONNECT_MIN_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0
_HEARTBEAT_SECONDS = 25.0
_SEND_QUEUE_MAX = 512
_MESSAGE_SIZE_LIMIT = 16 * 1024 * 1024


class RelayFrameWriter:
    """``ClientWriter`` that forwards server frames to the cloud relay.

    The remote runtime server writes newline-delimited JSON frames and awaits
    ``drain``. In relay mode those bytes must travel over the outbound WebSocket
    instead of a direct socket, so this writer queues the encoded frames and the
    relay's send loop flushes them. ``drain`` therefore just yields control,
    keeping the server's write path non-blocking.
    """

    def __init__(self, relay: "CloudRelayClient") -> None:
        self._relay = relay
        self._closed = False

    def write(self, data: bytes) -> None:
        if self._closed:
            return
        for line in data.split(b"\n"):
            if not line.strip():
                continue
            try:
                frame = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            self._relay.enqueue_outbound(frame)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self._closed = True

    async def wait_closed(self) -> None:
        self._closed = True


class CloudRelayClient:
    """Maintains the outbound relay connection for one runtime.

    Dials ``/remote/relay/runtime`` on the iTE Cloud API, registers the runtime,
    and then bridges frames in both directions until the process is stopped.
    Reconnects with exponential backoff so a dropped VPS connection heals
    without a restart.
    """

    def __init__(
        self,
        server: RemoteRuntimeServer,
        *,
        api_url: str,
        token_provider: Callable[[], Awaitable[str | None]],
        runtime_id: str,
        runtime_name: str,
        platform: str,
        fingerprint: str,
        project_id: str = "",
    ) -> None:
        self._server = server
        self._api_url = str(api_url or "").strip().rstrip("/")
        self._token_provider = token_provider
        self._runtime_id = str(runtime_id or "").strip()
        self._runtime_name = str(runtime_name or "iTE Runtime").strip() or "iTE Runtime"
        self._platform = str(platform or "").strip()
        self._fingerprint = str(fingerprint or "").strip()
        self._project_id = str(project_id or "").strip()
        self._outbound: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
            maxsize=_SEND_QUEUE_MAX
        )
        self._stop_event = asyncio.Event()
        self._connected = asyncio.Event()
        self._relay_client_id: str | None = None
        self._last_error = ""
        self._writer = RelayFrameWriter(self)

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def last_error(self) -> str:
        """Most recent relay failure reason, for honest startup diagnostics."""
        return self._last_error

    async def wait_connected(self, timeout: float) -> bool:
        """Wait for the first successful relay registration."""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def enqueue_outbound(self, frame: dict[str, Any]) -> None:
        """Queue a frame for delivery to the relay without blocking the caller."""
        if self._stop_event.is_set():
            return
        try:
            self._outbound.put_nowait(frame)
        except asyncio.QueueFull:
            # Slow consumer: drop the newest frame rather than stalling the agent.
            logger.warning("Relay outbound queue full; dropping frame")

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._outbound.put_nowait(None)
        except asyncio.QueueFull:
            pass

    @property
    def _websocket_url(self) -> str:
        base = self._api_url
        if base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        return f"{base}/remote/relay/runtime"

    async def run(self) -> None:
        """Connect, serve, and reconnect until :meth:`stop` is called."""
        from websockets.asyncio.client import connect

        backoff = _RECONNECT_MIN_SECONDS
        try:
            while not self._stop_event.is_set():
                token = await self._token_provider()
                if not token:
                    logger.warning(
                        "No iTE Cloud token available; retrying relay in %ss", backoff
                    )
                    if await self._sleep_or_stop(backoff):
                        break
                    backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)
                    continue

                try:
                    async with connect(
                        self._websocket_url,
                        additional_headers={"Authorization": f"Bearer {token}"},
                        max_size=_MESSAGE_SIZE_LIMIT,
                        ping_interval=20,
                        ping_timeout=20,
                    ) as websocket:
                        await self._serve(websocket, token)
                        backoff = _RECONNECT_MIN_SECONDS
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._last_error = str(exc) or exc.__class__.__name__
                    logger.warning("Relay connection failed: %s", exc)

                self._teardown()
                if self._stop_event.is_set():
                    break
                backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)
                if await self._sleep_or_stop(backoff):
                    break
        finally:
            # Run on cancellation too, so the server stops advertising a relay
            # client that is no longer there.
            self._teardown()

    async def _sleep_or_stop(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def _serve(self, websocket: Any, token: str) -> None:
        await websocket.send(
            json.dumps(
                {
                    "type": "relay_hello",
                    "payload": {
                        "runtimeId": self._runtime_id,
                        "token": token,
                        "name": self._runtime_name,
                        "platform": self._platform,
                        "fingerprint": self._fingerprint,
                        "projectId": self._project_id,
                    },
                }
            )
        )

        ready = await self._await_ready(websocket)
        if ready is None:
            return

        self._connected.set()
        self._server.set_relay_connected(True)
        client = self._server.attach_relay_client(self._writer)
        self._relay_client_id = client.client_id
        logger.info("Relay connected as runtime %s", self._runtime_id)

        sender = asyncio.create_task(self._send_loop(websocket))
        heartbeat = asyncio.create_task(self._heartbeat_loop(websocket))
        try:
            async for raw in websocket:
                await self._handle_message(raw)
        finally:
            sender.cancel()
            heartbeat.cancel()
            await asyncio.gather(sender, heartbeat, return_exceptions=True)

    async def _await_ready(self, websocket: Any) -> dict[str, Any] | None:
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=15.0)
        except asyncio.TimeoutError:
            logger.warning("Relay did not acknowledge registration in time")
            return None
        message = self._decode(raw)
        if message is None or message.get("type") != "relay_ready":
            logger.warning("Relay rejected registration: %s", message)
            return None
        return message

    def _decode(self, raw: Any) -> dict[str, Any] | None:
        try:
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            parsed = json.loads(text)
        except (ValueError, UnicodeDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _handle_message(self, raw: Any) -> None:
        message = self._decode(raw)
        if message is None or self._relay_client_id is None:
            return
        message_type = str(message.get("type") or "")

        if message_type == "frame":
            frame = message.get("frame")
            if not isinstance(frame, dict):
                return
            client = self._server.get_client(self._relay_client_id)
            if client is None:
                return
            await self._server.handle_client_message(
                client,
                {"type": frame.get("type"), "payload": frame.get("payload") or {}},
            )
            return

        if message_type == "app_attached":
            count = message.get("count")
            self._server.set_relay_app_count(int(count) if isinstance(count, int) else 0)
            return

        if message_type == "app_detached":
            count = message.get("count")
            self._server.set_relay_app_count(int(count) if isinstance(count, int) else 0)
            return

        if message_type == "relay_error":
            payload = message.get("payload") or {}
            logger.warning(
                "Relay error: %s (%s)",
                payload.get("message"),
                payload.get("code"),
            )
            return

        if message_type == "relay_shutdown":
            logger.info("Relay requested shutdown: %s", message.get("payload"))

    async def _send_loop(self, websocket: Any) -> None:
        while not self._stop_event.is_set():
            frame = await self._outbound.get()
            if frame is None:
                return
            try:
                await websocket.send(json.dumps({"type": "frame", "frame": frame}))
            except Exception as exc:
                logger.debug("Relay send failed: %s", exc)
                return

    async def _heartbeat_loop(self, websocket: Any) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=_HEARTBEAT_SECONDS
                )
                return
            except asyncio.TimeoutError:
                pass
            try:
                await websocket.send(json.dumps({"type": "heartbeat"}))
            except Exception:
                return

    def _teardown(self) -> None:
        self._connected.clear()
        self._server.set_relay_connected(False)
        self._server.set_relay_app_count(0)
        if self._relay_client_id is not None:
            self._server.detach_relay_client(self._relay_client_id)
            self._relay_client_id = None
        while not self._outbound.empty():
            try:
                self._outbound.get_nowait()
            except asyncio.QueueEmpty:
                break
