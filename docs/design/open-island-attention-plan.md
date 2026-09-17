# Open Island — User-Attention Round Trip (Approvals + Questions)

**Status:** Implemented (unit-tested) — live verification pending (§9 rows 1–8, 13)
**Scope:** Bidirectional. iTE must *send* the blocking request and *consume* the user's answer. No changes to Open Island.
**Depends on:** the emit-side bridge already shipped (`docs/design/open-island-ite-bridge-plan.md`)
**Reference clone:** `open-vibe-island/` @ `b50f87a` (v1.2.1) — **GPLv3, clean-room only** (see the bridge plan §12). This document reads the clone to learn the wire contract. No Swift may be copied into `ite-agent`.

---

## 0. How to read this document

Section 3 is the upstream contract **as verified by reading source**, with file:line for every claim. Sections 5–7 are the design. Section 11 lists what still needs empirical confirmation — treat those as blockers on the corresponding step, not as trivia.

The finding that shapes everything else is §3.5: **upstream clears a stale approval card automatically** on the next hook event for that session. That removes an entire class of cancellation work.

---

## 1. Objective

Today the island is a one-way mirror. When iTE needs the user — a destructive tool awaiting approval, or `plan_question` awaiting an answer — the island shows nothing useful. The row flips to "Running" and stays there, because `TOOL_CALL_START` is emitted *before* the tool executes (`agent.py:2121` precedes `invoke` at `:2143`) and the block happens inside `invoke` (`tools/registry.py:300-301`). The user only discovers the block by switching to the terminal.

**Goal:** when iTE blocks on user attention, the notch surfaces it, and the user can resolve it from the notch without switching apps.

**In scope:**

1. Tool approvals requiring confirmation (`ApprovalDecision.NEEDS_CONFIRMATION` → `request_confirmation`).
2. Agent questions (`plan_question` tool → `plan_question_callback`), answered from the notch.
3. *(Decision point — §5.9)* Plan-ready confirmation ("implement plan?").

**Out of scope:**

- Changing any existing TUI behaviour. The local modal remains the primary, always-available path.
- The "Always Allow" persistent-rule feature. Explicitly hidden (§5.7).
- Forking Open Island.
- Non-macOS. The integration is already macOS-gated.

### Success criteria

1. Trigger a tool that needs approval → the notch opens the session list, the row is actionable, and Allow/Deny are offered.
2. Click Allow → the tool executes; the iTE TUI does **not** also wait on its modal.
3. Click Deny → the tool does not execute and the agent is told the operation was declined.
4. Answer a `plan_question` from the notch → the agent receives the chosen option (or free text).
5. With Open Island stopped, every path behaves **exactly** as today: local modal only, no added latency, no errors.
6. With the integration disabled, zero socket attempts.
7. The "Always Allow" button is not rendered.

---

## 2. Locked decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Scope = anything requiring user attention**: approvals + plan questions | User directive |
| 2 | **Additive only.** Do not alter existing TUI approval/question behaviour; add the island as an additional option | User directive: "don't break what works already" |
| 3 | **Hide "Always Allow"** | User directive: no rule engine exists behind it today |
| 4 | Local modal stays primary; island is a *racer*, not a replacement | Follows from #2; also the safe default if the island is absent or wedged |

### Consequence of #2 that must be respected

Existing behaviour includes the TUI switching to the active thread when an approval arrives (`_turn.py:542-547`, `_confirmation_callback_for_session`). **Leave it alone.** If the island answers, the thread switch is harmless but pointless; suppressing it would be a behaviour change and is out of scope. Document it as a known, accepted rough edge.

---

## 3. Upstream contract — verified

All line references are in `open-vibe-island/` at the reference commit.

### 3.1 Commands and responses

Client → server (`BridgeTransport.swift`):

| Case | Line | Shape |
|---|---|---|
| `resolvePermission(sessionID:resolution:)` | `:85` | `{"type":"resolvePermission","sessionID":…,"resolution":…}` |
| `answerQuestion(sessionID:response:)` | `:86` | `{"type":"answerQuestion","sessionID":…,"response":…}` |

Server → client (`BridgeResponse`):

| Case | Line | Meaning |
|---|---|---|
| `claudeHookDirective(ClaudeHookDirective)` | `:211` | the answer to a parked `PermissionRequest` |
| `acknowledged` | `:209` | generic ack |

`CommandType.answerQuestion` / `.resolvePermission` encode/decode at `:137-146` and `:175-181`.

### 3.2 Types (`AgentSession.swift`)

```swift
enum PermissionResolution {                                  // :359-361
    case allowOnce(updatedInput: ClaudeHookJSONValue? = nil,
                   updatedPermissions: [ClaudePermissionUpdate] = [])
    case deny(message: String? = nil, interrupt: Bool = false)
}

struct QuestionPromptResponse {                              // :313-326
    var rawAnswer: String?
    var answers: [String: String]        // keyed by QUESTION TEXT
    var annotations: [String: QuestionAnswerAnnotation]
    init(answer: String)                 // convenience: sets rawAnswer only
}

struct QuestionOption     { label, description, allowsFreeform }       // :234-252
struct QuestionPromptItem { question, header, options, multiSelect }   // :254-271
struct QuestionPrompt     { id, title, options: [String], questions }  // :273-301
```

### 3.3 Permission flow — full trace

**Request side.** A `PermissionRequest` hook payload triggers (`BridgeServer.swift:~740-777`):

```swift
.permissionRequested(PermissionRequest(
    title:                payload.permissionRequestTitle,
    summary:              payload.permissionRequestSummary,
    affectedPath:         payload.permissionAffectedPath,
    primaryActionTitle:   "Allow Once",
    secondaryActionTitle: "Deny",
    toolName:             payload.toolName,          // ← controls the Always-Allow button
    toolUseID:            claudeToolUseID(for: payload),
    suggestedUpdates:     suggestions))
```

then **parks the connection** (`:773-776`):

```swift
pendingClaudeInteractions[payload.sessionID] = PendingClaudeInteraction(
    clientID: clientID, kind: .permission(payload))
```

**Resolution side** (`BridgeServer.swift:~410-436`): emits an `activityUpdated` with an allow/deny summary, calls `resolvePendingApproval(sessionID:resolution:)`, then `send(.response(.acknowledged), to: clientID)`.

**Direction of the reply.** The directive goes to `pendingInteraction.clientID` — i.e. **the same socket the request arrived on**. So the requesting connection must stay open and keep reading. This is why the interactive path cannot reuse the fire-and-forget worker.

**Keying.** `pendingClaudeInteractions` is keyed by `sessionID` **alone** (`:773`). The correlation key `sessionID|toolName|serializedToolInput` (`ClaudeHooks.swift:806-809`) only feeds `claudeToolUseID(for:)` (`:3056-3058`), which prefers `payload.toolUseID`. **Consequence: a correlation mismatch is cosmetic, not functional.** Still, send `tool_use_id` explicitly to keep the tool-use badge correct.

### 3.4 Question flow — full trace

**Request side.** `ClaudeHookPayload.questionPrompt` (`ClaudeHooks.swift:822-879`) requires *all* of:

- `tool_name == "AskUserQuestion"`
- `tool_input.questions` is an array
- each question has `question` (string), `header` (string), and a non-empty `options` array
- each option has `label` (string); `description` optional

Upstream then appends `QuestionOption(label: "Other", allowsFreeform: true)` to every question (`:854-857`) and uses the question text as the prompt title when there is exactly one question (`:871-876`).

**Resolution side** — `resolvePendingClaudeQuestion` (`BridgeServer.swift:3014-3054`):

```swift
let updatedInput = mergedClaudeQuestionInput(payload:payload, prompt:prompt, response:response)
emit(.activityUpdated(...))
send(.response(.claudeHookDirective(.permissionRequest(.allow(updatedInput: updatedInput)))),
     to: pendingInteraction.clientID)
```

**Note the directive kind: a question answer comes back as `.permissionRequest(.allow(updatedInput:))` — not a distinct "answer" directive.** Our client must therefore branch on *what request it sent*, not on the directive shape.

`mergedClaudeQuestionInput` (`:3060-3107`):

```swift
var answers = response.answers
if answers.isEmpty, let rawAnswer = response.rawAnswer, !rawAnswer.isEmpty,
   let fallbackQuestion = prompt.questions.first?.question {
    answers[fallbackQuestion] = rawAnswer
}
// merges into the ORIGINAL tool_input object:
updatedObject["answers"] = .object(answers.mapValues { .string($0) })
// plus updatedObject["annotations"] when annotations were supplied
```

**Consequences for us:**

- `QuestionPromptResponse(answer:)` (rawAnswer only) is sufficient for our single-question case — upstream folds it into `answers[<question text>]`.
- To recover the answer: read `updatedInput.answers` and look up our question text. If the value matches one of our option labels → `selected_option`; otherwise it is free text → `free_text`.
- `updatedInput` is the **full original `tool_input`** with `answers` merged in, so the lookup key is the exact question string we sent.

### 3.5 Stale-interaction auto-clear — the finding that saves the design

`clearStaleClaudeInteractionIfNeeded` (`BridgeServer.swift:2250-2264`):

```swift
guard pendingClaudeInteractions.removeValue(forKey: sessionID) != nil else { return }
emit(.actionableStateResolved(ActionableStateResolved(
    sessionID: sessionID,
    summary: "Approval was handled outside Open Island.",
    timestamp: .now)))
```

It is called at the **top of** every subsequent hook case for that session:

| Case | Line |
|---|---|
| `postToolUse` | `:780` |
| `postToolUseFailure` | `:827` |
| `permissionDenied` | `:846` |
| `stop` | `:889` |
| `stopFailure` | `:911` |
| (plus `:647`, `:667`, `:1013`) | |

**Therefore:** if the user answers in the iTE TUI instead, the island's card is cleared automatically by the next event we emit — and there *always* is one, because the tool only runs *after* the TUI approval resolves, producing `PostToolUse` (approve) or `PostToolUseFailure` (deny).

**Design consequence:** no explicit cancellation command is required. We only need to stop *our* socket read from hanging. That is a local `task.cancel()`, nothing on the wire.

**Residual gap (accepted):** between the TUI answer and the next hook event, the island may briefly show a stale card. With a long-running approved tool that window could be minutes. Mitigation if it looks bad in practice: on local-wins, send `resolvePermission` on a fresh connection to clear immediately. Do not build that unless §9 verification shows it is needed.

### 3.6 UI rendering, and the Always-Allow lever

**Auto-surface.** `IslandSurface.notificationSurface(for:)` (`IslandSurface.swift:23-34`) maps both `permissionRequested` and `questionAsked` to `.sessionList(actionableSessionID:)`. So the notch opens the list and marks the row — this is what fixes "I didn't even know it had blocked."

**Action body is chosen by phase** (`IslandPanelView.swift:1648-1660`):

```
.waitingForApproval → approvalActionBody   // :1714-1762
.waitingForAnswer   → questionActionBody   // :1766-1772
.completed          → completionActionBody
```

**`approvalActionBody` (`:1714-1762`)** renders:

- header `approval.toolPermissionRequested`
- `commandPreviewText` (falls back through `session.currentCommandPreviewText` → `permissionRequest.summary` → `session.summary`, `:1890-1896`)
- optional `session.permissionRequest?.affectedPath` (`:1726-1732`)
- buttons: `Deny` (secondary), `Allow Once` (warning), and — **only when a tool name is present**:

```swift
if let toolName = session.permissionRequest?.toolName {          // :1748
    Button(lang.t("approval.alwaysAllow", toolName)) { … }        // :1749-1759
}
```

**`questionActionBody` (`:1766-1772`)** renders `StructuredQuestionPromptView(prompt:onAnswer:)`. **It has no Always-Allow button at all.**

**The lever for decision #3:**

| Surface | Always-Allow shown? | How to hide |
|---|---|---|
| Permission card | yes, when `toolName != nil` | **omit `tool_name` from the `PermissionRequest` payload** |
| Question card | never — different view | nothing to do |

Since a question payload *must* carry `tool_name == "AskUserQuestion"` (§3.4), and questions never render the button anyway, omitting `tool_name` applies only to permission payloads. Send `tool_use_id` explicitly so the tool-use badge survives (§3.3).

**App-side resolution** (`AppModel.swift`), for reference on what the two buttons send:

```swift
approvePermission(for:action:)     // :1432-1461
    .deny             → .deny(message: "Permission denied in Open Island.", interrupt: false)
    .allowOnce        → .allowOnce()
    .allowWithUpdates → .allowOnce(updatedPermissions: updates)
answerQuestion(for:response:)       // :1469+ → QuestionPromptResponse(answer: …)
```

---

## 4. iTE-side current state

| Fact | Location |
|---|---|
| `Agent` wires `confirmation_callback` onto the approval manager, stores `plan_question_callback`, builds the bridge | `agent/agent.py:78-129` |
| `_build_open_island_bridge` appends `bridge.observe` to `_event_observers` | `agent/agent.py:94`, `:117-126` |
| `observe()` only enqueues; all I/O on a background worker (invariant #2) | `integrations/open_island/bridge.py:125-138`, `:199-214` |
| Approval decision raised inside tool execution | `tools/registry.py:249-262`; `request_confirmation` at `:301` |
| `TOOL_CALL_START` emitted **before** `invoke` | `agent/agent.py:2121` vs `:2143` |
| `_commands_for` maps no attention-related event | `integrations/open_island/bridge.py:297-318` |
| TUI approval racer (local modal + remote + telegram) | `ui/reup/_turn.py:2327-2428` |
| TUI question racer | `ui/reup/_composer.py:2200-2244` (entered from `_turn.py:2447`) |
| Local question card: `options: list[str]`, `recommended_index`, `allow_free_text`; returns `{selected_option, free_text, selected_index}` | `ui/reup/_composer.py:2125-2197` |
| Reference out-of-process approval + question round trip | `remote/host.py:645-703` |
| ~~`Agent.__aexit__` never calls `bridge.aclose()`~~ — **fixed** | `agent/agent.py:2453-2464` |
| Client: `send`/`try_send` open a fresh AF_UNIX connection per command and read until the first non-`hello` envelope; `default_timeout = 5.0` | `integrations/open_island/client.py:64-197` |

**Why nothing shows today:** approval blocks inside `invoke`, which the bridge never observes. The island sees a live tool and keeps the row "Running" indefinitely.

---

## 5. Design

### 5.1 Architecture

```
tools/registry.py  ──needs confirmation──►  approval_manager
                                                │
                                          confirmation_callback  (UI, _turn.py)
                                                │
                      ┌─────────────────────────┼─────────────────────────┐
                      ▼                         ▼                         ▼
              local ConfirmModal        remote server              Open Island   ← NEW
                      │                         │                         │
                      └───────── asyncio.wait(FIRST_COMPLETED) ───────────┘
                                                │
                                          decision → tool runs or is declined
```

The island is a **fourth racer** in two places that already race: `confirmation_callback` and the plan-question path. Nothing about the existing racers changes.

### 5.2 Client — a genuinely blocking exchange

`send()` cannot be used as-is for a long park: `default_timeout = 5.0`.

Add to `OpenIslandClient`:

```python
async def send_interactive(self, command, *, timeout: float) -> dict[str, Any] | None
```

Semantics: identical to `send()` but intended to be parked for a long time and **cancelled by the caller**. It must not swallow `asyncio.CancelledError`. Fail-open remains: connection refused / stale socket → `OpenIslandBridgeError` → caller treats as "island unavailable" and lets the local modal win.

Also add a payload builder in `payloads.py`:

```python
def permission_request(session_id, cwd, *, title, summary, affected_path,
                       tool_use_id, terminal) -> dict[str, Any]
```

which deliberately **omits `tool_name`** (§5.7) and sets `hook_event_name: "PermissionRequest"`.

### 5.3 Bridge — interactive methods

The bridge gains two async methods that **bypass the worker queue entirely**:

```python
async def request_approval(self, *, title, summary, affected_path,
                           tool_use_id, timeout) -> str
async def request_question(self, *, question, options, recommended_index,
                           allow_free_text, timeout) -> dict[str, Any] | None
```

Why bypass: invariant #2 ("`observe` only enqueues; the agent turn is never delayed") exists for *lifecycle* events. Here delay is the point. The method runs as its own task; the worker keeps draining normally so the island stays live while the user decides.

Return values are normalized, never exceptions:

```python
# request_approval
"approved" | "denied" | "unavailable"
```

`"unavailable"` covers: disabled, socket dead, malformed reply, timeout — i.e. "let the local modal be the only racer."

**Ordering requirement (must be honoured).** `PreToolUse` must reach the server *before* the `PermissionRequest`, both for tool-use correlation and so the row already shows the tool. `PreToolUse` is enqueued normally at `TOOL_CALL_START`. The interactive method must therefore `await self._queue.join()` (bounded) before opening its exchange. `aclose` already uses this pattern (`bridge.py:150`).

### 5.4 Wiring — UI side

The callbacks are supplied by the UI, and the UI already holds `self.agent`. Expose the bridge:

```python
# agent/agent.py
@property
def open_island_bridge(self) -> OpenIslandBridge | None:
    return self._open_island_bridge  # type: ignore[return-value]
```

In `confirmation_callback` (`_turn.py:2327`), add a fourth task alongside the existing racers, guarded to *fail silently* when the bridge is `None`/disabled:

```python
island_task = None
bridge = getattr(self.agent, "open_island_bridge", None)
if bridge is not None and bridge.enabled:
    island_task = asyncio.create_task(
        bridge.request_approval(
            title=f"Approval required: {confirmation.tool_name}",
            summary=confirmation.description,
            affected_path=(confirmation.affected_paths or [None])[0],
            tool_use_id=...,          # see §5.5
            timeout=_ISLAND_ATTENTION_TIMEOUT_SECONDS,
        )
    )
```

Then include it in the existing `FIRST_COMPLETED` wait, and **cancel every losing task** (including the island task) once a winner is determined. Cancelling the island task closes its socket; the island clears its own card on the next hook event (§3.5).

Same shape for `_present_plan_question_with_remote` (`_composer.py:2200-2244`), racing `bridge.request_question(...)`.

**Timeout:** a module constant, e.g. `_ISLAND_ATTENTION_TIMEOUT_SECONDS = 600.0`. Long enough that the local modal effectively decides, short enough to bound resource use. Upstream parks indefinitely (its own CLI allows 24h), so this is purely our own ceiling.

### 5.5 Where does `tool_use_id` come from?

`confirmation` (`ToolConfirmation`) carries `tool_name`, `description`, `command`, `diff`, `affected_paths` — **not** the call id. The bridge already sees `TOOL_CALL_START` with `call_id` but currently does **not** cache it (the bridge plan §3.10 removed the cache deliberately).

Two options:

- **(A)** Bridge caches `tool_name → call_id` from the last `TOOL_CALL_START`. Small, self-contained, and makes the interactive call independent of the confirmation object.
- **(B)** Thread `call_id` through `ToolConfirmation`. Wider blast radius, touches the safety layer.

**Recommendation: (A)** — the bridge already owns `_tools_in_flight` bookkeeping; a companion `_last_call_id_by_tool` dict is a two-line addition and keeps the safety layer untouched (respects decision #2).

If absent, omit `tool_use_id`. The correlation key mismatch is cosmetic (§3.3) — confirmed safe.

### 5.6 Cancellation and fail-open semantics

| Situation | Behaviour |
|---|---|
| Island disabled / not running | `request_approval` returns `"unavailable"` immediately (connect fails). Local modal unaffected. |
| User answers in the island | Local modal task cancelled, island directive applied. |
| User answers in the TUI | Island task cancelled; island clears its card on the next hook event. |
| User answers on mobile/Telegram | Same as TUI. |
| Nothing ever answers | Both racers stay pending — identical to today. |
| Socket dies mid-park | `OpenIslandBridgeError` → `"unavailable"`; local modal still pending. |
| Timeout | `"unavailable"`; local modal still pending. |
| Turn cancelled while parked | Task cancelled; `CancelledError` propagates; nothing sent on the wire. |

**Hard rule:** no path may convert an island failure into a refused approval. `"unavailable"` must mean "the island didn't answer", never "denied".

### 5.7 Hiding "Always Allow"

Send the permission payload **without `tool_name`**. Verified lever: `permissionRequest.toolName` is nil → the button's `if let` fails (`IslandPanelView.swift:1748`) → not rendered.

Two things to confirm live (§11):

1. That `permissionRequestTitle` / `permissionRequestSummary` / `permissionAffectedPath` still produce a sensible card with a nil tool name. If the title degrades, compensate by putting the tool name in the `summary` text we control.
2. That `toolUseID` still resolves via the explicit `tool_use_id` we send (`:3056-3058` — it prefers `payload.toolUseID`).

### 5.8 Question payload mapping

iTE `plan_question` gives `{question, options: list[str], recommended_index, allow_free_text, question_number}`. One question at a time. Map to:

```json
{
  "hook_event_name": "PermissionRequest",
  "session_id": "…",
  "cwd": "…",
  "tool_name": "AskUserQuestion",
  "tool_use_id": "…",
  "tool_input": {
    "questions": [{
      "question": "<iTE question text>",
      "header": "Plan question",
      "options": [{"label": "<option>", "description": ""}, …],
      "multiSelect": false
    }]
  }
}
```

- `tool_name` is **mandatory** here — upstream returns `nil` from `questionPrompt` otherwise, and the card falls through to `approvalActionBody` (which would render Deny/Allow Once for a question). This is the single most important detail on this path.
- `header` is **mandatory** (upstream's `compactMap` drops any question without it) — iTE has no equivalent, so supply a constant.
- `recommended_index` → set that option's `description` to `"Recommended"`. *Verify `StructuredQuestionPromptView` renders `description`* (§11); if it does not, the fallback is to append `" (recommended)"` to the label.
- `allow_free_text` → upstream **always** appends an `Other` freeform option, so free text is available regardless. When iTE says `allow_free_text = false` and the user picks `Other`, we receive typed text we must handle: treat it as `free_text` and let the plan-question tool decide, or blank it. **Open question (§11).**

**Answer mapping back.** From the directive's `updatedInput.answers`, look up by our exact question string:

```
value == one of our option labels  → {"selected_option": value, "free_text": "", "selected_index": idx}
otherwise                          → {"selected_option": "", "free_text": value, "selected_index": None}
```

Return the same dict shape the local card returns (`_composer.py:2125-2197`) so the caller is racer-agnostic.

### 5.9 Decision point — plan-ready confirmation

`_present_plan_ready_with_remote` (`_turn.py:2256-2282`, entered on `PLAN_READY`) blocks on "implement this plan?" — genuinely user attention.

It could ride the same permission machinery (`tool_name` omitted; title "Implement this plan?"; Allow → proceed, Deny → keep plan pending). But it is a different code path with different local options, and mapping "Deny" onto "save for refinement" needs a deliberate decision rather than a default.

**Recommendation:** land approvals + questions first (they share one mechanism), then add plan-ready as a follow-up slice once the racer pattern has been proven live. Do not bundle it into the first change.

---

## 6. Non-regression: TUI behaviour

The change is additive by construction — a new task inside an existing `FIRST_COMPLETED` race. The invariants to preserve, and how:

| Must not change | Guard |
|---|---|
| Local modal still appears and is focusable | Island task is only *added* to the race; the local task is created first and unchanged |
| Agent never blocked by an absent island | Connect failure returns `"unavailable"` immediately; no await on a dead socket |
| `observe()` never blocks | Interactive methods never touch the queue except a bounded `join()` before sending |
| No new errors when island absent | Every failure path returns a sentinel, never raises |
| Thread switching still works | Untouched (§2) |
| `plan_question` local card unchanged | Same racer pattern; same return dict shape |

**Regression test target:** run the full approval and question flows with `OPEN_ISLAND_SKIP_HOOKS=1` and assert behaviour matches today (timings aside).

---

## 7. Files to touch

| File | Change |
|---|---|
| `src/ite/integrations/open_island/client.py` | add `send_interactive()` |
| `src/ite/integrations/open_island/payloads.py` | add `permission_request()`, `question_request()`, directive parsers |
| `src/ite/integrations/open_island/bridge.py` | add `request_approval()`, `request_question()`, `_last_call_id_by_tool`, queue-drain helper |
| `src/ite/agent/agent.py` | expose `open_island_bridge`; call `bridge.aclose()` in `__aexit__` |
| `src/ite/ui/reup/_turn.py` | fourth racer in `confirmation_callback`; timeout constant |
| `src/ite/ui/reup/_composer.py` | fourth racer in `_present_plan_question_with_remote` |
| `tests/test_open_island_client.py` | interactive exchange, cancellation, long timeout |
| `tests/test_open_island_payloads.py` | permission/question payload shape, no `tool_name` on permissions, `AskUserQuestion` on questions, directive parsing |
| `tests/test_open_island_bridge.py` | `request_approval`/`request_question` outcomes, queue ordering, fail-open |
| `docs/design/open-island-ite-bridge-plan.md` | mark §8 (phase 2) as delivered; link here |

**Prerequisite fix, same change:** `Agent.__aexit__` must `await self._open_island_bridge.aclose()`. A leaked session that still shows Allow/Deny buttons is materially worse than a leaked summary line. This was flagged as a risk in the bridge plan and must land before the interactive path ships.

**No new config.** The existing `[integrations.open_island] enabled` gate covers this.

---

## 8. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | Interactive socket read hangs the approval path | High | Bounded timeout; cancellable task; connect failure short-circuits |
| 2 | `"unavailable"` misread as `"denied"` | High | Explicit tri-state return; unit test asserting no denial on island failure |
| 3 | `PreToolUse` not yet processed when `PermissionRequest` lands | Medium | `await queue.join()` before the exchange; live verify |
| 4 | Nil `tool_name` degrades the permission card title | Medium | Live check (§11); fallback = put tool name in our `summary` |
| 5 | Question falls through to the approval card (Deny/Allow Once for a question) | High | `tool_name` **must** be `AskUserQuestion` + `header` present; assert in tests |
| 6 | `Other` free-text returned when iTE disallows free text | Medium | Defined handling (§5.8); needs a decision |
| 7 | Stale island card after a TUI answer | Low | Self-clears (§3.5); optional immediate `resolvePermission` if visible in practice |
| 8 | Leaked session still offering Allow/Deny | High | `aclose()` prerequisite (§7) |
| 9 | Redundant thread switch when the island answers | Low | Accepted (§2) |
| 10 | Upstream protocol drift | Medium | All wire knowledge stays in `client.py`/`payloads.py`; tolerate unknown fields |

---

## 9. Verification plan

| # | Test | Method | Status |
|---|---|---|---|
| 1 | Approval appears in the notch | Live: force a confirmation-gated tool | **Passed (live)** — approval surfaced, approved from notch |
| 2 | Allow from the notch runs the tool | Live | **Passed (live)** — approved from notch, tool executed, local modal not used |
| 3 | Deny from the notch blocks the tool | Live | Pending |
| 4 | No Always-Allow button | Live screenshot; assert no `tool_name` on the wire | Payload-level covered (`test_permission_payload_omits_tool_name`); live pending |
| 5 | Question renders as a question card (options, not Allow/Deny) | Live | Payload-level covered (`test_question_request_requires_ask_user_question`); live pending |
| 6 | Question answer reaches the agent | Live; assert `selected_option`/`free_text` | Parse-level covered; live pending |
| 7 | TUI answer still clears the island card | Live: answer locally, observe `actionableStateResolved` | Pending |
| 8 | **Island absent** → identical behaviour, no delay | Kill Open Island, run the full flow, time it | Unit-covered (fail-open, sentinel returns); live timing pending |
| 9 | `OPEN_ISLAND_SKIP_HOOKS=1` → inert | Unit + live | Covered (existing `hooks_disabled` tests) |
| 10 | Stale socket mid-park → `"unavailable"`, no hang | Unit | Covered (`test_socket_failure_is_unavailable_not_denied`, `test_send_interactive_missing_socket_raises_bridge_error`) |
| 11 | Timeout → `"unavailable"` | Unit (short timeout) | Covered (client timeout → `OpenIslandBridgeError` → `"unavailable"`) |
| 12 | Task cancellation propagates `CancelledError` | Unit | Covered (`test_send_interactive_propagates_cancellation`) |
| 13 | Session teardown removes the card | Live after `aclose()` fix | `aclose()` landed; live pending |
| 14 | `pytest` + `ruff` + `mypy` clean | CI | Open Island suite green; new module `mypy`-clean. Repo-wide `ruff`/`mypy` are red from pre-existing mixin errors |

Tests 8 and 11 are the ones that decide whether this is safe to ship.

---

## 10. Implementation sequence

| Step | Deliverable | Gate | Status |
|---|---|---|---|
| 0 | `aclose()` in `Agent.__aexit__` | Test 13; prerequisite | Done |
| 1 | `client.send_interactive()` | Tests 10–12 | Done |
| 2 | Payload builders + parsers | Tests 4, 5 (payload-level), 6 (parse-level) | Done |
| 3 | `bridge.request_approval()` | Tests 1–3 live | Done (unit); live pending |
| 4 | Wire as fourth racer in `confirmation_callback` | Tests 2, 3, 8 live | Done; live pending |
| 5 | `bridge.request_question()` + `AskUserQuestion` mapping | Tests 5, 6 live | Done (unit); live pending |
| 6 | Wire as fourth racer in `_present_plan_question_with_remote` | Test 6 live | Done; live pending |
| 7 | Docs sweep; update the bridge plan's §8 | Test 14 | Done |

**Steps 0–4 are the minimum useful slice** — they solve the stated problem for approvals. Steps 5–6 extend it to questions, which decision #1 requires.

---

## 11. Must-verify before/while implementing

1. **Nil `tool_name` card quality.** Does the permission card still render a useful title/summary without it? (§5.7) — *Compensated in code*: `summary` carries the tool name and the command; confirm visually live.
2. **`tool_use_id` survives** with nil `tool_name`. (§5.7) — Needs live confirmation; unit tests pin that we send it.
3. **`StructuredQuestionPromptView` renders `QuestionOption.description`** — **Resolved: yes** (`IslandPanelView.swift:2230-2231`). `recommended_index` is carried as `"Recommended"` on that option.
4. **`Other` + `allow_free_text = False`** — Handled: free text is always available upstream, so a typed answer is returned as `free_text` and the plan-question tool decides. Not blanked.
5. **Does `await queue.join()` reliably order `PreToolUse` before the interactive send?** (§5.3) — Bounded drain implemented and unit-tested; needs live confirmation.
6. **Does the raw `hook_event_name` string `"PermissionRequest"` decode** into `ClaudeHookEventName.permissionRequest`? — **Resolved: yes** (`ClaudeHooks.swift:322`).
7. **Plan-ready confirmation**: in or out for this slice? (§5.9) — **Out.** Landed as the follow-up slice per §5.9.

---

## 12. Reference index

Upstream (read-only, GPLv3 — clean-room, do not copy):

| Concern | Location |
|---|---|
| Command enum | `Sources/OpenIslandCore/BridgeTransport.swift:82-123` |
| Response enum | `BridgeTransport.swift:205-265` |
| Resolution / question types | `Sources/OpenIslandCore/AgentSession.swift:234-361` |
| Permission request emission + park | `Sources/OpenIslandCore/BridgeServer.swift:~740-777` |
| `resolvePermission` handling | `BridgeServer.swift:~410-436` |
| `answerQuestion` handling | `BridgeServer.swift:438-464` |
| `resolvePendingClaudeQuestion` | `BridgeServer.swift:3014-3054` |
| `mergedClaudeQuestionInput` | `BridgeServer.swift:3060-3107` |
| Stale-interaction clear | `BridgeServer.swift:2250-2264` |
| Question prompt parsing | `Sources/OpenIslandCore/ClaudeHooks.swift:822-879` |
| Correlation key | `ClaudeHooks.swift:806-809` |
| Auto-surface on attention | `Sources/OpenIslandApp/IslandSurface.swift:23-34` |
| Approval action body + Always-Allow | `Sources/OpenIslandApp/Views/IslandPanelView.swift:1714-1762` |
| Question action body | `IslandPanelView.swift:1766-1772` |
| App-side resolution mapping | `Sources/OpenIslandApp/AppModel.swift:1432-1461`, `:1469+` |

iTE:

| Concern | Location |
|---|---|
| Bridge module | `src/ite/integrations/open_island/bridge.py` |
| Wire client | `src/ite/integrations/open_island/client.py` |
| Payload builders | `src/ite/integrations/open_island/payloads.py` |
| Terminal detection | `src/ite/integrations/open_island/terminal.py` |
| Agent bridge wiring | `src/ite/agent/agent.py:78-129`, `:2453-2464` |
| Tool approval path | `src/ite/tools/registry.py:249-320` |
| TUI approval racer | `src/ite/ui/reup/_turn.py:2327-2428` |
| TUI question racer | `src/ite/ui/reup/_composer.py:2200-2244` |
| Reference out-of-process round trip | `src/ite/remote/host.py:645-703` |
| Emit-side plan | `docs/design/open-island-ite-bridge-plan.md` |

---

## 13. Open questions (product/policy, need a decision)

1. Should a Deny from the notch also surface a notification back in iTE, or is the tool result sufficient?
2. Should the island be used at all when the TUI is focused and the modal is visible? (Possible follow-up: only race the island when the terminal is not frontmost.)
3. Plan-ready confirmation — include now or next slice? (§5.9)

