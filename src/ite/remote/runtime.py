from __future__ import annotations

import asyncio
import logging
import os
import platform
import signal
import sys
import time
from pathlib import Path

from ite.cloud.auth import DEFAULT_CLOUD_CLIENT_ID
from ite.config.loader import ensure_workspace_layout, load_config

from .host import HeadlessRuntimeHost
from .relay import CloudRelayClient

_CONNECT_REPORT_SECONDS = 15.0
# Must not outlive the cloud-issued runtime token; the supervisor re-provisions
# with a fresh token before this elapses.
_RUNTIME_TOKEN_TTL_SECONDS = 12 * 60 * 60


def _platform_label() -> str:
    return f"{sys.platform}-{platform.machine()}".strip("-")


def runtime_session_provider(api_url: str, runtime_token: str, token_file: str = ""):
    """Build a session provider backed by a delegated runtime token.

    A provisioned runtime has no user login on the host. The runtime token *is*
    the credential, so the LLM client resolves it instead of reading
    ``cloud_session.json``. When ``token_file`` is set the token is re-read on
    every call, so the host can rotate it in place without restarting the
    runtime. The token is treated as non-refreshable: the host replaces it
    before it expires.
    """
    from ite.cloud.auth import CloudSession

    def _provider():
        token = _read_runtime_token(token_file, runtime_token)
        if not token:
            return None
        return CloudSession(
            access_token=token,
            refresh_token="",
            access_expires_at=time.time() + _RUNTIME_TOKEN_TTL_SECONDS,
            api_url=str(api_url or "").strip().rstrip("/"),
            client_id=DEFAULT_CLOUD_CLIENT_ID,
        )

    return _provider


def _read_runtime_token(token_file: str, fallback: str) -> str:
    """Read the current runtime token, preferring the on-disk value.

    The host writes the token to a file it can rotate atomically. If the file is
    missing or unreadable we fall back to the value captured at startup rather
    than failing closed on a transient read error.
    """
    path = str(token_file or "").strip()
    if path:
        try:
            with open(path, encoding="utf-8") as handle:
                token = handle.read().strip()
            if token:
                return token
        except OSError:
            pass
    return str(fallback or "").strip()


async def _provisioned_access_check() -> bool:
    """Entitlement was enforced by the cloud when this runtime was provisioned.

    Re-checking here would need a user session, which a provisioned runtime
    deliberately does not have. The runtime token's scope is the gate instead.
    """
    return True


async def _serve_until_stopped(host: HeadlessRuntimeHost, relay: CloudRelayClient) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            # Windows / restricted environments: fall back to KeyboardInterrupt.
            pass

    relay_task = asyncio.create_task(relay.run())
    try:
        if await relay.wait_connected(_CONNECT_REPORT_SECONDS):
            print("iTE cloud runtime online. Attach from the mobile app.")
            print("Press Ctrl+C to stop.")
        else:
            reason = relay.last_error or "no response from the relay endpoint"
            print("Could not reach the iTE Cloud relay.", file=sys.stderr)
            print(f"  Reason: {reason}", file=sys.stderr)
            print(
                "  Check that the API is reachable and that its reverse proxy "
                "forwards WebSocket upgrades for /remote/relay/runtime.",
                file=sys.stderr,
            )
            print("  Still retrying in the background…", file=sys.stderr)

        await stop_event.wait()
    finally:
        relay.stop()
        relay_task.cancel()
        await asyncio.gather(relay_task, return_exceptions=True)
        await host.shutdown()


async def run_provisioned_runtime(
    cwd: Path,
    *,
    api_url: str,
    runtime_id: str,
    runtime_token: str,
    token_file: str = "",
    model: str = "",
) -> None:
    """Serve one runtime using a cloud-issued runtime token.

    This is what the host supervisor spawns per user. It never reads a user
    login: the token in the environment is the whole credential. When
    ``token_file`` is provided the host can rotate the token in place.
    """
    workspace = Path(cwd).resolve()
    ensure_workspace_layout(workspace)
    config = load_config(cwd=workspace)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    api_url = str(api_url or "").strip().rstrip("/")
    runtime_token = str(runtime_token or "").strip()
    if not api_url or not runtime_token:
        raise RuntimeError(
            "A provisioned runtime needs ITE_CLOUD_API_URL and ITE_RUNTIME_TOKEN. "
            "It is normally started by `ite remote serve`, not by hand."
        )

    # The cloud tells us which bundled model to use. A fresh runtime workspace
    # has no model configured, and without this it would try a direct provider
    # with no credentials.
    resolved_model = str(model or os.environ.get("ITE_MODEL") or "").strip()
    if resolved_model:
        config.model_name = resolved_model
        try:
            config.model.source_kind = "bundled"
        except (AttributeError, TypeError):
            pass

    host = HeadlessRuntimeHost.create(
        cwd=workspace,
        session_provider=runtime_session_provider(api_url, runtime_token, token_file),
        access_checker=_provisioned_access_check,
    )
    server = await host.start()
    resolved_runtime_id = runtime_id or server.runtime_id

    relay = CloudRelayClient(
        server,
        api_url=api_url,
        token_provider=lambda: _current_token(token_file, runtime_token),
        runtime_id=resolved_runtime_id,
        runtime_name=server.connection_info().get("runtime_name") or "iTE Runtime",
        platform=_platform_label(),
        fingerprint=server.connection_info().get("fingerprint") or "",
    )

    print(f"Runtime id: {resolved_runtime_id}")
    print(f"Connecting to {api_url} …")
    await _serve_until_stopped(host, relay)
    print("iTE cloud runtime stopped.")


async def _current_token(token_file: str, fallback: str) -> str | None:
    """Relay token provider: always reads the current (rotatable) token."""
    return _read_runtime_token(token_file, fallback) or None
