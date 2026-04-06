# csrc vs iTE Runtime Handoff

This document captures the current plain-English runtime map between `csrc` and `iTE`, the architectural gap that still matters most, and the single highest-leverage next patch to port.

It exists as a recovery note for future sessions so the work does not drift back into isolated UI fixes or provider-specific retries without preserving the larger runtime direction.

## Short Version

`csrc` is a runtime-first system that happens to render chat.

`iTE` is still mostly a chat/transcript-first system that has accumulated several runtime improvements on top.

The most important remaining gap is not another retry or memory tweak. It is the lack of a first-class append-only transcript/event model in `iTE`.

## Plain-English Map

### What `csrc` gets right

`csrc` separates the major runtime concerns more cleanly:

- token pressure and continuation policy are managed explicitly
- tool output is reduced before it poisons the whole context
- tool orchestration is treated as runtime infrastructure
- session memory has its own lifecycle
- UI/log rendering is synchronized against durable runtime state instead of being inferred from one mutable message list

Key reference files:

- [`csrc/query/tokenBudget.ts`](/Users/kiishidavid/Documents/Dev/Projects/ite/csrc/query/tokenBudget.ts)
- [`csrc/services/compact/autoCompact.ts`](/Users/kiishidavid/Documents/Dev/Projects/ite/csrc/services/compact/autoCompact.ts)
- [`csrc/services/compact/microCompact.ts`](/Users/kiishidavid/Documents/Dev/Projects/ite/csrc/services/compact/microCompact.ts)
- [`csrc/services/tools/toolOrchestration.ts`](/Users/kiishidavid/Documents/Dev/Projects/ite/csrc/services/tools/toolOrchestration.ts)
- [`csrc/services/SessionMemory/sessionMemory.ts`](/Users/kiishidavid/Documents/Dev/Projects/ite/csrc/services/SessionMemory/sessionMemory.ts)
- [`csrc/hooks/useLogMessages.ts`](/Users/kiishidavid/Documents/Dev/Projects/ite/csrc/hooks/useLogMessages.ts)
- [`csrc/state/AppStateStore.ts`](/Users/kiishidavid/Documents/Dev/Projects/ite/csrc/state/AppStateStore.ts)

### What `iTE` already has

`iTE` is no longer at the original baseline. It already has several important runtime pieces:

- compaction boundaries and artifact persistence
- a microcompact step for bulky tool output
- session memory as a distinct artifact
- recovery/retry behavior for transient bundled/cloud inference failures
- Reup-specific work to reduce stale cards, duplicate checklist noise, and bad tool/assistant rendering boundaries

Key current files:

- [`src/ite/context/manager.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/context/manager.py)
- [`src/ite/context/compact_artifacts.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/context/compact_artifacts.py)
- [`src/ite/memory/session_memory.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/memory/session_memory.py)
- [`src/ite/agent/agent.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/agent/agent.py)
- [`src/ite/ui/reup/app.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/ui/reup/app.py)
- [`src/ite/cloud/auth.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/cloud/auth.py)
- [`src/ite/client/llm_client.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/client/llm_client.py)

### What `iTE` is still missing

The most important missing piece is still the same one called out in the roadmap:

- there is no real append-only transcript/event model
- `ContextManager._messages` is still too close to being both the source of truth and the prompt assembly input
- compaction still mutates the live message structure in place
- UI truth, recovery behavior, and prompt construction still rely too much on state inferred from mutable chat history

This is why `iTE` can still feel fragile even after several legitimate fixes.

Reference:

- [`docs/architecture/context-runtime-roadmap.md`](/Users/kiishidavid/Documents/Dev/Projects/ite/docs/architecture/context-runtime-roadmap.md)

## Why This Matters

Several issues surfaced in live Reup testing all point back to the same architectural weakness:

- assistant conclusions appearing visually above later tool cards
- turns feeling stopped when they actually concluded, or vice versa
- stale or orphaned tool UI after failures and recoveries
- ambiguity around whether retry/continue resumed cleanly or replayed in a changed state
- compaction and restore behavior remaining too coupled to mutable prompt history

These are not just random UI bugs. They are signs that the runtime truth model is still too close to prompt assembly and transient UI state.

## Single Best Next Patch To Port From `csrc`

The single best next patch is:

Introduce a first-class append-only conversation log for `iTE`, then derive prompt assembly and Reup rendering from it.

In practical terms, add a transcript/event layer with records such as:

- `user_message`
- `assistant_message`
- `assistant_tool_call`
- `tool_result`
- `system_event`
- `compact_boundary`

This should be the next major slice because it addresses the root problem rather than another symptom.

## Recommended Implementation Shape

Do this incrementally, not as a flag-day rewrite.

### Step 1: Add the event model

Create a minimal `ConversationLog` or equivalent transcript structure that can record the events above in append-only order.

### Step 2: Dual-write from the agent loop

Keep current behavior working, but have the agent/runtime also write every meaningful event into the new transcript model.

That means:

- user input
- assistant text segments
- tool starts
- tool completions
- compaction boundaries
- recovery/system notices

### Step 3: Render Reup from transcript truth

Make Reup consume the transcript/event model instead of reconstructing truth from mutable in-flight widgets and `_messages`.

This is the part most likely to eliminate the “final answer showed up above later tool cards” and “stale running card” class of bugs in a principled way.

### Step 4: Build prompt assembly from transcript + layers

Move prompt construction toward:

1. response controls
2. session memory
3. durable memory
4. compact artifact
5. transcript tail

instead of treating the mutable message list as the main truth source.

## Why This Patch Wins Over Other Options

Do this before:

- another round of retry tweaks
- more checklist shaping
- additional bundled/cloud error handling
- deeper durable memory redesign

Reason:

those can all help, but they keep landing on top of a runtime that still does not cleanly separate:

- what happened
- what should be rendered
- what should be sent back to the model

`csrc` is ahead mainly because it is much more disciplined about that separation.

## Related Work Already Landed In `iTE`

This transcript-first next patch should build on, not replace, the stabilization work already done:

- microcompact and compaction continuity
- bundled/cloud retry and recovery improvements
- cloud auth degradation instead of UI-breaking tracebacks
- bundled model availability surfaced in Reup
- better todo ownership and checklist reuse
- stale tool-card cleanup after failure/recovery
- assistant/tool boundary rendering fixes

Those were still useful. They reduced instability and made the remaining architectural gap easier to see.

## Context Budget Reality Check

One important live-testing finding needs to be preserved explicitly:

The current Reup context meter is not mainly wrong because of fake math. It rises quickly because `iTE` is still carrying too much raw tool output forward in prompt context.

### Verified current settings

- workspace config sets `context_window = 200000` in [`.ite/config.toml`](/Users/kiishidavid/Documents/Dev/Projects/ite/.ite/config.toml)
- auto-compaction trigger is `85%` in [`src/ite/context/manager.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/context/manager.py)
- that means compaction starts at roughly `170000` tokens

### What the local estimator is doing

`ContextManager.estimate_current_context_tokens()` in [`src/ite/context/manager.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/context/manager.py) counts tokens over the actual prompt messages that will be sent back to the model by serializing each prompt message as JSON and tokenizing it.

Important notes:

- it does not include `tool_ui`
- it does not include tool schemas
- so the local estimate is not obviously inflated by UI metadata
- if anything, it may still slightly undercount relative to the full provider request

### The real reason context rises too fast

The main driver is prompt bloat from raw tool output, especially large `read_file` results.

Key facts:

- [`src/ite/tools/builtin/read_file.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/tools/builtin/read_file.py) allows up to `25000` tokens per read result
- those results are appended to the transcript tail and remain part of prompt context
- `microcompact_tool_outputs()` in [`src/ite/context/manager.py`](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/context/manager.py) starts too late, only when the prompt is within `8000` tokens of the compaction threshold
- that means long read-only audits can accumulate many large code dumps before cleanup starts

### Concrete measurements from this workspace

Using the live config loaded from this repo:

- empty-session prompt baseline: about `3899` tokens
- three large synthetic `read_file` results: about `40105` tokens (`20.1%`)
- six larger synthetic `read_file` results: about `148297` tokens (`74.1%`)

This means the “0 to 85 very fast” feeling is plausible even when the session has only been running for a short time, if the agent is doing broad code-reading work.

### Conclusion

This is primarily a prompt-assembly/runtime issue, not just a bad meter issue.

The important distinction:

- not mainly: “context percent is fake”
- mainly: “too much raw tool output is surviving in model context for too long”

### Best follow-up from this finding

If the next session needs the context-budget fix direction, do this before fiddling with the UI meter:

1. start tool-output compaction earlier for read-only audits
2. reduce how much `read_file` output is allowed to remain in carried-forward prompt context
3. separate “full tool output shown in UI” from “compressed tool summary sent back to the model”

This is another place where `csrc` is effectively ahead: it is more disciplined about early reduction of bulky context through token budgeting and microcompaction.

## If We Lose Session Context

If a future session needs the shortest accurate restart:

1. `csrc` is the more mature runtime reference.
2. `iTE` has several runtime stabilizers already, but is still centered on mutable message history.
3. The main remaining gap is the lack of a first-class append-only transcript/event model.
4. The next highest-leverage patch is to add that transcript model, dual-write into it, then move Reup rendering and prompt assembly onto it incrementally.
