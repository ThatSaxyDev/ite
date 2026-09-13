from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .host_identity import HostIdentity

logger = logging.getLogger(__name__)

_RECONNECT_MIN_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0
_HEARTBEAT_SECONDS = 25.0
_MESSAGE_SIZE_LIMIT = 16 * 1024 * 1024
_RESTART_BACKOFF_SECONDS = 5.0
_MAX_CONSECUTIVE_FAILURES = 3
# Refresh the runtime token well before the cloud's 12h TTL elapses.
_TOKEN_REFRESH_SECONDS = 6 * 60 * 60

# Per-user uids are drawn from a dedicated range so they never collide with
# system accounts or human logins on the box.
_UID_RANGE_START = 210_000
_UID_RANGE_SIZE = 20_000


class IsolationUnavailable(RuntimeError):
    """Raised when the host cannot create a real per-user boundary."""


@dataclass
class _Child:
    runtime_id: str
    user_id: str
    process: subprocess.Popen[bytes]
    base_dir: Path
    log_path: Path
    model: str = ""
    failures: int = 0
    monitor: asyncio.Task[None] | None = None


@dataclass
class _Allocations:
    """Stable uid-to-user map, persisted so a restart re-adopts the same tenants."""

    path: Path
    users: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "_Allocations":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            users = {
                str(user_id): int(uid)
                for user_id, uid in (data.get("users") or {}).items()
                if str(user_id).strip()
            }
        except (OSError, ValueError, TypeError):
            users = {}
        return cls(path=path, users=users)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"users": self.users}, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def uid_for(self, user_id: str) -> int:
        existing = self.users.get(user_id)
        if existing is not None:
            return existing
        taken = set(self.users.values())
        for offset in range(_UID_RANGE_SIZE):
            candidate = _UID_RANGE_START + offset
            if candidate not in taken:
                self.users[user_id] = candidate
                self.save()
                return candidate
        raise IsolationUnavailable(
            f"Exhausted the per-user uid range ({_UID_RANGE_START}.."
            f"{_UID_RANGE_START + _UID_RANGE_SIZE - 1})."
        )


class HostSupervisor:
    """Owns one machine's runtimes.

    Dials ``/remote/relay/host`` with the host token, receives ``provision`` /
    ``deprovision`` instructions, and runs one isolated child process per user.
    The supervisor never executes agent work itself.
    """

    def __init__(
        self,
        identity: HostIdentity,
        *,
        base_dir: Path,
        runtime_command: list[str] | None = None,
        child_env_factory: Callable[[str, str, str, str], dict[str, str]] | None = None,
    ) -> None:
        self._identity = identity
        self._base_dir = Path(base_dir)
        self._allocations = _Allocations.load(self._base_dir / "allocations.json")
        self._children: dict[str, _Child] = {}
        self._stop_event = asyncio.Event()
        self._websocket: Any = None
        self._last_error = ""
        self._runtime_command = runtime_command or [
            sys.executable,
            "-m",
            "ite.remote.child",
        ]
        self._child_env_factory = child_env_factory or self._build_child_env

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def websocket_url(self) -> str:
        base = self._identity.api_url
        if base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        return f"{base}/remote/relay/host"

    # -- isolation ---------------------------------------------------------

    def runtime_base_dir(self, user_id: str) -> Path:
        return self._base_dir / "runtimes" / user_id

    def _build_child_env(
        self, user_id: str, runtime_id: str, token: str, model: str = ""
    ) -> dict[str, str]:
        base = self.runtime_base_dir(user_id)
        env = {
            **os.environ,
            "HOME": str(base),
            "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_DATA_HOME": str(base / "data"),
            "ITE_CLOUD_API_URL": self._identity.api_url,
            "ITE_RUNTIME_ID": runtime_id,
            "ITE_RUNTIME_TOKEN": token,
            "ITE_RUNTIME_TOKEN_FILE": str(self._token_file_path(user_id)),
        }
        if model:
            env["ITE_MODEL"] = model
        return env

    def _token_file_path(self, user_id: str) -> Path:
        return self.runtime_base_dir(user_id) / "runtime-token"

    def _write_runtime_token(self, user_id: str, token: str) -> None:
        """Write the token where the child re-reads it, owner-only and atomic.

        Rotation is a file replace, so an already-running child picks up the new
        token on its next call without being restarted.
        """
        path = self._token_file_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(token, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        try:
            os.chown(path, self._allocations.uid_for(user_id), -1)
        except (PermissionError, OSError):
            pass

    def _prepare_user_dir(self, user_id: str, uid: int) -> Path:
        """Create the tenant directory tree, owned by that tenant's uid, 0700.

        This is the security boundary: a child running as its own uid cannot read
        a sibling tenant's directory even though it can run arbitrary shell.
        """
        base = self._base_dir / "runtimes"
        base.mkdir(parents=True, exist_ok=True)
        os.chmod(base, 0o711)  # traversable, not listable
        user_dir = base / user_id
        for directory in (
            user_dir,
            user_dir / "config",
            user_dir / "data",
            user_dir / "workspace",
        ):
            directory.mkdir(parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
            if hasattr(os, "chown"):
                try:
                    os.chown(directory, uid, uid)
                except (PermissionError, OSError):
                    # Non-root dev environments: degrade, but say so loudly.
                    pass
        return user_dir

    def _isolation_available(self) -> bool:
        return sys.platform.startswith("linux") and os.geteuid() == 0

    def _preexec_for(self, uid: int) -> Callable[[], None] | None:
        if not self._isolation_available():
            return None

        def _drop_privileges() -> None:  # pragma: no cover - Linux/root only
            os.setgid(uid)
            os.setuid(uid)

        return _drop_privileges

    def _child_log_path(self, user_id: str) -> Path:
        return self.runtime_base_dir(user_id) / "runtime.log"

    def _open_child_log(self, user_id: str) -> Any:
        """Append the child's output to a per-user file.

        Deliberately not a pipe: an undrained pipe can fill and block the child,
        and it hides the child's own diagnostics exactly when we need them most.
        """
        path = self._child_log_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "ab")  # noqa: SIM115 - closed right after spawn
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return handle

    def _read_child_log_tail(self, user_id: str, limit: int = 600) -> str:
        try:
            text = self._child_log_path(user_id).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text.strip()[-limit:]

    def _spawn_child(
        self, *, user_id: str, runtime_id: str, env: dict[str, str]
    ) -> subprocess.Popen[bytes]:
        log_handle = self._open_child_log(user_id)
        try:
            return subprocess.Popen(  # noqa: S603 - command is operator-configured
                self._runtime_command,
                cwd=str(self.runtime_base_dir(user_id) / "workspace"),
                env=env,
                preexec_fn=self._preexec_for(self._allocations.uid_for(user_id)),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            # The child holds its own duplicate of the fd.
            log_handle.close()

    # -- provisioning ------------------------------------------------------

    def provision(
        self,
        *,
        user_id: str,
        runtime_id: str,
        token: str,
        workspace: str = "",
        model: str = "",
    ) -> None:
        """Spawn one isolated runtime for ``user_id``. No-op if already running."""
        existing = self._children.get(runtime_id)
        if existing is not None:
            if existing.process.poll() is None:
                logger.info("Runtime %s already running; ignoring duplicate provision", runtime_id)
                # A fresh token still needs to land on disk for the running child.
                self._write_runtime_token(user_id, token)
                return
            # A previous child for this runtime has exited: adopt the new spawn.
            if existing.monitor is not None:
                existing.monitor.cancel()
            self._children.pop(runtime_id, None)

        if not self._isolation_available():
            logger.warning(
                "Per-user uid isolation is unavailable on this platform (needs Linux + root). "
                "Runtimes are environment-isolated only; do NOT treat this host as multi-tenant."
            )

        uid = self._allocations.uid_for(user_id)
        user_dir = self._prepare_user_dir(user_id, uid)
        self._write_runtime_token(user_id, token)

        resolved_model = str(model or "").strip()
        env = self._child_env_factory(user_id, runtime_id, token, resolved_model)

        # The workspace path is advertised by the cloud but must exist locally;
        # an unusable path fails loudly rather than silently using the wrong dir.
        if workspace and not Path(workspace).is_dir():
            logger.warning(
                "Provisioned workspace %s does not exist; using %s",
                workspace,
                user_dir / "workspace",
            )

        try:
            process = self._spawn_child(user_id=user_id, runtime_id=runtime_id, env=env)
        except OSError as exc:
            self._report_status(runtime_id, "failed", detail=f"spawn failed: {exc}")
            logger.error("Failed to spawn runtime %s: %s", runtime_id, exc)
            return

        child = _Child(
            runtime_id=runtime_id,
            user_id=user_id,
            process=process,
            base_dir=user_dir,
            log_path=self._child_log_path(user_id),
            model=resolved_model,
        )
        self._children[runtime_id] = child
        child.monitor = asyncio.create_task(self._monitor_child(child))
        self._report_status(runtime_id, "starting")
        logger.info(
            "Provisioned runtime %s for user %s (pid=%s, uid=%s, log=%s)",
            runtime_id,
            user_id,
            process.pid,
            uid,
            child.log_path,
        )

    def deprovision(self, runtime_id: str, reason: str = "") -> None:
        child = self._children.pop(runtime_id, None)
        if child is None:
            return
        if child.monitor is not None:
            child.monitor.cancel()
        if child.process.poll() is None:
            child.process.terminate()
            try:
                child.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.process.kill()
        # Files are intentionally left intact: sign-out must not destroy work.
        logger.info("Deprovisioned runtime %s (%s)", runtime_id, reason or "no reason given")

    async def _monitor_child(self, child: _Child) -> None:
        returncode = await asyncio.to_thread(child.process.wait)
        if self._stop_event.is_set():
            return
        if self._children.get(child.runtime_id) is not child:
            return  # superseded by a newer provision

        stderr_tail = self._read_child_log_tail(child.user_id)

        child.failures += 1
        detail = f"exit code {returncode}"
        if stderr_tail:
            detail = f"{detail}: {stderr_tail}"

        if child.failures >= _MAX_CONSECUTIVE_FAILURES:
            self._children.pop(child.runtime_id, None)
            self._report_status(
                child.runtime_id,
                "failed",
                detail=f"gave up after {child.failures} failures — {detail}",
            )
            logger.error(
                "Runtime %s failed repeatedly; not restarting. Log: %s",
                child.runtime_id,
                child.log_path,
            )
            return

        self._report_status(child.runtime_id, "failed", detail=detail)
        logger.warning(
            "Runtime %s exited (%s); restarting in %ss. Log: %s",
            child.runtime_id,
            detail,
            _RESTART_BACKOFF_SECONDS,
            child.log_path,
        )
        await asyncio.sleep(_RESTART_BACKOFF_SECONDS)
        if self._stop_event.is_set() or self._children.get(child.runtime_id) is not child:
            return
        self._restart(child)

    def _restart(self, child: _Child) -> None:
        token = self._read_runtime_token(child.user_id)
        env = self._child_env_factory(child.user_id, child.runtime_id, token, child.model)
        try:
            child.process = self._spawn_child(
                user_id=child.user_id, runtime_id=child.runtime_id, env=env
            )
        except OSError as exc:
            self._children.pop(child.runtime_id, None)
            self._report_status(child.runtime_id, "failed", detail=f"restart failed: {exc}")
            return
        child.monitor = asyncio.create_task(self._monitor_child(child))
        self._report_status(child.runtime_id, "starting")

    def _read_runtime_token(self, user_id: str) -> str:
        try:
            return self._token_file_path(user_id).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    # -- control channel ---------------------------------------------------

    def _report_status(self, runtime_id: str, state: str, detail: str = "") -> None:
        websocket = self._websocket
        if websocket is None:
            return
        payload = {"runtimeId": runtime_id, "state": state}
        if detail:
            payload["detail"] = detail

        async def _send() -> None:
            try:
                await websocket.send(json.dumps({"type": "runtime_status", "payload": payload}))
            except Exception:  # noqa: BLE001 - status is best-effort
                pass

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_send())

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        from websockets.asyncio.client import connect

        backoff = _RECONNECT_MIN_SECONDS
        try:
            while not self._stop_event.is_set():
                try:
                    async with connect(
                        self.websocket_url,
                        additional_headers={
                            "Authorization": f"Bearer {self._identity.host_token}"
                        },
                        max_size=_MESSAGE_SIZE_LIMIT,
                        ping_interval=20,
                        ping_timeout=20,
                    ) as websocket:
                        self._websocket = websocket
                        await self._serve(websocket)
                        backoff = _RECONNECT_MIN_SECONDS
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - reconnect on any failure
                    self._last_error = str(exc) or exc.__class__.__name__
                    logger.warning("Host control connection failed: %s", exc)
                finally:
                    self._websocket = None

                if self._stop_event.is_set():
                    break
                backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)
                if await self._sleep_or_stop(backoff):
                    break
        finally:
            for runtime_id in list(self._children):
                self.deprovision(runtime_id, reason="supervisor stopping")

    async def _serve(self, websocket: Any) -> None:
        await websocket.send(
            json.dumps(
                {
                    "type": "relay_hello",
                    "payload": {
                        "hostId": self._identity.host_id,
                        "token": self._identity.host_token,
                        "name": self._identity.name,
                        "platform": self._identity.platform,
                    },
                }
            )
        )

        ready = await self._await_ready(websocket)
        if ready is None:
            return

        logger.info("Host control channel online as %s", self._identity.host_id)
        heartbeat = asyncio.create_task(self._heartbeat_loop(websocket))
        refresher = asyncio.create_task(self._token_refresh_loop(websocket))
        try:
            async for raw in websocket:
                await self._handle_message(raw)
        finally:
            heartbeat.cancel()
            refresher.cancel()
            await asyncio.gather(heartbeat, refresher, return_exceptions=True)

    async def _await_ready(self, websocket: Any) -> dict[str, Any] | None:
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=15.0)
        except asyncio.TimeoutError:
            logger.warning("Host control channel was not acknowledged in time")
            return None
        message = self._decode(raw)
        if message is None or message.get("type") != "host_ready":
            logger.warning("Host control registration rejected: %s", message)
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
        if message is None:
            return
        message_type = str(message.get("type") or "")
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

        if message_type == "provision":
            user_id = str(payload.get("userId") or "")
            runtime_id = str(payload.get("runtimeId") or "")
            logger.info("Provisioning request received for user %s (runtime %s)", user_id, runtime_id)
            self.provision(
                user_id=user_id,
                runtime_id=runtime_id,
                token=str(payload.get("token") or ""),
                workspace=str(payload.get("workspace") or ""),
                model=str(payload.get("model") or ""),
            )
            return

        if message_type == "deprovision":
            self.deprovision(
                str(payload.get("runtimeId") or ""),
                reason=str(payload.get("reason") or ""),
            )
            return

        if message_type == "runtime_token":
            user_id = str(payload.get("userId") or "")
            token = str(payload.get("token") or "")
            if user_id and token:
                self._write_runtime_token(user_id, token)
                logger.info("Rotated runtime token for user %s", user_id)
            return

        if message_type == "pong":
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
            except Exception:  # noqa: BLE001
                return

    async def _token_refresh_loop(self, websocket: Any) -> None:
        """Ask the cloud to rotate each running runtime's token before it expires.

        The runtime token lives 12h; refreshing every 6h means a long-lived
        runtime never has to stop and reconnect to keep working.
        """
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=_TOKEN_REFRESH_SECONDS
                )
                return
            except asyncio.TimeoutError:
                pass
            for child in list(self._children.values()):
                if child.process.poll() is not None:
                    continue
                try:
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "token_refresh_request",
                                "payload": {
                                    "userId": child.user_id,
                                    "runtimeId": child.runtime_id,
                                },
                            }
                        )
                    )
                except Exception:  # noqa: BLE001 - a dropped socket ends the loop
                    return

    async def _sleep_or_stop(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False


def default_base_dir() -> Path:
    """Where per-user runtime directories live when the operator does not override."""
    env_value = os.environ.get("ITE_RUNTIME_BASE_DIR", "").strip()
    if env_value:
        return Path(env_value)
    if os.geteuid() == 0:
        return Path("/var/lib/ite")
    return Path.home() / ".ite" / "runtimes"


def ensure_base_dir(path: Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "chmod"):
        try:
            os.chmod(directory, 0o755 if not os.geteuid() == 0 else 0o711)
        except OSError:
            pass
    return directory


__all__ = [
    "HostSupervisor",
    "IsolationUnavailable",
    "default_base_dir",
    "ensure_base_dir",
]
