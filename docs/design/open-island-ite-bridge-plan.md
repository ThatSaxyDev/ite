# iTE → Open Island Bridge — Implementation Plan (iTE Half Only)

**Status:** Proposed
**Scope:** Emit-side integration in `ite-agent`. No changes to Open Island.
**Target:** Works with upstream Open Island as shipped (no fork required).
**Reference commit:** `open-vibe-island` @ `b50f87a` (v1.2.1)

---

## 1. Objective

Let any user who already runs [Open Island](https://github.com/Octane0411/open-vibe-island) see their `ite` sessions in the notch, with live activity, and click back into the right terminal — using the **stock, unmodified** Open Island app.

**Explicit accepted trade-off — corrected by live testing.** I originally predicted the notch would headline iTE sessions as "Claude Code". **That was wrong.** A live capture (§10.2) shows the row headline is the *workspace name* (derived from `cwd`), with a small `claude` tool badge alongside. So there is no embarrassing headline; the identity tell is a compact badge. Cosmetic only, and out of scope here — the fork removes it.

**Non-goal:** approvals-from-the-notch is *not* in the first slice. It is designed for in §8 and staged deliberately.

### Success criteria

A user with Open Island running and iTE open:

1. Sees an iTE session appear in the notch within ~1s of the first turn.
2. Sees the session summary update as iTE runs tools.
3. Sees the session clear when the turn ends / session closes.
4. Can click the session and land back in the correct terminal/tab.
5. Suffers **zero** behavioural change to iTE when Open Island is not running (fail-open).
6. Suffers zero change if they never enable the integration.

---

## 2. Why this works at all — the liveness question

The single most important thing verified, because it decides feasibility.

Open Island keeps Claude sessions alive using **process discovery** (`ps`) plus transcript scanning. iTE is a Python process named `ite` with no Claude-format transcript, so a naive integration risks the session being pruned seconds after it appears (upstream issue #510 describes exactly this).

**This is a non-issue for us.** The session is created as *hook-managed*, which short-circuits process polling:

| Step | Source | Effect |
|---|---|---|
| `handleClaudeHook` `.sessionStart` emits `SessionStarted(origin: .live, …)` | `BridgeServer.swift:646-664` | marks session as hook-originated |
| `.sessionStarted` → `session.isHookManaged = payload.origin == .live` | `SessionState.swift:79` | flag set |
| `isVisibleInIsland` → `if isHookManaged { return !isSessionEnded }` | `AgentSession.swift:571` | **process discovery bypassed** |

So a hook-managed session stays visible as long as it is not ended — **regardless of whether a matching OS process exists.** This is the same mechanism upstream uses for Claude Desktop and Conductor, where the process is also invisible to the app.

**Consequence for design:** iTE must explicitly send `SessionEnd` when a session truly closes. Nothing else will garbage-collect it.

---

## 3. Verified upstream wire contract

All facts below were read from source at the reference commit.

### 3.1 Transport

| Property | Value | Source |
|---|---|---|
| Socket path (primary) | `~/Library/Application Support/OpenIsland/bridge.sock` | `BridgeTransport.swift` |
| Socket path (override) | `OPEN_ISLAND_SOCKET_PATH` | `BridgeTransport.swift` |
| Socket path (legacy alias) | `VIBE_ISLAND_SOCKET_PATH`, `/tmp/open-island-<uid>.sock` | `BridgeTransport.swift` |
| Framing | newline-delimited JSON | `BridgeTransport.swift:268-323` |
| Date encoding | milliseconds since 1970 | `BridgeTransport.swift:325-361` |
| Per-process opt-out | `OPEN_ISLAND_SKIP_HOOKS=1` | `HookSkipConfiguration.swift` |

### 3.2 Envelope

Client → server:
```json
{"type": "command", "command": {"type": "<commandType>", ...}}
```

Server → client (first frame on connect — **must be skipped**):
```json
{"type": "hello", "hello": {"protocolVersion": 1, "serverLabel": "local-bridge"}}
```

Server → client (reply):
```json
{"type": "response", "response": {"type": "acknowledged"}}
{"type": "response", "response": {"type": "claudeHookDirective", ...}}
```

### 3.3 Commands we will use

`BridgeCommand` is a closed enum of 11 cases (`BridgeTransport.swift:82-123`). We use exactly two:

| Command | Payload key | Purpose |
|---|---|---|
| `processClaudeHook` | `claudeHook` | lifecycle + activity (fire-and-forget) |
| `processClaudeHook` | `claudeHook` | permission round trip (blocking, §8) |

There is no generic "register an agent" command. `registerClient` accepts `.observer` only (`BridgeTransport.swift:78-80`) — it is a receive-only subscription, not an emit path.

### 3.4 Agent identity — why the label says "Claude"

`hookSource` is settable on the wire, but the resolver has a hard default:

```swift
var resolvedAgentTool: AgentTool {
    switch hookSource {
    case "qoder": return .qoder
    case "qwen": return .qwenCode
    case "factory", "droid": return .factory
    case "codebuddy": return .codebuddy
    case "kimi": return .kimiCLI
    default: return .claudeCode          // ← everything else, including us
    }
}
```
`ClaudeHooks.swift:883-898`

`AgentTool` is a closed 13-case enum (`AgentSession.swift:3-16`) and `AgentSession.init(from:)` decodes it strictly (`AgentSession.swift:497`) — an unknown tool string **throws**. Combined with the title being hardcoded:

```swift
var sessionTitle: String { "Claude · \(workspaceName)" }   // ClaudeHooks.swift:690-692
```

…there is no wire-only way to make the tool badge read "iTE". **We send `hook_source: "claude"` and accept the badge.** This is the known, accepted cost of shipping without a fork.

**What this actually looks like (measured, not predicted).** The badge is not the headline. Row rendering calls `spotlightWorkspaceName` (`AgentSession+Presentation.swift:117-133`), which prefers `jumpTarget.workspaceName` and only falls back to splitting `title` on `·`. Our `SessionStart` supplies `cwd`, so the headline becomes the **cwd's last path component** — a real project name. The `claude` badge is `AgentTool.shortName` for `.claudeCode` (`AgentSession.swift:49-52`). See §10.2 for captured evidence.

### 3.5 Payload fields that matter

| JSON key | Swift | Required | We supply |
|---|---|---|---|
| `cwd` | `cwd` | yes | `config.cwd` |
| `hook_event_name` | `hookEventName` | yes | mapped (§5) |
| `session_id` | `sessionID` | yes | `Session.session_id` |
| `tool_name` | `toolName` | on tool events | iTE tool name |
| `tool_input` | `toolInput` | on tool events | serialized args |
| `tool_use_id` | `toolUseID` | on tool events | iTE `call_id` |
| `tool_response` | `toolResponse` | on `PostToolUse` | tool result |
| `prompt` | `prompt` | on `UserPromptSubmit` | user message |
| `last_assistant_message` | `lastAssistantMessage` | on `Stop` | response text |
| `error` | `error` | on failures | error string |
| `source` | `source` | on `SessionStart` | `"startup"` |
| `terminal_app` | `terminalApp` | for jump-back | detected (§6) |
| `terminal_tty` | `terminalTTY` | for jump-back | detected (§6) |
| `terminal_session_id` | `terminalSessionID` | for jump-back | detected (§6) |
| `terminal_title` | `terminalTitle` | for jump-back | detected (§6) |
| `hook_source` | `hookSource` | no | `"claude"` |

**Important:** if we write to the socket directly from Python we must populate the `terminal_*` fields ourselves. The upstream `OpenIslandHooks` CLI normally computes these via AppleScript/Warp probes (`ClaudeHookPayload.withRuntimeContext`). Without them, jump-back degrades to `"Unknown"` (`defaultJumpTarget`, `ClaudeHooks.swift:694-704`). This is the single largest piece of real work in the iTE half — see §6.

### 3.6 Session title — generated names cannot be sent, but the prompt acts as a topic

iTE generates a real session name per thread. **That name cannot be displayed in the
island.** The stored session title is not payload-driven; it is a hardcoded property:

```
BridgeServer.swift:2350   title: payload.sessionTitle
ClaudeHooks.swift:690-692 var sessionTitle: String { "Claude · \(workspaceName)" }
ClaudeHooks.swift:682-684 var workspaceName: String { WorkspaceNameResolver.workspaceName(for: cwd) }
WorkspaceNameResolver.swift:6-27   last path component of cwd
```

The wire field that *looks* like it should carry a name — `ClaudeHookPayload.title` — is
decoded (`ClaudeHooks.swift:244`, `:466`) and then **never read**. Grepping every
`title: payload` assignment across `BridgeServer.swift` returns only
`payload.sessionTitle` and `payload.permissionRequestTitle`; `payload.title` appears
nowhere.

#### Correction — the rendered headline *does* carry the first prompt

An earlier revision of this section claimed the headline was *always* the cwd basename.
That was wrong, and a live capture (§10.2) disproved it. The rendered headline is:

```
AgentSession+Presentation.swift:171-188
    spotlightHeadlineText = spotlightWorkspaceName + " · " + initialPromptText
AgentSession+Presentation.swift:190-194
    initialPromptText ?? latestPromptText        // "session topic", not the latest
```

So with a prompt present the row reads `ite · <first prompt>`, not just `ite`. The
`sessionTitle` property above feeds the *stored* `AgentSession.title`; it is not what the
eye reads in the spotlight row.

**Revised consequences**

1. The cwd basename supplies the workspace half of the headline; the **first user prompt**
   supplies the topic half.
2. Per-thread distinction **is** achievable — two iTE threads in the same folder differ by
   their first prompt. This is the only lever available, and it is why `UserPromptSubmit`
   is worth sending (see §5).
3. The bare `ite` headline seen in the §10.2 probe capture was the folder name in the
   absence of any prompt. The probe sent no `UserPromptSubmit`. Not branding.
4. iTE's *generated* session names still have no route into the island. That half needs
   the fork.

#### The duplication this causes — upstream behaviour, not a payload bug

Because `defaultClaudeMetadata` populates both prompt fields from the *same* source:

```
ClaudeHooks.swift:709-710   initialUserPrompt: prompt ?? promptPreview,
                            lastUserPrompt:    prompt ?? promptPreview,
```

…and the row renders both unconditionally:

```
AgentSession+Presentation.swift:171-188   headline  = workspace · initialPrompt
AgentSession+Presentation.swift:196-204   "You:"     = latestPrompt
```

…a session with **exactly one prompt renders that prompt twice.** No equality guard exists
anywhere in the presentation layer (grepped).

This is inherent to upstream's "topic vs latest prompt" split, and reproduces for any
single-prompt session regardless of agent — `claude` sessions behave identically. iTE
merely exercises it. It self-resolves after 20 minutes of inactivity, when detail lines
collapse (`AgentSession+Presentation.swift:18`, `:305-315`).

The iTE-side lever is to stop sending the prompt at all, which removes both the duplicate
*and* the topic — regressing the per-thread distinction in consequence 2. **Not
recommended.** The clean fix is a one-line guard upstream (or in the fork):

```swift
// spotlightPromptLineText
guard latestPromptText != initialPromptText else { return nil }
```

This is the same category of limitation as the `claude` badge (§3.4) — cosmetic, and
removable only by forking. The fork change set is small and now well-scoped:

1. Add an `.ite` case to `AgentTool` (`AgentSession.swift:3-16`) with `displayName`,
   `shortName`, and `brandColorHex` entries. Swift's exhaustive switches will fail the
   build at every `AgentTool` switch site until each is handled — this is the bulk of the
   work, and it is mechanical.
2. Add a `processIteHook` case to `BridgeCommand` (`BridgeTransport.swift:82-123`).
3. Make `sessionTitle` (`ClaudeHooks.swift:690-692`) honour `payload.title` when present.
   Because `SessionStart` is the only event that carries a title and
   `ensureClaudeSessionExists` only runs when the session does not already exist
   (`BridgeServer.swift:2341-2343`), a title that is generated after the first turn also
   needs a title-update path on a later event.
4. Add the `guard latestPromptText != initialPromptText` fix above (§3.6 duplication).

### 3.7 Assistant message renders raw markdown

The third row in the live capture shows an unrendered markdown fragment:

```
The Open Island changes are a single coherent unit: **make tool calls render
correctly in the island.** All uncommitted, looks complete but hasn't been v…
```

Upstream clips the `Stop` payload's `last_assistant_message` to a single line
(`toolResponsePreview` / `clipped`, `ClaudeHooks.swift:794-796`) and renders it verbatim —
it does not strip markdown. So `**bold**`, backticks and heading markers appear literally.

This one **is** within the iTE half: strip or flatten light markdown when building the
`Stop` payload, since the field is a one-line preview rather than a document. Deferred
pending a decision on how much fidelity to keep (fenced code blocks and links may be worth
preserving).

### 3.8 Activity wording — why the island showed "Thinking" instead of iTE's text

iTE's TUI names each phase of a turn ("Brewing", "Reading file", "Searching code" — see
`src/ite/ui/tool_narrative.py:896-974`, `progress_label`). None of that reached the island.

**The island has no free-text activity field.** Its status line is derived solely from the
session's `currentTool`:

```
AgentSession+Presentation.swift:263-268
    case .running:
        if let activity = spotlightRunningActivityText { return activity }
        return spotlightPromptLineText == nil ? "Running" : "Thinking"

AgentSession+Presentation.swift:361-374
    spotlightRunningActivityText = currentToolDisplayName(currentTool) + preview
```

`currentTool` is written only from `defaultClaudeMetadata.currentTool`
(`ClaudeHooks.swift:712`), i.e. the `tool_name` field. So during pure reasoning — no tool in
flight — `currentTool` is `nil` and the island falls back to the literal **"Thinking"**,
while the TUI shows a gerund.

The merge rules confirm `PreToolUse` is the *only* usable lever
(`BridgeServer.swift:2871-2886`):

| Event | Effect on `currentTool` |
|---|---|
| `PreToolUse` | sets it (update wins) |
| `SessionStart`, `UserPromptSubmit`, `Notification`, `PreCompact` | keeps existing — **cannot** set it |
| `PostToolUse`, `Stop`, `StopFailure`, `SessionEnd` | clears it (when no update sent) |

**Solution — carried in the iTE half only.** Send a `PreToolUse` payload whose `tool_name`
is iTE's own label, with **no** `tool_input` and no `tool_use_id`:

```
payloads.activity_status(session_id, cwd, label, terminal) -> PreToolUse(tool_name=label)
```

The island then renders `humanized(label)` with no preview appended — displaying iTE's
wording verbatim. The label comes from the same `progress_label` the TUI and the remote
host use (`src/ite/remote/host.py:377-391` already reuses it for exactly this reason).

#### The rotation must be timer-driven, not event-driven

An earlier revision resolved the label once per turn and cached it, to avoid flicker. **That
was wrong**, and it is what made the island look frozen: it showed one word
("Contemplating") and never changed, while the TUI kept cycling.

The TUI's rotation is a *timer*, not a reaction to events:

```
app.py:825          self.set_interval(4.5, self._tick_aside_gerund)
_panels.py:2031-2034   def _tick_aside_gerund(self):
                           ...
                           self._aside_gerund_index += 1
tool_narrative.py:956-974   _ASIDE_GERUNDS = (Thinking, Considering, Contemplating, ...)
```

`_tick_aside_gerund` advances a counter every 4.5s. It emits **no event**, so no amount of
event mapping could reproduce it. The bridge therefore runs its own
`_ROTATION_INTERVAL_SECONDS = 4.5` task while a turn is running.

Emission points:

| Trigger | Label sent | Notes |
|---|---|---|
| `AGENT_START` | a starting gerund | last in the batch — `UserPromptSubmit` keeps `currentTool`, so ordering is what makes the label win |
| every 4.5s while reasoning | a fresh gerund | paused while `_tools_in_flight > 0` so a live tool's label is never overwritten |
| `CONTEXT_COMPACTED` | `"Compacting context"` | after `PreCompact` |
| `TOOL_CALL_START` | the real tool name + input preview | takes over from the rotation |

Rotation stops on `AGENT_END`, `AGENT_ERROR`, and `aclose`, so a finished session does not
keep mutating.

**Verified live** (`scripts/open_island_demo.py --reason 12`):
```
-> agent_start
   island: Sussing
   island: Whirring
   island: Spelunking
-> tool_call_start
   island: Read File config/loader.py
```

**Why not `Notification`:** it preserves `currentTool` rather than setting it, so it cannot
drive the status line — it only writes `summary`, which the spotlight row does not render.

**Cleanup:** each synthetic `PreToolUse` registers a pending context upstream. Those are
dropped wholesale at `Stop` / `StopFailure` / `SessionEnd`
(`BridgeServer.swift:2700-2714`), so they do not accumulate across turns.

**Known residual:** the TUI lowercases its label (`_threads.py:917`) while the island
title-cases via `humanizedToolName`. The island reads "Brewing" where the TUI reads
"brewing" — consistent with the island's own capitalised statuses ("Ready", "Thinking").

### 3.9 What the activity line can and cannot show

Verified live via the demo, the rendered lines are:

```
island: Read File config/loader.py      <- file path IS shown, during the tool
island: Edit config/loader.py
island: Shell pytest -q
```

`island_status_text` = `humanizedToolName(currentTool)` + the first renderable key from
`tool_input` (`PREVIEW_KEY_PRIORITY`, §3.5). So **the file being read or edited is already
visible** while that tool runs.

What is **not** available: a history. The island renders exactly one activity line per
session — the most recent event wins and previous ones are discarded. There is no log,
timeline, or per-tool list in the spotlight row.

The only *list* surface the island renders is `activeTasks`
(`IslandPanelView.swift:1449-1471`), a checklist with status icons and strikethrough,
driven by `TaskCreate` / `TaskUpdate` tool names via `updateTask`
(`BridgeServer.swift:2773-2804`):

| Field | Accepted key |
|---|---|
| title | `subject` ?? `description` |
| id | `id`, or `taskId`/`task_id` on update |
| status | `pending` \| `in_progress` \| `completed` |

iTE has a comparable surface — the `todos` tool (`src/ite/tools/builtin/todo.py`), with
`add` / `complete` / `update` / `remove` / `reopen` actions over `content`-bearing items.
Mapping it onto `TaskCreate`/`TaskUpdate` would give a visible checklist of "what
happened". That is a deliberate next step rather than something done here, because it
requires emitting a synthetic `tool_name` that impersonates a Claude Code tool, which is a
behavioural decision rather than a mechanical one.

### 3.10 Raw JSON must never reach the UI (fixed)

A live session rendered this in the notch:

```
$ {limit: 6.0}
```

**Cause — four steps, all on our side.**

1. iTE sent a tool's raw arguments, e.g. `git_log` with `{"limit": 10}`
   (`GitLogParams.limit = 10`, `src/ite/tools/builtin/git_tools.py:167`).
2. `normalize_tool_input` found no key in `PREVIEW_KEY_PRIORITY` and no alias to promote,
   so it passed the object through unchanged.
3. Upstream's `toolInputPreview` then found no priority key holding a *string*, so it fell
   back to serialising the **entire object** — `ClaudeHooks.swift:1126-1150`
   (`stringValue(for: .object)` renders `{key: value}` with sorted keys).
4. `runningDetailText` wraps any preview as `"$ \(preview)"`
   (`IslandPanelView.swift:1898-1901`), which is why an internal parameter appeared as if
   it were a shell command.

**The rule now enforced: only send `tool_input` when the island can actually render from
it.** `normalize_tool_input` returns `None` when no `PREVIEW_KEY_PRIORITY` key holds a
non-empty **string**, and callers omit the field entirely. `has_renderable_preview` encodes
the test. Non-string values do not count, because upstream's `stringValue` only produces
text for `.string`.

Result for the reported case:

| | Before | After |
|---|---|---|
| wire | `tool_input: {"limit": 10}` | *(field omitted)* |
| notch | `$ {limit: 10}` | `Git Log` |

**A second, related change.** `post_tool_use` now carries **no** `tool_input`. Upstream
clears `currentToolInputPreview` only when an update omits it
(`BridgeServer.swift:2888-2903`), so sending it on completion let a finished tool's preview
survive — a rotated gerund would then render as `Mulling config/loader.py`. Omitting it
clears the preview, which also made the per-`call_id` argument cache unnecessary and it was
removed.

**Guarded by tests** (`NonRenderableInputTests`), including a table across the tool
argument shapes we know: `git_log {limit}`, `git_diff {staged_only}`, `read_file {limit}`,
`todos {action, items}`, `memory {action, limit}`, `list_dir {}`. Each asserts the rendered
line contains no `{` or `}`.

**Trade-off, stated plainly:** tools whose arguments have no island equivalent now show only
their humanised name — `Git Log`, `Todos`, `Plan Question` — rather than a detail line.
That is a deliberate choice: a clean name beats leaking internals. Enriching specific tools
would mean curating per-tool previews, which the wire protocol does not have a field for.

---

## 4. Architecture

```
ite (Python)                                      Open Island (stock)
─────────────                                     ───────────────────
AgentEvent stream  (agent/events.py)
        │
        ▼
OpenIslandBridge  (integrations/open_island/)
  ├─ event mapper      AgentEvent → hook payload
  ├─ session registry  session_id → bridge state
  └─ socket client     newline-JSON over AF_UNIX
        │
        └──────────── Unix socket ────────────► BridgeServer → AppModel → notch UI
```

**Design rules**

1. **Fail-open, always.** Any error, timeout, or missing socket disables the bridge for that event and logs at debug. Never raise into the agent loop.
2. **Off by default.** Opt-in via config. No socket I/O unless enabled.
3. **Never block the turn** for lifecycle events. Fire-and-forget with a short timeout.
4. **Own the event loop, not the UI.** Subscribe to `AgentEvent`; do not touch Textual.

---

## 5. Event mapping

iTE `AgentEventType` (`src/ite/agent/events.py:10-30`) → Claude hook event names (`ClaudeHooks.swift:315-330`):

| iTE event | Open Island event | Notes |
|---|---|---|
| `AGENT_START` | `SessionStart` | `source: "startup"`; creates session |
| *(user message)* | `UserPromptSubmit` | `prompt` = user text |
| `TOOL_CALL_START` | `PreToolUse` | `tool_name`, `tool_input`, `tool_use_id` |
| `TOOL_CALL_COMPLETE` | `PostToolUse` | `tool_response` = result |
| `TOOL_CALL_COMPLETE` (failed) | `PostToolUseFailure` | `error` = failure text |
| `TEXT_COMPLETE` | `Stop` | `last_assistant_message` |
| `AGENT_END` | `Stop` | turn complete, session stays open |
| `AGENT_ERROR` | `StopFailure` | `error`, `error_details` |
| `CONTEXT_COMPACTED` | `PreCompact` | reuse for the compaction indicator |
| *(session close / quit)* | `SessionEnd` | **mandatory** — only thing that clears the notch |
| *(approval needed)* | `PermissionRequest` | blocking — staged, §8 |

Deliberately unmapped in v1: `TEXT_DELTA` (noisy, no UI value), `PLAN_READY`, `USAGE_UPDATE`, `LOOP_DETECTED`, subagent events.

**Note on `AGENT_START` vs `AGENT_END` semantics.** iTE's `AGENT_START`/`AGENT_END` bracket a *turn*, not a process lifetime. Open Island's `SessionStart`/`SessionEnd` bracket a *session*. Mapping `AGENT_END`→`Stop` (not `SessionEnd`) is therefore correct, and `SessionEnd` must be emitted on iTE session teardown — otherwise stale bubbles persist forever (§2).

---

## 6. Terminal / jump-back detection
**Status: confirmed required.** Live capture (§10.2) shows the missing fields render as a
visible `Unknown` badge next to every session. This is not optional polish — it is the
first thing a user notices. Socket-direct emission bypasses the upstream CLI's
AppleScript/Warp probing, so we own this.

The one genuinely substantial component. All of it is local, best-effort, and degrades to `"Unknown"` without breaking anything.

**Inputs available**
- `TERM_PROGRAM` env var → `terminal_app` (`iTerm.app`, `Apple_Terminal`, `WarpTerminal`, `ghostty`, `vscode`)
- `os.ttyname(sys.stdin.fileno())` or `ps -o tty= -p <ppid>` → `terminal_tty` (`/dev/ttys003`)
- `TERM_SESSION_ID` (iTerm) / `ITERM_SESSION_ID` → `terminal_session_id`
- OSC 0/2 title, or `ps` on the parent shell → `terminal_title`

**Rules**
- Detect once per session, cache on the bridge state.
- Run detection in a thread executor; never block the event loop.
- Any failure → omit the field. Do **not** send `"Unknown"` explicitly; let upstream fall back.

**Explicitly out of scope in v1:** Warp precision jump (`warp_pane_uuid` requires querying Warp's SQLite state — upstream does this in `withRuntimeContext`). Regular Warp jump-back will still work; only per-pane precision is lost.

---

## 7. Module layout & wiring

### 7.1 New package

```
src/ite/integrations/__init__.py
src/ite/integrations/open_island/__init__.py
src/ite/integrations/open_island/client.py     # AF_UNIX client, envelope codec, hello skip
src/ite/integrations/open_island/payloads.py   # Claude-shaped payload builders
src/ite/integrations/open_island/terminal.py   # terminal detection (§6)
src/ite/integrations/open_island/bridge.py     # session registry + event mapper
```

Each file single-purpose. `client.py` holds all wire knowledge; nothing else builds JSON envelopes.

### 7.2 Wiring point

`agent.run()` is consumed in exactly **three** real places:

| Consumer | Location | Bridge? |
|---|---|---|
| Reup TUI | `src/ite/ui/reup/_turn.py:1862` | yes |
| Remote host | `src/ite/remote/host.py:317` | yes |
| Subagent | `src/ite/tools/subagent.py:202` | no — subagents fold into parent session |

Rather than edit all consumers, add a **tee** at the `Agent` level: a small async wrapper that yields events through unchanged while forwarding a copy to any registered observer. One code path, no UI coupling, no duplication.

Subagent events stay unmapped in v1 (upstream has `SubagentStart`/`SubagentStop`, but iTE subagents are internal — mapping them would need verification and is deferred).

### 7.3 Config

New opt-in section, following existing `Config` conventions (`src/ite/config/config.py`):

```toml
[integrations.open_island]
enabled = false
# socket_path = "~/Library/Application Support/OpenIsland/bridge.sock"  # optional override
```

- Default `enabled = false`.
- macOS-only in practice; must no-op cleanly on Linux/Windows.
- Respect `OPEN_ISLAND_SKIP_HOOKS=1` as a kill switch.
- Surface state through the existing `/hooks`-style command surface so users can toggle it.

---

## 8. Phase 2 — approvals from the notch (designed, not built in v1)

Worth documenting now because it constrains phase 1 design.

The round trip already exists end-to-end:

```
iTE ApprovalManager.check_approval()  →  needs confirmation
        │
        ▼
send processClaudeHook {hook_event_name: "PermissionRequest"}   ← blocks on socket
        │
        ▼
notch shows Allow / Deny  →  user clicks
        │
        ▼
BridgeServer sends resolvePermission  →  socket read returns claudeHookDirective
        │
        ▼
map allow/deny → ApprovalDecision  →  agent continues
```

**Verified affordances**
- `PermissionRequest` has a 24h interactive timeout for Claude-format hooks (`OpenIslandHooksCLI.swift`), so waiting on a human is supported.
- Correlation key is `sessionID|toolName|serializedToolInput` (`ClaudeHooks.swift:806-809`) and `PreToolUse` stashes context under it (`BridgeServer.swift:687-692`) — we must send `PreToolUse` **before** `PermissionRequest` with identical `tool_name`/`tool_input`, or the correlation breaks.
- iTE side already has the right shape: `ApprovalManager` (`src/ite/safety/approval.py:227`), `ApprovalContext` (`:24-33`), `ApprovalDecision` (`:12-16`), and a reference implementation of an out-of-process approval round trip at `src/ite/remote/server.py:641` (`request_approval`) → `:669` (`resolve_approval_request`).

**Why it is staged:** it puts a blocking socket read on the critical approval path. If it misbehaves, the agent hangs. It needs the fail-open path (timeout → fall back to in-terminal prompt) proven first. Phase 1 validates the transport for free.

---

## 9. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | Session bubble leaks after iTE exits (no `SessionEnd`) | High | Emit `SessionEnd` on shutdown; add stale-session sweep |
| 2 | Handler crash in hook-managed session | Medium | Wrap all dispatch; fail-open |
| 3 | Protocol drift (`protocolVersion: 1`, no stability guarantee) | Medium | Pin to verified commit; isolate wire code in `client.py`; tolerate unknown fields |
| 4 | Jump-back lands in wrong tab | Medium | Best-effort detection; omission is safe (§6) |
| 5 | macOS-only assumption leaks | Low | Gate on `sys.platform`; no-op elsewhere |
| 6 | Upstream changes `resolvedAgentTool` default | Low | Label is cosmetic; affects nothing functional |
| 7 | Socket read blocks the event loop | Medium | Timeouts everywhere; never await indefinitely in v1 |

**Deliberately not a risk:** the "Claude Code" label. Accepted.

---

## 10. Verification plan

Each item must be demonstrable before the slice is considered done.

| # | Test | Method | Status |
|---|---|---|---|
| 1 | Session appears | Open Island running, iTE turn → bubble in notch ≤1s | **PASSED — live** (§10.2) |
| 2 | Session survives | Wait 60s mid-turn → bubble still present (proves hook-managed liveness, §2) | **PASSED — live** |
| 3 | Activity updates | Run a tool → summary changes | Pending (needs step 4) |
| 4 | Session clears | End session → bubble disappears | **PASSED — live** |
| 5 | **Fail-open** | Kill Open Island, run a full iTE turn → zero errors, zero delay, zero UI change | **PASSED — live** (transport level) |
| 6 | Disabled | `enabled = false` → no socket connection attempted | Pending (needs step 3) |
| 7 | Non-macOS | Import + run on Linux → clean no-op | Pending |
| 8 | Jump-back | Click bubble → correct terminal focused | Pending (needs step 5) |
| 9 | Regression | Full `pytest` + `ruff` + `mypy` clean | **PASSED** for new module |
| 10 | No leakage | `OPEN_ISLAND_SKIP_HOOKS=1` → bridge inert | Covered by unit tests |
| 11 | Stale socket | Socket file present, app stopped → reported unavailable, no hang, no error | **PASSED — live** |
| 12 | Handshake | `hello` greeting received, command → `acknowledged` | **PASSED — live** |
| 13 | Bubble renders correctly | Visual capture of a real session | **PASSED — live** (§10.2); reveals `Unknown` terminal badge |

Test 2 is the one that matters most — it is the assumption the whole design rests on.

Tests 5 and 9 are the ones the user base will notice if violated.

### 10.1 Live verification results

Exercised against a real running Open Island install via `scripts/open_island_probe.py`.

**Handshake — PASSED.** Greeting frame matched the source exactly:
```json
{"type": "hello", "hello": {"protocolVersion": 1, "serverLabel": "local-bridge"}}
```
A `processClaudeHook` / `SessionStart` command returned `{"type": "acknowledged"}`.

**Liveness (test 2) — PASSED, and this is the headline result.** The linchpin assumption
in §2 is now confirmed empirically, not just by reading source. A session was created with
a synthetic id and left untouched for 75 seconds. Observed: `sessionStarted` at t=0, then
**zero eviction events** for the full window. No process-discovery pruning occurred, even
though no matching OS process exists. Hook-managed liveness holds as designed.

**SessionEnd (test 4) — PASSED.** Emitting `SessionEnd` produced `sessionCompleted` for
each session, and the corresponding notch bubbles were removed. Confirms the mandatory
teardown path in §9 risk #1 is both necessary and sufficient.

**Observer role — verified usable.** `broadcast()` sends every `AgentEvent` to all
connected clients regardless of role (`BridgeServer.swift:3131-3139`), and
`registerClient(observer)` is accepted. This is how the probe observes state without
reading the UI, and it is available to iTE later if out-of-band state observation is
ever needed.

### 10.2 Live capture — bubble rendered (PASSED)

A session emitted by `scripts/open_island_probe.py --hold` was captured on screen. What
the notch rendered for a synthetic `SessionStart` with `cwd` set to the `ite` repo:

| Element | Observed | Derived from |
|---|---|---|
| Headline | `ite` | `spotlightWorkspaceName` → `jumpTarget.workspaceName` → last path component of `cwd` |
| Tool badge | `claude` | `AgentTool.shortName` for `.claudeCode` (`AgentSession.swift:49-52`) |
| Terminal badge | `Unknown` | `spotlightTerminalBadge` → `jumpTarget.terminalApp` → the `?? "Unknown"` fallback |
| Elapsed | `<1m` | session age |
| Status | `Ready` | `initialPhase: .completed` |
| Header | `SESSIONS 1 total · 1 done` | session counters |

**Three conclusions.**

1. **Visual acceptance — better than predicted.** The headline is workspace-derived, so we
   do *not* get "Claude Code" as a primary label. Note the headline read `ite` only because
   the probe's `cwd` was the `ite` repo; a user in another project sees *that* project's name.
   This is not iTE branding — it is workspace branding, which is arguably the more useful
   behaviour and matches how the other agents present.
2. **The identity tell is small.** One `claude` badge. Purely cosmetic, no functional impact.
   This is the whole of what the fork buys on the labelling front.
3. **Terminal detection is now confirmed as the top polish gap.** The `Unknown` badge is
   exactly the `?? "Unknown"` fallback forewarned in §6 — `defaultJumpTarget` had no
   `terminal_app` to use because socket-direct emission bypasses the upstream CLI's
   AppleScript/Warp probing. It is visible to the user immediately, so §6 moves from
   "nice to have" to **required for a shippable look**.

Also confirmed: the phase renders `Ready` because `SessionStart` is sent with
`initialPhase: .completed`. Real turn activity must drive it to a running state — that is
step 4 (activity mapping), and it is what makes the bubble feel live rather than static.

### 10.3 Live finding — stale socket file (resolved)

Discovered while probing a real machine. Open Island had been run previously and left
`~/Library/Application Support/OpenIsland/bridge.sock` on disk while the app itself was
not running. Consequences:

- The socket file **exists** — a naive `Path.exists()` liveness check returns `True`.
- Any connect attempt fails with `ConnectionRefusedError` (errno 61).

An availability check based on file existence is therefore a **false positive**, and any
code that trusts it will attempt a send that immediately fails. Resolved in `client.py`
by splitting the two concerns:

| Method | Semantics |
|---|---|
| `socket_exists()` | File presence only. Explicitly documented as *not* a liveness check. |
| `is_available()` | Performs a real connect. Returns `False` on stale socket, refusal, or timeout. |

Both paths are covered by regression tests, and the fail-open behaviour was confirmed
against the real stale socket (`try_send` → `None`, no exception raised).

**Design consequence:** never gate behaviour on `socket_exists()`. Either probe with
`is_available()` or simply attempt the send and swallow `OpenIslandBridgeError`.

---

## 11. Delivery sequence

| Step | Deliverable | Gate | Status |
|---|---|---|---|
| 1 | `client.py` — socket, envelope, hello-skip | Handshake against live app | **Done** — 19 tests, ruff + mypy clean, live-verified |
| 2 | `payloads.py` + `bridge.py` — session lifecycle only | Tests 1, 2, 4 pass | Next *(transport-level equivalent already proven by the probe)* |
| 3 | Config gating + command surface | Tests 6, 7, 10 pass | Pending |
| 4 | Tool activity mapping | Test 3 passes | Pending — required for a live-feeling bubble |
| 5 | `terminal.py` + jump-back | Tests 8 pass | Pending — **now required, not optional** (§6) |
| 6 | Fail-open hardening | Tests 5, 11 pass | Partially covered by step 1 |
| 7 | Docs (`docs/`) + verification sweep | Tests 9 clean | Pending |

Steps 1–3 are the minimum shippable slice. Steps 4–6 make it "look pretty and work pretty."
Step 5 was promoted to required after the live capture showed a visible `Unknown` badge.

**Step 1 notes.** Delivered `src/ite/integrations/open_island/client.py` with a fail-open
`try_send()`, verified against an in-process Unix socket server (19 tests) **and against a
live Open Island install**. Handshake, liveness (75s, no eviction), and `SessionEnd`
teardown all confirmed — see §10.1. A reusable live probe lives at
`scripts/open_island_probe.py`.

The transport is proven. What is **not** yet built is the layer above it: nothing in iTE
emits these commands yet, so a normal `ite` session does not appear in the notch. That is
steps 2–4.

---

## 12. Follow-on (separate effort, not this plan)

Two things this work explicitly sets up but does not do:

1. **Fork Open Island** to add a first-class `ite` source — new `AgentTool` case, `ite` source in the CLI, icon, installer. Removes the "Claude Code" label and unlocks honest identity.
2. **Upstream pitch.** A clean, working iTE integration with a documented protocol surface is a far stronger proposal than an empty request. This plan produces exactly that evidence: the event mapping, the liveness finding, and a real user population.

**Licensing constraint (must hold).** Open Island is **GPLv3**. The iTE half must be a **clean-room implementation of the wire protocol**, written from behaviour — not ported from their Swift. Invoking the app over its socket is arm's length; copying source into `ite-agent` would taint the package. No Swift from `open-vibe-island` may enter this repo.

---

## 13. Open questions

1. **Turn vs session for `SessionStart`.** Send once per iTE session, or per turn? Leaning once per session; needs a live test.
2. **`UserPromptSubmit` source.** The prompt text is available at the turn entry point but not carried on `AgentEvent` — needs a small plumbing decision.
3. **Multiple concurrent iTE sessions.** `session_id` is per-`Session` (`session.py:63`), so identifiers are unique — but whether upstream renders multiple bubbles well is unverified.
4. **`Stop` vs `StopFailure` for cancelled turns.** Should a user interrupt read as failure or completion? Needs a decision.
