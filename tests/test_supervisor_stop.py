from __future__ import annotations

import asyncio
import contextlib
import json
import signal
import tempfile
import time
import unittest
from pathlib import Path

from websockets.asyncio.server import serve

from ite.remote.host_identity import HostIdentity
from ite.remote.supervisor import HostSupervisor


class SupervisorStopTests(unittest.TestCase):
    """A service manager stops the unit with SIGTERM.

    The host supervisor parks on an in-flight websocket read, so signalling it
    must both record the stop and close the control channel. If it does not,
    `systemctl restart` blocks until TimeoutStopSec expires and systemd has to
    SIGKILL the process, which skips the graceful deprovision of children.
    """

    def test_signal_stops_supervisor_promptly(self) -> None:
        elapsed = asyncio.run(self._run_until_signalled())
        self.assertLess(
            elapsed,
            5.0,
            f"supervisor took {elapsed:.2f}s to stop; systemd would SIGKILL it",
        )

    async def _run_until_signalled(self) -> float:
        online = asyncio.Event()

        async def handler(websocket) -> None:
            await websocket.recv()
            await websocket.send(json.dumps({"type": "host_ready", "payload": {}}))
            online.set()
            with contextlib.suppress(Exception):
                # Closed by the supervisor when it handles the stop signal.
                async for _message in websocket:
                    pass

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            identity = HostIdentity(
                host_id="host_test",
                host_token="token",
                api_url=f"http://127.0.0.1:{port}",
                name="test",
                platform="linux-x64",
            )
            with tempfile.TemporaryDirectory(prefix="ite-sup-") as base:
                supervisor = HostSupervisor(identity, base_dir=Path(base))
                task = asyncio.create_task(supervisor.run())
                await asyncio.wait_for(online.wait(), timeout=5.0)

                started = time.monotonic()
                supervisor._on_shutdown_signal(signal.SIGTERM)
                try:
                    await asyncio.wait_for(task, timeout=8.0)
                finally:
                    if not task.done():
                        task.cancel()
                return time.monotonic() - started


if __name__ == "__main__":
    unittest.main()
