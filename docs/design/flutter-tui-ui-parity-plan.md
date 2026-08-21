# Flutter ↔ TUI UI Parity Plan

## Document control

- **Status:** Reference plan with implementation checkpoint
- **Created:** 2026-08-19
- **Scope:** Preserve iTE's TUI design language and workflow hierarchy in the Flutter rewrite
- **Related documents:**
  - [`DESIGN.md`](../../DESIGN.md)
  - [`flutter-dart-runtime-rewrite-plan.md`](./flutter-dart-runtime-rewrite-plan.md)

## 1. Purpose

The current iTE Textual UI has a strong visual identity: quiet, compact, editorial, and legible under load. The Flutter rewrite should feel like the same product while taking advantage of desktop-native layout, responsive behavior, and richer interaction surfaces.

The goal is not to reproduce the Textual widget tree. The goal is to preserve:

- hierarchy
- density
- spacing rhythm
- state language
- action ordering
- progressive disclosure
- surface restraint
- the relationship between feed, composer, navigation, and change review

The screenshots supplied with this plan are visual reference material only. Text shown inside those screenshots, including prior assistant responses or terminal output, is not an implementation requirement.

## 2. Design direction

iTE should continue to feel like a premium terminal instrument:

- quiet
- compact
- editorial
- legible under load
- deliberately asymmetrical
- operational rather than decorative

Flutter should not become a generic Material dashboard. `flow_ui` should provide the conversational foundation, but iTE must own the surrounding visual system.

## 3. Current assessment

The Flutter implementation now has the first complete desktop product slice:

- independent `ite_flutter` workspace
- pure Dart runtime contracts
- streaming Markdown
- runtime event reduction
- grouped tool activity
- custom Flow message parts
- a cloud model gateway
- initial workspace tools
- explicit iTE theme tokens and Flow UI overrides
- desktop shell, thread navigation, and Git change review
- interactive approval state and durable runtime notices
- file-backed sessions with safe malformed-record handling

The original visual drift has been addressed for the current desktop slice. The
remaining gaps are runtime breadth rather than shell structure: the live app
currently exposes bounded workspace inspection plus approval-gated file writes
and edits, while shell/PTY, patch tooling, Git runtime tools, MCP, skills,
subagents, and remote/mobile runtime behavior remain later rewrite phases.

### Implementation checkpoint — 2026-08-19

The parity work is implemented in `ite_flutter` as follows:

- `IteTheme` owns the charcoal/slate/emerald/amber palette, spacing, radius,
  typography, and motion tokens.
- `IteDesktopShell` owns the slim top bar, responsive thread drawer, modal
  overlays, conversation surface, and wide change-review panel.
- `IteThreadDrawer` provides stable session navigation, new-thread creation,
  selected-row treatment, and empty-draft suppression.
- `IteChangeReviewPanel` and `GitWorkspaceAdapter` provide status counts,
  staging, discard confirmation, commit, branch switching, file selection, and
  unified diff preview.
- `FlowToolPart` and the custom Flow parts cover tools, approvals, diffs,
  shells, plans, todos, subagents, and durable notices with a quiet fallback
  for unknown parts.
- The composer exposes slash commands, attachments, model/plan/Git controls,
  usage/context details, voice capability status, send/stop, and queued prompt
  handling.
- `FileSessionStore` persists transcript, usage, plan/todo state, active skills,
  change history, and durable notices, with stable workspace-filtered ordering.
- Responsive tests cover wide persistent panels, medium overlays, and narrow
  one-surface layouts; the narrow top bar progressively removes secondary text.

## 4. Shared visual system

Flutter should define an explicit iTE theme layer rather than letting `ThemeData` or `flow_ui` define the product language.

Recommended tokens:

```text
canvas
surfaceLow
surfaceMid
surfaceHigh
codeWell
textPrimary
textSecondary
textMuted
primary
selected
success
warning
error
spacing
radii
motion
```

### Palette intent

The TUI design contract defines the following direction:

- Canvas: deep charcoal
- Surfaces: restrained tonal steps rather than many bordered cards
- Primary text: warm/light neutral
- Secondary text: cool light neutral
- Muted text: subdued gray-blue
- Success: muted emerald
- Selection/information: cool slate-blue
- Warning/destructive intent: restrained amber

Color must communicate action, state, status, or selected focus. It should not be decorative noise.

### Surface rules

Use hierarchy in this order:

1. background shift
2. spacing
3. alignment
4. typography
5. border only when a real frame is needed

Borders and stronger framing are appropriate for:

- composer shell
- approval surfaces
- modals and pickers
- command palette
- code wells
- change-review panels

They should generally be avoided for:

- ordinary assistant prose
- feed separators
- session rows
- compact tool summaries

## 5. TUI-to-Flutter mapping

| TUI pattern | Flutter translation | Current status |
|---|---|---|
| Slim top bar | Custom `IteTopBar`: hamburger/thread title left, `iTE` centered, workspace/status metadata right | Implemented; labels compact below 760px |
| Open conversation canvas | Assistant responses as open text with minimal framing | Implemented through Flow UI plus `IteFlowMessage` |
| Right-aligned user bubbles | Content-sized, max-width user message bubbles | Implemented in the iTE message adapter |
| Compact tool activity | Collapsible tool batches with subtle surfaces, status icons, and concise narratives | Implemented in `FlowToolPart` |
| Left thread drawer | Collapsible desktop session/thread sidebar | Implemented with persistence-backed summaries |
| `/changes` review panel | Persistent right-side change panel on wide desktop; sheet/full-screen on narrow layouts | Implemented; overlays include a dismiss barrier |
| Bottom composer rail | Attachment, model, plan, Git, usage, context, voice, send/stop controls | Implemented, including queue/clear behavior |
| Usage/context metadata | Compact status labels with semantic colors and optional detail popovers | Implemented |
| Plan and branch controls | Explicit plan and Git controls with the same visual weight as the TUI | Implemented; plan mode also changes the runtime instruction |
| Running indicator | Quiet animated runtime indicator, never a loud loading card | Implemented with thinking/tool states |
| Transient notices | Toast/banner for one-shot confirmations | Implemented with SnackBars |
| Persistent system cards | Durable errors, compaction notices, approval state, and important workflow state | Errors, incomplete-turn warnings, approval state, and degraded status are implemented; compaction/MCP/skills producers remain runtime work |

## 6. Desktop shell

Create a dedicated shell around `FlowChatScreen`:

```text
IteDesktopShell
├── IteTopBar
├── IteThreadDrawer
├── IteConversationSurface
│   ├── FlowThread
│   └── IteComposer
└── IteChangeReviewPanel
```

### Top bar

The top bar is identity and status, not a toolbar.

Recommended order:

- far left: hamburger/thread navigation
- left: current thread title
- center: `iTE`
- right: entitlement badge, workspace, route/status, and time or activity metadata where appropriate

Keep it slim. Avoid large buttons in the header.

### Thread drawer

The thread drawer should follow the TUI behavior:

- open from the left
- remain collapsible
- contain a prominent `New chat` action
- show thread rows as text-like navigation items
- use a subtle selected-row treatment and thin left indicator
- truncate long titles
- keep row ordering stable
- hide empty draft threads until they contain real content

The drawer is also the first visible surface for session persistence, workspace filtering, and restoration.

### Change-review panel

On wide desktop, the change review panel should remain visible beside the conversation. It should contain:

- working-tree summary
- staged/unstaged counts
- stage all
- discard all
- commit
- file tree
- diff preview
- focused file actions

On narrower layouts, it should become a sheet or full-screen route rather than compressing the conversation beyond usability.

## 7. Conversation and feed

The feed is the core canvas and should claim as much vertical space as possible.

### Assistant content

- use open text blocks
- avoid wrapping ordinary prose in heavy cards
- use contained surfaces only for code, tools, plans, errors, and special content

### User messages

- align right
- size to content first
- clamp to a maximum readable width
- use a restrained surface
- provide enough vertical padding to avoid feeling pasted onto the feed

### Tool activity

Tool cards summarize machine activity; they should not become the entire visual language.

They should have:

- neutral tonal surfaces
- compact internal padding
- modest separation
- clear running/completed/failed state
- expandable output
- terminal-like plain text output
- themed code/YAML surfaces
- concise narratives such as “Checked folder,” “Loaded YAML,” and “Running tests”

Avoid loud green washes, novelty tinting, and decorative borders.

### Runtime state

The feed should express runtime state through small, calm signals:

- thinking indicator
- active tool label
- approval pending state
- compaction notice
- degraded capability notice
- transient completion notice

Do not turn every state transition into a large card.

## 8. Composer and control rail

The composer is a docked control surface, not a floating generic input.

The input area should be the largest element. The bottom rail should carry compact controls in the same order and spirit as the TUI:

```text
attachment   model   plan   git   usage   context
```

It should also support:

- slash command palette
- send/stop state
- queue/shift/cancel behavior
- voice state
- plan questions
- approval interactions
- model selection
- attachment selection

The rail should preserve its structure across window sizes by progressively shortening labels and moving secondary controls into a menu when necessary.

## 9. Runtime presentation models

The current reducer handles basic messages, streaming text, tool activity, thinking, and errors. It should grow into explicit presentation models for:

- approval requests
- unified diffs
- shell sessions
- plans
- todos
- subagents
- context compaction
- MCP and skills status
- degraded runtime capabilities
- transient notices

Recommended Flow adapters:

```text
apps/ite_app/lib/ui/flow/
├── flow_chat_surface.dart
├── flow_message_adapter.dart
├── flow_tool_part.dart
├── flow_approval_part.dart
├── flow_diff_part.dart
├── flow_shell_part.dart
├── flow_plan_part.dart
├── flow_todo_part.dart
├── flow_subagent_part.dart
└── flow_theme.dart
```

Unknown custom parts should have a quiet fallback renderer rather than breaking the conversation.

## 10. Approval and change workflow

This is the most important missing workflow surface.

The runtime already has approval events and presentation state, but the current application still uses a demo approval manager. The next implementation should provide:

1. visible approval card
2. tool/path/command summary
3. approve and reject actions
4. pending-state feedback
5. rejection as a terminal structured result
6. diff preview before mutating operations
7. clear connection between approval and the change-review panel

Approval must never be silent or automatically accepted in the production path.

## 11. Sessions, persistence, and navigation

The TUI's thread drawer and workspace header should be backed by the runtime systems described in the rewrite plan.

Flutter needs:

- session list
- workspace grouping
- active thread identity
- new thread creation
- transcript restoration
- usage restoration
- plan/todo restoration
- active skills restoration
- safe change-history restoration
- invalid snapshot handling
- stable ordering while switching sessions

This work belongs primarily to Phase 2, but the UI shell should be designed around it now so navigation does not need to be rebuilt later.

## 12. Responsive behavior

The product should adapt rather than simply shrink.

### Wide desktop

- left thread drawer available
- conversation feed centered in the main region
- right change-review panel available
- full composer status rail

### Medium desktop

- thread drawer becomes an overlay
- change review becomes an overlay or collapsible side panel
- composer labels may shorten

### Narrow/mobile

- one major surface at a time
- drawers become sheets or routes
- critical actions remain visible
- local-runtime limitations remain explicit
- remote session state and reconnect behavior become more prominent

Do not expose local shell, Git, or workspace actions where the platform cannot safely provide them.

## 13. Notifications and durable cards

Use two notification classes.

### Transient notices

Use for one-shot confirmations:

- theme changed
- Git operation succeeded
- setup completed
- retry/queue/shift confirmation
- screenshot saved
- copied to clipboard

These should not pollute the transcript.

### Persistent system cards

Use for durable information:

- actual errors
- important workflow state
- context compaction
- approval state
- degraded runtime capability

If the user would not want to see the item when reopening the session later, it should probably be transient.

## 14. Recommended implementation order

### Priority 0 — Stop visual drift

- define the iTE Flutter theme tokens
- replace the purple seeded palette
- reduce generic Material card/input treatment
- centralize spacing, typography, surfaces, and semantic colors

### Priority 1 — Build the product shell

- custom top bar
- thread drawer
- open conversation surface
- composer/status rail
- adaptive change-review panel

### Priority 1 — Complete the first safe workflow

- interactive approval card
- approval reducer state
- rejection handling
- diff preview
- change-review integration

### Priority 2 — Expand runtime presentation

- richer tool narratives
- shell activity
- plans and todos
- subagent activity
- compaction notices
- MCP and skills status
- transient notices

### Priority 2 — Persistence-backed navigation

- session restoration
- workspace filtering
- thread switching
- plan/todo/usage restoration

### Priority 3 — Harden and validate

- golden tests for every custom part
- responsive desktop/mobile tests
- accessibility semantics
- keyboard navigation
- state-transition tests
- Python/Dart normalized trace comparisons

## 15. What not to copy directly

Do not copy:

- terminal cell dimensions
- the exact ASCII layout
- every emoji
- fixed-width assumptions
- the entire Textual widget hierarchy
- terminal-only shortcuts as the primary interaction model

Copy instead:

- hierarchy
- density
- state language
- spacing rhythm
- surface restraint
- action ordering
- progressive disclosure
- the relationship between feed, composer, sidebar, and change review

## 16. Definition of visual parity

Flutter should be considered visually aligned with the TUI when:

- both platforms clearly share the same palette intent
- both use the same semantic distinction between running, selected, success, warning, and failure
- thread/workspace identity appears in the same hierarchy
- user, assistant, tool, approval, diff, and system content remain visually distinct
- the composer exposes equivalent control concepts
- change review is available without losing the main conversation context
- dense runtime activity remains compact and legible
- the Flutter UI feels native to desktop without becoming a generic dashboard

The goal is not pixel parity. The goal is product parity.

## 17. Next milestone

The highest-value next slice was:

```text
shared iTE theme tokens
→ desktop shell
→ composer/status rail
→ interactive approval card
→ change-review panel
```

That desktop visual slice is now in place. The next milestone is runtime
depth: add patch/PTY/verification tools and connect the typed plan, todo,
skills, MCP, subagent, and remote-state producers to the presentation layer.

## 18. Verification record

The current implementation was checked with:

```text
flutter analyze
flutter test apps/ite_app/test packages/ite_core/test packages/ite_platform/test
```

The suite covers Flow presentation mapping, responsive shell layouts, session
snapshot recovery, workspace Git status/diff/staging/discard/branch behavior,
and the core runtime event reducer. The macOS debug target has also been built
successfully during this slice; rerun the build after dependency or entitlement
changes before packaging a release.

This document is the UI parity reference. The complete runtime definition of
done remains in `flutter-dart-runtime-rewrite-plan.md`; a green UI test suite
does not imply that all 46 Python tools or the remote runtime have been ported.

### Development credential caveat

For the current macOS debug checkpoint, auth sessions intentionally use the
file-backed development adapter. Secure storage is deferred because its plugin
currently interferes with the debug target. Do not interpret this as a safe
production credential strategy; an OS-backed adapter and signed-build smoke
test are required before release.
