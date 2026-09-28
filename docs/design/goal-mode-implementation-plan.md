# Goal Mode Implementation Plan

**Status:** Proposed implementation plan  
**Owner:** iTE runtime / Reup  
**Scope:** Persistent, evidence-driven `/goal` mode for a single iTE session (thread)  
**Last reviewed:** 2026-09-28

## 1. Outcome

Implement Codex-style Goal mode in iTE so a user can set one durable objective for the current thread and let iTE continue safely until it is:

- completed with recorded evidence;
- paused, cleared, or otherwise interrupted by the user;
- blocked pending user input;
- stopped because bundled-model quota is exhausted; or
- stopped by a real anti-spin safety condition.

The feature is deliberately **not** “raise `max_turns`.” In Goal mode, there must be no arbitrary goal-wide or agent-loop turn cap. A goal may consume as many model/tool rounds as required while it remains active and is making defensible progress.

Goal mode must preserve iTE's existing sandbox and approval policy. It gives the agent more persistence, not more authority.

## 2. Product Contract

### 2.1 User-facing command surface

| Command | Behavior |
| --- | --- |
| `/goal <objective>` | Create a goal for this thread and immediately start its initial work turn. Reject replacement when a goal already exists; direct the user to `/goal edit` or `/goal clear`. |
| `/goal` | Show objective, state, elapsed active time, work metrics, latest evidence, and next action. |
| `/goal pause` | Stop future automatic continuation. If a turn is currently active, cancel it and preserve partial progress. |
| `/goal resume` | Mark a paused/blocked/budget-limited goal active and queue exactly one continuation. |
| `/goal clear` | Remove the goal after confirmation in Reup; never delete chat, todos, files, or prior goal history. |
| `/goal edit <objective>` | Update the objective and reset only completion candidacy/evidence freshness; retain history and work metrics. If active, first pause and settle the running turn, then leave the revised goal paused for an explicit resume. |

`/goal <objective>` is both the initial user prompt and the definition of done. It should be phrased as an outcome with verification and constraints whenever possible.

### 2.2 One lifecycle controller; two first-class interfaces

The Goal panel is the primary lifecycle control surface for a person using Reup. Slash commands remain equally capable for people who prefer the keyboard, remote/headless use, scripts, and discoverability. Neither interface is a second-class wrapper around the other.

| User intent | Slash-command entry point | Goal-panel entry point | One authoritative implementation |
| --- | --- | --- | --- |
| Create | `/goal <objective>` | empty-state `Create goal` action (when a goal does not exist) | `GoalLifecycleController.create()` |
| Inspect | `/goal` | top-bar Goal badge opens the panel | `GoalLifecycleController.view()` / read model |
| Pause | `/goal pause` | `Pause` button | `GoalLifecycleController.pause()` |
| Resume | `/goal resume` | `Resume` button | `GoalLifecycleController.resume()` |
| Edit | `/goal edit <objective>` | `Edit` button and inline panel editor | `GoalLifecycleController.edit()` |
| Clear | `/goal clear` | `Clear` button and confirmation | `GoalLifecycleController.clear()` |

The panel must **not** simulate its buttons by injecting `/goal …` into the composer or invoking the command dispatcher. That would create misleading transcript cards, split validation rules, and make control of a running turn depend on composer state. Commands and panel messages both call the same lifecycle controller, which performs state change, cancellation coordination, autosave, header/panel refresh, and remote-state broadcast once.

The controller belongs with the session/runtime orchestration, not inside the widget. The widget emits typed requests such as `GoalSidePanel.PauseRequested`; Reup receives them and calls the controller. `GoalSidePanel` renders state and owns focus/layout only—it never mutates `Session` directly.

### 2.3 Lifecycle

```text
created ──► active ──► completed
             │  │
             │  ├──► blocked ──► active
             │  ├──► budget_limited ──► active
             │  └──► paused ──► active
             │
             └──► cleared
```

- **active:** automatic continuation is permitted only at a safe idle boundary.
- **paused:** user-controlled halt; work remains visible and resumable.
- **blocked:** iTE needs information, access, approval, or another external change. The goal does not self-retry.
- **budget_limited:** bundled-provider quota is exhausted. Save the quota window/reset information and do not retry until the user resumes after changing provider or waiting for reset.
- **completed:** completion is final for automatic continuation but remains inspectable.
- **cleared:** no active goal exists. Keep a small historical summary in the session transcript/goal history for auditability.

An interruption (application quit, Ctrl-C, cancelled turn, switching away from a running remote host) transitions an active goal to **paused**, rather than treating it as complete or blocked.

## 3. UX

### 3.1 Always-visible state and entry point

Add a clickable `Goal` status badge to Reup's top-right `#header-meta-group`, ahead of the workspace label:

```text
≡  Fix cache invalidation                    Goal • 12m  WORKSPACE: ite  /changes /hooks /aside
```

Badge states:

| State | Label and treatment |
| --- | --- |
| active | `Goal • 12m` in the success/primary color; elapsed time counts upward once per second. |
| paused | `Goal • paused` in muted color. |
| blocked | `Goal • needs input` in warning color. |
| budget_limited | `Goal • usage limit` in warning/error color. |
| completed | Do not occupy the permanent header slot; show a short completion notice with a `View goal` action, and retain it in Goal details. |

Do not put the full objective or lifecycle buttons in the header. The top bar is status, not a toolbar: it must stay slim, preserve workspace metadata, and act only as the persistent entry point to the panel. Use a compact `#goal-toggle` `Button` styled as an inline status token—transparent, borderless, content-width, one row high—rather than a large header button. This retains mouse and keyboard activation without adding heavy chrome.

### 3.2 Goal details panel — the primary control surface

Clicking the badge opens a dedicated right-side Goal panel. A user must be able to pause, resume, edit, and clear an active goal here while a turn is running; entering a slash command is never required.

The panel is a compact operational surface, not a dashboard. In visual priority order, it contains:

1. a one-row header: `Goal`, current status, live elapsed count-up, and Close;
2. the complete objective, wrapped naturally and editable only after selecting `Edit`;
3. the current decision-critical state: next action while active, exact blocker when blocked, or quota/reset guidance when budget-limited;
4. one compact action row: state-dependent `Pause` or `Resume`, then `Edit`, then `Clear`;
5. concise work accounting: active work time, model rounds, tool outcomes, changed files, and verification passes/attempts;
6. current execution todos and a scrollable, bounded activity/evidence feed with useful test/command excerpts.

Action semantics:

| Panel state | Primary action | Other actions | Behavior while a turn is running |
| --- | --- | --- | --- |
| active | `Pause` | Edit, Clear | Pause immediately suppresses continuation, requests turn cancellation, then commits `paused` only after cleanup. Edit uses `Pause and edit`; Clear confirms, cancels safely, then clears. |
| paused | `Resume` | Edit, Clear | Resume queues exactly one continuation through the same safe gate; Edit saves in place; Clear confirms and archives a summary. |
| blocked | `Resume` | Edit, Clear | Resume is explicit user acknowledgement that the blocker has been addressed; it never self-retries. |
| budget_limited | `Resume` | Edit, Clear | Resume re-evaluates available provider usage / current model before scheduling work. |
| completed | — | Edit goal, Clear | No automatic work restarts. Editing creates a renewed active candidacy only after explicit user confirmation. |

`Edit` opens an inline edit state inside the panel (multiline objective field plus Save/Cancel), rather than requiring the composer. If it is active, Save first follows the pause-and-settle path so a turn cannot keep executing under the old objective. `Clear` always requires a confirmation surface because it removes the current lifecycle state, while retaining the compact history summary.

The panel's timer is derived from timestamps and refreshed every second. It is never persisted every second; it is persisted on lifecycle transitions, work-turn boundaries, and normal autosave.

### 3.3 Composer and conversation behavior

- Do not add a duplicate lifecycle-button rail to the composer in the MVP. The composer remains available for steering messages and slash-command users; the Goal badge and panel are the obvious click path for lifecycle control.
- A compact, read-only goal progress line above the composer is optional only if it fits without consuming a useful row. It may say `Goal active • 12m • open Goal`, but it is never the sole Pause/Resume/Edit/Clear affordance.
- Normal user messages remain valid steering messages. They become part of the same goal context and do **not** silently replace the objective.
- A user message explicitly asking for a status update should receive the update, then automatic continuation may resume only after that response has finished and no message is queued.
- A goal completion, blocker, and usage-limit event appears as a durable conversation card, not only a transient notification.

## 4. Domain Model and Persistence

Create `src/ite/agent/goal.py` for the value types and lifecycle methods; keep `Session` as the owner of the current goal.

```python
class GoalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    BUDGET_LIMITED = "budget_limited"
    COMPLETED = "completed"

@dataclass
class GoalMetrics:
    active_elapsed_seconds: float = 0.0
    work_elapsed_seconds: float = 0.0
    model_rounds: int = 0
    continuation_count: int = 0
    tool_calls_started: int = 0
    tool_calls_succeeded: int = 0
    tool_calls_failed: int = 0
    files_changed: int = 0
    verification_attempts: int = 0
    verification_passes: int = 0

@dataclass
class GoalEvent:
    timestamp: str
    kind: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)

@dataclass
class GoalState:
    goal_id: str
    objective: str
    status: GoalStatus
    created_at: str
    updated_at: str
    active_started_at: str | None
    completed_at: str | None
    metrics: GoalMetrics
    events: list[GoalEvent]
    latest_evidence: str | None
    blocker: str | None
    budget_details: dict[str, Any] | None
```

Rules:

- Keep a bounded event ledger (for example, 100 events) in the session snapshot. It is a compact audit trail, not a replacement for the transcript.
- `active_elapsed_seconds` means wall-clock time while the goal is active, including a running work turn and normal safe-boundary continuation. It stops when paused, blocked, budget-limited, or completed.
- `work_elapsed_seconds` means time inside an actual agent turn. It is separate from elapsed time so the user can distinguish “this goal has existed for 25 minutes” from “iTE has actively worked for 18 minutes.”
- On a clean shutdown, fold the active interval into `active_elapsed_seconds`, mark the goal paused, and autosave. On an unclean restart, restore an active persisted goal as paused; never count time while iTE was not running.
- Keep goal history in a new `goal_history` snapshot field. Clearing a goal appends a compact final event rather than discarding evidence.

Add backwards-compatible optional fields to `SessionSnapshot` and `Session.snapshot_kwargs()`. Old session JSON must load with `goal_state=None` and `goal_history=[]`.

## 5. Runtime Design

### 5.1 Separate goal continuation from a single agentic loop

Current behavior is bounded by `Config.max_turns` in `Agent._agentic_loop()`. For normal requests, retain this behavior.

For a goal:

1. run an initial agent turn;
2. after the turn ends, update work metrics and evaluate the goal state;
3. only if the goal is active and continuation conditions are met, queue **one** hidden continuation payload;
4. dispatch that continuation only after the thread is idle and no user/remote/queued work is pending;
5. repeat until a lifecycle stop condition occurs.

This is intentionally event-driven. Do not turn the Reup event loop into a tight `while True` background task.

The agent loop itself must not emit `Maximum turns (...) reached` for an active goal. Replace its numeric loop condition with a policy check that permits work while the active session goal remains runnable. The loop detector, failed-provider handling, cancellation, approval handling, and malformed/repeated-discovery safeguards remain in force.

### 5.2 Safe continuation gate

Add one authoritative method, likely on the Reup run-state/controller:

```python
def should_continue_goal(session, run_state) -> GoalContinuationDecision:
    # continue only if all are true:
    # - goal.status is ACTIVE
    # - no active turn, shell prompt, approval, plan question, or subagent wait exists
    # - no user, remote, recovery, or ordinary queued payload exists
    # - the previous turn did not end with an agent error
    # - there was observable progress since the last continuation
    # - no completion/blocker/budget transition occurred
```

Observable progress means at least one useful tool result, file change, verification attempt, or accepted evidence update. A text-only continuation that does not call a tool must not trigger another automatic continuation; mark the goal blocked/needs input with the model's explanation instead of spinning.

Do not auto-continue during Plan-only mode. A user can use `/plan` before creating a goal, but creating a goal starts execution mode only after the user has approved the plan.

### 5.3 Goal-aware prompts and completion authority

Extend `get_system_prompt()` / `ContextManager` with an active-goal section containing the exact objective, state, recent progress, latest evidence, and remaining todos.

The continuation prompt must require the model to:

- compare the objective to concrete evidence before completing;
- perform the next highest-value scoped action if the evidence is insufficient;
- keep approvals and user instructions intact;
- report a blocker precisely when an external decision/input is required;
- avoid restating a status update as a substitute for work.

Introduce an internal `goal_outcome` tool, bound to the active session similarly to the existing stateful todos/memory tools. It exposes only:

- `complete`: requires a completion summary and evidence references;
- `report_blocked`: requires the blocker, attempted paths, and the exact input needed;
- `record_evidence`: records verified test/benchmark/artifact evidence.

The model may request completion, but the runtime validates that it supplied evidence and records the request as an auditable event. User actions alone control pause, resume, edit, clear, and budget-limited recovery. A completion request with missing evidence remains active and adds a corrective prompt.

## 6. Time and Work Accounting

Goal mode starts iTE's first-class work-accounting system. The initial implementation should collect only state that is accurate, inexpensive, and user-useful.

| Signal | Recorded when | Why |
| --- | --- | --- |
| Active elapsed time | goal state transition and display tick | Count-up timer in header/panel. |
| Agent work time | each agent-turn start/end | Separates active effort from paused time. |
| Model rounds | every successful model response cycle | Shows iteration depth without treating it as a limit. |
| Continuations | each automatic follow-up payload | Explains autonomous progress. |
| Tool outcomes | tool start/complete events | Shows whether work is advancing or failing. |
| Changed files | successful results with diffs or changed paths | Concrete implementation progress. |
| Verification | test/lint/typecheck/recognized verification tool results | Evidence for completion. |
| Compactions / retries | existing agent events | Makes long-running behavior explainable. |

Use `time.monotonic()` for live work-duration measurement in `SessionRunState`; serialize final accumulated durations as seconds. Use ISO wall-clock timestamps only for display/history. This avoids elapsed-work errors if the system clock changes while a turn runs.

Do not build a global analytics backend in this phase. The metrics are per-thread, local, snapshot-persisted, and visible in the Goal panel. Backend analytics can be considered only after product usage demonstrates a need.

## 7. Bundled Usage and the Adjacent API

### Confirmed API contract

The adjacent `ite-cloud-api` already supplies everything iTE needs for MVP:

- `POST /inference/chat` rejects exhausted bundled quota with `quota_exhausted`, the exhausted window, reset time, and fresh quota snapshot.
- It rejects model-specific request pacing with `model_rate_limited` and a reset time.
- Each successful streamed `message_complete` event contains updated `quotas`.
- `GET /usage/summary` returns entitlement, usage, and all quota windows.

Relevant backend files:

- `../ite-cloud-api/src/routes/inference.ts`
- `../ite-cloud-api/src/routes/usage.ts`
- `../ite-cloud-api/src/lib/usage.ts`

### Decision: no API change for Goal MVP

No `ite-cloud-api` migration or endpoint is required for initial Goal mode. The iTE runtime already receives quota data and formats quota failures. On `quota_exhausted` or `model_budget_exhausted`, it must transition the goal to `budget_limited`, persist the details, stop automatic work, and show the reset/provider-switch action.

For BYOK/local models, iTE cannot accurately know account spend remaining. Show `Usage availability: provider-managed` and continue until ordinary completion, blocker, cancellation, or a provider error.

Possible future API work—explicitly out of MVP—is aggregate cross-device Goal history/activity. It would require authenticated goal-event ingestion, retention policy, privacy review, and schema migrations. Do not add it merely to render the local timer.

## 8. Reup, Remote, and Headless Runtime

### Reup

Use the existing seams:

- Header composition: `src/ite/ui/reup/app.py`
- Header refresh: `src/ite/ui/reup/_threads.py`
- Turn lifecycle/event dispatch: `src/ite/ui/reup/_turn.py`
- Composer queue/compaction continuation: `src/ite/ui/reup/_composer.py`
- Contextual-panel manager and header-button handlers: `src/ite/ui/reup/_panels.py`
- Existing side-panel widget conventions: `src/ite/ui/reup/widgets/side_panels.py`
- Styling: `src/ite/ui/reup/reup.tcss`
- Existing workboard/todos presentation: `src/ite/ui/reup/command_views.py`

#### Reuse the established side-panel architecture

The Goal panel must be implemented as `GoalSidePanel` in `src/ite/ui/reup/widgets/side_panels.py`, alongside `CommandsSidePanel`, `HooksSidePanel`, and `ChangeReviewSidePanel`. Do not create a bespoke panel system or place a permanent Goal container in `app.py`.

Follow the existing Reup mechanics exactly:

1. Import and store `self._goal_panel: GoalSidePanel | None` in `ReupApp`, as it already does for Commands, Hooks, and Change Review.
2. Add `_goal_panel_is_open()`, `_toggle_goal_panel()`, `_show_goal_panel()`, `_hide_goal_panel()`, and `_refresh_goal_panel()` to `_panels.py`.
3. `_show_goal_panel()` mounts `GoalSidePanel(id="goal-panel")` on `self.screen`; `_hide_goal_panel()` removes it safely and restores prompt focus through `_maybe_focus_prompt()`.
4. Opening Goal deterministically closes Commands, Hooks, Change Review, and the thread switcher first. These are mutually exclusive split panels in the same limited terminal canvas; never allow overlapping right-side operational panels. Opening any of those panels must likewise hide Goal.
5. Add a compact `#goal-toggle` `Button` beside `#plan-badge` in `#header-meta-group`, update its label/state from `refresh_header()`, and handle `Button.Pressed` in `_panels.py`. It launches the panel only.
6. Let `GoalSidePanel` emit typed action messages (`PauseRequested`, `ResumeRequested`, `EditRequested`, `EditSaved`, `ClearRequested`, `CloseRequested`). Reup routes each to `GoalLifecycleController`; after a successful state transition, it invokes one shared refresh path for session snapshot, header badge, panel contents, composer metadata, and remote broadcast.

The current split-panel styles establish the placement: `HooksSidePanel` and `ChangeReviewSidePanel` split right; Commands and thread navigation split left. Goal belongs on the right with Hooks/Changes because it explains and controls current work. Start with the Hooks width constraints (`38%`, `min-width: 42`, `max-width: 72`) and tune from real terminal screenshots—not guessed browser breakpoints. At a size where a right split would violate the conversation shell's usable minimum, push a full-screen `GoalModal`/overlay that reuses the very same `GoalSidePanel` content and messages. It is a constrained fallback, not a second feature surface.

#### Panel widget structure, interaction, and styling

Make the critical structure explicit in the widget tree before applying TCSS:

```text
GoalSidePanel (#goal-panel, split:right)
├── header: title + status/timer metadata + Close
├── Scrollable body
│   ├── objective block
│   ├── state/detail block (next action, blocker, or usage reset)
│   ├── action row (Pause|Resume, Edit, Clear)
│   ├── compact metric rail
│   ├── todos
│   └── activity/evidence feed
└── inline edit state (objective editor + Save + Cancel; replaces body focus when active)
```

Use `Static`, `Horizontal`, `Vertical`, and `ScrollableContainer` in the same style as the existing panels. Keep button handlers narrow: Close may call the Reup hide helper; all lifecycle buttons post a typed message upward. Do not make the widget reach into the session, active task, or command registry.

Style `#goal-panel` as a quiet `$surface` right split with compact padding, a single subtle left boundary only where a true panel frame needs it, and a one-row header. Use the active Textual theme tokens already used by Hooks/Changes. State color is semantic and restrained: success/primary for active, muted for paused, warning for blocked/budget, and no decorative color multiplication. Prefer spacing, background shifts, aligned metadata, and bold sparingly over nested cards and separator lines. Keep activity rows compact and scrollable; do not turn each event into a bordered card.

This conforms to `DESIGN.md`: the top bar remains identity/status rather than a toolbar; every terminal row earns its space; the feed stays open; important layout behavior is encoded as widgets first; and theme tokens, not a hard-coded Goal palette, own rendering.

#### Concurrency and refresh rules

Panel actions are valid during a running turn, but must be serialized with continuation dispatch:

1. **Pause:** atomically mark a non-persisted `pause_requested`/continuation-suppression flag, cancel the active agent task using the existing turn-cancellation path, await its cleanup, transition to `paused`, autosave, then refresh UI. A cancellation cannot race a queued goal continuation.
2. **Resume:** clear suppression and place one goal-continuation candidate behind the existing queued-payload precedence. The safe continuation gate—not the panel click—decides when it can dispatch.
3. **Edit:** when active, `Pause and edit` settles the active turn first; saving the new objective invalidates completion freshness, records an edit event, and leaves the goal paused until the user chooses Resume. This never lets a stale in-flight prompt finish under changed instructions.
4. **Clear:** show confirmation; on approval, use the same pause-and-settle path if necessary, append the historical summary, clear current state, autosave, hide/refresh the panel, and remove the badge.

Use the existing interval model for live display (`set_interval`) but render the timer from monotonic timestamps. Start the lightweight goal-display tick only while an active goal exists or the panel is open. It updates in-memory widgets only; persistence remains lifecycle/turn-boundary based.

### Local remote companion

Extend `_build_remote_runtime_state()` and `HeadlessRuntimeHost.build_state()` to serialize a compact `goal` payload:

```json
{
  "status": "active",
  "objective": "…",
  "elapsedActiveSeconds": 720,
  "workElapsedSeconds": 510,
  "metrics": { "modelRounds": 8, "toolCallsSucceeded": 14 },
  "blocker": null,
  "budgetDetails": null
}
```

The mobile client can initially render this read-only. A later mobile slice should add pause/resume/edit/clear remote actions. Do not advertise full remote lifecycle controls until both `ite_remote` and the runtime protocol support them.

### Headless cloud runtime

The command registry must recognize `/goal`, and its runtime host must start the first work turn after successful creation. Avoid implementing this as a Reup-only special case; otherwise mobile/headless `/goal` would mutate state but never execute.

Persisted thread restoration is currently a Reup capability. Make the headless-host persistence decision explicit during implementation: either add session snapshots there or surface that an interrupted cloud-host goal is resumable only while its host process survives. The recommended result is parity through shared snapshot orchestration, but it is a separate deliverable from local Reup MVP.

## 9. Implementation Phases

### Phase 0 — Foundation and tests first

1. Add `GoalStatus`, `GoalState`, `GoalMetrics`, event ledger, duration helpers, and unit tests.
2. Add optional snapshot fields and backward-compatible restoration tests.
3. Add `Session` goal lifecycle methods: create, pause, resume, update, block, budget-limit, complete, clear, and snapshot/history export.
4. Add a single `GoalLifecycleController` API used by every caller, including explicit transitional guards for `pause_requested` and in-flight work.

**Exit criteria:** legacy session JSON loads unchanged; goal metrics survive save/load; elapsed time excludes paused/offline time.

### Phase 1 — Command and agent contract

1. Add `src/ite/commands/goal.py` and registry registration.
2. Add native Reup `/goal` routing so creation starts the first work turn rather than only printing command output.
3. Add `goal_outcome` tool and state binding; include it in the default registry.
4. Add active-goal prompt section and continuation prompt.
5. Make `Agent._agentic_loop()` goal-aware: no `max_turns` terminal condition for active goals; retain all non-count safety stops.
6. Route `/goal pause`, `/goal resume`, `/goal edit`, and `/goal clear` through `GoalLifecycleController`, not separate command-local state transitions.

**Exit criteria:** `/goal` creates a persistent goal, starts work, completion requires evidence, and normal prompts still retain `max_turns` behavior.

### Phase 2 — Safe continuation and lifecycle transitions

1. Implement a single continuation gate after final agent events/turn cleanup.
2. Respect queued user messages, approvals, shell input, plan questions, subagents, errors, cancellations, compaction recovery, and session changes.
3. Record work/tool/verification metrics from existing agent events.
4. Convert quota failures into `budget_limited`; convert genuine model-reported blockers into `blocked`.
5. Pause and save active goals during clean app shutdown/cancellation.

**Exit criteria:** goals continue only at safe boundaries; they never spin after no-progress text; quota errors stop rather than retry; shutdown/restart behavior is honest.

### Phase 3 — Reup UX

1. Add the header Goal badge and one-second derived display timer, keeping the header status-only.
2. Build `GoalSidePanel` in `widgets/side_panels.py`; add the standard `_show/_hide/_toggle/_refresh` integration in `_panels.py`, the `ReupApp` panel attribute, panel exclusivity, and theme rerender support.
3. Wire every panel action to the shared lifecycle controller, including pause/cancel ordering, resume through the safe gate, inline edit, and destructive-clear confirmation.
4. Add the full-screen/modal fallback only for terminals too narrow to support a useful split panel; reuse the same content/messages.
5. Integrate goal information into `/stats` and `/workboard` while keeping the existing Plan UI distinct.

**Exit criteria:** an active goal is impossible to miss, timer counts accurately while active, a user can complete every lifecycle action from the panel during a turn, and panel/slash actions produce indistinguishable lifecycle results.

### Phase 4 — Remote parity and release hardening

1. Add the compact goal payload to local remote and headless runtime state.
2. Add protocol/client controls only once their callbacks and cancellation semantics are fully defined.
3. Update documentation and command palette descriptions.
4. Run full regression, manual long-running smoke tests, and provider quota simulations.

**Exit criteria:** remote state reflects goal progress accurately; unsupported remote controls are visibly unavailable rather than silently ignored.

## 10. Test Plan

### Unit

- all lifecycle transitions and invalid transitions;
- duration accumulation with `monotonic()` values;
- snapshot round trip and old snapshot compatibility;
- bounded event ledger;
- goal command parsing/validation/update protection;
- completion request without evidence is rejected;
- quota/rate-limit error classification;
- continuation gate decisions for each pending-work condition.

### Agent/runtime integration

- goal exceeds normal `max_turns` without `Maximum turns` error;
- normal request still stops at `max_turns`;
- no-tool continuation becomes blocked and does not spin;
- a completion tool call with evidence completes and saves;
- tool progress increases metrics and verification failures remain active;
- compaction followed by goal continuation does not duplicate a user message;
- cancel/pause stops current work and prevents a queued continuation;
- session switch never dispatches a goal continuation into another session;
- bundled quota exhaustion transitions to `budget_limited` with reset information.

### Textual/Reup

- active/paused/blocked/budget-limited header badge rendering;
- count-up display updates without persisting every tick;
- Goal panel mounts, closes, restores focus, and is mutually exclusive with existing split panels;
- each button emits its typed request and reaches the same lifecycle-controller method as its slash-command equivalent;
- Pause/Edit/Clear invoked while a turn is active cannot race turn cleanup or enqueue a continuation;
- inline panel edit validation, Save/Cancel focus behavior, and Clear confirmation;
- keyboard focus/order and activation for every panel control;
- normal, compact, and narrow terminal layout including the full-screen fallback;
- restored goal appears correctly after session resume;
- header, side panel, optional composer hint, and remote state agree on metrics/state;
- visual checks across supported themes: no hard-coded palette, clipped action rows, border-heavy cards, or a crowded top bar.

### Remote/headless

- slash command changes state and begins work;
- remote-state payload includes compact goal state;
- cancel/pause serializes a truthful stopped state;
- unavailable remote controls fail explicitly.

Run at least:

```bash
pytest tests/test_session_manager.py tests/test_remote_commands.py tests/test_reup_command_palette.py
pytest
ruff check .
mypy src/ite
```

If backend code is ever added, run from `../ite-cloud-api`:

```bash
npm test
npm run typecheck
npm run build
```

## 11. Acceptance Scenarios

1. A user runs `/goal Make the full test suite pass without changing public APIs. Verify with pytest.` iTE begins work, the header shows `Goal • 0m`, and the panel shows live work metrics.
2. The model fixes one failure and reports status. The goal remains active and iTE safely queues the next investigation instead of waiting for “continue.”
3. The model stops with only prose and no new tool/evidence. iTE marks the goal `needs input` rather than issuing unbounded follow-ups.
4. A test passes and the model records it as completion evidence. iTE marks the goal completed and stops automatically.
5. The bundled provider returns `quota_exhausted`. iTE saves `budget_limited`, displays the reset/provider-switch guidance, and makes no automatic retry.
6. While iTE is working, the user clicks `Goal • 12m`, presses `Pause`, and sees work settle into `paused` without typing in the composer or allowing another continuation. They can then edit the objective inline, resume it, or clear it with confirmation; each outcome matches the equivalent `/goal` command.
7. The user pauses or exits iTE. The timer stops; reopening the session shows a paused, resumable goal with its history and elapsed work.

## 12. Key Risks and Guardrails

| Risk | Guardrail |
| --- | --- |
| Infinite autonomous loop | Event-driven continuation, no-progress stop, loop detector, explicit user controls. |
| False completion | Evidence-required outcome tool plus recorded proof. |
| Bypassing approvals | Reuse existing tool registry, sandbox, and approval manager unchanged. |
| Misleading elapsed time after crash | Persist completed intervals; restore unexpected active sessions as paused. |
| Duplicate continuation after compaction or retry | One authoritative continuation gate and one queued payload precedence order. |
| Remote behavior diverges | Share state serialization and command controller; make unsupported controls explicit. |
| Goal data bloats snapshots/context | Bounded event ledger and compact prompt summary only. |
| Panel and slash commands drift | Both are thin input adapters over `GoalLifecycleController`; test identical transitions, audit events, and UI refreshes. |
| Click action races a running turn | Suppress continuation before cancellation; serialize pause/edit/clear with turn cleanup; only the safe gate may dispatch the next turn. |
| Panel crowds or visually fragments the terminal | Reuse right-side split-panel constraints, close competing panels, use a narrow full-screen fallback, and follow `DESIGN.md`'s no-line/low-chrome rules. |

## 13. Decisions Already Made

- Goal scope is one session/thread, not global memory or workspace config.
- Goals have no arbitrary max-turn cap. Existing subagent limits remain.
- The first timer is per-goal elapsed active time, backed by real per-turn work accounting.
- Quota handling uses the existing API contract; no backend modification is needed for MVP.
- Plan mode and Goal mode are complementary: plan shapes the work; goal persists execution toward verified completion.
- No files, worktrees, permissions, or tool scope become broader because a goal is active.
- The Goal panel is the primary click-based lifecycle surface. `/goal` commands and panel controls have full parity through one controller; no control action depends on the composer.
- Goal is a right-side operational panel and is mutually exclusive with existing split panels; the top bar holds only its compact status launcher.

## 14. Deferred Decisions

- Whether completed/cleared goal summaries remain indefinitely in session JSON or are capped by age/count.
- Full remote/mobile lifecycle controls and background-host persistence.
- Cross-device goal history/analytics through `ite-cloud-api`.
- Optional user-selected per-goal spend/time budgets. The default remains “run until verified completion, blocker, pause, cancellation, or provider usage exhaustion.”
