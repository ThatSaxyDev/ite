# Cloud header connectivity

The Pro/Free badge must resolve to Offline when iTE Cloud cannot be reached,
rather than waiting through the retry policy used by other cloud operations.

## Status checks

- Background plan and connectivity checks use a scoped request budget: no
  transport retries, at most two seconds per HTTP request, and a five-second
  budget shared across authentication, token refresh, and account metadata.
- The UI waits at most six seconds for a status check. It then shows Offline
  and remains usable, even if a transport is still finishing underneath.
- Unfinished requests stay tracked by purpose, preventing new checks from
  accumulating behind a stalled request. Late completion cannot overwrite the
  header; a subsequent check establishes the current state.
- The badge requests fresh metadata. Cached entitlements remain available to
  other consumers but do not prove that the server is currently reachable.
- Unknown and offline states check every two seconds. Known online states
  check every thirty seconds. After the first failed online probe, the next
  checks use the two-second interval; three failures confirm an outage.
- A failed explicit plan refresh marks Offline immediately. Successful
  recovery refreshes the plan and restores Pro or Free automatically.

This changes background status checks, not the retry policy for other cloud
operations or the saved login session.

## Shutdown

Background cloud reads (plan, models, usage, activity, Settings, updates, and
access checks) run in disposable daemon workers rather than asyncio's default
executor. Closing the TUI cancels tracked checks and prevents new ones. The
worker cancellation flag prevents additional HTTP requests after an in-flight
transport returns. An uninterruptible transport or DNS call cannot keep the
Python process alive while waiting for the terminal to return.

## Test in the TUI

Use the local checkout so the installed release does not hide these changes:

```sh
source .venv/bin/activate
python -m ite.main
```

1. With an existing cloud login, stop the cloud server before opening iTE.
   The top plan badge should change from its spinner to **Offline** within
   about six seconds of the background check starting.
2. Type in the composer and open `/help` or `/permissions`. The interface
   should still respond while offline.
3. Start the server again without restarting iTE. The header should recover
   to **Pro** or **Free** after the next successful background checks.
4. Leave iTE running and stop the server again. Detection can take about
   thirty seconds until the next regular probe, then several seconds to
   confirm the outage. The header should settle on Offline again.
5. Repeat with a server that accepts connections but does not respond.
   Status checking should still stop the header spinner rather than waiting
   for minutes or launching overlapping requests.
6. With the server still offline, exit through `/exit`. The shell prompt should
   return without a second Ctrl+C. Repeat immediately after launching iTE and
   after opening Settings, to cover requests that are still in flight.

Automated coverage is in `tests/test_cloud_status_budget.py`, including the
mounted Textual header, simulated outage/recovery, cached metadata, timeout
handling, and prevention of overlapping requests.
