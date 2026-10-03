# MCP Connections: implementation plan

**Status:** Proposed implementation plan; implementation has not started.
**Date:** 3 October 2026
**Baseline:** iTE 0.2.32; [current-state audit](mcp-current-state-audit.md).
**Product decision:** Settings → Connections (MCP) → dedicated management page. Use focused modals for adding, credentials, and destructive confirmations. All ordinary workflows must be available through visible TUI controls.

## 1. Outcome and scope

Users should connect services to iTE without knowing TOML, transport names, environment-variable syntax, or MCP internals. They must be able to add, sign in, use, reconnect, configure, disable, and remove a connection inside Reup. Advanced users retain custom commands, configuration files, and CLI automation.

This work covers the entire MCP path: configuration and persistence, credentials, authentication, process startup, transport lifecycle, agent capability exposure, permissions, schemas and results, diagnostics, TUI navigation, command compatibility, remote behavior, documentation, packaging, and verification.

Success means:

- Settings contains a discoverable Connections entry, accessible without a slash command.
- Users can complete an authenticated connection journey without editing a file or restarting iTE.
- A connection's displayed state reflects its actual condition and offers an appropriate next action.
- Changing, signing out, or removing connection A does not damage connection B or unrelated iTE credentials.
- Capabilities and account/project scope are understandable and enforceable.
- Local executable launch has a clear trust boundary; connection consent and individual action approval remain distinct.
- Existing configurations work through a documented compatibility path.
- Shared operations power TUI, CLI, slash commands, and remote surfaces.

The first release includes custom remote URLs, custom local servers, supported authentication methods, capability management, and a small verified catalog. Catalog expansion, MCP resources/prompts, and embedded MCP application interfaces are later milestones with explicit gates; they must not block the complete tools-based connection journey.

## 2. Confirmed baseline and implementation constraints

The audit verified a real local stdio server through connect, discovery, tool call, stop, and shutdown. The focused baseline suite reported 73 passed, 2 failed, and 2 subtests passed. The two failures concern tests expecting global secrets during config load while implementation reads them lazily at connect. Resolve that contract explicitly rather than changing tests merely to make them green.

The active code is in `src/ite/ui/reup/`, its mixins and widgets. Do not use historical files in `legacy/`. New imports use canonical widget/helper modules, not migration re-exports from `app.py`.

Follow [DESIGN.md](../../DESIGN.md): active-theme tokens, compact terminal layouts, restrained surfaces, readable light themes, keyboard access, themed centered modals, visible action rows, and transient notices for routine success. Avoid unrelated Settings restyling. The current `SettingsPanel` is a mounted shell surface, not a full-screen Textual `Screen`; extend its navigation deliberately rather than replacing the app shell.

## 3. Navigation and page structure

```text
Chat → Settings
         └─ Connections (MCP) · Manage
              ├─ Connections list
              │    ├─ Add connection modal
              │    └─ Connection detail page
              │         ├─ Sign-in / credential modal
              │         ├─ Configuration and access
              │         ├─ Available tools
              │         ├─ Troubleshooting
              │         └─ Remove / sign-out confirmation
              └─ Back to Settings → Back to chat
```

### Settings entry

Add a section near session configuration and Permissions, separate from cloud account/plan content. Label it **Connections (MCP)**, explain “Connect services and tools to iTE,” show connected/attention counts, and provide a real **Manage connections** button.

Opening this page must not depend on cloud sign-in, subscription status, successful MCP initialization, or completion of account/usage requests. Populate from a local snapshot immediately and refresh asynchronously.

### Connections list

Header: Back to Settings, Connections, Add connection. Include a search/filter control when list size warrants it. Rows show display name, textual status, scope, and a short action/failure summary. Provider or endpoint details belong in the detail view or secondary text. Include disabled, invalid, and disconnected entries. An empty state offers Add connection directly.

Keep row order stable during state changes. Preserve selection, focus, and scroll across refresh. A status update must not remount the full page or move a focused row. Use a single-column layout on narrow terminals; an optional list/detail arrangement on wide terminals must share the same navigation semantics.

### Connection detail

Show name, description/provider, actual status, scope, authenticated account when verifiable, and primary contextual action. Sections cover connection settings, credentials, available tools/access, startup behavior, and troubleshooting. Put advanced transport, headers, command arguments, working directory, timeout, and context-resolution controls behind an Advanced disclosure.

Provide distinct controls for Connect, Disconnect, Enable/Disable, Sign in, Reconnect, Sign out, Edit, and Remove. Do not label a disconnect as removal or a credential reset as a generic reset. Reveal inherited global definitions and project overrides so users understand which record an edit affects.

| Action | Meaning |
|---|---|
| Connect | Establish a live session and discover allowed capabilities. |
| Disconnect | Stop this session's connection; preserve definition and credentials. |
| Disable | Persist the disabled setting and stop exposing capabilities. |
| Reconnect | Replace the failed/stale session using saved credentials; does not blindly repeat a previous action. |
| Sign out | Disconnect and clear credentials for the selected account binding only. |
| Remove | Delete the selected definition and its unshared credential binding after confirmation. |
| Copy to another scope | Create a separate definition; do not copy secret values implicitly. |

### Focus and responsive behavior

Tab/Shift+Tab reach every action; Enter activates; Escape closes the current modal or returns one page level. Dirty edits require Save/Discard/Keep editing. Closing an untouched modal leaves no stored connection. Cancel during sign-in/connection cancels the operation and cleans up listeners/processes.

Restore focus to the originating control after a modal and to the selected row after returning from details. Retain chat/composer state when entering/leaving Settings. Test at 80×24 and 60×20, plus a large terminal; ensure scrolling keeps essential actions reachable. Handle long names, URLs, tool descriptions, Unicode, empty names, and hundreds of tools without horizontal clipping. State must never rely on color alone.

## 4. Add and edit journeys

### Supported entry choices

1. **Choose a service:** small bundled catalog with verified setup recipes.
2. **Paste a connection URL:** custom hosted HTTP/SSE setup; auto transport inference with an advanced override.
3. **Import a configuration:** explicitly selected JSON/TOML input, including common `mcpServers` JSON shapes, validated and previewed before saving or executing.
4. **Run a local server:** advanced command plus separate argument list, environment fields, and working-directory picker/input.

All choices converge on the same draft model and operation service. Display name is separate from immutable identity and tool namespace. URL-only setup should normally need a name, authentication choice, and scope; keep protocol details out of the normal path.

### Draft → review → save/connect

- Validate required fields inline; reject contradictory command/URL/transport/auth combinations.
- Validate URL schemes, nonempty commands, argument structure, positive bounded timeouts, callback ports, names, and credential-field requirements.
- Remote defaults require HTTPS; allow HTTP for explicit local development endpoints with clear context.
- Authentication discovery must be cancellable and bounded. Use verified catalog metadata or supported server discovery; do not infer a required secret from a failed call alone.
- Preview imported definitions individually, reject unsupported fields with useful messages, and identify inline secrets without displaying their values. Never automatically import another app's stored credentials.
- Show what a local executable will run, its source, and dependency requirements before authorizing startup.
- Persist a valid definition independently from the connection attempt. Save and connect is the default; failed authentication/connection leaves a manageable entry with Retry/Edit/Remove. Save for later is available.
- Secret values go directly to credential storage, never through composer submission or agent conversation content.
- Editing a live endpoint/command/auth configuration requires a controlled disconnect and reconnect. A failed replacement retains a repairable saved definition; never keep old tools advertising a new endpoint.

### Scope and accounts

Use **Available in all projects** and **Only this project** in the UI. Keep global/workspace names in advanced help. Credentials/account choice and availability scope are distinct: a project-specific account must not silently reuse a global account.

A project definition may override a global definition. Show that relationship and provide explicit removal choices: remove the project override (reveals global), or disable in this project (persists a project tombstone/disabled override). Removing an override must not unexpectedly launch the revealed global connection.

Multiple accounts for the same provider are separate records. Account identity is shown only when returned by a trusted provider/API. Otherwise show “Account details unavailable” and a user-supplied label. Changing scope or renaming preserves the correct credential binding; copying requires explicit account selection/sign-in.

## 5. Domain model and shared service

Retain TOML as the compatible definition format. Introduce typed runtime/storage abstractions; do not add a second competing authoritative configuration database.

| Model | Responsibilities |
|---|---|
| `ConnectionDefinition` | Stable ID, display name, provider ID, protocol namespace, scope/origin, enabled/auto-connect, transport settings, credential reference, capability selection, validated revision. |
| `ConnectionDraft` | Unsaved form/import data, validation errors, intended scope and auth method; secrets are transient and excluded from repr/serialization. |
| `CredentialBinding` | Stable connection/account identity, workspace isolation when applicable, endpoint/auth fingerprint, store type; no secret values in public snapshots. |
| `ConnectionSnapshot` | Current definition, desired state, lifecycle status, auth phase, discovered capabilities/counts, sanitized failure, permitted next actions. |
| `ConnectionFailure` | Typed category, safe explanation, retryability, suggested actions, diagnostic correlation ID; raw details remain controlled. |
| `ConnectionEvent` | Connection ID, operation ID/revision, state/capability changes, sanitized progress; never credentials. |

Generate IDs for TUI-created records. For legacy records, derive a stable mapping from scope plus canonical workspace and legacy key until a user-approved normal save persists metadata. Endpoint/auth changes invalidate credential applicability and launch trust; display-name changes do not. IDs and mappings live in versioned metadata managed by the same repository abstraction.

Proposed service operations:

```text
list_connections / get_connection / subscribe
validate_draft / preview_import / save_definition / edit_definition
copy_definition / remove_definition / set_enabled / set_auto_connect
set_credentials / sign_in / sign_out / change_account
connect / disconnect / reconnect / cancel_operation
discover_capabilities / set_capability_selection
diagnose / export_sanitized_diagnostics / reconcile_configuration
```

The service owns mutation order, rollback/repair state, scope semantics, locking, operation cancellation, and registry synchronization. UI handlers render snapshots and call operations; they do not mutate `manager._clients`. Commands and remote adapters use these same methods.

Have an application-scoped definition/credential repository and an explicitly session-scoped runtime manager initially. All sessions observe repository revision changes; disabled/removed definitions invalidate capabilities in every applicable live session. Keep OAuth interactions serialized per credential binding, and avoid accidental sign-out races between sessions. Do not share transports across sessions unless separately designed and tested.

## 6. Lifecycle and state contract

Separate saved enabled state, live connectivity, and authentication progress. States exposed to users:

| State | User-facing next action |
|---|---|
| Needs setup / invalid | Edit settings; show the specific invalid field. |
| Disabled | Enable. |
| Disconnected | Connect. |
| Needs sign-in | Sign in / enter key. |
| Connecting | Progress and Cancel. |
| Waiting for sign-in | Open browser/link, Cancel, or Retry after failure. |
| Connected | Tools/access, Disconnect, or Edit. |
| Reconnecting | Progress and Cancel. |
| Failed | Safe explanation with Retry, Edit, Sign in, or Troubleshoot as appropriate. |

Maintain an operation ID and definition revision so late worker events cannot overwrite a newer edit, remove, cancel, or workspace switch. Serialize lifecycle changes per connection; deduplicate double clicks. Bound startup, sign-in, calls, diagnostics, and shutdown separately.

Reconcile adds, edits, disabled entries, removals, external TOML edits, and workspace changes. Last valid unrelated configurations remain usable when one definition is invalid. Represent parse errors as management entries; do not expose invalid definitions to the agent. Do not rewrite a malformed file automatically; offer repair/import or a safe save strategy after review.

Mark transport failures unhealthy and remove stale callable capabilities. Authentication failures become needs-sign-in where classification is reliable. Update session degradation summaries when service availability recovers, rather than leaving a permanent startup warning. Counts distinguish configured, enabled, connected, available tools, and needs-attention states.

Reconnect with bounded backoff and no tight idle polling. Respect explicit disconnect and disable throughout the session. Auto-connect should not unexpectedly open a browser on startup: attempt saved credentials, then present needs-sign-in. Explicit Sign in initiates the browser interaction.

## 7. Credentials, OAuth, and persistence

### Required repairs

- Preserve all unrelated TOML tables when updating MCP secrets/config; quote server keys correctly and preserve comments where feasible.
- Make writes atomic and use cross-process locking or a revision-checked equivalent; prevent shared temporary-file and lost-update races.
- Invalidate affected cache entries after every credential mutation and external revision change.
- Resolve legacy environment precedence explicitly: inherited process environment → global definition env → global saved env → project definition env → project saved env. Later layers win. Preserve placeholder provenance so a final injected value can satisfy a configured placeholder; unresolved placeholders fail with a field-specific message.
- Do not overwrite config objects with resolved secrets. Build ephemeral effective connection settings for startup/calls and redact their repr/logging.
- One connection's reset/sign-out/remove must never delete the whole OAuth store or unrelated credential sections.

### Credential storage contract

Prefer OS keyring for newly entered API keys, sensitive headers, client credentials, and persisted OAuth material. Store nonsecret references in TOML. Namespace by stable connection/account identity and workspace where applicable, not just server name. Audit declared dependencies and frozen-runtime keyring backends.

If secure storage is unavailable or locked, show a repairable state and allow retry/unlock guidance. Offer explicit session-only credentials. Never silently fall back to plaintext disk. Preserve legacy plaintext support for compatibility, clearly show its storage source, and offer a one-time move to secure storage. Migration must verify the new credential before deleting the old value.

Disconnect does not clear credentials. Sign out deletes only the selected binding. Remove deletes unshared credentials; warn when an explicitly shared binding is referenced elsewhere. Provider-side revocation is a separate action when supported; local sign-out must not claim remote revocation occurred.

### Browser OAuth

Keep the verified SDK OAuth implementation for protocol details and wrap it with storage, typed progress, bounded cancellation, and endpoint/binding isolation. Verify discovery, refresh, PKCE/state behavior, callback cleanup, and API compatibility against the SDK version chosen for distribution.

Present browser opening, waiting, completed, cancelled, and failed states. Provide a fallback authorization link when opening the browser fails, without recording callback codes/tokens in transcript/logs. Reject stale callbacks after cancellation. Clean up callback listeners on timeout, shutdown, workspace switch, and cancelled operations.

For remote sessions, do not open a loopback callback on the user's phone and imply it reaches the iTE host. Detect unsupported flow, explain that sign-in must occur on the host, and retain a pending connection; implement a secure remote handoff only after a separately tested design. Device-code flow may be used only when the provider supports it.

### Client credentials and token/header auth

Provide masked fields with plain labels for token endpoint, client ID, client secret, optional scope, and header name/value. Treat sensitive header values and `auth` tokens as credentials. Validate all required fields before saving/starting. Bound token requests, serialize refresh, and report revoked/invalid credentials accurately. Define one bounded refresh retry where safe; do not endlessly retry 401/403 responses or assume every 403 is token expiry.

### Secret containment

Redact legacy `/mcp env set` input before composer history and any command feed/remote serialization. Scan UI errors, logs, stderr tails, diagnostics exports, clipboard operations, session metadata, telemetry, and exception reprs. Diagnostic bundles exclude tokens, authorization URLs with sensitive query data, environment values, sensitive headers, and raw output containing known secrets. Clear secret form references after submit/cancel as far as the language/runtime permits.

## 8. Local launch trust and permissions

Before first local launch, show executable/package source, arguments, working directory, relevant file access, and environment policy. Launch consent is stored outside project-controlled TOML and bound to workspace/definition command fingerprint. Imported/project-provided auto-connect commands cannot self-authorize. Changed executable/arguments/cwd invalidate consent. Background startup surfaces needs-approval rather than blocking chat with an unsolicited prompt.

Use the minimum required inherited environment for new guided local connections; explicitly configure required pass-through values. Provide a documented compatibility migration for legacy inherited-environment behavior. Do not claim that the subprocess is OS-sandboxed. Detect missing executables and dependencies without installing or executing arbitrary imported scripts. Show supported install instructions; any future install action needs explicit source/version review.

Reuse current permission modes for individual MCP calls. Connection consent does not grant unrestricted remote actions. Server annotations are hints; unknown actions remain conservative. Preserve learning-mode execution rejection and review plan-mode read-only behavior against the trust model. User-disabled capabilities are rejected at execution, even if a model emits a stale or guessed tool name.

## 9. Tool schemas, capability exposure, and results

- Preserve canonical complete JSON Schema, including `$defs`, refs, combinators, enums, and top-level constraints. Adapt only at provider boundaries when needed and test those adaptations; never silently drop required meaning.
- Keep legacy `server__tool` aliases stable where valid. Separate display-name changes from protocol namespaces; detect collisions and handle provider name limits with deterministic mappings rather than raw truncation.
- Persist per-connection enabled tools/capability groups. Show purposes, read/write/destructive hints, and limitations in ordinary language. New capabilities discovered after setup remain unselected until reviewed under the connection's configured policy.
- Refresh capabilities through supported notifications or explicit refresh; guard with revision checks. Apply registry changes atomically and reject stale removed/disabled invocations. Define behavior for in-flight calls: prevent new calls immediately, cancel only when supported, and show uncertain outcomes for interrupted writes.
- Initially expose selected tools through the existing catalog. Measure large catalogs, then add demand-based discovery using existing optimizer/client facilities where appropriate; do not ship competing selection systems.
- Preserve structured content, text, image/audio blocks, resource references, errors, and metadata in an internal result envelope. Adapt for model modality support and TUI rendering. A structured-only result must not become an empty success.
- Bound result size and media decoding; do not fetch arbitrary resource URLs automatically or render raw base64 in chat. Explain unavailable media support and retain safe metadata/references.
- Remove identifier-name heuristics that turn optional schema inputs into required fields. Explicit schema requirements and provider-specific declared context hints may provide recovery suggestions without rejecting valid calls.
- Error copy describes the actual state. Say “Retry” or “You can reconnect” when no retry is scheduled; show retry progress only for real operations.

### Retry rules

Reconnect restores connectivity; it does not automatically replay the last tool call. A timeout/drop after dispatch may mean a write succeeded. Mark such results “Outcome unknown” and offer verification. Replay only under an explicitly trusted safe/idempotent contract and bounded policy; server annotations alone are insufficient proof. Authentication refresh and transport retry must not multiply attempts independently.

## 10. Diagnostics and observability

Replace configuration-only doctor output with shared structured checks: definition validity, scope/source, credential availability/storage health, executable resolution, transport support, bounded endpoint/connectivity/auth discovery, callback availability, handshake, and tool discovery.

Opening Troubleshoot is read-only and must not run tools or launch an unapproved local process. Offer explicit Test connection and Refresh tools actions. Never invoke a random discovered tool as a health probe. Provider-specific read-only checks require a reviewed recipe and user-visible purpose.

Display actionable categories: missing dependency, invalid setup, sign-in needed, insufficient access, unreachable endpoint, startup/call timeout, server exited, unsupported transport, schema incompatibility, and storage unavailable. Keep technical details expandable and sanitized. Allow safe diagnostic export with a preview.

Log connection/operation IDs, transport category, state transitions, timing, tool counts, retry counts, and sanitized failure categories. Do not add telemetry uploads as part of this feature. Define log rotation/retention and keep diagnostic overhead bounded.

## 11. Commands, remote access, and compatibility

| Surface | Planned behavior |
|---|---|
| Settings → Manage connections | Primary full management interface. |
| `/mcp` | Opens the same Connections page in Reup. |
| `/mcp list` | Explicit textual/status output for command/remote use. |
| `/mcp add` | Opens Add connection in Reup. |
| `/mcp copy <name> --scope ...` | Explicit scope-copy operation. |
| `/mcp start`, `/mcp stop`, `/mcp doctor` | Shared-service shortcuts preserving known names. |
| `/mcp reset <name>` | Compatibility alias for a clearly documented connection-specific credential operation; never global token deletion. |
| `ite mcp add ...` | Same create/validate/persist service; support prompted credentials/auth options without secrets in argv by default. |
| Additional CLI management | List, edit, remove, enable/disable, connect/test, auth/sign-out, import/export, doctor as supported operations; structured safe output and predictable exit codes. |

Do not silently change the old `/mcp add <existing-name> --scope ...` copy behavior. Route unambiguous legacy usage to copy with a deprecation notice; conflicting/new syntax must explain the replacement. Update help catalog, command completion, native dispatch, streaming cards, and remote command handling together.

Remote clients use typed safe snapshots and service operations; redact credentials in events. Enforce existing remote authorization and apply host-side launch/action consent. Resource/media references must not expose host-local files accidentally. Preserve protocol compatibility or version new messages explicitly. Unsupported remote sign-in has a visible host-action-required state rather than hanging.

Existing `[mcp_servers.*]` definitions remain readable. Preserve enabled/auto-connect, env placeholders, headers, cwd, context-resolution maps, and supported transport/auth settings. Warn about unsupported settings without discarding unrelated servers. Configuration export excludes credentials by default and explains required sign-in after import.

## 12. Catalog and extended protocol support

Bundle a small versioned catalog so Add connection works without downloading executable recipes at runtime. Entries include provider ID, display label, purposes, verified URL or pinned local recipe, auth method, credential fields, required scopes/dependencies/platforms, docs/help, recovery instructions, and verification date. **GitHub and Notion are the two required initial provider test targets and catalog candidates.** They cover developer workflows and everyday knowledge work. Additional providers can follow actual end-to-end validation; this plan does not claim provider certification.

Catalog failures never prevent custom URL/local setup. Avoid arbitrary package upgrades and unreviewed remote recipes. Local installs must name what will run. Catalog updates and package update policy need explicit provenance/version handling.

### Required real-provider test targets: GitHub and Notion

Provider documentation was checked on 3 October 2026. These are selected test targets, **not integrations already verified in iTE**. Recheck provider requirements when implementing and record actual discovered tool schemas rather than hard-coding a permanently fixed tool list.

| Provider | Primary connection | Authentication test | Why it belongs in the first test set |
|---|---|---|---|
| GitHub official MCP | `https://api.githubcopilot.com/mcp/`, Streamable HTTP | Personal access token entered in a masked field and sent as a bearer authorization header. Also validate browser OAuth where iTE's client registration and provider policy permit it; do not promise custom-host OAuth before verifying it. | Repository/issue workflows, secret headers, permission-restricted tools, large catalogs, and selected capabilities. |
| Notion hosted MCP | `https://mcp.notion.com/mcp`, Streamable HTTP | Interactive browser OAuth and workspace selection. The hosted service currently requires interactive authorization; do not substitute a Notion API token as if it were equivalent. | Notes/pages for ordinary users, browser callbacks, account/workspace selection, and content access. |

GitHub supports hosted and local deployment, with provider-side read-only/toolset configuration. Use its documented read-only header or endpoint for the initial read checks; use a deliberately writable sandbox connection for mutation checks. Provider OAuth may require a client application/registration and be limited by organization policy. Sources: [official GitHub setup](https://docs.github.com/en/copilot/how-tos/copilot-in-your-ide/customize-copilot/extend-copilot-with-tools-and-context/set-up-the-github-mcp-server), [server configuration](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md), and [official server repository](https://github.com/github/github-mcp-server).

Notion also documents an SSE fallback at `https://mcp.notion.com/sse`; use it as an additional transport check. Prefer the hosted service over its older local package, which is no longer actively maintained. Source: [Notion connection documentation](https://developers.notion.com/guides/mcp/get-started-with-mcp).

Notion's search/read/change tools and access-reporting capabilities vary with connection settings and workspace plan. Validate the discovered access information and use a supported search route; do not mistake a plan limitation for broken authentication. Source: [Notion supported tools](https://developers.notion.com/guides/mcp/mcp-supported-tools).

#### Test data and prerequisites

- GitHub: a dedicated sandbox repository, known README content, seeded issues, and a test credential restricted to the required resources/actions. Record organization restrictions when applicable.
- Notion: a dedicated test workspace or explicitly scoped test area, a parent page, and seeded notes containing a unique search marker. Use accounts with access to that area.
- Enter credentials/sign in through the new Settings flow. Do not reuse secrets from another app, place real values in TOML examples, or commit tokens/callbacks in evidence.
- Require read-only success first. Run mutation cases only with explicitly authorized sandbox access; clean up created test content and record cleanup.

#### GitHub end-to-end cases

1. Settings → Connections → Add → GitHub → choose scope → enter masked token → save/connect.
2. Discover capabilities; read the sandbox README and list/fetch a seeded issue. Verify returned content against known fixtures through agent and UI paths.
3. Disable an advertised capability and confirm a stale/direct model invocation is blocked at execution.
4. On a writable sandbox connection, create a uniquely named test issue, read it back, and close it. Declining the action approval must create nothing.
5. Replace the token, revoke/expire a dedicated test token, and use a credential lacking the required repository access. Verify correct recovery and distinguish insufficient access from sign-in failure.
6. Disconnect/reconnect, restart iTE, change project scope, and remove the connection entirely through controls; verify no stale tools or credentials remain.
7. Exercise the official local server as a secondary deployment variant using a pinned official binary or container recipe. Verify launch consent, environment credentials, missing executable/dependency, stderr redaction, stop/shutdown, and package cleanup. The remote path must not require Docker.

#### Notion end-to-end cases

1. Settings → Connections → Add → Notion → choose scope → Sign in → authorize the intended workspace → connect.
2. Exercise browser-open failure/link fallback, cancel before callback, timeout, and a stale callback after cancel; verify listeners and connection workers are cleaned up.
3. Discover allowed tools/access, search for the seeded marker, fetch the page, and display its content. Handle plan-restricted parameters/tools with clear explanations.
4. With authorized sandbox write access, create a uniquely named child page, update a block/content, fetch it to verify, and archive or otherwise clean up the test page using a supported operation.
5. Sign out and sign in to a different test account/workspace where available. Verify the old binding/tools/data do not leak into the new connection.
6. Restart, refresh/re-authenticate, disconnect/reconnect, disable, and remove through controls. Verify credential persistence and revocation behavior with real evidence.
7. Repeat the read lifecycle against the documented SSE endpoint. For remote UI, verify the host-sign-in-required state rather than assuming a phone browser can complete a host-local callback.

#### Cross-provider isolation and release evidence

Keep GitHub and Notion connected simultaneously. Sign out, reset, disable, edit, and remove one while reading through the other. The unaffected provider must retain its saved credentials, live tools, and working calls. Also verify similarly named project/global records do not share credentials accidentally.

For each provider record: iTE revision/build/platform, provider endpoint and check date, auth path, sanitized account/workspace label, discovered tool names/schema hashes, steps and observed results, cancellation/failure cases, cleanup, and outstanding limitations. Never record raw credentials. Live tests are opt-in and separate from credential-free CI fixtures.

**Release gate:** both GitHub and Notion must pass the complete native add → authenticate → read → authorized sandbox write → reconnect → disable → remove journey, plus the two-provider isolation check. A fixture-only success or successful discovery alone does not satisfy this gate. If an account/policy blocks a case, mark it blocked with the reason and obtain an appropriate test environment before claiming completion.

After the tools release, add capability negotiation and resources/resource templates/prompts with separate controls. Resources need bounded reads, permission checks, subscription cleanup, and context budgets; prompts need user-triggered selection and visible argument entry. Embedded MCP Apps require a separate renderer/trust/origin design and are not implied by Textual support. Track these as planned follow-on work, not completed MCP parity.

## 13. Suggested code organization

These are proposed responsibilities, not a requirement to create every file before its milestone needs it.

| Location | Work |
|---|---|
| `src/ite/tools/mcp/models.py` | Definitions, snapshots, events, failure categories, capability/result types. |
| `src/ite/tools/mcp/service.py` | Shared lifecycle/management operations and subscriptions. |
| `src/ite/tools/mcp/repository.py` | Compatible definition storage, scope resolution, IDs/revisions, migration. |
| `src/ite/tools/mcp/credentials.py` | Credential bindings, keyring adapters, cache, migration/redaction interfaces. |
| Existing `client.py`, `mcp_manager.py`, `oauth.py`, `client_credentials.py`, `mcp_tool.py` | Transport/auth/tool integration; evolve behind the service, avoid a parallel implementation. |
| `src/ite/tools/mcp/diagnostics.py`, `catalog.py` | Shared checks and vetted recipes. |
| `src/ite/config/config.py`, `loader.py` | Schema compatibility and non-destructive persistence; remove duplicate secret/lifecycle logic incrementally. |
| `src/ite/ui/reup/settings.py`, `_threads.py` | Settings entry, shell route/back navigation, focus and workspace changes. |
| `src/ite/ui/reup/connections.py` | List/detail widgets and view state; split supporting widgets when size warrants it. |
| `src/ite/ui/reup/connection_modals.py`, `styles/connections.tcss` | Add/import/credential/confirmation flows and theme-aware layout. |
| `src/ite/ui/reup/_turn.py`, `_helpers.py`, `_streaming.py` | Native command routes, secret-input redaction, truthful activity/diagnostic rendering. |
| `src/ite/main.py`, `commands/info.py`, `commands/help_catalog.py` | Shared CLI/slash adapters, compatibility and corrected help. |
| `src/ite/agent/session.py`, `tools/registry.py`, `safety/permissions.py` | Session ownership, atomic capabilities, stale-call rejection, permission continuity. |
| `src/ite/remote/` and active remote UI adapters | Safe snapshots/actions, operation state, host OAuth limitations. |
| `scripts/build_runtime.py`, `hooks/`, `pyproject.toml`, `uv.lock` | Verified SDK/keyring/runtime packaging and dependency bounds. |

Keep app/mixins as integration points, not a new management god class. Choose the smallest typed abstractions that centralize actual duplicated behavior.

## 14. Work breakdown and release gates

Implement in the following dependency order. Each phase should produce reviewable changes and leave the app runnable; do not ship a dead Manage button or a setup form backed by unsafe persistence.

| Phase | Deliverables | Exit gate |
|---|---|---|
| 0 — Contracts and baseline | Confirm SDK/storage contracts, regression fixtures, scope/identity decisions, state/result interfaces, navigation specification. | Reproduced audit defects have regression cases; baseline failures are explained and an intentional lazy-secret contract is documented. |
| 1 — Persistence and secret repairs | Non-destructive atomic writes, isolated reset, precedence, cache invalidation, redaction, safe names, typed credential storage. | Connection A operations preserve B and unrelated tables; changed credentials take effect without restart; no secret leaks in tested paths. |
| 2 — Shared service and runtime | Definition inventory, invalid/disabled records, reconciliation, lifecycle/cancellation, registry events, session recovery. | Create/edit/disable/remove works live; failed connections lose stale tools; concurrent operations and late events cannot corrupt state. |
| 3 — Settings manager | Settings entry, list/detail pages, navigation/focus, management actions, advanced edit, safe diagnostics. | Everything can be inspected/managed through visible controls; keyboard/theme/resize tests pass. |
| 4 — Add/auth journeys | URL/local/import/catalog setup, masked credential and browser OAuth flows, trust consent, account/scope selection. | Complete add → sign in → use → reconnect → remove without TOML; cancel/error/host-sign-in-required paths are repairable. |
| 5 — Capability and result correctness | Full schemas, selected tools, refresh, structured/media envelope, size bounds, safe retry policy. | Schema/result fixtures preserve semantics; stale/disabled tools cannot execute; ambiguous writes are never replayed blindly. |
| 6 — Surface alignment and migration | CLI/slash/remote adapters, compatibility aliases, secure-store migration, docs/help/packaging. | Existing configs remain usable; all surfaces share the same semantics; migration is idempotent and recoverable. |
| 7 — End-to-end release | Required GitHub and Notion journeys and isolation checks, cross-platform/frozen builds, performance and failure-path verification, release notes. | Both required providers pass the native journey gate; all first-release acceptance criteria pass and tested/unsupported provider/transport cases are documented. |
| 8 — Expansion | Larger catalog, demand-based discovery, resources/prompts, separately designed MCP Apps. | Each addition has a user task, permission model, bounded context behavior, and fixture/provider evidence. |

A first release is complete only after phases 0–7. Follow-on phase 8 is explicit scope, not a reason to postpone normal connection management indefinitely. No time estimate is asserted until the service/storage contracts and initial provider set are validated.

### Audit finding coverage

| Audit finding | Required phase |
|---|---|
| Shared secrets file overwritten | 1: preserve tables and verify with MCP/client-credential/OpenRouter fixtures. |
| Reset deletes all OAuth tokens | 1: isolated credential binding removal and legacy-store migration. |
| Global secrets override project secrets | 1: explicit layer resolution with provenance tests. |
| Stale keyring cache | 1: mutation/external-revision invalidation. |
| Token input in history | 1: composer/feed/remote redaction; phase 4 masked direct input. |
| No live-client reconciliation | 2: add/edit/remove/disable/workspace revisions. |
| Unsafe TOML names | 1: quoted keys and identity/display separation. |
| Lost input schema / structured results | 5: full canonical schemas and result envelopes. |
| False connected status | 2: transport failure classification and stale capability removal. |
| Invalid/disabled entries disappear | 2–3: inventory plus repair/enable UI. |
| Doctor lacks tests and may expose auth | 1 redaction; 3 shared bounded diagnostics. |
| Startup launch bypasses consent | 2 lifecycle gate; 4 local trust flow. |
| Commands/docs disagree | 6: compatibility routing and coordinated help/docs. |
| Cancellation, races, raw logs, optional-context heuristics | 1–2 storage/lifecycle; 5 schemas/results; 7 failure-path verification. |

## 15. Verification plan

### Service and storage regression tests

- Unrelated secret/config tables and comments survive set/unset/reset/remove; ID/namespace names round-trip with dots/spaces/Unicode.
- Global/project/process/placeholder precedence, duplicate names, project override removal, disabled tombstones, workspace isolation, and cross-account selection.
- Secret set/unset is immediately observed after the cache was already populated; cross-process updates do not lose data.
- Keyring locked/missing/error, session-only credentials, legacy migration, partial migration recovery, repeated migration, and shared-binding removal.
- Concurrent connect/reconnect/edit/remove, cancel during startup/auth/discovery/call, and stale worker/callback events.
- Shutdown cleanup, external config parse failures, session switching, degradation recovery, disabled/removed/stale tool rejection at execution.

### Protocol and auth fixtures

Use hermetic real fixture servers for stdio and local HTTP/SSE plus SDK auth mocks where appropriate. Exercise browser OAuth discovery, callback/state/expiry/cancel/refresh and fallback links, invalid token/access-denied cases, client-credentials refresh concurrency, missing executables, server exits, zero tools, malformed schemas, tool-list changes, call timeout, and ambiguous writes. Explicitly verify WebSocket support or advertise it as unavailable for that build.

Test full `$defs`/`$ref`/combinator schemas, structured-only responses, mixed text/media/resource content, errors with structured details, oversized output, model modality fallback, and tool namespace collisions/limits. Avoid snapshot tests that merely mirror implementation fields.

### Textual interaction and layout tests

Extend `tests/test_reup_settings.py` and add focused connection-manager/modal tests using Textual's pilot. Complete journeys by clicking/keyboard controls without commands. Verify Add, sign-in, failed/retry, edit, enable/disable, remove, import, dirty-close, focus restoration, preserved chat state, theme changes, narrow/tall content, and active-session/workspace changes. Render headless snapshots or use the existing layout smoke approach for action clipping and scrim/table themes.

### Existing integration suites

Run focused MCP/CLI/info-command/tool-schema tests and affected Settings, command-palette, permission, learning-mode, remote, and session lifecycle tests. Run lint/type checks on changed Python modules, then the required repository checks before release. A docs-only plan does not itself require runtime tests.

### Provider, platform, and performance checks

Verify the initial catalog with actual successful authentication and a reviewed representative task per provider; distinguish fixture coverage from real-provider evidence. Use dedicated test accounts and never put credentials in test fixtures or reports. Test macOS, Windows, Linux, editable install, pipx/uv tool install, and frozen-runtime builds. Verify missing Node/uvx, package cache permissions, browser unavailable, keyring backend differences, proxy/TLS/network failures, and remote OAuth host handoff limitations.

Measure cold/warm Settings opening, connection startup, tool discovery, cancellation cleanup, and catalog size/token costs. Inventory rendering must not wait on network/auth; discovery of one slow connection must not freeze Settings or chat. Establish acceptable budgets from existing app behavior and enforce no unbounded loops/output/memory growth. Verify repeated open/close/connect cycles do not leak workers, sockets, processes, subscriptions, or widgets.

## 16. Documentation, rollout, and completion

Update `docs/mcp.md` with Settings-first instructions, screenshots/text layouts, authentication, scope/account distinctions, reconnect/remove, local dependency setup, permissions, import/export, and advanced TOML examples. Update `docs/commands.md`, command help/completion, configuration references, README links, remote docs, and release notes. Explain compatibility notices and credential migration without exposing values.

Roll out the repaired service behind existing operations first, then wire complete native flows. Preserve old definition readability and supported command behavior until deprecation is documented. Before changing the on-disk format, take a nonsecret configuration backup and define recovery; secure-store migration must be reversible without exporting secrets to plaintext. Keep schema versions readable across the announced compatibility window.

The release checklist is complete when:

- [ ] Settings exposes Connections independently of cloud account state.
- [ ] Add/edit/sign-in/connect/reconnect/disconnect/disable/remove work from visible TUI controls.
- [ ] URL, local, import, and verified catalog routes share validation and service operations.
- [ ] Scope and account identity are explicit; project overrides cannot select the wrong credentials.
- [ ] Credentials are isolated, secure where supported, redacted, and immediately updated.
- [ ] Invalid and disabled definitions are visible and repairable.
- [ ] Tool selection is enforced at invocation and updates without restarting.
- [ ] Full schemas and structured/media results survive supported model/UI paths.
- [ ] Transport/auth failures produce truthful statuses and safe next actions.
- [ ] Local startup consent and per-action permissions remain enforceable.
- [ ] Cancellation, retries, concurrent sessions, and shutdown do not leak resources or duplicate writes.
- [ ] CLI/slash/remote behavior and docs match the native experience.
- [ ] Regression, provider, platform, packaging, and layout evidence is recorded.
- [ ] GitHub and Notion pass the required real-provider journeys and cross-provider credential/tool isolation checks.

The implementation should deliver one coherent Connections product, backed by the repaired MCP runtime, rather than a Settings button that sends users back to commands.


## Implementation verification (2026-10-03)

The Settings Connections page, add/edit/import/credentials dialogs, connection management service, scoped keyring bindings, local startup review, capability selection, schema preservation, safe config writes, and legacy credential reset repairs are implemented in the working tree. Existing definitions do not require a bulk migration. Secrets are not automatically exported or rewritten merely by opening Settings.

Compatibility evidence: 79 focused tests and 2 subtests pass across Connections, MCP, CLI modes, Settings, and info commands. This includes a real local FastMCP process, quoted server names, credential scope isolation, project/global definition preservation on reset, dynamic tool selection, cancellation, and narrow terminal form action visibility. New implementation files pass targeted Ruff and mypy checks; the diff passes whitespace checks.

GitHub and Notion recipes have fixture coverage for stored bearer credentials and scoped OAuth tokens respectively. Per user direction, live provider sign-in and representative provider tasks are deferred to the user's test accounts. Fixture results do not certify the providers' current authentication flow.

Full repository verification remains incomplete: full-suite collection encounters a pre-existing import of `SettingsScreen` in `tests/test_reup_modals.py`, while the existing Settings implementation exports `SettingsPanel`. Broader UI regressions, platform/frozen builds, multi-session synchronization, and end-to-end media/model handling still require validation before the release checklist above can be marked complete.

Intentional compatibility notices: local executable startup requires stored approval of the launch definition; background connection attempts do not open an OAuth browser; `/mcp` without arguments and `/mcp add` without a name now open the native Settings controls. Existing argument-based commands, config scopes, and `server__tool` names remain available.
