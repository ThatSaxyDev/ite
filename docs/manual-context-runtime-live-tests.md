# Manual Context Runtime Live Tests

This document is the live validation checklist for the upgraded context runtime.

For the fuller operator-facing pass that covers durable retrieval, compaction, autosave, and restore together, also use:

- [`docs/live-memory-and-context-eval-pass.md`](/Users/kiishidavid/Documents/Dev/Projects/ite/docs/live-memory-and-context-eval-pass.md)

The current goal is to validate three things in the app itself:

1. manual compaction behaves like a real runtime action
2. resumed sessions can compact correctly
3. transcript truth is preserved while the active prompt window narrows

## Test 1: Manual Compaction In Feed

### Goal

Verify `/compact` behaves like a real runtime event in reup.

### Steps

1. Start `iTE` in this repo.
2. Create a thread with several turns:
   - ask for code inspection
   - ask follow-up questions
   - let it read files and continue work
3. Run:

```text
/compact
```

### Expected

- A feed notice appears saying `Compacting context`
- Then a feed card appears saying `Context automatically compacted`
- You should not only see a generic `/compact` command-result card on success

### Failure signals

- Only a generic `/compact` command card appears
- No in-feed compaction notice appears
- The command says compaction failed without a reason

## Test 2: Resumed Session Manual Compaction

### Goal

Verify compaction still works after session restore.

### Steps

1. In a non-trivial thread, create several turns.
2. Save or rely on autosave.
3. Open the session again with:

```text
/sessions
```

or directly:

```text
/sessions <session_id>
```

4. After the session is restored, run:

```text
/compact
```

### Expected

- The same `Compacting context` notice appears
- Compaction succeeds
- The next turn still understands the active task

### Follow-up prompt

```text
Where were we, what has already been done, and what is the next concrete step?
```

### Expected follow-up behavior

- It should not restart the task from scratch
- It should not forget the active work
- It should continue from the correct current state

## Test 3: Active Window Narrowing

### Goal

Verify compaction narrows the active prompt window instead of destroying transcript truth.

### Steps

1. Start a thread and create clearly identifiable early and late messages.

Example:

```text
Early instruction: remember this is phase A.
```

Later:

```text
Now we are in phase B. The next step is transcript refactor work.
```

2. Run `/compact`.
3. Ask:

```text
What is the current phase and next step?
```

### Expected

- It should answer from the compacted state plus preserved tail
- It should prioritize the later `phase B` state
- It should not behave as if all early raw context remained equally active

### Why this matters

The runtime now keeps transcript truth append-only internally, but the active prompt window should move forward at compaction boundaries.

## Test 4: Status Before Compaction

### Goal

Verify compaction status helps explain why auto-compaction has or has not fired.

### Steps

Run:

```text
/compact status
```

### Expected

- current token estimate
- trigger threshold
- message count
- eligibility flag

### Usage

This is the quick diagnostic before deciding whether to wait for auto-compaction or force `/compact`.

## Test 5: Failure Diagnostics

### Goal

Verify compaction failures surface the real reason.

### Steps

If `/compact` fails, note the exact feed message.

### Expected

You should now see a concrete failure reason when the provider emits one, for example:

- cloud auth/session failure
- empty compaction response
- missing usage metadata
- provider error text

### Failure signal

If the UI still only says `Compaction did not produce a summary.` with no detail, that is a bug.

## Test 6: Repeated Compactions

### Goal

Verify the runtime remains coherent after more than one compaction.

### Steps

1. Continue a thread after the first compaction.
2. Add more turns.
3. Run `/compact` again.
4. Ask for the current state and next step.

### Expected

- No crash
- No duplicate tool-result confusion
- No restart-from-zero behavior
- Continuity should still come through from compact artifact plus session memory plus preserved tail

## What To Record

If a live test fails, capture:

1. the exact command used
2. whether the session was fresh or resumed
3. the visible feed messages
4. whether cloud or local provider was in use
5. whether `/compact status` showed eligibility before the test

That information should be enough to distinguish:

- UI wiring failures
- provider-response failures
- restore-path bugs
- prompt continuity bugs
