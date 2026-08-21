# iTE Flutter/Dart Runtime Rewrite Plan

## Document control

- **Status:** Planning baseline with implementation checkpoint
- **Created:** 2026-08-18
- **Scope:** Complete rewrite of the active iTE Python runtime in Dart, with Flutter as the native UI
- **Primary target:** Desktop-first Flutter application for macOS, Linux, and Windows
- **Secondary target:** Mobile companion/remote surface after desktop runtime parity
- **Python runtime role:** Behavioral reference and differential-test oracle only
- **Explicitly excluded:** `ite_macos`, the previous Flutter frontend layered over the Python runtime, and any production dependency on Python
- **UI parity companion:** [`flutter-tui-ui-parity-plan.md`](./flutter-tui-ui-parity-plan.md)

This document is the durable source of truth for the rewrite. Future implementation work should update this document when an architectural decision, compatibility rule, parity requirement, or milestone changes.

## 1. Mission

Build a native Dart implementation of iTE’s runtime so that Flutter owns the complete user experience while Dart owns the complete agent execution model.

The final product must be able to:

1. Load configuration and credentials.
2. Create, restore, and persist sessions.
3. Stream model responses.
4. Assemble and execute tool calls.
5. Enforce approval and sandbox policy.
6. Modify and verify real workspaces.
7. Compact and recover context.
8. Run plans, todos, skills, memory, hooks, MCP tools, and subagents.
9. Display all runtime activity through a polished Flutter interface.
10. Support cloud inference and the remote runtime protocol.

The project is not a visual port. It is a runtime replacement with a new UI.

## 2. Non-negotiable architectural decisions

### 2.1 No Python in the production runtime

The Flutter application must not start, embed, or communicate with the Python runtime to perform normal agent work.

Python remains useful for:

- Understanding current behavior
- Generating deterministic reference traces
- Comparing Dart and Python outputs during migration
- Importing legacy session/configuration data

Once parity is reached, Python is no longer part of the application path.

### 2.2 New independent project

Create a new sibling project named `ite_flutter/`. Do not place the rewrite inside the current Python package and do not reuse the previous Flutter frontend as the runtime foundation.

The existing Python implementation stays intact while the rewrite is developed. This allows side-by-side testing without making the active runtime unstable.

### 2.3 Pure Dart core, Flutter presentation

The runtime core must not import Flutter. It should be usable from:

- Flutter desktop
- A future Dart CLI
- Headless integration tests
- A background/isolate execution host
- A future remote runtime server

Flutter widgets consume typed runtime events and never directly execute tools.

### 2.4 Desktop-first local execution

Local file access, arbitrary shell execution, git operations, PTY sessions, and workspace discovery are desktop capabilities. Mobile cannot safely provide equivalent behavior without a workspace host.

Therefore:

- Desktop is the first full-runtime target.
- Mobile initially acts as a remote/companion surface or a restricted client.
- Any future mobile-local capability must be explicitly designed and permissioned.

## 3. Current Python system map

The active source of truth is `ite/src/ite/`. The legacy UI snapshots under `src/ite/ui/reup/legacy/` are not part of this plan.

### 3.1 Runtime entry and orchestration

- `src/ite/main.py` — CLI entry point and startup modes
- `src/ite/agent/agent.py` — agentic loop, tool-call handling, retries, compaction recovery, planning, execution follow-through
- `src/ite/agent/session.py` — session composition, lifecycle, active plan, todos, skills, memory, subagents, change history
- `src/ite/agent/events.py` — runtime event contract
- `src/ite/agent/session_manager.py` — session snapshots, checkpoints, atomic persistence, corruption quarantine
- `src/ite/agent/subagent_runtime.py` — subagent lifecycle, concurrency, metrics, circuit breaking, cancellation, state restoration

### 3.2 Model and context

- `src/ite/client/llm_client.py` — OpenAI-compatible transport, cloud inference, streaming, tool calls, usage, retries, provider errors
- `src/ite/client/response.py` — streamed response types and token usage
- `src/ite/context/manager.py` — prompt assembly, transcript state, token estimates, compaction, pruning, usage
- `src/ite/context/compaction.py` — summary generation
- `src/ite/context/compact_artifacts.py` — persisted compaction summaries
- `src/ite/context/loop_detector.py` — repeated action/cycle detection
- `src/ite/context/transcript.py` — transcript event storage and restoration

### 3.3 Configuration and safety

- `src/ite/config/config.py` — typed configuration and policy models
- `src/ite/config/loader.py` — global/workspace layering, environment overrides, AGENTS.md loading, TOML persistence
- `src/ite/safety/approval.py` — approval decisions and command safety classification
- `src/ite/safety/sandbox.py` — workspace path validation
- `src/ite/safety/git_sandbox.py` — git-specific sandbox behavior
- `src/ite/tools/policy.py` — plan-mode and tool-selection policy
- `src/ite/hooks/hook_system.py` — blocking/background lifecycle hooks

### 3.4 Tools and extensions

- `src/ite/tools/base.py` — tool/result/confirmation/diff contracts
- `src/ite/tools/registry.py` — registration, normalization, validation, policy, approval, execution, telemetry
- `src/ite/tools/discovery.py` — workspace tool discovery
- `src/ite/tools/mcp/` — MCP transports, auth, OAuth, dynamic tools
- `src/ite/tools/subagent.py` — subagent definitions and tool behavior
- `src/ite/skills/` — skill discovery, trust, references, prompt rendering
- `src/ite/memory/` — persistent memory, intent parsing, retrieval, response controls

### 3.5 Active built-in tool inventory

The current runtime exposes 46 built-in tool classes. Port them by behavior and contract, not by Python file structure.

#### Filesystem and editing

- `read_file`
- `write_file`
- `edit`
- `apply_patch`
- `list_dir`
- `glob`
- `grep`
- `list_archive`
- `read_json`
- `edit_json`
- `read_toml`
- `write_toml`
- `read_yaml`
- `write_yaml`
- `read_env`
- `write_env`

#### Shell and verification

- `shell`
- `shell_start`
- `shell_poll`
- `shell_send`
- `shell_stop`
- `run_tests`
- `run_linter`
- `run_typecheck`

#### Git

- `git_status`
- `git_diff`
- `git_log`
- `git_branch`
- `git_commit`
- `git_push`
- `git_remote`

#### Network and media

- `http_request`
- `web_search`
- `web_fetch`
- `read_pdf`
- `read_image`
- `read_document`

#### Runtime and meta-tools

- `skills`
- `todos`
- `memory`
- `plan_question`
- `spawn_subagent`
- `spawn_subagents`
- `wait_subagent`
- `list_subagents`
- `cancel_subagent`
- `subagent_metrics`

### 3.6 UI and remote behavior

- `src/ite/ui/reup/` — active Textual UI implementation
- `src/ite/DESIGN.md` — visual/design behavior to reinterpret for Flutter
- `src/ite/remote/protocol.py` — versioned remote event/state serialization
- `src/ite/remote/server.py` — pairing, authentication, state sync, prompt/approval control

The Textual widget tree is not being ported. Its user-visible behaviors are being mapped to Flutter surfaces.

## 4. Target Dart architecture

```text
ite_flutter/
├── packages/
│   ├── ite_core/
│   │   ├── lib/
│   │   │   ├── domain/
│   │   │   ├── agent/
│   │   │   ├── context/
│   │   │   ├── tools/
│   │   │   ├── sessions/
│   │   │   ├── configuration/
│   │   │   ├── protocols/
│   │   │   └── ite_core.dart
│   │   └── test/
│   └── ite_platform/
│       ├── lib/
│       │   ├── filesystem/
│       │   ├── processes/
│       │   ├── git/
│       │   ├── secure_storage/
│       │   ├── networking/
│       │   └── ite_platform.dart
│       └── test/
└── apps/
    └── ite_app/
        ├── lib/
        │   ├── runtime/
        │   ├── state/
        │   ├── ui/
        │   ├── theme/
        │   └── main.dart
        └── test/
```

### 4.1 Domain layer

Use immutable, typed models for:

- Chat messages and content parts
- Tool calls and results
- Runtime events
- Usage
- Session snapshots
- Plans and todos
- Changes and diffs
- Skills and memory records
- Subagent runs
- Approval requests
- Runtime health/degraded state

Every model that crosses a process, persistence, network, or UI boundary must have explicit serialization.

### 4.2 Runtime layer

Core services:

- `AgentOrchestrator`
- `SessionRuntime`
- `ContextManager`
- `ModelGateway`
- `ToolRegistry`
- `ApprovalManager`
- `SandboxPolicy`
- `SessionStore`
- `ChangeHistory`
- `SkillManager`
- `MemoryManager`
- `HookSystem`
- `SubagentRuntime`
- `McpManager`

### 4.3 Platform layer

Abstract platform behavior behind interfaces:

- Filesystem access
- Process launching and cancellation
- PTY support
- Environment variables
- Path resolution
- Secure credential storage
- Application data directories
- Clipboard and file picking
- Native notifications if needed

No tool should call platform APIs directly when an interface can represent the operation.

## 5. Canonical runtime event pipeline

```text
user input
  ↓
session/runtime state update
  ↓
prompt construction
  ↓
model gateway streaming
  ↓
text/tool-call assembly
  ↓
tool policy and validation
  ↓
approval/sandbox checks
  ↓
tool execution and progress
  ↓
tool result appended to context
  ↓
continuation/compaction decision
  ↓
final response or next model turn
```

The UI receives only events and derived state. The runtime never depends on widget lifecycle or Flutter `BuildContext`.

## 6. Agent state machine

The Dart loop should be implemented as an explicit state machine rather than a single large method.

```text
idle
→ preparing_turn
→ requesting_model
→ streaming_response
→ awaiting_tool_execution
→ executing_tools
→ appending_tool_results
→ checking_continuation
→ completed
```

Alternative branches:

```text
checking_continuation → compacting → auto_resuming
checking_continuation → retrying_response
checking_continuation → loop_detected
any state → cancelled
any state → failed
```

Planning adds a second state machine:

```text
asking_questions
→ writing_plan
→ awaiting_implementation_confirmation
→ executing
→ summarizing
→ idle
```

Required parity behaviors:

- Maximum turns
- Empty response retry
- Incomplete response continuation
- Raw tool markup suppression
- Duplicate discovery caching
- Loop detection
- Execution follow-through
- Tool-call argument assembly
- Usage updates
- Threshold compaction
- Overflow compaction and recovery
- Plan question limits
- Plan/execution todo scopes

## 7. Phased implementation plan

### Phase 0 — Behavioral contract freeze

**Goal:** Convert the current Python behavior into observable fixtures.

Work:

- Define normalized event trace format.
- Build deterministic fake-model responses.
- Capture basic chat, tools, approval, shell, planning, compaction, subagent, MCP, and persistence scenarios.
- Record differences caused by timestamps, UUIDs, process IDs, and filesystem ordering.
- Define session/config compatibility requirements.

Exit criteria:

- At least one fixture exists for every major runtime branch.
- A future Dart implementation can be compared without inspecting widget output.

### Phase 1 — Dart workspace and contracts

**Goal:** Establish the new project without touching production behavior.

Work:

- Create `ite_flutter/` package workspace.
- Add linting, formatting, test, and CI commands.
- Define immutable domain models.
- Define JSON serialization.
- Define sealed runtime events.
- Add fake implementations for model, filesystem, process, persistence, and approval.

Exit criteria:

- Pure Dart tests run independently of Flutter.
- A fake runtime can emit a complete streamed turn.

### Phase 2 — Configuration and persistence

**Goal:** Read and write the same conceptual configuration and session state.

Work:

- TOML config loading and precedence.
- Environment overrides.
- Secure credential abstraction.
- Platform data directories.
- Atomic session writes.
- Corrupt-file quarantine.
- Checkpoints.
- Session listing by workspace.
- Snapshot compaction.
- Legacy Python session migration.

Exit criteria:

- Dart can restore a representative Python-created session.
- A crash during write does not corrupt the previous valid snapshot.

### Phase 3 — Model gateways

**Goal:** Stream equivalent model responses from direct and cloud providers.

Work:

- OpenAI-compatible HTTP transport.
- SSE parser.
- Tool-call delta assembly.
- Reasoning-content handling.
- Usage extraction.
- Cancellation and timeouts.
- Retry/error classification.
- Ollama/custom/OpenRouter support.
- iTE Cloud inference envelope and auth.

Exit criteria:

- Fake-model and real-provider streams produce identical normalized runtime events.
- Tool calls split across arbitrary stream chunks assemble correctly.

### Phase 4 — Agent orchestration

**Goal:** Achieve parity for the core loop before porting every tool.

Work:

- Implement the agent state machine.
- Add context manager integration.
- Add tool-call event emission.
- Add continuation and retry behavior.
- Add compaction and overflow recovery.
- Add plan mode.
- Add execution follow-through.
- Add loop detection.

Exit criteria:

- Core Python/Dart traces match for fake-model fixtures.
- The Dart runtime can execute a no-op tool and continue correctly.

### Phase 5 — Safety and tool framework

**Goal:** Make tool execution safe before adding powerful tools.

Work:

- Tool registry.
- Tool schemas.
- Parameter validation.
- Alias normalization.
- Risk metadata.
- Plan-mode policy.
- Approval manager.
- Sandbox validation.
- Command-safety classification.
- Tool progress callbacks.
- Tool telemetry.

Exit criteria:

- A blocked tool cannot execute.
- A rejected approval cannot execute.
- A path escape cannot read or write.
- Tool failures become structured results rather than runtime crashes.

### Phase 6 — Core tools

**Goal:** Make the Dart runtime useful on a real workspace.

Port in this order:

1. `read_file`, `list_dir`, `glob`, `grep`
2. `write_file`, `edit`, `apply_patch`
3. `shell`
4. `shell_start`, `shell_poll`, `shell_send`, `shell_stop`
5. `git_status`, `git_diff`, `git_log`, `git_branch`
6. `run_tests`, `run_linter`, `run_typecheck`
7. `git_commit`, `git_push`, `git_remote`
8. JSON, TOML, YAML, environment, archive, and media tools

Exit criteria:

- The runtime can inspect, edit, verify, and review a real workspace.
- Every mutating tool produces a reviewable `ToolResult` and, where applicable, a `FileDiff`.

### Phase 7 — Context, memory, skills, hooks, and subagents

**Goal:** Reach behavioral parity for the supporting runtime systems.

Work:

- Persistent memory stores and retrieval.
- Session memory.
- Skills discovery and trust.
- Reference-file loading.
- Hook execution and history.
- Subagent spawning, waiting, cancellation, metrics, and circuit breaking.
- Todo persistence and plan/execution scopes.
- Change history undo/redo and conflict detection.

Exit criteria:

- The major context and lifecycle features survive session save/reload.
- Degraded capabilities are reported without preventing unrelated runtime features.

### Phase 8 — MCP and extension migration

**Goal:** Replace Python extension mechanisms with Dart/language-neutral mechanisms.

Work:

- MCP stdio.
- Streamable HTTP/SSE.
- OAuth and client credentials.
- Dynamic tool registration.
- Server startup failure isolation.
- Dart-native discovered tools.
- Language-neutral executable tool protocol.
- Migration documentation for existing `.ite/tools/*.py` tools.

Decision:

Python custom tools will not be silently executed by the Dart runtime. They must either be migrated to Dart or exposed through an explicit external-process protocol.

Exit criteria:

- MCP tools behave like built-in tools.
- Extension failures do not crash the agent.
- The migration path for existing user tools is documented and testable.

### Phase 9 — Flutter UI and Flow UI integration

**Goal:** Build the native iTE experience on top of the runtime event stream.

Use [`flow_ui`](https://pub.dev/packages/flow_ui) for the conversational base. At planning time it provides `FlowChatScreen`, `FlowThread`, `FlowMessage`, `FlowComposer`, streaming indicators, model selection, attachments, menus, theming, and custom message parts.

Integration rules:

- Pin the package to a known minor version.
- Wrap it behind iTE adapters.
- Keep persisted transcript models independent of `FlowMessageData`.
- Map runtime events to presentation models through a reducer.
- Use custom parts for tools, approvals, diffs, shells, plans, todos, and subagents.
- Provide fallback rendering for unknown custom parts.
- Add golden tests for every custom part.

Recommended adapter structure:

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

Build the surrounding iTE shell independently:

- Session/workspace sidebar
- Change review panel
- Context/usage panel
- MCP and skills status
- Settings and setup screens
- Command palette
- Desktop window layout

Exit criteria:

- A user can prompt, watch streaming output, inspect tool activity, approve a change, and review a diff without leaving the main surface.

### Phase 10 — Cloud and remote runtime

**Goal:** Port service and companion capabilities after local parity is stable.

Work:

- Cloud auth and secure token storage.
- Bundled inference.
- Usage and entitlement status.
- Cloud error/fallback behavior.
- Dart remote server.
- Pair code and reconnect tokens.
- Versioned line-delimited JSON protocol.
- Remote state snapshots.
- Prompt, cancellation, session switching, approvals, and plan questions.

Exit criteria:

- Dart runtime can be controlled by the existing remote protocol or a documented protocol version.
- Mobile can reconnect and recover state after temporary network loss.

### Phase 11 — Differential validation and hardening

**Goal:** Prove parity and safety before cutover.

Work:

- Python/Dart fixture comparison.
- Property tests for serialization and stream assembly.
- Tool sandbox tests.
- Approval bypass tests.
- Shell cancellation and process cleanup tests.
- MCP fixture servers.
- Persistence crash tests.
- Large transcript performance tests.
- Desktop integration tests.
- Flutter golden and interaction tests.

Exit criteria:

- No critical parity differences remain unexplained.
- No known approval, sandbox, credential, or process-leak vulnerabilities remain.

### Phase 12 — Cutover

**Goal:** Make Dart the product runtime.

Rollout order:

1. Demo mode
2. Read-only workspace mode
3. Editing and approval mode
4. Shell/git/verification mode
5. Full local parity
6. Cloud and remote parity
7. Default Dart runtime
8. Python runtime archived as reference tooling

Keep a rollback path until several real workspaces have been restored, edited, verified, and reopened successfully.

## 8. Flow UI integration contract

### Use directly

- `FlowChatScreen`
- `FlowThread`
- `FlowComposer`
- `FlowMenu`
- `FlowModelSelector`
- `FlowAttachmentGroup`
- `FlowStreamingText`
- `FlowThinkingIndicator`
- `FlowSuggestionGroup`

### Wrap with iTE adapters

- Tool cards
- Approval cards
- Unified diffs
- Shell sessions
- Plan questions
- Todo/workboard state
- Subagent activity
- Context compaction notices
- Runtime degraded-state notices

### Package risks

The package is pre-1.0 and its API is still settling. Minor releases may contain breaking changes. Pin the version, wrap public types, and maintain a small compatibility test suite. ([flow_ui package](https://pub.dev/packages/flow_ui))

The package’s visual defaults should be treated as inspiration and a useful starting point, not as the complete iTE design system. iTE still needs its own spacing, surfaces, state colors, desktop chrome, accessibility rules, and interaction conventions.

## 9. Persistence and migration rules

### Configuration

Support:

- Existing TOML keys where their semantics remain valid
- Global/workspace precedence
- Environment overrides
- Secure credential migration
- Explicit warnings for unsupported keys

### Sessions

Support:

- Existing session IDs
- Workspace filtering
- Transcript restoration
- Usage restoration
- Plan/todo restoration
- Active skills
- Change history where safe
- Compaction artifact references

Invalid or incomplete snapshots should be quarantined rather than silently discarded.

### Skills

Preserve markdown/YAML skill discovery and trust semantics. Skills are content, not executable Python plugins.

### Custom tools

Provide a migration guide from `.ite/tools/*.py` to:

- Dart-native tools
- MCP servers
- Language-neutral executable tools

## 10. Platform capability matrix

| Capability | macOS | Linux | Windows | Mobile | Web |
|---|---:|---:|---:|---:|---:|
| Local workspace files | Full | Full | Full | Restricted | Restricted |
| Arbitrary shell | Full | Full | Full, platform-specific | No by default | No |
| PTY shell sessions | Required | Required | Separate implementation | No by default | No |
| Git | Full | Full | Full | Remote only initially | No |
| Local MCP stdio | Full | Full | Full, tested separately | No | No |
| HTTP MCP | Full | Full | Full | Possible | Possible |
| Cloud inference | Full | Full | Full | Full | Possible |
| Remote companion | Full | Full | Full | Primary use case | Possible |

No feature should appear enabled on a platform where its underlying capability is unavailable.

## 11. Testing strategy

### Unit tests

- Domain serialization
- Event constructors
- Stream assembly
- Tool parameter normalization
- Policy decisions
- Sandbox path checks
- Approval decisions
- Token estimates
- Compaction selection
- Loop detection
- Memory scoring
- Skill parsing
- Session snapshot migration

### Integration tests

- Fake model plus real orchestrator
- Temporary filesystem tools
- Shell lifecycle
- Git worktrees
- Persistence crash/recovery
- MCP fixture servers
- Hook commands
- Subagent lifecycle
- Cloud mock server
- Remote protocol client/server

### Flutter tests

- Conversation rendering
- Streaming updates
- Custom tool parts
- Approval flows
- Diff review
- Composer behavior
- Session switching
- Responsive desktop/mobile layouts
- Accessibility semantics
- Golden snapshots for important surfaces

### Differential tests

Run the same deterministic scenarios through Python and Dart and compare normalized traces. Normalize only values that are inherently nondeterministic; do not normalize away meaningful behavioral differences.

## 12. Security requirements

- Never log API keys, cloud tokens, MCP secrets, or voice credentials.
- Store credentials in platform secure storage where available.
- Validate every filesystem path against the active sandbox.
- Classify dangerous shell commands before approval.
- Treat approval rejection as a terminal non-execution result.
- Kill child processes and process groups on cancellation.
- Redact sensitive command text in UI and telemetry.
- Validate MCP TLS/auth configuration.
- Expire remote pair codes.
- Keep reconnect tokens scoped and revocable.
- Require explicit confirmation for destructive git/filesystem operations.
- Preserve audit-relevant tool metadata without storing secrets.

## 13. Performance requirements

- Streaming text must not rebuild the entire transcript for every token.
- Long transcripts must be virtualized or incrementally rendered.
- Tool output must be capped and progressively loaded where possible.
- Large diffs must render lazily.
- CPU-heavy parsing and indexing may move to isolates.
- Shell output must use bounded buffers and cursors.
- Startup should initialize optional MCP, memory, and skill systems independently so one failure does not block the runtime.
- Session snapshots must not block the UI thread.

## 14. First implementation sequence

The next work should be deliberately narrow:

1. Create `ite_flutter/` with pure Dart and Flutter packages.
2. Add domain models and sealed runtime events.
3. Add a deterministic fake model gateway.
4. Add a minimal `AgentOrchestrator` with text streaming and one fake tool.
5. Add event reduction into presentation state.
6. Integrate pinned `flow_ui`.
7. Render user messages, assistant streaming, thinking, and one custom tool part.
8. Add a fake approval request and custom approval card.
9. Add the desktop shell around `FlowChatScreen`.
10. Capture the first Flutter golden/demo flow.
11. Only then begin real filesystem and shell tools.

The first vertical slice is successful when it can show:

```text
prompt → streamed response → tool activity → approval → result → final response
```

without Python involvement.

## 15. Definition of done

The rewrite is complete when:

- Dart is the only production runtime.
- Flutter is the primary UI.
- Core runtime behavior matches the agreed Python reference fixtures.
- All 46 built-in tool capabilities are ported or explicitly replaced.
- Safety, approval, sandbox, and cancellation behavior is tested.
- Sessions and configuration migrate safely.
- Context compaction and recovery work in real long-running sessions.
- Skills, memory, hooks, MCP, subagents, git, media, and verification are available at parity or have documented intentional replacements.
- Cloud and remote protocols are supported.
- Desktop packaging works on the supported platforms.
- Mobile behavior is honest about local-runtime limitations.
- Flow UI is isolated behind adapters so it can evolve independently.
- The talk demo works offline or through deterministic replay.

## 16. Working rule for future changes

Every implementation change must answer four questions:

1. Which Python behavior or contract is being replaced?
2. Which Dart layer owns the behavior?
3. How is it observed through runtime events?
4. Which fixture, unit test, integration test, or UI test proves it?

If a feature cannot answer those questions, it is not ready to be considered part of the rewrite.

## 17. Current implementation checkpoint — 2026-08-19

The rewrite is active in the sibling `ite_flutter/` workspace. The current
position by phase is:

| Phase | Status | Evidence / boundary |
|---|---|---|
| 0 — Behavioral contract freeze | Partial | Typed runtime events and deterministic fake gateways exist; Python/Dart normalized trace fixtures are not complete. |
| 1 — Dart workspace and contracts | Substantially complete | `ite_core` and `ite_platform` packages, JSON models, events, reducers, fakes, and tests are in place. |
| 2 — Configuration and persistence | Partial | File-backed session persistence, workspace filtering, atomic replacement, malformed-record recovery, and OS-storage boundary interfaces exist; TOML parity, production secure-storage activation, quarantine, checkpoints, and legacy migration remain. |
| 3 — Model gateways | Partial | Cloud model streaming, tool-call assembly, reasoning, usage, auth integration, and cooperative cancellation exist; provider breadth, retries, timeout classification, and differential stream fixtures remain. |
| 4 — Agent orchestration | Partial | Streamed turns, continuation through tools, usage, cancellation, approval events, plan-mode instruction, deterministic context compaction, and compaction events exist; loop detection, retry policy, provider-backed summaries, and the full planning state machine remain. |
| 5 — Safety and tool framework | Substantially advanced | Central schema/unknown-tool validation, plan-mode blocking, approval metadata, shell risk classification, catastrophic-command blocking, structured rejection, and workspace path validation are tested; full telemetry and complete command policy remain. |
| 6 — Core tools | Early usable slice | `read_file`, `list_dir`, `glob`, `grep`, approval-gated `write_file`, `edit`, bounded/cancellable `shell`, and runtime `git_status`, `git_diff`, `git_branch`, `git_log`, and `git_commit` are implemented. Patch tooling, PTY sessions, verification, push/remote, and media tools remain. |
| 7 — Context, memory, skills, hooks, and subagents | Contracts added | Serializable plan/todo/skill/memory/subagent/capability models and in-memory managers exist; filesystem discovery, durable stores, hooks, real subagent execution, and runtime event producers remain. |
| 8 — MCP and extension migration | Not started | The UI reports MCP/skills as not connected rather than presenting them as enabled. |
| 9 — Flutter UI and Flow UI integration | Desktop slice implemented | iTE theme, responsive shell, composer/status rail, custom runtime parts, approval surface, session drawer, Git review, and tests are implemented. |
| 10 — Cloud and remote runtime | Partial | Cloud auth/inference status is connected; remote Dart runtime, reconnect, pairing, and mobile state sync remain. |
| 11 — Differential validation and hardening | Early | Analyzer, broad core/platform/app tests, cancellation/safety/compaction tests, responsive tests, Git tests, and macOS debug build pass; golden, crash, secure-storage, performance, and Python/Dart differential suites remain. |
| 12 — Cutover | Not started | Python remains the behavioral reference; Dart is not yet the complete production replacement. |

The UI checkpoint is intentionally documented separately in
`flutter-tui-ui-parity-plan.md`. A polished Flutter shell should not be read as
evidence that the complete 46-tool runtime, remote protocol, or mobile local
execution model has already been ported.

### Development credential caveat

The current macOS debug checkpoint intentionally uses `FileStorageAdapter`
because the secure-storage plugin has not been stabilized in the debug target.
This stores the development session JSON in the application-support directory
and is not an acceptable production credential boundary. Before release, the
app must switch to an OS-backed secure-storage adapter and pass a macOS signed
build smoke test; this caveat is a release gate, not an intentional final
replacement.

### Current stopping-point verification

Before using the current slice for manual testing, run from `ite_flutter/`:

```text
flutter pub get
flutter analyze
flutter test apps/ite_app/test packages/ite_core/test packages/ite_platform/test
flutter build macos --debug
```

The last command is a build check only; manual macOS debug use still carries
the file-backed credential caveat above.
