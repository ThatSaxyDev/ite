from __future__ import annotations

import asyncio
import hashlib
import inspect
import ipaddress
import json
import socket
import ssl
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from .protocol import REMOTE_PROTOCOL_VERSION, json_safe, utc_now_iso
from .security import load_or_create_tls_identity
from .security import remote_storage_dir
from .uri import create_connection_uri


MaybeAsync = Callable[..., Any] | Callable[..., Awaitable[Any]]


class ClientWriter(Protocol):
    """Minimal write surface shared by direct sockets and the cloud relay.

    The remote runtime server writes newline-delimited JSON frames and then
    awaits ``drain``. Direct TLS clients hand it an ``asyncio.StreamWriter``;
    relay mode hands it a writer that forwards the same bytes over the relay
    WebSocket, so the server can stay transport-agnostic.
    """

    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...

    def close(self) -> None: ...

    async def wait_closed(self) -> None: ...


@dataclass
class _ApprovalRequest:
    future: asyncio.Future[bool]
    created_at: datetime
    payload: dict[str, Any]


@dataclass
class _ResolvedApprovalRequest:
    approved: bool
    created_at: datetime


@dataclass
class _PlanQuestionRequest:
    future: asyncio.Future[dict[str, Any]]
    created_at: datetime
    payload: dict[str, Any]


@dataclass
class _PlanReadyRequest:
    future: asyncio.Future[bool]
    created_at: datetime
    payload: dict[str, Any]


@dataclass
class _ClientConnection:
    client_id: str
    writer: ClientWriter
    address: str
    device_id: str = ""
    name: str = ""
    platform: str = ""
    token: str | None = None
    authenticated: bool = False
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class _TrustedDevice:
    device_id: str
    token: str
    name: str
    platform: str
    issued_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def is_active(self) -> bool:
        return self.revoked_at is None and datetime.now(timezone.utc) < self.expires_at

    def to_json(self) -> dict[str, str | None]:
        return {
            "device_id": self.device_id,
            "token": self.token,
            "name": self.name,
            "platform": self.platform,
            "issued_at": self.issued_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "_TrustedDevice":
        def _parse_datetime(value: Any) -> datetime:
            if isinstance(value, str) and value:
                parsed = datetime.fromisoformat(value)
                return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc)

        revoked_value = payload.get("revoked_at")
        revoked_at = None
        if isinstance(revoked_value, str) and revoked_value:
            parsed = datetime.fromisoformat(revoked_value)
            revoked_at = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        return cls(
            device_id=str(payload.get("device_id") or "").strip(),
            token=str(payload.get("token") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            platform=str(payload.get("platform") or "").strip(),
            issued_at=_parse_datetime(payload.get("issued_at")),
            last_seen_at=_parse_datetime(payload.get("last_seen_at")),
            expires_at=_parse_datetime(payload.get("expires_at")),
            revoked_at=revoked_at,
        )


class RemoteRuntimeServer:
    PAIRING_TTL_MINUTES = 10
    TOKEN_TTL_DAYS = 30
    MAX_FAILED_ATTEMPTS = 5
    FAILED_ATTEMPT_WINDOW_SECONDS = 60
    FAILED_ATTEMPT_BLOCK_SECONDS = 120
    SHUTDOWN_NOTIFY_TIMEOUT_SECONDS = 0.5
    SHUTDOWN_CLOSE_TIMEOUT_SECONDS = 0.5

    def __init__(
        self,
        *,
        state_provider: MaybeAsync,
        submit_prompt: MaybeAsync,
        cancel_turn: MaybeAsync,
        switch_session: MaybeAsync | None = None,
        clear_command_ui: MaybeAsync | None = None,
        set_model: MaybeAsync | None = None,
        access_checker: MaybeAsync | None = None,
        transport: str = "direct",
        runtime_id: str | None = None,
    ) -> None:
        self._state_provider = state_provider
        self._submit_prompt = submit_prompt
        self._cancel_turn = cancel_turn
        self._switch_session = switch_session
        self._clear_command_ui = clear_command_ui
        self._set_model = set_model
        self._access_checker = access_checker
        self._transport = "relay" if str(transport or "").strip().lower() == "relay" else "direct"
        self._runtime_id_override = str(runtime_id or "").strip()
        self._relay_connected = False
        self._relay_app_count = 0
        self._server: asyncio.AbstractServer | None = None
        self._host: str = "0.0.0.0"
        self._port: int = 0
        self._display_host: str = "127.0.0.1"
        self._pair_code: str = ""
        self._pair_code_expires_at: datetime | None = None
        self._runtime_name: str = ""
        self._fingerprint: str = ""
        self._tls_cert_path: Path | None = None
        self._tls_key_path: Path | None = None
        self._clients: dict[str, _ClientConnection] = {}
        self._client_tasks: set[asyncio.Task[Any]] = set()
        self._trusted_devices: dict[str, _TrustedDevice] = {}
        self._failed_auth_attempts: dict[str, list[datetime]] = {}
        self._approval_requests: dict[str, _ApprovalRequest] = {}
        self._resolved_approval_requests: dict[str, _ResolvedApprovalRequest] = {}
        self._plan_question_requests: dict[str, _PlanQuestionRequest] = {}
        self._plan_ready_requests: dict[str, _PlanReadyRequest] = {}
        self._trusted_devices_path = remote_storage_dir() / "trusted-devices.json"
        self._load_trusted_devices()

    @property
    def is_running(self) -> bool:
        if self._transport == "relay":
            return self._relay_connected
        return self._server is not None

    @property
    def transport(self) -> str:
        return self._transport

    @property
    def runtime_id(self) -> str:
        """Stable runtime id derived from the TLS identity fingerprint."""
        if self._runtime_id_override:
            return self._runtime_id_override
        if self._fingerprint:
            digest = hashlib.sha256(self._fingerprint.encode("utf-8")).hexdigest()
            return f"rt_{digest[:32]}"
        return ""

    def set_relay_connected(self, connected: bool) -> None:
        self._relay_connected = bool(connected)

    def attach_relay_client(
        self,
        writer: ClientWriter,
        *,
        client_name: str = "iTE Cloud Relay",
        device_id: str = "cloud-relay",
    ) -> _ClientConnection:
        """Register the cloud relay as an authenticated client of this server.

        The relay carries the same frames a direct client would, so it is
        modelled as a normal authenticated client whose writer forwards to the
        cloud. This lets the existing broadcast/approval machinery work
        unchanged in relay mode.
        """
        client = _ClientConnection(
            client_id=uuid.uuid4().hex,
            writer=writer,
            address="relay",
            device_id=device_id,
            name=client_name,
            authenticated=True,
        )
        self._clients[client.client_id] = client
        self._relay_connected = True
        return client

    def detach_relay_client(self, client_id: str) -> None:
        self._clients.pop(client_id, None)
        if not any(client.authenticated for client in self._clients.values()):
            self._relay_connected = False

    def get_client(self, client_id: str) -> _ClientConnection | None:
        return self._clients.get(client_id)

    async def handle_client_message(
        self,
        client: _ClientConnection,
        message: dict[str, Any],
    ) -> None:
        """Dispatch a single decoded frame for a client connection."""
        if not client.authenticated:
            await self._handle_handshake(client, message)
            return
        await self._handle_authenticated_message(client, message)

    @property
    def pair_code(self) -> str:
        if not self._pair_code or self._pair_code_is_expired():
            self.regenerate_pair_code()
        return self._pair_code

    @property
    def authenticated_client_count(self) -> int:
        if self._transport == "relay":
            return self._relay_app_count
        return sum(1 for client in self._clients.values() if client.authenticated)

    def has_authenticated_clients(self) -> bool:
        if self._transport == "relay":
            return self._relay_app_count > 0
        return self.authenticated_client_count > 0

    def set_relay_app_count(self, count: int) -> None:
        self._relay_app_count = max(0, int(count))

    @property
    def relay_app_count(self) -> int:
        return self._relay_app_count

    @property
    def trusted_device_count(self) -> int:
        return sum(1 for device in self._trusted_devices.values() if device.is_active())

    def _load_trusted_devices(self) -> None:
        path = self._trusted_devices_path
        if not path.exists():
            self._trusted_devices = {}
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._trusted_devices = {}
            return
        devices: dict[str, _TrustedDevice] = {}
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                device = _TrustedDevice.from_json(item)
                if device.device_id:
                    devices[device.device_id] = device
        self._trusted_devices = devices

    def _persist_trusted_devices(self) -> None:
        payload = [device.to_json() for device in self._trusted_devices.values()]
        self._trusted_devices_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _find_device_by_token(self, token: str) -> _TrustedDevice | None:
        for device in self._trusted_devices.values():
            if device.token == token:
                return device
        return None

    def trusted_devices_snapshot(self) -> list[dict[str, Any]]:
        devices = sorted(
            self._trusted_devices.values(),
            key=lambda item: item.last_seen_at,
            reverse=True,
        )
        return [
            {
                "device_id": device.device_id,
                "device_id_short": device.device_id[:8],
                "name": device.name,
                "platform": device.platform,
                "issued_at": device.issued_at.isoformat(),
                "last_seen_at": device.last_seen_at.isoformat(),
                "expires_at": device.expires_at.isoformat(),
                "status": "active"
                if device.is_active()
                else ("revoked" if device.revoked_at is not None else "expired"),
            }
            for device in devices
        ]

    def revoke_device(self, selector: str) -> _TrustedDevice | None:
        token = selector.strip().lower()
        if not token:
            return None
        for device in self._trusted_devices.values():
            if device.device_id.lower() == token or device.device_id.lower().startswith(token):
                if device.revoked_at is None:
                    device.revoked_at = datetime.now(timezone.utc)
                    self._persist_trusted_devices()
                return device
        return None

    def revoke_all_devices(self) -> int:
        revoked = 0
        now = datetime.now(timezone.utc)
        for device in self._trusted_devices.values():
            if device.revoked_at is None:
                device.revoked_at = now
                revoked += 1
        if revoked:
            self._persist_trusted_devices()
        return revoked

    @property
    def exposure_mode(self) -> str:
        if self._transport == "relay":
            return "relay"
        return "local" if self._host in {"127.0.0.1", "::1", "localhost"} else "lan"

    def _client_address_key(self, client: _ClientConnection) -> str:
        address = client.address.split(":", 1)[0].strip()
        return address or "unknown"

    def _prune_failed_attempts(self, key: str, *, now: datetime) -> list[datetime]:
        window_start = now - timedelta(seconds=self.FAILED_ATTEMPT_WINDOW_SECONDS)
        attempts = [
            attempt
            for attempt in self._failed_auth_attempts.get(key, [])
            if attempt >= window_start
        ]
        if attempts:
            self._failed_auth_attempts[key] = attempts
        else:
            self._failed_auth_attempts.pop(key, None)
        return attempts

    def _is_address_throttled(self, client: _ClientConnection, *, now: datetime) -> bool:
        attempts = self._prune_failed_attempts(self._client_address_key(client), now=now)
        if len(attempts) < self.MAX_FAILED_ATTEMPTS:
            return False
        blocked_since = attempts[-self.MAX_FAILED_ATTEMPTS]
        return now < blocked_since + timedelta(seconds=self.FAILED_ATTEMPT_BLOCK_SECONDS)

    def _record_failed_attempt(self, client: _ClientConnection, *, now: datetime) -> None:
        key = self._client_address_key(client)
        attempts = self._prune_failed_attempts(key, now=now)
        attempts.append(now)
        self._failed_auth_attempts[key] = attempts

    def _clear_failed_attempts(self, client: _ClientConnection) -> None:
        self._failed_auth_attempts.pop(self._client_address_key(client), None)

    def _pair_code_is_expired(self) -> bool:
        expires_at = self._pair_code_expires_at
        return expires_at is None or datetime.now(timezone.utc) >= expires_at

    def regenerate_pair_code(self) -> str:
        self._pair_code = f"{uuid.uuid4().int % 1000000:06d}"
        self._pair_code_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self.PAIRING_TTL_MINUTES
        )
        return self._pair_code

    def ensure_identity(self) -> None:
        """Load the runtime's TLS identity (fingerprint + runtime name).

        Relay mode needs this: :attr:`runtime_id` is derived from the
        fingerprint and the relay registration carries the runtime name, but
        neither is populated by binding a socket. Relay mode never binds one,
        so without this the runtime cannot derive a stable id and never appears
        in the mobile app. Safe to call more than once.
        """
        if self._fingerprint and self._runtime_name:
            return
        identity = load_or_create_tls_identity()
        self._runtime_name = str(identity["runtime_name"])
        self._fingerprint = str(identity["fingerprint"])
        self._tls_cert_path = Path(identity["cert_path"])
        self._tls_key_path = Path(identity["key_path"])

    async def start(self, *, host: str = "0.0.0.0", port: int = 0) -> dict[str, Any]:
        if self._server is not None:
            return self.connection_info()

        self.ensure_identity()
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(
            certfile=str(self._tls_cert_path),
            keyfile=str(self._tls_key_path),
        )

        self._host = host
        self._server = await asyncio.start_server(
            self._handle_client,
            host=host,
            port=port,
            ssl=ssl_context,
        )
        sock = next(iter(self._server.sockets or []), None)
        if sock is None:
            raise RuntimeError("Remote server failed to bind a socket.")
        bound_host, bound_port = sock.getsockname()[:2]
        self._host = str(bound_host)
        self._port = int(bound_port)
        self._display_host = (
            "127.0.0.1" if self.exposure_mode == "local" else self._detect_display_host()
        )
        self.regenerate_pair_code()
        return self.connection_info()

    async def stop(
        self,
        *,
        reason: str = "bridge_stopped",
        message: str = "Remote bridge stopped.",
    ) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
            try:
                await asyncio.wait_for(
                    server.wait_closed(),
                    timeout=self.SHUTDOWN_CLOSE_TIMEOUT_SECONDS,
                )
            except Exception:
                pass

        if self.has_authenticated_clients():
            try:
                await asyncio.wait_for(
                    self._broadcast(
                        "remote_shutdown",
                        {
                            "reason": reason,
                            "message": message,
                            "timestamp": utc_now_iso(),
                        },
                    ),
                    timeout=self.SHUTDOWN_NOTIFY_TIMEOUT_SECONDS,
                )
            except Exception:
                pass

        for client in list(self._clients.values()):
            try:
                client.writer.close()
            except Exception:
                pass

        client_tasks = list(self._client_tasks)
        for task in client_tasks:
            task.cancel()
        if client_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*client_tasks, return_exceptions=True),
                    timeout=self.SHUTDOWN_CLOSE_TIMEOUT_SECONDS,
                )
            except Exception:
                pass
        self._client_tasks.clear()

        for client in list(self._clients.values()):
            try:
                await asyncio.wait_for(
                    client.writer.wait_closed(),
                    timeout=self.SHUTDOWN_CLOSE_TIMEOUT_SECONDS,
                )
            except Exception:
                pass
        self._clients.clear()
        for request in self._approval_requests.values():
            if not request.future.done():
                request.future.cancel()
        self._approval_requests.clear()
        for request in self._plan_question_requests.values():
            if not request.future.done():
                request.future.cancel()
        self._plan_question_requests.clear()
        for request in self._plan_ready_requests.values():
            if not request.future.done():
                request.future.cancel()
        self._plan_ready_requests.clear()

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
        info: dict[str, Any] = {
            "protocol_version": REMOTE_PROTOCOL_VERSION,
            "running": self.is_running,
            "transport": self._transport,
            "runtime_id": self.runtime_id,
            "tls_enabled": True,
            "exposure_mode": self.exposure_mode,
            "runtime_name": self._runtime_name,
            "fingerprint": self._fingerprint,
            "authenticated_clients": self.authenticated_client_count,
            "trusted_devices": self.trusted_device_count,
        }
        if self._transport == "relay":
            return info
        info.update(
            {
                "host": self._host,
                "port": self._port,
                "display_host": self._display_host,
                "pair_code": self.pair_code,
                "pair_code_expires_at": self._pair_code_expires_at.isoformat()
                if self._pair_code_expires_at
                else None,
                "connect_uri": create_connection_uri(
                    self._display_host,
                    self._port,
                    self.pair_code,
                    name=self._runtime_name,
                    fingerprint=self._fingerprint,
                    expires_at=self._pair_code_expires_at,
                ),
            }
        )
        return info

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
        resolved = self._resolved_approval_requests.pop(request_id, None)
        if resolved is not None:
            return resolved.approved
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._approval_requests[request_id] = _ApprovalRequest(
            future=future,
            created_at=datetime.now(timezone.utc),
            payload=dict(payload),
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

    async def resolve_approval_request(
        self,
        request_id: str,
        approved: bool,
    ) -> bool:
        if not request_id:
            return False
        request = self._approval_requests.get(request_id)
        resolved = request is not None
        if request is None:
            self._resolved_approval_requests[request_id] = _ResolvedApprovalRequest(
                approved=bool(approved),
                created_at=datetime.now(timezone.utc),
            )
        elif not request.future.done():
            request.future.set_result(bool(approved))
        await self._broadcast(
            "approval_resolved",
            {"request_id": request_id, "approved": bool(approved)},
        )
        return resolved

    async def request_plan_question(
        self,
        payload: dict[str, Any],
        *,
        timeout: float = 300.0,
    ) -> dict[str, Any] | None:
        if not self.has_authenticated_clients():
            return None
        request_id = str(payload.get("request_id") or uuid.uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._plan_question_requests[request_id] = _PlanQuestionRequest(
            future=future,
            created_at=datetime.now(timezone.utc),
            payload=dict(payload),
        )
        outbound = dict(payload)
        outbound["request_id"] = request_id
        await self._broadcast("plan_question_request", outbound)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._plan_question_requests.pop(request_id, None)

    async def resolve_plan_question_request(
        self,
        request_id: str,
        answer: dict[str, Any],
    ) -> bool:
        request = self._plan_question_requests.get(request_id)
        if request is None:
            return False
        if not request.future.done():
            request.future.set_result(answer)
        await self._broadcast(
            "plan_question_resolved",
            {
                "request_id": request_id,
                "answered": True,
                "request": json_safe(request.payload),
                "answer": json_safe(answer),
            },
        )
        return True

    async def request_plan_ready(
        self,
        payload: dict[str, Any],
        *,
        timeout: float = 300.0,
    ) -> bool | None:
        if not self.has_authenticated_clients():
            return None
        request_id = str(payload.get("request_id") or uuid.uuid4())
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._plan_ready_requests[request_id] = _PlanReadyRequest(
            future=future,
            created_at=datetime.now(timezone.utc),
            payload=dict(payload),
        )
        outbound = dict(payload)
        outbound["request_id"] = request_id
        await self._broadcast("plan_ready_request", outbound)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._plan_ready_requests.pop(request_id, None)

    async def resolve_plan_ready_request(
        self,
        request_id: str,
        approved: bool,
    ) -> bool:
        request = self._plan_ready_requests.get(request_id)
        if request is None:
            return False
        if not request.future.done():
            request.future.set_result(bool(approved))
        await self._broadcast(
            "plan_ready_resolved",
            {"request_id": request_id, "approved": bool(approved)},
        )
        return True

    async def _build_state_payload(self) -> dict[str, Any]:
        state = await self._call(self._state_provider)
        payload = json_safe(state)
        if isinstance(payload, dict):
            payload.setdefault("protocol_version", REMOTE_PROTOCOL_VERSION)
            payload.setdefault("server", self.connection_info())
            payload.setdefault("timestamp", utc_now_iso())
            pending_plan_question = None
            if self._plan_question_requests:
                request_id, request = next(iter(self._plan_question_requests.items()))
                pending_plan_question = json_safe(request.payload)
                pending_plan_question["request_id"] = request_id
            pending_plan_ready = None
            if self._plan_ready_requests:
                request_id, request = next(iter(self._plan_ready_requests.items()))
                pending_plan_ready = json_safe(request.payload)
                pending_plan_ready["request_id"] = request_id
            payload["pending_plan_question"] = pending_plan_question
            payload["pending_plan_ready"] = pending_plan_ready
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
        task = asyncio.current_task()
        if task is not None:
            self._client_tasks.add(task)
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
        except asyncio.CancelledError:
            raise
        finally:
            if task is not None:
                self._client_tasks.discard(task)
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
        device_id = str(payload.get("device_id") or "").strip() or uuid.uuid4().hex
        device_name = str(payload.get("client_name") or "").strip() or "iTE Remote"
        device_platform = str(payload.get("platform") or "").strip()
        now = datetime.now(timezone.utc)

        if not await self._has_remote_access():
            await self._send(
                client,
                "error",
                {
                    "code": "remote_entitlement_denied",
                    "message": "Remote companion requires bundled access for this iTE account.",
                    "recovery_hint": "Sign in to an account with bundled access on your computer, then run `/remote on` again.",
                },
            )
            return

        if self._is_address_throttled(client, now=now):
            await self._send(
                client,
                "error",
                {
                    "message": "Too many failed pairing attempts. Wait a moment, then try again with a fresh secure link.",
                },
            )
            return

        authenticated = False
        if token:
            trusted_device = self._find_device_by_token(token)
            if (
                trusted_device is not None
                and trusted_device.device_id == device_id
                and trusted_device.is_active()
            ):
                authenticated = True
                trusted_device.last_seen_at = now
                trusted_device.name = device_name
                trusted_device.platform = device_platform
                self._persist_trusted_devices()
                self._clear_failed_attempts(client)
            else:
                self._record_failed_attempt(client, now=now)
                await self._send(
                    client,
                    "error",
                    {
                        "message": "Trusted device token is invalid or expired. Pair again with a fresh secure link.",
                    },
                )
                return
        elif pair_code and pair_code == self.pair_code and not self._pair_code_is_expired():
            authenticated = True
            token = uuid.uuid4().hex
            self._trusted_devices[device_id] = _TrustedDevice(
                device_id=device_id,
                token=token,
                name=device_name,
                platform=device_platform,
                issued_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(days=self.TOKEN_TTL_DAYS),
            )
            self._persist_trusted_devices()
            self._clear_failed_attempts(client)

        if not authenticated:
            self._record_failed_attempt(client, now=now)
            await self._send(
                client,
                "error",
                {"message": "Pairing failed. Check the current pair code."},
            )
            return

        client.authenticated = True
        client.device_id = device_id
        client.token = token
        client.name = device_name
        client.platform = device_platform

        await self._send(
            client,
            "paired",
            {
                "token": token,
                "device_id": device_id,
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

        if not await self._has_remote_access():
            await self._send(
                client,
                "error",
                {
                    "code": "remote_entitlement_denied",
                    "message": "Remote companion access is no longer available for this iTE account.",
                    "recovery_hint": "Manage bundled access on your computer, then reconnect from the mobile app.",
                },
                request_id=request_id,
            )
            try:
                client.writer.close()
                await client.writer.wait_closed()
            except Exception:
                pass
            return

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
        if msg_type == "clear_command_ui":
            # The client has shown (or dismissed) the surface a command asked
            # for, so the runtime stops advertising it.
            if self._clear_command_ui is not None:
                await self._call(self._clear_command_ui)
            await self._send(
                client,
                "command_ack",
                {"ok": True, "message": "Command UI cleared."},
                request_id=request_id,
            )
            return
        if msg_type == "set_model":
            model_name = str(payload.get("model") or "").strip()
            if not model_name:
                await self._send(
                    client,
                    "command_ack",
                    {"ok": False, "message": "Model name is required."},
                    request_id=request_id,
                )
                return
            if self._set_model is None:
                await self._send(
                    client,
                    "command_ack",
                    {"ok": False, "message": "Model switching is unavailable."},
                    request_id=request_id,
                )
                return
            applied = bool(await self._call(self._set_model, model_name))
            await self._send(
                client,
                "command_ack",
                {
                    "ok": applied,
                    "message": (
                        f"Model set to {model_name}."
                        if applied
                        else "Could not apply that model."
                    ),
                },
                request_id=request_id,
            )
            return
        if msg_type == "approval_response":
            approval_id = str(payload.get("request_id") or "").strip()
            approved = bool(payload.get("approved"))
            resolved = await self.resolve_approval_request(approval_id, approved)
            if not resolved:
                await self._send(
                    client,
                    "command_ack",
                    {"ok": False, "message": "Approval request no longer exists."},
                    request_id=request_id,
                )
                return
            await self._send(
                client,
                "command_ack",
                {"ok": True, "message": "Approval response recorded."},
                request_id=request_id,
            )
            return
        if msg_type == "plan_question_response":
            question_id = str(payload.get("request_id") or "").strip()
            request = self._plan_question_requests.get(question_id)
            if request is None:
                await self._send(
                    client,
                    "command_ack",
                    {"ok": False, "message": "Plan question no longer exists."},
                    request_id=request_id,
                )
                return
            answer = {
                "selected_option": str(payload.get("selected_option") or "").strip(),
                "free_text": str(payload.get("free_text") or "").strip(),
                "selected_index": payload.get("selected_index"),
            }
            if not request.future.done():
                request.future.set_result(answer)
            await self._broadcast(
                "plan_question_resolved",
                {
                    "request_id": question_id,
                    "answered": True,
                    "request": json_safe(request.payload),
                    "answer": json_safe(answer),
                },
            )
            await self._send(
                client,
                "command_ack",
                {"ok": True, "message": "Plan question response recorded."},
                request_id=request_id,
            )
            return
        if msg_type == "plan_ready_response":
            prompt_id = str(payload.get("request_id") or "").strip()
            request = self._plan_ready_requests.get(prompt_id)
            if request is None:
                await self._send(
                    client,
                    "command_ack",
                    {"ok": False, "message": "Plan ready prompt no longer exists."},
                    request_id=request_id,
                )
                return
            approved = bool(payload.get("approved"))
            if not request.future.done():
                request.future.set_result(approved)
            await self._broadcast(
                "plan_ready_resolved",
                {"request_id": prompt_id, "approved": approved},
            )
            await self._send(
                client,
                "command_ack",
                {"ok": True, "message": "Plan ready response recorded."},
                request_id=request_id,
            )
            return

        await self._send(
            client,
            "error",
            {"message": f"Unsupported message type: {msg_type or 'unknown'}"},
            request_id=request_id,
        )

    async def _has_remote_access(self) -> bool:
        if self._access_checker is None:
            return True
        return bool(await self._call(self._access_checker))

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
