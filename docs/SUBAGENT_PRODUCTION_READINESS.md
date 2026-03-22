# Subagent System Production-Readiness Report

**Verified on:** 2026-03-22  
**Status:** Functional and substantially hardened, but not yet fully production-ready

---

## Current Architecture

```text
User request
  -> Tool registry
  -> Session
     -> SubagentRuntime
        -> spawn_subagent / spawn_subagents
        -> wait_subagent / list_subagents / cancel_subagent
     -> SubagentTool
        -> isolated child Agent runs
        -> in-process retry with carried context
  -> Reup UI
     -> live wait cards
     -> specialist result rendering
```

### Core Files

| Component | File | Current role |
|-----------|------|--------------|
| Registry | `src/ite/tools/registry.py` | Registers built-ins, refreshes subagents, normalizes orchestration args |
| Session wiring | `src/ite/agent/session.py` | Creates `SubagentRuntime`, syncs runtime tools, runs discovery, refreshes subagents |
| Runtime | `src/ite/agent/subagent_runtime.py` | Manages background specialist runs, progress, wait/cancel, retention |
| Subagent execution | `src/ite/tools/subagent.py` | Defines built-ins, executes child agents, handles retry/continuation |
| Runtime tools | `src/ite/tools/builtin/subagent_runtime_tools.py` | `spawn_subagent`, `spawn_subagents`, `wait_subagent`, `list_subagents`, `cancel_subagent` |
| Prompt guidance | `src/ite/prompts/system.py` | Orchestration guidance for parallel fan-out |
| Reup rendering | `src/ite/ui/reup/tool_views.py` | Specialist result and runtime card rendering |
| Reup live wait UI | `src/ite/ui/reup/app.py` | Running wait cards and live subrun visibility |

---

## Built-In Specialists

| Name | Purpose | Tools | Max Turns | Timeout | Retry Attempts |
|------|---------|-------|-----------|---------|----------------|
| `codebase_investigator` | Code structure/pattern investigation | `read_file`, `grep`, `glob`, `list_dir` | 20 | 600s | 2 |
| `code_reviewer` | Review and risk finding | `read_file`, `grep`, `list_dir` | 30 | 600s | 2 |
| `tooling_guardian` | Tooling and policy audit | `read_file`, `grep`, `glob`, `list_dir` | 40 | 600s | 2 |
| `verification_reviewer` | Regression-focused validation guidance | `read_file`, `grep`, `glob`, `list_dir`, `shell` | 12 | 360s | 1 |

---

## What Is Production-Ready Enough Today

- Background orchestration exists and works through `spawn_subagent`, `spawn_subagents`, `wait_subagent`, `list_subagents`, and `cancel_subagent`.
- Parallel fan-out exists and can launch multiple child runs concurrently.
- Duplicate active specialist requests are reused instead of spawning redundant runs.
- Subagent failures now surface structured metadata to the UI instead of only generic wrapper errors.
- Retry now happens inside the same subagent execution path for timeout and max-turn failures.
- Retry carries forward partial output, parsed findings/actions, and activity/tool trail into the continuation prompt.
- Batch fan-out now has a hard guardrail: `spawn_subagents` rejects batches over `8`.
- Finished runtime tasks are pruned from `_tasks`.
- Terminal run retention now prevents `_runs` from growing without bound by keeping only the most recent finished runs.
- Repeated specialist failures/timeouts now trip a runtime circuit breaker and temporarily block new spawns for that specialist.

---

## What Was Fixed During Hardening

### Already addressed

1. **Runtime wiring gaps**
   - `spawn_subagents` is wired into session runtime setup.

2. **Parallel orchestration**
   - Batch fan-out is available through `spawn_subagents`.

3. **Prompt duplication**
   - The duplicated subagent guidance paragraph in the system prompt has been removed.

4. **Task cleanup**
   - Completed runtime tasks are removed from `_tasks` automatically.

5. **Concurrency guardrail**
   - Batch size is capped at `8`.

6. **Retry/resume behavior**
   - In-process retry now exists for timeout and max-turn failures.
   - Retry metadata includes `attempt_count`, `retries_used`, and `recovered_after_retry`.

7. **UI visibility**
   - Reup can render structured failure context and retry recovery state.
   - Wait cards can show multiple active subruns and their activity.

8. **Run retention**
   - Terminal run history is pruned to a bounded size.

---

## Remaining Production Risks

### High

1. **Crash-safe orphan cleanup is still missing**
   - If the host process dies abruptly, background subagent tasks are not recovered or explicitly finalized.

2. **No provider/resource budgeting**
   - There is still no token/cost-aware throttling beyond the batch-size cap.

### Medium

3. **Retries are continuation-by-prompt, not true child-session resume**
   - This is good enough for many failures, but it is not durable session checkpoint/resume.

4. **No explicit crash recovery state**
   - Retained run metadata is in-memory only for the active session.

5. **Limited operator controls in UI**
   - There is no dedicated dashboard, progress bar, or click-to-cancel interface yet.

6. **No circuit-breaker telemetry**
   - Specialist failure rates, timeout rates, and retry rates are not aggregated or persisted.

### Low

8. **Fallback mutating-tool detection still uses a hardcoded list**
   - Registry-derived metadata is the real source of truth, but the fallback remains heuristic.

9. **No strict TOML schema validator**
   - Invalid user subagent TOML still degrades more softly than a full schema-driven validation path.

---

## Recommended Path To Production

### Phase 1: Runtime Safety

1. Add a circuit breaker per specialist.
   - Trip after repeated failures/timeouts in a window.
   - Surface the breaker state to the parent and UI.

2. Add crash-safe shutdown/finalizer handling.
   - Ensure active subagent tasks are explicitly cancelled during abnormal teardown.

3. Add runtime metrics.
   - Track spawn count, completion rate, timeout rate, retry rate, and breaker trips.

### Phase 2: Recovery Quality

4. Add richer retry checkpoints.
   - Persist more structured attempt state than the current prompt carry-over.

5. Add differentiated retry policies.
   - Timeout retry policy should differ from max-turn retry policy.
   - Some specialists may deserve more attempts or wider timeout backoff than others.

### Phase 3: Operator UX

6. Build a dedicated subagent status view.
   - One place to see all runs, status, attempts, retries, duration, and failure cause.

7. Add explicit recovery notes in wait/completed cards.
   - Show when a run completed only after retry.

8. Add cancellation controls in UI.

### Phase 4: Policy and Documentation

9. Document fan-out decision rules.
   - When to use blocking `subagent_*` vs runtime orchestration tools.

10. Add a subagent operator playbook.
   - Expected states, failure modes, recovery behavior, and manual test scenarios.

---

## How To Test The Current System

### Automated

Run the full subagent-related verification suite:

```bash
python3 -m unittest \
  tests.test_tooling_v01 \
  tests.test_subagent_runtime \
  tests.test_reup_command_palette \
  tests.test_reup_tool_views \
  tests.test_system_prompt \
  tests.test_agent_tool_recovery \
  tests.test_cli_modes -q
```

### Manual smoke scenarios

1. **Single specialist**
   - Prompt: `Research how subagents work in this codebase. Use the subagent.`
   - Expect: one blocking specialist card with live progress and a clean result.

2. **Parallel batch fan-out**
   - Prompt: `Investigate registry, runtime, reup UI, and prompt guidance in parallel, then merge the results.`
   - Expect: one `spawn_subagents` call, multiple runs launched immediately, then `wait_subagent`.

3. **Oversized batch protection**
   - Force or script a request with more than `8` specialist requests.
   - Expect: clean tool failure explaining the batch cap.

4. **Retry after max turns**
   - Use a specialist with a constrained turn budget or a deliberately broad task.
   - Expect: retry inside the same run, visible retry messaging, final completion if recovery succeeds.

5. **Retry after timeout**
   - Use a deliberately long-running specialist task.
   - Expect: timeout retry inside the same run, carried-forward continuation behavior.

6. **Duplicate request reuse**
   - Trigger the same specialist goal twice while the first is active.
   - Expect: reuse of the active run instead of duplicate spawning.

7. **Task cleanup**
   - Run specialists to completion and verify the runtime no longer accumulates completed tasks indefinitely.

8. **Retention cleanup**
   - Create many completed runs in one session.
   - Expect: old terminal runs eventually age out of retained runtime state.

---

## Current Bottom Line

The system has crossed from prototype into credible pre-production shape. It now has:

- real parallel orchestration
- bounded fan-out
- in-process retry with carried context
- bounded runtime retention
- meaningful UI visibility

The main blockers left are operational hardening, not core architecture:

- circuit breaking
- crash-safe cleanup
- better runtime metrics
- stronger operator UX

Once those are in, the subagent system is in a realistic position for production use.
