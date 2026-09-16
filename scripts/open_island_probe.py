#!/usr/bin/env python3
"""Live probe for the iTE <-> Open Island bridge transport.

Exercises the wire protocol against a running Open Island instance and reports
what it observes. Read-only with respect to iTE: it speaks the bridge directly
and never touches agent state.

Usage:
    python scripts/open_island_probe.py                 # availability + handshake
    python scripts/open_island_probe.py --round-trip    # + session lifecycle
    python scripts/open_island_probe.py --watch 75      # + liveness observation
    python scripts/open_island_probe.py --hold /tmp/stop  # keep bubble up until file exists

`--hold PATH` keeps the session on screen indefinitely for manual inspection
(screenshots, UI checks). Create PATH to end the session and clean up.

Every command creates a session keyed by a probe id; the script always sends
SessionEnd for anything it started so the notch is left clean.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from ite.integrations.open_island.client import (
    OpenIslandClient,
    encode_command,
    hooks_disabled,
)


def _log(message: str) -> None:
    print(message, flush=True)


async def _connect(client: OpenIslandClient) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_unix_connection(str(client.socket_path))
    hello = await asyncio.wait_for(reader.readline(), timeout=3)
    _log(f"  greeting: {json.loads(hello.decode())}")
    return reader, writer


def _hook(event: str, session_id: str, cwd: str, **extra: object) -> dict:
    payload: dict[str, object] = {
        "cwd": cwd,
        "hook_event_name": event,
        "session_id": session_id,
        "hook_source": "claude",
    }
    payload.update(extra)
    return {"type": "processClaudeHook", "claudeHook": payload}


async def _check_availability(client: OpenIslandClient) -> bool:
    _log("availability")
    _log(f"  socket path:   {client.socket_path}")
    _log(f"  file exists:   {client.socket_exists()}")
    hooks_off = hooks_disabled()
    _log(f"  skip env set:  {hooks_off}")

    live = await client.is_available()
    _log(f"  bridge live:   {live}")

    if not live:
        _log("")
        if client.socket_exists():
            _log("  Socket file is present but refuses connections.")
            _log("  This is a stale socket — Open Island is not running.")
        else:
            _log("  No socket file. Open Island has never run or was never installed.")
        _log("  Start Open Island, then re-run this probe.")
    return live


async def _round_trip(
    client: OpenIslandClient,
    cwd: str,
    watch: float,
    hold_path: str | None = None,
) -> None:
    session_id = f"ite-probe-{int(time.time())}"
    _log("")
    _log(f"session lifecycle (probe id: {session_id})")
    if hold_path is not None:
        _log(f"holding session open until '{hold_path}' exists (Ctrl-C to abort)")

    reader, writer = await _connect(client)
    try:
        writer.write(encode_command({"type": "registerClient", "role": "observer"}))
        writer.write(
            encode_command(
                _hook("SessionStart", session_id, cwd, source="startup", model="ite-probe")
            )
        )
        await writer.drain()

        started = time.monotonic()
        acknowledged = False
        saw_start = False
        evictions = 0

        while time.monotonic() - started < watch:
            if hold_path is not None and Path(hold_path).exists():
                _log("  sentinel detected — ending session")
                break

            try:
                line = await asyncio.wait_for(reader.readline(), timeout=2)
            except TimeoutError:
                elapsed = time.monotonic() - started
                _log(f"  [{elapsed:5.1f}s] idle — session still present")
                continue

            if not line:
                _log("  connection closed by server")
                break

            envelope = json.loads(line.decode())
            elapsed = time.monotonic() - started

            if envelope.get("type") != "event":
                if envelope.get("response", {}).get("type") == "acknowledged":
                    acknowledged = True
                continue

            event = envelope.get("event", {})
            for key, payload in event.items():
                if not isinstance(payload, dict):
                    continue
                if payload.get("sessionID") != session_id:
                    continue
                if key == "sessionStarted":
                    saw_start = True
                if key in {"sessionCompleted", "sessionEnded"}:
                    evictions += 1
                _log(f"  [{elapsed:5.1f}s] event: {key}")

        _log("")
        _log("  results")
        _log(f"    acknowledged:      {acknowledged}")
        _log(f"    sessionStarted:    {saw_start}")
        _log(f"    evicted:           {bool(evictions)}")
        _log(f"    survived {watch:g}s:     {not evictions and saw_start}")
        if not evictions and saw_start:
            _log("    -> hook-managed liveness holds (no process discovery eviction)")
    finally:
        writer.write(encode_command(_hook("SessionEnd", session_id, cwd)))
        await writer.drain()
        await asyncio.sleep(0.4)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        _log("")
        _log(f"  sent SessionEnd for {session_id} — notch left clean")


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--round-trip",
        action="store_true",
        help="create a session, verify acknowledgement, then clean up",
    )
    parser.add_argument(
        "--watch",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="how long to observe the session (implies --round-trip)",
    )
    parser.add_argument(
        "--hold",
        metavar="PATH",
        default=None,
        help="keep the session open until PATH exists, then clean up (implies --round-trip)",
    )
    parser.add_argument("--cwd", default=None, help="cwd to report to Open Island")
    args = parser.parse_args()

    cwd = args.cwd or str(Path.cwd())

    client = OpenIslandClient()
    if not await _check_availability(client):
        return 1

    if args.hold is not None:
        watch = max(args.watch, 86_400.0)
        await _round_trip(client, cwd, watch, hold_path=args.hold)
    elif args.round_trip or args.watch != 10.0:
        await _round_trip(client, cwd, args.watch)
    else:
        _log("")
        _log("  Bridge reachable. Re-run with --round-trip to exercise a session,")
        _log("  or --watch 75 to confirm the session is not evicted.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
