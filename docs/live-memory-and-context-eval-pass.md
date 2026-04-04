# Live Memory And Context Eval Pass

This document is the real-world evaluation script for the upgraded `iTE` runtime.

Use it when you want to answer one question:

`Does iTE preserve the right context and retrieve the right memory in a real session?`

This is not a unit-test checklist. It is a live operator pass for the actual app.

## What This Evaluates

This pass validates five runtime behaviors together:

1. typed durable memory retrieval
2. session continuity across long threads
3. compaction behavior during active work
4. autosave plus restore behavior
5. retrieval quality after restore and compaction

## Success Criteria

The pass is successful if all of the following feel true in live use:

- tool queries recall `reference` memory rather than unrelated project summaries
- architecture queries recall `project` memory rather than command/tool noise
- current-task continuity survives `/compact`
- current-task continuity survives autosave and `/sessions`
- the agent does not restart work from scratch after restore
- memory retrieval remains relevant after compaction and restore

## Test Setup

Run this inside the `ite` repo.

Recommended conditions:

- use one provider consistently for the full pass
- keep one thread for the full sequence
- do not manually clear memory between steps unless the test says to

Before starting, it is useful to know:

- `/compact`
- `/compact status`
- `/sessions`

## Pass 1: Durable Retrieval By Intent

### Goal

Verify that memory retrieval is typed and intent-aware.

### Step 1: Store Reference Memory

Use this prompt:

```text
Remember this for this workspace: use pytest for tests.
```

Expected:

- confirmation that the memory was stored

### Step 2: Store Project Memory

Use this prompt:

```text
Remember this for this workspace: the runtime is layered around sessions, tools, context, and UI orchestration.
```

Expected:

- confirmation that the memory was stored

### Step 3: Tool Query

Use this prompt:

```text
What test tool should we use here?
```

Expected:

- answer mentions `pytest`
- answer does not drift into architecture explanation

Failure signals:

- answer talks about sessions/tools/context architecture instead of the test tool
- answer says nothing is remembered even though the memory was stored

### Step 4: Architecture Query

Use this prompt:

```text
Explain the architecture of this repo.
```

Expected:

- answer surfaces the layered runtime idea
- answer does not center on `pytest`

Failure signals:

- answer mainly talks about tests or commands
- answer ignores the stored project memory entirely

## Pass 2: Long Session Continuity

### Goal

Verify that current-task continuity is preserved through a realistic long thread.

### Starter Prompt

Paste this:

```text
Audit the context and memory architecture of this repo in depth. Compare the current iTE implementation against the csrc runtime, identify the biggest architectural gaps, inspect the relevant files, and build a phased refactor plan. Keep going until you have a concrete implementation roadmap with tradeoffs, but do not stop at a high-level summary. Read code, reason about it, and update your conclusions as you learn more.
```

### Follow-Up Prompts

Run 4 to 6 follow-ups such as:

```text
Now inspect the actual implementation files you referenced and verify your claims one by one.
```

```text
Turn that into an implementation plan mapped to exact classes, methods, and tests.
```

```text
Now challenge your own plan and identify the biggest risks or bad assumptions.
```

```text
Continue and propose the first patch slice only, with migration safety in mind.
```

### Expected

- the session becomes meaningfully long
- the agent maintains a coherent task thread
- it does not repeatedly rediscover the same repo facts

## Pass 3: Manual Compaction Mid-Task

### Goal

Verify continuity after compaction in the middle of active work.

### Step 1

Run:

```text
/compact status
```

Record:

- current tokens
- trigger threshold
- message count

### Step 2

Run:

```text
/compact
```

Expected:

- feed shows `Compacting context`
- then `Context automatically compacted`

### Step 3

Immediately ask:

```text
Where were we, what has already been done, and what is the next concrete step?
```

Expected:

- it continues from the active task
- it names work already completed
- it gives the next step without resetting the thread

Failure signals:

- it restarts the audit from zero
- it gives a generic summary detached from the active task
- it loses the current next step

## Pass 4: Autosave And Restore

### Goal

Verify restore quality after the session has already compacted.

### Step 1

After compaction, keep working for 2 to 4 more turns.

### Step 2

Let autosave happen naturally or switch away from the thread.

### Step 3

Restore the session:

```text
/sessions
```

or:

```text
/sessions <session_id>
```

### Step 4

Ask:

```text
Where were we, what has already been done, and what is the next concrete step?
```

Expected:

- continuity survives restore
- answer still reflects the post-compaction state
- it does not behave like a fresh thread

Failure signals:

- it loses the active task
- it ignores recent post-compaction turns
- it gives a stale pre-compaction summary as if it were current state

## Pass 5: Retrieval After Compaction And Restore

### Goal

Verify memory retrieval still behaves by intent after the session has been compacted and restored.

### Step 1: Tool Query After Restore

Ask:

```text
What test tool should we use here?
```

Expected:

- answer still mentions `pytest`

### Step 2: Architecture Query After Restore

Ask:

```text
Explain the architecture of this repo again, briefly.
```

Expected:

- answer still surfaces the layered runtime fact
- answer does not collapse into tool/test memory

Failure signals:

- retrieval quality is worse after compaction/restore than before
- the wrong durable memory type dominates the answer

## Optional Stress Pass: Repeated Compaction

### Goal

Verify repeated compactions do not break continuity.

### Steps

1. Continue the thread for several more turns.
2. Run `/compact` again.
3. Ask for current state and next step again.

Expected:

- no crash
- no transcript confusion
- no “start over” behavior

## What To Record

If a pass fails, record:

1. provider used
2. whether the session was fresh or restored
3. whether compaction had already happened
4. exact prompts used
5. exact response text that was wrong
6. `/compact status` output if compaction was involved
7. whether autosave or manual restore was involved

## Evaluation Rubric

Score each area from `0` to `2`.

### Durable Retrieval

- `0`: wrong memory surfaces or no memory surfaces
- `1`: partially right but noisy or inconsistent
- `2`: correct memory type surfaces consistently

### Post-Compact Continuity

- `0`: loses task state
- `1`: keeps some continuity but misses active step
- `2`: continues cleanly from current work

### Post-Restore Continuity

- `0`: restore feels like a new thread
- `1`: partial continuity with obvious gaps
- `2`: restore feels like a real continuation

### UX Signals

- `0`: compaction state is confusing or invisible
- `1`: partially visible but still hard to reason about
- `2`: compaction and context pressure are easy to understand

## Interpreting Results

### Good enough to continue

If all categories score mostly `2`, the next work should move to:

- more end-to-end eval coverage
- memory write hardening
- retrieval tuning

### Not good enough yet

If continuity fails after `/compact` or `/sessions`, do not keep adding features.

Go back to:

- prompt assembly
- transcript boundary handling
- restore behavior

If retrieval fails by intent, the next work should stay in:

- durable memory typing
- retrieval ranking and lane selection

not in compaction UI or extra memory features.
