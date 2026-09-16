from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ite.integrations.open_island.client import (
    OpenIslandBridgeError,
    OpenIslandClient,
    encode_command,
    hooks_disabled,
    resolve_socket_path,
)

_HELLO_LINE = json.dumps(
    {
        "type": "hello",
        "hello": {"protocolVersion": 1, "serverLabel": "local-bridge"},
    }
)


async def _serve(socket_path: Path, responses: list[str], received: list[str]) -> None:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write((_HELLO_LINE + "\n").encode("utf-8"))
        await writer.drain()

        line = await reader.readline()
        if line:
            received.append(line.decode("utf-8").strip())

        if not responses:
            # Hold the connection open without replying so callers observe a
            # timeout rather than an end-of-stream.
            await asyncio.sleep(3600)
            return

        for response in responses:
            writer.write((response + "\n").encode("utf-8"))
            await writer.drain()

        writer.close()

    server = await asyncio.start_unix_server(handle, path=str(socket_path))
    async with server:
        await server.serve_forever()


class ResolveSocketPathTests(unittest.TestCase):
    def test_open_island_env_var_wins(self) -> None:
        path = resolve_socket_path(
            env={
                "OPEN_ISLAND_SOCKET_PATH": "/tmp/custom.sock",
                "VIBE_ISLAND_SOCKET_PATH": "/tmp/legacy.sock",
            },
            home="/Users/someone",
        )
        self.assertEqual(path, Path("/tmp/custom.sock"))

    def test_legacy_env_var_used_as_fallback(self) -> None:
        path = resolve_socket_path(
            env={"VIBE_ISLAND_SOCKET_PATH": "/tmp/legacy.sock"},
            home="/Users/someone",
        )
        self.assertEqual(path, Path("/tmp/legacy.sock"))

    def test_empty_env_var_is_ignored(self) -> None:
        path = resolve_socket_path(
            env={"OPEN_ISLAND_SOCKET_PATH": ""},
            home="/Users/someone",
        )
        self.assertEqual(
            path,
            Path("/Users/someone/Library/Application Support/OpenIsland/bridge.sock"),
        )

    def test_default_path_matches_upstream_location(self) -> None:
        path = resolve_socket_path(env={}, home="/Users/someone")
        self.assertEqual(
            path,
            Path("/Users/someone/Library/Application Support/OpenIsland/bridge.sock"),
        )


class HooksDisabledTests(unittest.TestCase):
    def test_skip_env_var_disables(self) -> None:
        self.assertTrue(hooks_disabled({"OPEN_ISLAND_SKIP_HOOKS": "1"}))

    def test_legacy_skip_env_var_disables(self) -> None:
        self.assertTrue(hooks_disabled({"VIBE_ISLAND_SKIP": "1"}))

    def test_other_values_do_not_disable(self) -> None:
        self.assertFalse(
            hooks_disabled({"OPEN_ISLAND_SKIP_HOOKS": "0", "VIBE_ISLAND_SKIP": ""})
        )


class EncodeCommandTests(unittest.TestCase):
    def test_envelope_shape_matches_bridge_contract(self) -> None:
        encoded = encode_command({"type": "processClaudeHook"})
        self.assertTrue(encoded.endswith(b"\n"))

        envelope = json.loads(encoded.decode("utf-8"))
        self.assertEqual(envelope["type"], "command")
        self.assertEqual(envelope["command"], {"type": "processClaudeHook"})

    def test_nested_payload_is_preserved(self) -> None:
        payload = {"type": "processClaudeHook", "claudeHook": {"session_id": "abc"}}
        envelope = json.loads(encode_command(payload).decode("utf-8"))
        self.assertEqual(envelope["command"]["claudeHook"]["session_id"], "abc")


class OpenIslandClientTests(unittest.IsolatedAsyncioTestCase):
    async def _start_server(
        self,
        responses: list[str],
    ) -> tuple[Path, list[str], asyncio.Task[None]]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        socket_path = Path(tmp.name) / "bridge.sock"
        received: list[str] = []
        task = asyncio.create_task(_serve(socket_path, responses, received))

        for _ in range(100):
            if socket_path.exists():
                break
            await asyncio.sleep(0.01)

        self.addCleanup(task.cancel)
        return socket_path, received, task

    async def test_hello_is_skipped_and_response_returned(self) -> None:
        socket_path, received, _ = await self._start_server(
            [json.dumps({"type": "response", "response": {"type": "acknowledged"}})]
        )
        client = OpenIslandClient(socket_path=socket_path)

        result = await client.send({"type": "processClaudeHook"})

        self.assertEqual(result, {"type": "acknowledged"})
        self.assertEqual(len(received), 1)
        self.assertEqual(json.loads(received[0])["type"], "command")

    async def test_directive_response_is_returned(self) -> None:
        directive = {
            "type": "response",
            "response": {
                "type": "claudeHookDirective",
                "directive": {"type": "permissionRequest"},
            },
        }
        socket_path, _, _ = await self._start_server([json.dumps(directive)])
        client = OpenIslandClient(socket_path=socket_path)

        result = await client.send({"type": "processClaudeHook"})

        self.assertEqual(result, directive["response"])

    async def test_timeout_raises_bridge_error(self) -> None:
        socket_path, _, _ = await self._start_server([])
        client = OpenIslandClient(socket_path=socket_path)

        with self.assertRaises(OpenIslandBridgeError):
            await client.send({"type": "processClaudeHook"}, timeout=0.2)

    async def test_missing_socket_raises_bridge_error(self) -> None:
        client = OpenIslandClient(socket_path="/tmp/definitely-not-a-bridge.sock")

        with self.assertRaises(OpenIslandBridgeError):
            await client.send({"type": "processClaudeHook"})

    async def test_try_send_fails_open_when_socket_missing(self) -> None:
        client = OpenIslandClient(socket_path="/tmp/definitely-not-a-bridge.sock")

        self.assertIsNone(await client.try_send({"type": "processClaudeHook"}))

    async def test_try_send_fails_open_on_timeout(self) -> None:
        socket_path, _, _ = await self._start_server([])
        client = OpenIslandClient(socket_path=socket_path)

        self.assertIsNone(
            await client.try_send({"type": "processClaudeHook"}, timeout=0.2)
        )

    async def test_is_available_reflects_live_bridge(self) -> None:
        socket_path, _, _ = await self._start_server([])

        self.assertTrue(await OpenIslandClient(socket_path=socket_path).is_available())
        self.assertFalse(
            await OpenIslandClient(socket_path="/tmp/definitely-not-a-bridge.sock").is_available()
        )

    async def test_is_available_is_false_for_stale_socket_file(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        stale_path = Path(tmp.name) / "bridge.sock"

        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.bind(str(stale_path))
        probe.close()

        self.assertTrue(stale_path.exists())
        self.assertFalse(await OpenIslandClient(socket_path=stale_path).is_available())

    async def test_socket_exists_is_true_for_stale_socket_file(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        stale_path = Path(tmp.name) / "bridge.sock"

        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.bind(str(stale_path))
        probe.close()

        self.assertTrue(OpenIslandClient(socket_path=stale_path).socket_exists())

    async def test_socket_environment_override_is_honoured(self) -> None:
        socket_path, _, _ = await self._start_server(
            [json.dumps({"type": "response", "response": {"type": "acknowledged"}})]
        )

        with mock.patch.dict(
            os.environ, {"OPEN_ISLAND_SOCKET_PATH": str(socket_path)}
        ):
            client = OpenIslandClient()
            self.assertEqual(client.socket_path, socket_path)
            self.assertEqual(
                await client.send({"type": "processClaudeHook"}),
                {"type": "acknowledged"},
            )


if __name__ == "__main__":
    unittest.main()
