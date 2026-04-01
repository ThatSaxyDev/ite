# Context Runtime Roadmap

This document captures the target context architecture for `iTE`, the current implementation status, and the next slices to build.

It exists to keep the compaction and memory work grounded in a stable runtime contract rather than continuing to layer features on top of a transcript-centric model.

## Target State

`iTE` should move from a single-threaded `chat transcript + heuristic memory bundle` design to a layered runtime:

1. Transcript layer
Raw conversation/events, resumable, append-only, compaction-aware.

2. Working memory layer
Structured session state for the current conversation only.

3. Durable memory layer
Typed, validated, cross-session memory with explicit save/use rules.

4. Retrieval/orchestration layer
Decides what to inject into prompts and when, without overloading the transcript.

5. Compaction layer
Boundary-based context reduction, not transcript replacement.

The design principle is correctness first. Better retrieval on top of a weak context runtime is the wrong optimization order.

## Current Status

The codebase is no longer at the original baseline, but it is not yet at the target architecture either.

### Landed

#### Compact boundaries and artifacts

- Compact-boundary metadata is persisted in session snapshots and restored in [`src/ite/context/manager.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/context/manager.py).
- Compaction summary artifacts are stored via [`src/ite/context/compact_artifacts.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/context/compact_artifacts.py).
- Agent-driven and manual compaction both record `summary_artifact_id`, trigger metadata, and compaction counts in:
  - [`src/ite/agent/agent.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/agent/agent.py)
  - [`src/ite/commands/session.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/commands/session.py)

#### Live compaction is less synthetic than before

- Compaction preserves a recent raw tail using [`ContextManager.select_compaction_tail()`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/context/manager.py).
- When an artifact id is available, the live session now keeps a system-level compact artifact in context rather than always injecting a fake `Context Restoration` user/assistant exchange.
- Restore also prefers artifact-backed continuation when the compact boundary references a saved summary artifact.

#### Session memory exists as a distinct layer

- [`src/ite/memory/session_memory.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/memory/session_memory.py) provides structured session memory.
- Session memory is refreshed from stable session state in [`src/ite/agent/session.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/agent/session.py).
- Session memory is injected into prompt assembly in [`src/ite/prompts/system.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/prompts/system.py).
- Session memory uses the system-level `ite` data dir as the canonical store, with workspace fallback only if needed.

#### Persistence hardening improved

- Corrupt session files are quarantined instead of crashing session listing or load.
- Corrupt checkpoint files now get the same quarantine treatment in [`src/ite/agent/session_manager.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/agent/session_manager.py).

#### Manual compaction is now testable

- `/compact` and `/compact status` exist in [`src/ite/commands/session.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/commands/session.py).
- Reup shows manual compaction in-feed:
  - `Compacting context`
  - `Context automatically compacted`
- Cloud-style compaction response handling was fixed in [`src/ite/context/compaction.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/context/compaction.py).

#### Session command surface is cleaner

- `/sessions` is now the single user-facing restore command:
  - `/sessions`
  - `/sessions --list`
  - `/sessions <session_id>`
- `/resume` was removed from the user-facing command registry.

### Still Missing

#### No real transcript abstraction yet

This is the biggest remaining architectural gap.

`ContextManager._messages` is still the primary live runtime structure, and compaction still mutates that structure in place through [`replace_with_summary()`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/context/manager.py).

That means the source of truth is still too close to prompt assembly.

#### No append-only conversation log

There is no dedicated `ConversationLog` or transcript event store yet.

We do not yet have a first-class record of:

- user message
- assistant message
- tool call
- tool result
- system event
- compact boundary

with replay and trimming semantics independent from prompt construction.

#### Durable memory redesign has not started

The durable memory system is still the heuristic manager in [`src/ite/memory/manager.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/memory/manager.py).

It does not yet implement the planned typed schema:

- user
- feedback
- project
- reference

#### Retrieval is still too bundled

Prompt memory is still largely derived through the existing memory manager rather than a staged retrieval pipeline.

The intended retrieval order is not fully implemented:

1. response controls
2. session memory
3. durable memory
4. compact artifact
5. transcript tail

## Phase Tracking

### Phase 1: Foundation First

#### Done

- compact-boundary metadata
- compact artifact persistence
- preserved raw tail
- checkpoint/session corruption hardening

#### Not done

- `ConversationLog`
- append-only transcript model
- compact boundaries as first-class transcript records
- prompt assembly separated from transcript mutation

### Phase 2: Session Memory

#### Done

- `SessionMemoryManager`
- structured current-session artifact
- system-level storage
- prompt injection

#### Still needed

- explicit token budgeting
- update policy tuning
- stronger lifecycle tests for stale session memory and refresh cadence

### Phase 3: Durable Memory Redesign

Not started.

### Phase 4: Retrieval Overhaul

Not started in the intended staged form.

### Phase 5: Compaction Migration

Partial.

We now have the pieces:

- session memory
- compact artifacts
- compact boundaries
- preserved raw tail

But they still sit on top of a mutable `_messages` runtime.

### Phase 6: Evaluation and Guardrails

Partially started.

There are tests for:

- compact boundary round-tripping
- checkpoint corruption handling
- session memory generation
- prompt injection
- manual compaction
- resumed-session manual compaction
- reup compaction feed behavior
- cloud-style compaction response handling

Still missing are broader transcript integrity and long-session replay tests.

## Runtime Invariants

These are the invariants the next refactor should preserve.

1. No orphaned tool results.
Compaction and restore must not leave a tool result without its originating assistant tool call.

2. Compact boundaries are durable.
If compaction happened, the runtime must retain explicit evidence that it happened.

3. Session continuity is layered.
Current-session continuity should come from session memory plus compact artifacts plus recent tail, not from fake replay prompts alone.

4. Restore must be safe on partial corruption.
Bad session or checkpoint files should be quarantined, not crash the runtime.

5. Manual compaction must exercise the real pipeline.
`/compact` should not be a fake shortcut; it should use the same compaction machinery as the automatic path.

## Next Implementation Slice

The next meaningful patch set should be narrowly scoped.

### Goal

Introduce a transcript model without doing a flag-day rewrite.

### Scope

1. Add a minimal `ConversationLog` or equivalent transcript event abstraction.

2. Record compact boundaries as transcript events, not just special messages.

3. Separate transcript truth from prompt assembly:
   - system prompt
   - response controls
   - session memory
   - durable memory
   - compact artifact
   - recent preserved tail

4. Keep compatibility with the current `_messages` path while migrating.

### Out of scope for this slice

- full durable memory schema migration
- retrieval rewrite
- replacing all snapshot formats
- aggressive compaction prompt redesign

## Practical Recommendation

Do not start by trying to make retrieval smarter.

The next improvement with the highest leverage is changing the runtime contract for context continuity:

- transcript truth
- session continuity
- durable memory
- compact artifacts

That is the foundation worth building on.
