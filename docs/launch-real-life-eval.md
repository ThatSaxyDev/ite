# Launch Real-Life Eval

This document is the launch-blocking live evaluation pass for `iTE`.

Use it when the question is not "did a unit test pass?" but:

`Can a real user stay in one session, do real work, survive context pressure, resume later, and still trust the product?`

This pass is intentionally hard on the product. It should be. The launch date is fixed, so this document is designed to expose the failures that would still embarrass us in real usage.

It is grounded in the runtime concerns called out in:

- [`docs/architecture/csrc-vs-ite-runtime-handoff.md`](/Users/kiishidavid/Documents/Dev/Projects/ite/docs/architecture/csrc-vs-ite-runtime-handoff.md)
- [`docs/manual-context-runtime-live-tests.md`](/Users/kiishidavid/Documents/Dev/Projects/ite/docs/manual-context-runtime-live-tests.md)
- [`docs/live-memory-and-context-eval-pass.md`](/Users/kiishidavid/Documents/Dev/Projects/ite/docs/live-memory-and-context-eval-pass.md)
- [`docs/reup-live-test-runbook.md`](/Users/kiishidavid/Documents/Dev/Projects/ite/docs/reup-live-test-runbook.md)

## What This Eval Decides

This eval answers five launch questions:

1. Can `iTE` stay coherent through a long, tool-heavy working session?
2. Can it compact without destroying continuity?
3. Can it restore a real session without stale, reordered, or orphaned UI?
4. Can it keep context growth under control during heavy repo-reading work?
5. Can an operator tell what happened when something fails?

If the product fails any blocker in this doc, launch should be treated as at risk until the failure is either fixed or explicitly accepted.

## Required Setup

Run this from:

- `/Users/kiishidavid/Documents/Dev/Projects/ite`

Use the real Reup/TUI flow, not a mocked path.

Recommended conditions:

- use one provider consistently for a full pass
- keep one thread for the main scenario unless a step says otherwise
- do not manually clear memory mid-pass
- do not restart the app unless the step says to

Useful commands:

- `/compact`
- `/compact status`
- `/sessions`

## Launch Gates

Treat these as launch gates, not suggestions.

### Gate A: Continuity

The agent must not restart from zero after compaction or restore.

### Gate B: Feed Truth

Reup must not show obviously stale, duplicated, reordered, or orphaned tool/assistant cards.

### Gate C: Context Pressure

The context meter must roughly track the actual session behavior, and heavy code-reading work must not produce surprising early collapse without visible explanation.

### Gate D: Recovery Clarity

When the provider, compaction path, or restore path fails, the user must see a concrete reason instead of a vague dead-end.

### Gate E: Operator Trust

After a long session, the operator must still be able to ask:

```text
Where were we, what has already been done, and what is the next concrete step?
```

and get a grounded answer.

## Severity Model

Use this severity when recording failures:

- `P0`: launch blocker, trust-breaking, data-loss-like, or continuity-breaking
- `P1`: severe, user-visible instability that makes long-session use unreliable
- `P2`: serious but survivable rough edge with a clear workaround
- `P3`: polish issue that does not block launch on its own

## Pass 1: Baseline Session Trust

### Goal

Confirm that the session begins coherent and that memory retrieval is not obviously muddled.

### Steps

1. Launch `ite`.
2. In one thread, paste:

```text
Remember this for this workspace: use ruff before pytest when touching Python files.
```

3. Then paste:

```text
Remember this for this workspace: the runtime is organized around session state, tool execution, context continuity, and UI rendering.
```

4. Ask:

```text
Before running tests in this repo, what should we run first?
```

5. Ask:

```text
How is this repo structured at a high level?
```

### Expected

- test-tool retrieval mentions `ruff`
- architecture retrieval mentions runtime/session/context structure
- answers do not swap the two memories

### Failure Signals

- test-tool prompt gets an architecture answer
- architecture prompt gets a test-command answer
- the product says nothing is remembered when the memory was just stored

### Severity

- wrong-memory retrieval with obvious user confusion: `P1`
- slight answer drift but still useful: `P2`

## Pass 2: Long Real Work Session

### Goal

Force the product into the exact kind of session that causes runtime drift: broad code reading, repeated reasoning, and tool-heavy exploration.

### Starter Prompt

Use this exact prompt:

```text
Audit the context and runtime architecture of this repo in depth. Compare the current iTE implementation against the csrc runtime, identify the biggest architectural gaps, inspect the relevant files, and build a phased upgrade plan. Keep going until you have a concrete roadmap with implementation slices, tradeoffs, and verification points. Read code, update your conclusions as you learn more, and do not stop at a high-level summary.
```

### Follow-Ups

Run at least 5 follow-ups. Use prompts like:

```text
Now verify each runtime claim you just made against the actual implementation files one by one.
```

```text
Turn that into an implementation plan mapped to exact files, classes, methods, and tests.
```

```text
Challenge your own proposal and identify the weakest assumptions or hidden migration risks.
```

```text
Continue and propose only the first patch slice, with migration safety and verification in mind.
```

```text
Now inspect the code paths around compaction, restore, and prompt assembly and correct any weak conclusions.
```

### Record During This Pass

At least twice during the long session, record:

- the visible context percentage
- whether the agent appears to be rediscovering the same facts
- whether tool cards remain visually coherent
- whether the session still feels like one continuous thread

### Expected

- the thread becomes materially long
- the agent stays on the same task
- the agent does not repeatedly restart its own investigation
- tool activity still looks ordered and understandable

### Failure Signals

- assistant conclusions appear above later tool cards in a confusing way
- running cards get stuck or remain stale after the turn resolves
- the agent starts rediscovering the same repo facts as if prior work vanished
- the session feels like several disconnected short chats instead of one working thread

### Severity

- continuity collapse or tool-card disorder that breaks trust: `P0`
- repeated rediscovery or visible stale-card confusion: `P1`

## Pass 3: Context Pressure Reality Check

### Goal

Decide whether the context meter behavior matches what is actually happening in the session.

### Steps

1. In the same long-running thread, run:

```text
/compact status
```

2. Record:

- current token estimate
- trigger threshold
- message count
- whether compaction is already eligible

3. Continue the working session with 2 to 4 more code-reading prompts.

4. Run `/compact status` again and record the same values.

### Expected

- the token estimate moves in a way that roughly matches visible heavy tool usage
- the product does not feel like it jumps to high pressure for no reason
- if pressure is high, there is a believable cause, such as large `read_file` output accumulation

### Failure Signals

- context percentage jumps sharply with no clear heavy session activity
- context pressure feels disconnected from actual tool-heavy work
- the operator cannot tell why compaction has or has not triggered

### Severity

- obviously misleading context behavior that undermines operator trust: `P1`
- slightly confusing meter behavior with usable fallback diagnostics: `P2`

## Pass 4: Manual Compaction Mid-Task

### Goal

Verify that compaction behaves like a real runtime transition, not a brittle side path.

### Steps

1. Run:

```text
/compact
```

2. Immediately after compaction, ask:

```text
Where were we, what has already been done, and what is the next concrete step?
```

3. Then ask:

```text
What is the current phase of work, and what should you not repeat?
```

### Expected

- Reup shows a meaningful in-feed compaction state
- the post-compaction answer reflects the active task
- already-completed work is named as already done
- the next step is concrete, not generic

### Failure Signals

- the product restarts the investigation from zero
- the answer ignores recently completed work
- the answer is a vague summary with no real next step
- the feed only shows a generic slash-command result instead of a proper runtime state

### Severity

- restart-from-zero after compaction: `P0`
- vague or stale post-compaction continuity: `P1`

## Pass 5: Restore After Compaction

### Goal

Verify that a resumed session is still the same session.

### Steps

1. After Pass 4, continue working for 2 to 4 more turns.
2. Let autosave happen naturally or switch away and back.
3. Reopen the session using:

```text
/sessions
```

or:

```text
/sessions <session_id>
```

4. Immediately ask:

```text
Where were we, what has already been done, and what is the next concrete step?
```

5. Then ask:

```text
What happened most recently before this restore?
```

### Expected

- the restored session still understands the active task
- recent post-compaction turns are not lost
- the visible feed does not look stale or mismatched
- restore feels like continuation, not reconstruction by guesswork

### Failure Signals

- restore falls back to stale earlier state
- the next-step answer ignores the most recent turns
- tool cards look duplicated, reordered, or orphaned
- the session feels like a degraded replay rather than the same thread

### Severity

- stale or wrong restored state that changes the meaning of the work: `P0`
- visible feed disorder or partial continuity loss: `P1`

## Pass 6: Repeat Compaction Stability

### Goal

Verify the runtime remains coherent after multiple compaction boundaries.

### Steps

1. Continue the same restored thread for a few more turns.
2. Run:

```text
/compact
```

3. Ask:

```text
What is the current phase and next step?
```

4. Ask:

```text
List the completed work versus the remaining work only.
```

### Expected

- no crash
- no duplicate tool-result confusion
- no restart-from-zero behavior
- continuity survives repeated compaction

### Failure Signals

- repeated compaction causes confused state or duplicate history behavior
- the product acts like older summary state is current truth
- completed and remaining work get mixed together

### Severity

- repeated compaction breaks continuity: `P0`
- repeated compaction introduces confusing but survivable state drift: `P1`

## Pass 7: Failure And Recovery Clarity

### Goal

Verify that when something goes wrong, the operator sees a concrete reason.

### Steps

During the full pass, record any failure involving:

- provider auth/session problems
- compaction failures
- tool-call failures
- restore failures

If a compaction failure can be reproduced safely, note the exact feed message and whether the product exposed the underlying reason.

### Expected

- provider/auth problems surface concrete, actionable text
- compaction failures expose a reason
- the UI does not silently leave stale running state behind

### Failure Signals

- generic dead-end messages with no reason
- visible stale running cards after failure
- the operator cannot tell whether the turn ended, failed, or is still live

### Severity

- no actionable failure reason and broken UI state: `P1`
- weak failure wording with otherwise correct state: `P2`

## Evidence To Capture

For every failure, capture all of the following:

1. exact prompt or command
2. whether the session was fresh, compacted, restored, or compacted-then-restored
3. what Reup showed in the feed
4. what the agent actually answered
5. `/compact status` output near the failure, if relevant
6. provider mode in use
7. whether the issue is reproducible

If possible, also capture:

- session id
- approximate context percentage at time of failure
- whether tool-heavy repo reading had just occurred

## Launch Result Template

Use this exact template at the end of the pass:

```text
Launch Real-Life Eval

Pass 1 Baseline Session Trust: pass/fail
Pass 2 Long Real Work Session: pass/fail
Pass 3 Context Pressure Reality Check: pass/fail
Pass 4 Manual Compaction Mid-Task: pass/fail
Pass 5 Restore After Compaction: pass/fail
Pass 6 Repeat Compaction Stability: pass/fail
Pass 7 Failure And Recovery Clarity: pass/fail

Open Issues:
- [P0/P1/P2/P3] ...
- [P0/P1/P2/P3] ...

Launch Recommendation:
- ship
- ship with explicit known risks
- do not ship

Notes:
- ...
- ...
```

## Minimum Ship Standard

Do not call the product launch-ready if any of the following are still happening in this eval:

- restart-from-zero behavior after compaction
- stale or wrong restored state after `/sessions`
- visibly broken tool/assistant ordering that changes user understanding
- context pressure behavior that feels unexplainable during normal repo-reading work
- failure states that leave the operator unsure whether the turn completed, failed, or is still running

If none of those happen, and the remaining issues are `P2` or `P3`, the product is likely strong enough to ship with eyes open.
