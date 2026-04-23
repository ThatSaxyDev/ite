from __future__ import annotations

import asyncio
import inspect
import ipaddress
import json
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from .protocol import REMOTE_PROTOCOL_VERSION, json_safe, utc_now_iso
from .uri import create_connection_uri, create_simple_uri, parse_connection_uri


MaybeAsync = Callable[..., Any] | Callable[..., Awaitable[Any]]


@dataclass
class _ApprovalRequest:
    future: asyncio.Future[bool]
    created_at: datetime


@dataclass
class _ClientConnection:
    client_id: str
    writer: asyncio.StreamWriter
    address: str
    name: str = ""
    platform: str = ""
    token: str | None = None
    authenticated: bool = False
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RemoteRuntimeServer:
    PAIRING_TTL_MINUTES = 10

    def __init__(
        self,
        *,
        state_provider: MaybeAsync,
        submit_prompt: MaybeAsync,
        cancel_turn: MaybeAsync,
        switch_session: MaybeAsync | None = None,
    ) -> None:
        self._state_provider = state_provider
        self._submit_prompt = submit_prompt
        self._cancel_turn = cancel_turn
        self._switch_session = switch_session
        self._server: asyncio.AbstractServer | None = None
        self._host: str = "0.0.0.0"
        self._port: int = 0
        self._display_host: str = "127.0.0.1"
        self._pair_code: str = ""
        self._pair_code_expires_at: datetime | None = None
        self._client_tokens: set[str] = set()
        self._clients: dict[str, _ClientConnection] = {}
        self._approval_requests: dict[str, _ApprovalRequest] = {}

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def pair_code(self) -> str:
        if not self._pair_code or self._pair_code_is_expired():
            self.regenerate_pair_code()
        return self._pair_code

    @property
    def authenticated_client_count(self) -> int:
        return sum(1 for client in self._clients.values() if client.authenticated)

    def has_authenticated_clients(self) -> bool:
        return self.authenticated_client_count > 0

    def _pair_code_is_expired(self) -> bool:
        expires_at = self._pair_code_expires_at
        return expires_at is None or datetime.now(timezone.utc) >= expires_at

    def regenerate_pair_code(self) -> str:
        self._pair_code = f"{uuid.uuid4().int % 1000000:06d}"
        self._pair_code_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self.PAIRING_TTL_MINUTES
        )
        return self._pair_code

    async def start(self, *, host: str = "0.0.0.0", port: int = 0) -> dict[str, Any]:
        if self._server is not None:
            return self.connection_info()

        self._host = host
        self._server = await asyncio.start_server(self._handle_client, host=host, port=port)
        sock = next(iter(self._server.sockets or []), None)
        if sock is None:
            raise RuntimeError("Remote server failed to bind a socket.")
        bound_host, bound_port = sock.getsockname()[:2]
        self._host = str(bound_host)
        self._port = int(bound_port)
        self._display_host = self._detect_display_host()
        self.regenerate_pair_code()
        return self.connection_info()

    async def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
            await server.wait_closed()
        for client in list(self._clients.values()):
            try:
                client.writer.close()
                await client.writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()
        for request in self._approval_requests.values():
            if not request.future.done():
                request.future.cancel()
        self._approval_requests.clear()

    def _detect_display_host(self) -> str:
        candidates: list[str] = []
        candidates.extend(self._detect_route_hosts())
        candidates.extend(self._detect_hostname_hosts())

        seen: set[str] = set()
        filtered: list[str] = []
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if self._is_reachable_display_host(candidate):
                filtered.append(candidate)

        if filtered:
            private_hosts = [host for host in filtered if ipaddress.ip_address(host).is_private]
            if private_hosts:
                return private_hosts[0]
            return filtered[0]
        return "127.0.0.1"

    def _detect_route_hosts(self) -> list[str]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return [str(sock.getsockname()[0])]
        except Exception:
            return []

    def _detect_hostname_hosts(self) -> list[str]:
        try:
            infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
        except Exception:
            return []
        hosts: list[str] = []
        for info in infos:
            address = info[4][0]
            if isinstance(address, str):
                hosts.append(address)
        return hosts

    def _is_reachable_display_host(self, host: str) -> bool:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        return not (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
        )

    def connection_info(self) -> dict[str, Any]:
        return {
            "protocol_version": REMOTE_PROTOCOL_VERSION,
            "running": self.is_running,
            "host": self._host,
            "port": self._port,
            "display_host": self._display_host,
            "pair_code": self.pair_code,
            "pair_code_expires_at": self._pair_code_expires_at.isoformat()
            if self._pair_code_expires_at
            else None,
            "authenticated_clients": self.authenticated_client_count,
            "connect_uri": create_simple_uri(self._display_host, self._port, self.pair_code),
        }

    async def publish_state(self) -> None:
        if not self.has_authenticated_clients():
            return
        payload = await self._build_state_payload()
        await self._broadcast("remote_state", payload)

    async def publish_event(self, payload: dict[str, Any]) -> None:
        if not self.has_authenticated_clients():
            return
        await self._broadcast("agent_event", payload)

    async def request_approval(
        self,
        payload: dict[str, Any],
        *,
        timeout: float = 120.0,
    ) -> bool | None:
        if not self.has_authenticated_clients():
            return None
        request_id = str(payload.get("request_id") or uuid.uuid4())
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._approval_requests[request_id] = _ApprovalRequest(
            future=future,
            created_at=datetime.now(timezone.utc),
        )
        outbound = dict(payload)
        outbound["request_id"] = request_id
        await self._broadcast("approval_request", outbound)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._approval_requests.pop(request_id, None)

    async def _build_state_payload(self) -> dict[str, Any]:
        state = await self._call(self._state_provider)
        payload = json_safe(state)
        if isinstance(payload, dict):
            payload.setdefault("protocol_version", REMOTE_PROTOCOL_VERSION)
            payload.setdefault("server", self.connection_info())
            payload.setdefault("timestamp", utc_now_iso())
        return payload

    async def _call(self, callback: MaybeAsync, *args: Any) -> Any:
        result = callback(*args)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        address = writer.get_extra_info("peername")
        address_text = ""
        if isinstance(address, tuple) and address:
            address_text = f"{address[0]}:{address[1]}"
        client = _ClientConnection(
            client_id=uuid.uuid4().hex,
            writer=writer,
            address=address_text,
        )
        self._clients[client.client_id] = client

        try:
            while not reader.at_eof():
                raw = await reader.readline()
                if not raw:
                    break
                try:
                    message = json.loads(raw.decode("utf-8"))
                except Exception:
                    await self._send(client, "error", {"message": "Invalid JSON payload."})
                    continue
                if not isinstance(message, dict):
                    await self._send(client, "error", {"message": "Message must be an object."})
                    continue
                if not client.authenticated:
                    await self._handle_handshake(client, message)
                    continue
                await self._handle_authenticated_message(client, message)
        finally:
            self._clients.pop(client.client_id, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_handshake(
        self,
        client: _ClientConnection,
        message: dict[str, Any],
    ) -> None:
        if str(message.get("type") or "") != "hello":
            await self._send(
                client,
                "error",
                {"message": "Authenticate first with a hello message."},
            )
            return

        payload = message.get("payload") or {}
        token = str(payload.get("token") or "").strip()
        pair_code = str(payload.get("pair_code") or "").strip()

        authenticated = False
        if token and token in self._client_tokens:
            authenticated = True
        elif pair_code and pair_code == self.pair_code and not self._pair_code_is_expired():
            authenticated = True
            token = uuid.uuid4().hex
            self._client_tokens.add(token)

        if not authenticated:
            await self._send(
                client,
                "error",
                {"message": "Pairing failed. Check the current pair code."},
            )
            return

        client.authenticated = True
        client.token = token
        client.name = str(payload.get("client_name") or "").strip()
        client.platform = str(payload.get("platform") or "").strip()

        await self._send(
            client,
            "paired",
            {
                "token": token,
                "server": self.connection_info(),
                "client_id": client.client_id,
            },
        )
        await self._send(client, "remote_state", await self._build_state_payload())
        await self.publish_state()

    async def _handle_authenticated_message(
        self,
        client: _ClientConnection,
        message: dict[str, Any],
    ) -> None:
        msg_type = str(message.get("type") or "").strip()
        payload = message.get("payload") or {}
        request_id = str(message.get("request_id") or "").strip() or None

        if msg_type == "ping":
            await self._send(client, "pong", {"timestamp": utc_now_iso()}, request_id=request_id)
            return
        if msg_type == "get_state":
            await self._send(
                client,
                "remote_state",
                await self._build_state_payload(),
                request_id=request_id,
            )
            return
        if msg_type == "submit_prompt":
            message_text = str(payload.get("message") or "").strip()
            if not message_text:
                await self._send(
                    client,
                    "command_ack",
                    {"ok": False, "message": "Prompt is required."},
                    request_id=request_id,
                )
                return
            await self._call(self._submit_prompt, message_text)
            await self._send(
                client,
                "command_ack",
                {"ok": True, "message": "Prompt submitted."},
                request_id=request_id,
            )
            return
        if msg_type == "cancel_turn":
            await self._call(self._cancel_turn)
            await self._send(
                client,
                "command_ack",
                {"ok": True, "message": "Turn cancelled."},
                request_id=request_id,
            )
            return
        if msg_type == "switch_session":
            if self._switch_session is None:
                await self._send(
                    client,
                    "command_ack",
                    {"ok": False, "message": "Session switching is unavailable."},
                    request_id=request_id,
                )
                return
            session_id = str(payload.get("session_id") or "").strip()
            if not session_id:
                await self._send(
                    client,
                    "command_ack",
                    {"ok": False, "message": "Session ID is required."},
                    request_id=request_id,
                )
                return
            switched = bool(await self._call(self._switch_session, session_id))
            await self._send(
                client,
                "command_ack",
                {
                    "ok": switched,
                    "message": "Session switched." if switched else "Session not found.",
                },
                request_id=request_id,
            )
            if switched:
                await self.publish_state()
            return
        if msg_type == "approval_response":
            approval_id = str(payload.get("request_id") or "").strip()
            request = self._approval_requests.get(approval_id)
            approved = bool(payload.get("approved"))
            if request is None:
                await self._send(
                    client,
                    "command_ack",
                    {"ok": False, "message": "Approval request no longer exists."},
                    request_id=request_id,
                )
                return
            if not request.future.done():
                request.future.set_result(approved)
            await self._broadcast(
                "approval_resolved",
                {"request_id": approval_id, "approved": approved},
            )
            await self._send(
                client,
                "command_ack",
                {"ok": True, "message": "Approval response recorded."},
                request_id=request_id,
            )
            return

        await self._send(
            client,
            "error",
            {"message": f"Unsupported message type: {msg_type or 'unknown'}"},
            request_id=request_id,
        )

    async def _broadcast(
        self,
        frame_type: str,
        payload: dict[str, Any],
        *,
        exclude_client_id: str | None = None,
    ) -> None:
        stale_clients: list[str] = []
        for client in list(self._clients.values()):
            if not client.authenticated or client.client_id == exclude_client_id:
                continue
            try:
                await self._send(client, frame_type, payload)
            except Exception:
                stale_clients.append(client.client_id)
        for client_id in stale_clients:
            client = self._clients.pop(client_id, None)
            if client is None:
                continue
            try:
                client.writer.close()
                await client.writer.wait_closed()
            except Exception:
                pass

    async def _send(
        self,
        client: _ClientConnection,
        frame_type: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> None:
        frame = {
            "type": frame_type,
            "payload": json_safe(payload),
        }
        if request_id:
            frame["request_id"] = request_id
        encoded = (json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        async with client.write_lock:
            client.writer.write(encoded)
            await client.writer.drain()
