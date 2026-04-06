# Reup Live Test Runbook

This is the practical live test for the primary `ite` experience.

Use this when you want to validate the real Reup/Textual workflow end to end, not the legacy surface and not `ite --chat`.

Run everything from the `ite` repo root:

- `/Users/kiishidavid/Documents/Dev/Projects/ite`

## Goal

Confirm that Reup:

1. preserves workspace memory correctly
2. stays coherent in a long working session
3. compacts context cleanly in-feed
4. resumes correctly after `/sessions`
5. does not restart work from zero after compaction or restore

## Start

1. Launch:

```bash
ite
```

2. Stay in one Reup session for the whole pass.
3. Do not manually clear memory.

## Pass 1: Memory Retrieval

Paste:

```text
Remember this for this workspace: use ruff before pytest when touching Python files.
```

Then:

```text
Remember this for this workspace: the runtime is organized around session state, tool execution, context continuity, and UI event rendering.
```

Then:

```text
Before running tests in this repo, what should we run first?
```

Expected:

- answer mentions `ruff`
- answer does not drift into architecture

Then:

```text
How is this repo structured at a high level?
```

Expected:

- answer mentions the layered runtime idea
- answer does not center on `ruff`

## Pass 2: Long Session

Paste:

```text
Review how Reup handles long-running turns, tool activity, and session continuity in this repo. Compare the current iTE behavior against the csrc source tree, identify the most important runtime gaps, inspect the relevant implementation files, and turn that into a practical upgrade plan with concrete patch slices. Keep going until you have a real roadmap grounded in code.
```

Then use 4 to 6 follow-ups such as:

```text
Now verify the runtime claims you just made by checking the actual source files one by one.
```

```text
Turn that into a patch plan mapped to exact files, classes, methods, and tests.
```

```text
Now challenge your own proposal and identify the highest-risk assumptions or weak spots.
```

```text
Continue and propose only the first implementation slice, with migration safety and verification in mind.
```

Expected:

- the thread becomes meaningfully long
- the agent stays on the same task
- the agent does not keep rediscovering the same facts

## Pass 3: Reup Compaction

Run:

```text
/compact status
```

Record:

- current tokens
- trigger threshold
- message count

Then run:

```text
/compact
```

Expected in Reup:

- a live in-feed state appears for `Compacting context`
- the compaction card resolves cleanly
- the feed does not fall back to a broken generic command-result pattern

Immediately ask:

```text
Where were we, what has already been done, and what is the next concrete step?
```

Expected:

- it continues the active task
- it names work already completed
- it gives a concrete next step
- it does not restart from scratch

## Pass 4: Reup Restore

Keep working for 2 to 4 more turns.

Then run:

```text
/sessions
```

Open the same session again.

Immediately ask:

```text
Where were we, what has already been done, and what is the next concrete step?
```

Expected:

- the restored session still knows the active task
- continuity feels real, not reconstructed badly
- there is no obvious tool-result or transcript confusion

## Pass 5: Repeat Stability

Continue for a few more turns.

Run:

```text
/compact
```

Then ask:

```text
What is the current phase and next step?
```

Expected:

- no crash
- no duplicate tool confusion
- no restart-from-zero behavior

## Fail Signals

Treat these as failures:

- Reup shows only a generic slash-command result instead of real compaction state
- the thread restarts from zero after compaction
- restore loses the current task
- the next step after compaction is vague or unrelated
- memory retrieval mixes up test-tool memory and architecture memory

## What To Capture

If a step fails, capture:

1. the exact prompt or command
2. whether it happened before or after `/sessions`
3. what Reup showed in the feed
4. what the answer actually said
5. what `/compact status` showed before compaction

## Result Template

Use this simple result format:

```text
Pass 1: pass/fail
Pass 2: pass/fail
Pass 3: pass/fail
Pass 4: pass/fail
Pass 5: pass/fail

Notes:
- ...
- ...
```
