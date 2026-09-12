from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from ite.cloud.auth import CloudSession, _load_cloud_session, _refresh_cloud_session
from ite.config.config import Config

from .server import ClientWriter, RemoteRuntimeServer

logger = logging.getLogger(__name__)

RUNTIME_RELAY_PATH = "/remote/relay/runtime"
RUNTIME_REGISTER_PATH = "/remote/runtimes"
RUNTIME_HEARTBEAT_PATH = "/remote/runtimes/heartbeat"

StatusCallback = Callable[[str, str], Any] | Callable[[str, str], Awaitable[Any]]


def _derive_ws_url(api_url: str, path: str) -> str:
    parts = urlsplit(api_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    base_path = parts.path.rstrip("/")
    return urlunsplit((scheme, parts.netloc, f"{base_path}{path}", "", ""))


async def resolve_cloud_session(config: Config) -> CloudSession | None:
    """Load the stored cloud session and refresh it when the access token is stale."""
    session = _load_cloud_session()
    if session is None:
        return None
    api_url = str(config.cloud_api_url or "").strip().rstrip("/")
    if not api_url or session.api_url.rstrip("/") != api_url:
        return None
    if session.is_access_valid and session.access_token:
        return session
    try:
        refreshed = await asyncio.to_thread(_refresh_cloud_session, session)
    except Exception:
        return None
    if refreshed is None or not refreshed.access_token:
        return None
    if refreshed.api_url.rstrip("/") != api_url:
        return None
    return refreshed


class _RelayClientWriter:
    """Adapts the relay WebSocket to the runtime server's ClientWriter surface.

    The server writes newline-delimited JSON frames synchronously and then
    awaits ``drain``; this writer buffers those bytes and forwards each decoded
    frame to the cloud on drain.
    """

    def __init__(self, relay: CloudRelayClient) -> None:
        self._relay = relay
        self._buffer = bytearray()
        self._closed = False
        self._closed_event = asyncio.Event()

    def write(self, data: bytes) -> None:
        if self._closed:
            return
        self._buffer.extend(data)

    async def drain(self) -> None:
        if self._closed or not self._buffer:
            return
        data = bytes(self._buffer)
        self._buffer.clear()
        await self._relay.forward_runtime_bytes(data)

    def close(self) -> None:
        self._closed = True
        self._closed_event.set()

    async def wait_closed(self) -> None:
        await self._closed_event.wait()


class CloudRelayClient:
    """Maintains an outbound cloud relay connection for a RemoteRuntimeServer."""

    RECONNECT_BASE_SECONDS = 1.0
    RECONNECT_MAX_SECONDS = 30.0
    HEARTBEAT_SECONDS = 20.0
    AUTH_TIMEOUT_SECONDS = 20.0

    def __init__(
        self,
        server: RemoteRuntimeServer,
        *,
        config: Config,
        runtime_id: str | None = None,
        status_callback: StatusCallback | None = None,
    ) -> None:
        self._server = server
        self._config = config
        self._runtime_id = str(runtime_id or "").strip()
        self._status_callback = status_callback
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._socket: ClientConnection | None = None
        self._writer: _RelayClientWriter | None = None
        self._relay_client: Any = None
        self._send_lock = asyncio.Lock()

    @property
    def runtime_id(self) -> str:
        return self._runtime_id or self._server.runtime_id

    @property
    def is_running(self) -> bool:
        return self._server.is_running and not self._stopping

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await self._teardown_connection()

    async def _run_forever(self) -> None:
        delay = self.RECONNECT_BASE_SECONDS
        while not self._stopping:
            try:
                await self._connect_once()
                delay = self.RECONNECT_BASE_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.debug("Cloud relay connection ended: %s", exc)
                await self._notify_status("disconnected", str(exc))
            if self._stopping:
                break
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
            delay = min(delay * 2, self.RECONNECT_MAX_SECONDS)

    async def _connect_once(self) -> None:
        session = await resolve_cloud_session(self._config)
        if session is None:
            raise RuntimeError("No active iTE Cloud session for relay mode.")

        self._runtime_id = self._runtime_id or self._server.runtime_id
        if not self._runtime_id:
            raise RuntimeError("The runtime could not derive a stable runtime id.")

        await self._register_runtime(session)

        ws_url = _derive_ws_url(session.api_url, RUNTIME_RELAY_PATH)
        async with websockets.connect(
            ws_url,
            open_timeout=self.AUTH_TIMEOUT_SECONDS,
            ping_interval=None,
            max_size=8 * 1024 * 1024,
        ) as socket:
            self._socket = socket
            writer = _RelayClientWriter(self)
            self._writer = writer
            await self._send_message(
                {
                    "type": "relay_hello",
                    "payload": {
                        "runtimeId": self._runtime_id,
                        "token": session.access_token,
                        "name": self._server.connection_info().get("runtime_name") or "",
                        "platform": _platform_name(),
                        "fingerprint": self._server.connection_info().get("fingerprint") or "",
                    },
                }
            )
            ready = await asyncio.wait_for(
                self._await_ready(socket), timeout=self.AUTH_TIMEOUT_SECONDS
            )
            if ready is None:
                raise RuntimeError("Cloud relay rejected the runtime registration.")

            self._relay_client = self._server.attach_relay_client(writer)
            await self._notify_status("connected", "")

            heartbeat = asyncio.create_task(self._heartbeat_loop())
            try:
                await self._receive_loop(socket)
            finally:
                heartbeat.cancel()
                try:
                    await heartbeat
                except (asyncio.CancelledError, Exception):
                    pass
                await self._teardown_connection()

    async def _await_ready(self, socket: ClientConnection) -> str | None:
        while True:
            raw = await socket.recv()
            message = _decode(raw)
            if message is None:
                continue
            mtype = str(message.get("type") or "")
            if mtype == "relay_ready":
                return str(message.get("runtimeId") or self._runtime_id)
            if mtype == "relay_error":
                payload = message.get("payload") or {}
                raise RuntimeError(str(payload.get("message") or "Relay registration failed."))

    async def _receive_loop(self, socket: ClientConnection) -> None:
        while True:
            try:
                raw = await socket.recv()
            except websockets.ConnectionClosed:
                return
            message = _decode(raw)
            if message is None:
                continue
            await self._handle_message(message)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        mtype = str(message.get("type") or "")
        if mtype == "frame":
            frame = message.get("frame")
            if isinstance(frame, dict) and self._relay_client is not None:
                await self._server.handle_client_message(self._relay_client, frame)
            return
        if mtype == "app_count":
            self._server.set_relay_app_count(int(message.get("count") or 0))
            return
        if mtype == "app_attached":
            self._server.set_relay_app_count(int(message.get("count") or 0))
            return
        if mtype == "app_detached":
            self._server.set_relay_app_count(int(message.get("count") or 0))
            return
        if mtype == "request_state":
            if self._server.has_authenticated_clients():
                await self._server.publish_state()
            return
        if mtype == "ping":
            await self._send_message({"type": "pong"})
            return
        if mtype == "relay_error":
            payload = message.get("payload") or {}
            raise RuntimeError(str(payload.get("message") or "Relay error."))
        if mtype == "relay_shutdown":
            raise RuntimeError("Relay connection closed by the cloud.")

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.HEARTBEAT_SECONDS)
            await self._send_message(
                {
                    "type": "heartbeat",
                    "runtimeId": self._runtime_id,
                    "appCount": self._server.relay_app_count,
                }
            )

    async def forward_runtime_bytes(self, data: bytes) -> None:
        for line in data.split(b"\n"):
            if not line.strip():
                continue
            try:
                frame = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            await self._send_message({"type": "frame", "frame": frame})

    async def _send_message(self, message: dict[str, Any]) -> None:
        socket = self._socket
        if socket is None:
            return
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        async with self._send_lock:
            try:
                await socket.send(encoded)
            except websockets.ConnectionClosed:
                raise

    async def _register_runtime(self, session: CloudSession) -> None:
        api_url = session.api_url.rstrip("/")
        info = self._server.connection_info()
        payload = {
            "runtimeId": self._runtime_id,
            "name": str(info.get("runtime_name") or "iTE Runtime"),
            "platform": _platform_name(),
            "fingerprint": str(info.get("fingerprint") or ""),
            "capabilities": {"transport": "relay", "protocolVersion": info.get("protocol_version")},
        }
        headers = {"authorization": f"Bearer {session.access_token}"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{api_url}{RUNTIME_REGISTER_PATH}", headers=headers, json=payload
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Could not register runtime with iTE Cloud: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(
                f"iTE Cloud rejected runtime registration ({response.status_code})."
            )

    async def _teardown_connection(self) -> None:
        if self._relay_client is not None:
            try:
                self._server.detach_relay_client(self._relay_client.client_id)
            except Exception:
                pass
            self._relay_client = None
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        socket = self._socket
        self._socket = None
        if socket is not None:
            try:
                await socket.close()
            except Exception:
                pass
        self._server.set_relay_app_count(0)
        await self._notify_status("disconnected", "")

    async def _notify_status(self, status: str, message: str) -> None:
        callback = self._status_callback
        if callback is None:
            return
        try:
            result = callback(status, message)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass


def _decode(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(raw, str):
        return None
    try:
        message = json.loads(raw)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


def _platform_name() -> str:
    import platform

    return f"{platform.system()} {platform.release()}".strip()
