from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from dataclasses import dataclass, field
from typing import Any

from ite.remote.server import RemoteRuntimeServer
from ite.remote.server import _ApprovalRequest
from ite.remote.server import _PlanQuestionRequest
from ite.remote.server import _PlanReadyRequest
from ite.remote.server import _TrustedDevice
from ite.remote.security import load_or_create_tls_identity
from ite.remote.uri import parse_connection_uri


@dataclass
class _FakeClient:
    client_id: str = "client-1"
    address: str = "127.0.0.1:50000"
    authenticated: bool = False
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self.writer = _FakeWriter()


class _FakeWriter:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.frames.append(__import__("json").loads(data.decode("utf-8")))

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _HangingWriter(_FakeWriter):
    async def drain(self) -> None:
        await asyncio.sleep(10)

    async def wait_closed(self) -> None:
        await asyncio.sleep(10)


class RemoteRuntimeServerStateTests(unittest.IsolatedAsyncioTestCase):
    def _isolated_server(self) -> RemoteRuntimeServer:
        server = RemoteRuntimeServer(
            state_provider=lambda: {},
            submit_prompt=lambda _message: None,
            cancel_turn=lambda: None,
        )
        temp_dir = Path(tempfile.mkdtemp(prefix="ite-remote-test-"))
        server._trusted_devices_path = temp_dir / "trusted-devices.json"
        server._trusted_devices = {}
        return server

    async def test_build_state_payload_includes_pending_plan_prompts(self) -> None:
        server = self._isolated_server()
        server._state_provider = lambda: {"current_session": {"session_id": "session-1"}}
        loop = asyncio.get_running_loop()
        server._plan_question_requests["pq-1"] = _PlanQuestionRequest(
            future=loop.create_future(),
            created_at=datetime.now(timezone.utc),
            payload={
                "session_id": "session-1",
                "question": "Pick a direction",
                "options": ["A", "B"],
                "recommended_index": 0,
                "allow_free_text": True,
                "question_number": 1,
            },
        )
        server._plan_ready_requests["pr-1"] = _PlanReadyRequest(
            future=loop.create_future(),
            created_at=datetime.now(timezone.utc),
            payload={
                "session_id": "session-1",
                "plan_text": "1. Do it",
                "question_count": 1,
            },
        )

        payload = await server._build_state_payload()

        self.assertEqual(payload["pending_plan_question"]["request_id"], "pq-1")
        self.assertEqual(payload["pending_plan_question"]["question"], "Pick a direction")
        self.assertEqual(payload["pending_plan_ready"]["request_id"], "pr-1")
        self.assertEqual(payload["pending_plan_ready"]["plan_text"], "1. Do it")

    async def test_build_state_payload_preserves_runtime_command_feed(self) -> None:
        server = self._isolated_server()
        server._state_provider = lambda: {
            "current_session": {"session_id": "session-1"},
            "command_feed": [
                {
                    "id": "cmd-1",
                    "session_id": "session-1",
                    "command": "/init --force",
                    "timestamp": "2026-04-23T20:00:00+00:00",
                    "status": "running",
                    "output": "Scanning project structure...",
                    "metadata": {
                        "kind": "generic",
                        "command_name": "/init",
                    },
                }
            ],
        }

        payload = await server._build_state_payload()

        self.assertEqual(len(payload["command_feed"]), 1)
        self.assertEqual(payload["command_feed"][0]["command"], "/init --force")
        self.assertEqual(payload["command_feed"][0]["status"], "running")
        self.assertEqual(payload["command_feed"][0]["metadata"]["kind"], "generic")

    async def test_resolve_plan_question_request_completes_pending_future(self) -> None:
        server = self._isolated_server()
        future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        server._plan_question_requests["pq-1"] = _PlanQuestionRequest(
            future=future,
            created_at=datetime.now(timezone.utc),
            payload={"question": "Pick one"},
        )

        resolved = await server.resolve_plan_question_request(
            "pq-1",
            {"selected_option": "A", "free_text": "", "selected_index": 0},
        )

        self.assertTrue(resolved)
        self.assertEqual(future.result()["selected_option"], "A")

    async def test_resolve_plan_ready_request_completes_pending_future(self) -> None:
        server = self._isolated_server()
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        server._plan_ready_requests["pr-1"] = _PlanReadyRequest(
            future=future,
            created_at=datetime.now(timezone.utc),
            payload={"plan_text": "1. Do it"},
        )

        resolved = await server.resolve_plan_ready_request("pr-1", True)

        self.assertTrue(resolved)
        self.assertTrue(future.result())

    async def test_resolve_approval_request_completes_pending_future(self) -> None:
        server = self._isolated_server()
        client = _FakeClient(authenticated=True)
        server._clients[client.client_id] = client
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        server._approval_requests["approval-1"] = _ApprovalRequest(
            future=future,
            created_at=datetime.now(timezone.utc),
            payload={"tool_name": "git_commit"},
        )

        resolved = await server.resolve_approval_request("approval-1", True)

        self.assertTrue(resolved)
        self.assertTrue(future.result())
        self.assertEqual(client.writer.frames[0]["type"], "approval_resolved")
        self.assertEqual(client.writer.frames[0]["payload"]["request_id"], "approval-1")

    async def test_resolve_approval_before_request_prevents_stale_mobile_prompt(
        self,
    ) -> None:
        server = self._isolated_server()
        client = _FakeClient(authenticated=True)
        server._clients[client.client_id] = client

        resolved = await server.resolve_approval_request("approval-early", False)
        approved = await server.request_approval(
            {"request_id": "approval-early", "tool_name": "git_commit"},
            timeout=0.01,
        )

        self.assertFalse(resolved)
        self.assertFalse(approved)
        self.assertEqual(
            [frame["type"] for frame in client.writer.frames],
            ["approval_resolved"],
        )
        self.assertFalse(client.writer.frames[0]["payload"]["approved"])

    async def test_connection_info_exposes_secure_link_fields(self) -> None:
        server = self._isolated_server()
        identity = load_or_create_tls_identity()
        server._runtime_name = str(identity["runtime_name"])
        server._fingerprint = str(identity["fingerprint"])
        server._host = "127.0.0.1"
        server._display_host = "127.0.0.1"
        server._port = 9123
        server.regenerate_pair_code()
        info = server.connection_info()
        parsed = parse_connection_uri(str(info["connect_uri"]))

        self.assertTrue(info["tls_enabled"])
        self.assertTrue(str(info["fingerprint"]).startswith("sha256:"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["host"], info["display_host"])
        self.assertEqual(parsed["pair_code"], info["pair_code"])
        self.assertEqual(parsed["fingerprint"], info["fingerprint"])
        self.assertEqual(info["exposure_mode"], "local")
        self.assertEqual(info["transport"], "direct")
        self.assertTrue(str(info["runtime_id"]).startswith("rt_"))

    async def test_connection_info_direct_mode_defaults(self) -> None:
        server = self._isolated_server()
        server._fingerprint = "sha256:abc123"
        info = server.connection_info()

        self.assertEqual(info["transport"], "direct")
        self.assertEqual(info["runtime_id"], "rt_" + __import__("hashlib").sha256(
            b"sha256:abc123"
        ).hexdigest()[:32])
        self.assertIn("connect_uri", info)
        self.assertIn("pair_code", info)

    async def test_connection_info_relay_mode_omits_direct_connect_data(self) -> None:
        server = RemoteRuntimeServer(
            state_provider=lambda: {},
            submit_prompt=lambda _message: None,
            cancel_turn=lambda: None,
            transport="relay",
            runtime_id="rt_custom",
        )
        server._fingerprint = "sha256:abc123"
        server._runtime_name = "vps-runtime"
        server._host = "0.0.0.0"
        server._display_host = "10.0.0.5"
        server._port = 9123

        info = server.connection_info()

        self.assertEqual(info["transport"], "relay")
        self.assertEqual(info["runtime_id"], "rt_custom")
        self.assertEqual(info["exposure_mode"], "relay")
        for leaked in ("connect_uri", "pair_code", "pair_code_expires_at", "host", "port", "display_host"):
            self.assertNotIn(leaked, info)
        self.assertTrue(str(info["runtime_id"]).startswith("rt_"))

    async def test_relay_mode_running_tracks_connection_state(self) -> None:
        server = RemoteRuntimeServer(
            state_provider=lambda: {},
            submit_prompt=lambda _message: None,
            cancel_turn=lambda: None,
            transport="relay",
        )

        self.assertFalse(server.is_running)
        server.set_relay_connected(True)
        self.assertTrue(server.is_running)
        server.set_relay_connected(False)
        self.assertFalse(server.is_running)

    async def test_build_state_payload_relay_mode_uses_relay_identity(self) -> None:
        server = RemoteRuntimeServer(
            state_provider=lambda: {},
            submit_prompt=lambda _message: None,
            cancel_turn=lambda: None,
            transport="relay",
            runtime_id="rt_state_test",
        )
        server._fingerprint = "sha256:def456"
        server._state_provider = lambda: {"current_session": {"session_id": "s-1"}}

        payload = await server._build_state_payload()

        self.assertEqual(payload["server"]["transport"], "relay")
        self.assertEqual(payload["server"]["runtime_id"], "rt_state_test")
        self.assertNotIn("connect_uri", payload["server"])

    async def test_handshake_rejects_when_access_checker_denies_remote(self) -> None:
        server = RemoteRuntimeServer(
            state_provider=lambda: {},
            submit_prompt=lambda _message: None,
            cancel_turn=lambda: None,
            access_checker=lambda: False,
        )
        client = _FakeClient()

        await server._handle_handshake(
            client,
            {
                "type": "hello",
                "payload": {
                    "pair_code": "123456",
                    "device_id": "device-1",
                },
            },
        )

        self.assertFalse(client.authenticated)
        self.assertEqual(client.writer.frames[0]["type"], "error")
        self.assertEqual(
            client.writer.frames[0]["payload"]["code"],
            "remote_entitlement_denied",
        )

    async def test_stop_notifies_authenticated_clients_before_closing(self) -> None:
        server = self._isolated_server()
        client = _FakeClient(authenticated=True)
        server._clients[client.client_id] = client

        await server.stop(reason="bridge_stopped", message="Remote bridge stopped.")

        self.assertEqual(client.writer.frames[0]["type"], "remote_shutdown")
        self.assertEqual(client.writer.frames[0]["payload"]["reason"], "bridge_stopped")
        self.assertTrue(client.writer.closed)

    async def test_stop_does_not_hang_on_stuck_client_socket(self) -> None:
        server = self._isolated_server()
        server.SHUTDOWN_NOTIFY_TIMEOUT_SECONDS = 0.01
        server.SHUTDOWN_CLOSE_TIMEOUT_SECONDS = 0.01
        client = _FakeClient(authenticated=True)
        client.writer = _HangingWriter()
        server._clients[client.client_id] = client

        await asyncio.wait_for(server.stop(), timeout=0.2)

        self.assertEqual(server._clients, {})
        self.assertTrue(client.writer.closed)

    async def test_revoke_all_devices_marks_tokens_inactive(self) -> None:
        server = self._isolated_server()
        now = datetime.now(timezone.utc)
        server._trusted_devices["device-1"] = _TrustedDevice(
            device_id="device-1",
            token="token-1",
            name="Phone",
            platform="android",
            issued_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(days=365),
        )

        revoked = server.revoke_all_devices()

        self.assertEqual(revoked, 1)
        self.assertFalse(server._trusted_devices["device-1"].is_active())

    async def test_revoke_device_matches_prefix(self) -> None:
        server = self._isolated_server()
        now = datetime.now(timezone.utc)
        server._trusted_devices["device-abcdef12"] = _TrustedDevice(
            device_id="device-abcdef12",
            token="token-1",
            name="Phone",
            platform="android",
            issued_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(days=365),
        )

        revoked = server.revoke_device("device-a")

        self.assertIsNotNone(revoked)
        assert revoked is not None
        self.assertEqual(revoked.device_id, "device-abcdef12")
        self.assertIsNotNone(revoked.revoked_at)

    async def test_failed_attempt_throttling_blocks_after_threshold(self) -> None:
        server = self._isolated_server()
        client = type("Client", (), {"address": "192.168.0.5:5000"})()
        now = datetime.now(timezone.utc)

        for _ in range(server.MAX_FAILED_ATTEMPTS):
            server._record_failed_attempt(client, now=now)

        self.assertTrue(server._is_address_throttled(client, now=now))

        later = now + timedelta(seconds=server.FAILED_ATTEMPT_BLOCK_SECONDS + 1)
        self.assertFalse(server._is_address_throttled(client, now=later))

    async def test_stop_cancels_registered_client_tasks(self) -> None:
        server = self._isolated_server()

        async def _wait_forever() -> None:
            try:
                while True:
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(_wait_forever())
        server._client_tasks.add(task)

        await server.stop()

        self.assertTrue(task.cancelled())
        self.assertEqual(server._client_tasks, set())


if __name__ == "__main__":
    unittest.main()
