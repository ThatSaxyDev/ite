from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SOCKET_ENV_VARS = ("OPEN_ISLAND_SOCKET_PATH", "VIBE_ISLAND_SOCKET_PATH")
_SKIP_ENV_VARS = ("OPEN_ISLAND_SKIP_HOOKS", "VIBE_ISLAND_SKIP")
_SOCKET_RELATIVE_PATH = ("Library", "Application Support", "OpenIsland", "bridge.sock")

_COMMAND_ENVELOPE_TYPE = "command"
_RESPONSE_ENVELOPE_TYPE = "response"
_HELLO_ENVELOPE_TYPE = "hello"


class OpenIslandBridgeError(Exception):
    """Raised when a bridge exchange with Open Island cannot be completed."""


def hooks_disabled(env: dict[str, str] | None = None) -> bool:
    """Return True when the per-process Open Island opt-out is set.

    Mirrors the upstream ``HookSkipConfiguration`` behaviour: only the exact
    value ``1`` disables hooks, so an empty or unrelated value is ignored.
    """
    source = os.environ if env is None else env
    for name in _SKIP_ENV_VARS:
        if source.get(name, "").strip() == "1":
            return True
    return False


def resolve_socket_path(
    env: dict[str, str] | None = None,
    home: Path | str | None = None,
) -> Path:
    """Resolve the bridge socket path using upstream precedence.

    ``OPEN_ISLAND_SOCKET_PATH`` wins, then the legacy ``VIBE_ISLAND_SOCKET_PATH``
    alias, then the stable per-user location under Application Support.
    """
    source = os.environ if env is None else env
    for name in _SOCKET_ENV_VARS:
        value = source.get(name, "").strip()
        if value:
            return Path(value).expanduser()

    home_dir = Path(home).expanduser() if home is not None else Path.home()
    return home_dir.joinpath(*_SOCKET_RELATIVE_PATH)


def encode_command(command: dict[str, Any]) -> bytes:
    """Serialise a bridge command into a newline-delimited JSON envelope."""
    envelope = {"type": _COMMAND_ENVELOPE_TYPE, "command": command}
    payload = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
    return (payload + "\n").encode("utf-8")


class OpenIslandClient:
    """Minimal newline-delimited JSON client for the Open Island bridge socket.

    Speaks the verified wire protocol directly rather than shelling out to the
    upstream ``OpenIslandHooks`` binary, so the caller controls the payload
    verbatim. Fails open: every failure surfaces as ``OpenIslandBridgeError``.
    """

    def __init__(
        self,
        socket_path: Path | str | None = None,
        default_timeout: float = 5.0,
    ) -> None:
        self._socket_path = Path(socket_path) if socket_path is not None else None
        self.default_timeout = default_timeout

    @property
    def socket_path(self) -> Path:
        if self._socket_path is not None:
            return self._socket_path
        return resolve_socket_path()

    def socket_exists(self) -> bool:
        """Return True when the socket file is present on disk.

        Note this is *not* a liveness check: a socket file left behind by a
        terminated Open Island still exists but refuses connections.
        """
        try:
            return self.socket_path.exists()
        except OSError:
            return False

    async def is_available(self) -> bool:
        """Probe the bridge and report whether it accepts a connection.

        Performs a real connect, because a stale socket file from a stopped
        Open Island would otherwise report as available.
        """
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self.socket_path)),
                timeout=self.default_timeout,
            )
        except (OSError, TimeoutError):
            return False

        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True

    async def send(
        self,
        command: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Send one command and return the bridge response, if any.

        The server emits a ``hello`` envelope immediately on connect; it is
        skipped while waiting for the matching ``response`` envelope.
        """
        effective_timeout = self.default_timeout if timeout is None else timeout
        path = str(self.socket_path)

        try:
            return await asyncio.wait_for(
                self._exchange(path, command),
                timeout=effective_timeout,
            )
        except TimeoutError as exc:
            raise OpenIslandBridgeError(
                f"Open Island bridge timed out after {effective_timeout:g}s"
            ) from exc
        except OSError as exc:
            raise OpenIslandBridgeError(
                f"Open Island bridge unavailable at {path}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise OpenIslandBridgeError(
                "Open Island bridge returned a malformed envelope"
            ) from exc

    async def try_send(
        self,
        command: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Fail-open variant of :meth:`send`. Never raises."""
        try:
            return await self.send(command, timeout=timeout)
        except OpenIslandBridgeError as exc:
            logger.debug("Open Island bridge send skipped: %s", exc)
            return None

    async def _exchange(
        self,
        path: str,
        command: dict[str, Any],
    ) -> dict[str, Any] | None:
        reader, writer = await asyncio.open_unix_connection(path)
        try:
            writer.write(encode_command(command))
            await writer.drain()

            while True:
                line = await reader.readline()
                if not line:
                    return None

                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                envelope = json.loads(text)
                if not isinstance(envelope, dict):
                    continue

                kind = envelope.get("type")
                if kind == _HELLO_ENVELOPE_TYPE:
                    continue
                if kind == _RESPONSE_ENVELOPE_TYPE:
                    response = envelope.get("response")
                    return response if isinstance(response, dict) else None
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def send_sync(
        self,
        command: dict[str, Any],
        *,
        timeout: float = 2.0,
    ) -> dict[str, Any] | None:
        """Blocking send for teardown paths where no event loop is available.

        Used from ``atexit`` handlers: the asyncio loop is typically already
        closed by then, but a leaked session in the notch is exactly the
        failure this integration must avoid. Fail-open like the async path.
        """
        import socket as socket_module

        sock = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(str(self.socket_path))
            sock.sendall(encode_command(command))

            buffer = b""
            while True:
                try:
                    chunk = sock.recv(8192)
                except (TimeoutError, OSError):
                    return None
                if not chunk:
                    return None

                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    try:
                        envelope = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(envelope, dict):
                        continue
                    if envelope.get("type") == _RESPONSE_ENVELOPE_TYPE:
                        response = envelope.get("response")
                        return response if isinstance(response, dict) else None
        except (OSError, TimeoutError):
            return None
        finally:
            try:
                sock.close()
            except OSError:
                pass
