from __future__ import annotations

import asyncio
import platform
import signal
import sys
from pathlib import Path

from ite.cloud.auth import get_cloud_session, get_remote_companion_access_status
from ite.config.loader import ensure_workspace_layout, load_config

from .host import HeadlessRuntimeHost
from .relay import CloudRelayClient


def _platform_label() -> str:
    return f"{sys.platform}-{platform.machine()}".strip("-")


async def _resolve_token(config) -> str | None:
    """Return a valid cloud access token, refreshing it via the stored session."""
    session = await asyncio.to_thread(get_cloud_session, config)
    if session is None:
        return None
    return session.access_token or None


async def run_cloud_runtime(cwd: Path) -> None:
    """Serve one headless iTE runtime to iTE Cloud until interrupted.

    Fails loudly when the account lacks remote access or is not signed in: a
    runtime that silently connects and cannot work would be worse than no
    runtime at all.
    """
    workspace = Path(cwd).resolve()
    ensure_workspace_layout(workspace)
    config = load_config(cwd=workspace)

    status = await asyncio.to_thread(get_remote_companion_access_status, config)
    if not status.is_valid:
        raise RuntimeError(
            str(getattr(status, "message", "") or "").strip()
            or "Remote companion requires an active iTE Pro subscription. "
            "Sign in on this machine first."
        )

    session = await asyncio.to_thread(get_cloud_session, config)
    if session is None or not session.api_url:
        raise RuntimeError("Not signed in to iTE Cloud. Run `ite` and sign in first.")

    host = HeadlessRuntimeHost.create(cwd=workspace)
    server = await host.start()
    runtime_id = server.runtime_id

    relay = CloudRelayClient(
        server,
        api_url=session.api_url,
        token_provider=lambda: _resolve_token(config),
        runtime_id=runtime_id,
        runtime_name=server.connection_info().get("runtime_name") or "iTE Runtime",
        platform=_platform_label(),
        fingerprint=server.connection_info().get("fingerprint") or "",
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            # Windows / restricted environments: fall back to KeyboardInterrupt.
            pass

    relay_task = asyncio.create_task(relay.run())
    print(f"iTE cloud runtime online as {runtime_id}. Attach from the mobile app.")
    print("Press Ctrl+C to stop.")

    try:
        await stop_event.wait()
    finally:
        relay.stop()
        relay_task.cancel()
        await asyncio.gather(relay_task, return_exceptions=True)
        await host.shutdown()
        print("iTE cloud runtime stopped.")
