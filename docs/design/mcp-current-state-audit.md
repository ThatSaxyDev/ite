# MCP current-state audit and product direction

Date: 3 October 2026. Repository package version: 0.2.32.

## Assessment

iTE has a working MCP tools client with multiple transports, browser OAuth, token authentication, machine credentials, and integration with agent tool execution. It does not yet offer a complete connections experience for ordinary users. Setup, credentials, troubleshooting, and removal are fragmented across configuration files and commands. Several persistence and runtime defects need fixing before a friendlier interface can be reliable.

This is a baseline investigation, not an implemented redesign. Only this document was added. No user credentials or external MCP accounts were accessed.

## What happens today

### Configuration and installation

`MCPServerConfig` in `src/ite/config/config.py:47` defines enabled/auto-connect settings, timeouts, transport settings, environment variables, headers, browser OAuth settings, machine credentials, and context-resolution hints.

`load_config()` layers user and project configuration and injects workspace secrets. Invalid individual MCP definitions are logged and dropped so they do not stop iTE from starting (`src/ite/config/loader.py:472`). Global MCP environment secrets are read lazily from the OS keyring when connecting.

There are two different add operations:

| Entry point | Actual behavior |
|---|---|
| `ite mcp add <name> <url-or-command>` | Creates/persists a definition; defaults to global scope. Supports explicit URL, command, arguments, transport, and scope flags. |
| `/mcp add <name>` | Copies an existing definition from the opposite scope. Does not create a new connection or open an interactive setup flow. |
| Editing TOML | Exposes the full configuration, including authentication settings unavailable as flags on the CLI add command. |

The help catalog calls `/mcp add` “Add a server interactively,” contradicting its implementation (`src/ite/commands/help_catalog.py:60`, `src/ite/commands/info.py:747`). The CLI add command has no OAuth, header, or API-key flags. Adding an authenticated remote URL therefore does not finish its authentication setup.

The runtime's empty state directs users to add `[mcp_servers.<name>]` blocks and suggests starting a server when none exists (`src/ite/ui/reup/command_views.py:119`). The list is a rendered command card, with command hints rather than native setup/manage controls. No dedicated MCP setup modal or connections settings flow was found in the active Reup UI.

iTE launches configured local executables; it does not manage installation and updates as a product feature. `npx`/`uvx` may install packages themselves. Node/Python tooling, provider configuration, arguments, and tokens remain the user's responsibility.

### Connection lifecycle

`AgentSession.initialize()` initializes `MCPManager` and registers connected tools (`src/ite/agent/session.py:151`). Enabled definitions become client objects. Disabled definitions are skipped entirely and are absent from the MCP list and configured count.

By default `auto_connect = false`: a configured server is “ready” until `/mcp start <name>`. Auto-connect servers connect concurrently at session initialization. Defaults are a 10-second startup timeout and a 300-second browser OAuth timeout. Optional MCP failure degrades the session rather than preventing use of iTE.

Supported transport implementations (`src/ite/tools/mcp/client.py:148`):

| Transport | Current support |
|---|---|
| Local process / stdio | Command, arguments, environment, working directory, stderr logs; private npm cache for literal `npx`/`npm` commands. |
| Streamable HTTP | URL, headers, auth; default for URLs except the `/sse` suffix. |
| SSE | Explicit setting or inferred `/sse` URL; configurable read timeout. |
| WebSocket | Conditional on the installed FastMCP providing `WSTransport`; rejects configured headers/auth. Not guaranteed usable in every installation. |

Transport inference is configuration based, not discovery. The client enters a FastMCP connection and lists tools once. There is no iTE-managed periodic health check, automatic reconnection, or handling of tool-list changes. A failed tool call does not update connection status. `/mcp stop` removes the tools and returns the client to “ready”; it does not persist a disabled state. An auto-connect server can reconnect in a new session.

### Authentication and secret storage

| Method | Current behavior |
|---|---|
| Local process credentials | Configured environment plus inherited iTE process environment. |
| Remote headers/token | Configured headers and `auth` passed to FastMCP. |
| Browser OAuth | FastMCP OAuth wrapped with progress reports; browser authorization, localhost callback, shared file-backed token store. |
| Client credentials | Custom async HTTP auth fetches a bearer token and caches/refreshes it against expiry. Requires configured token endpoint, ID, and secret. |

Global MCP environment values use the OS keyring; global secrets TOML tracks key names. Workspace environment values use plaintext `.ite/secrets.toml` with mode 0600. Browser OAuth tokens are also plaintext JSON with mode 0600 at `get_data_dir()/auth/mcp_oauth_tokens.json`. These are different storage mechanisms, not one credential abstraction.

`/mcp env` offers list, where, set, import, and unset; changes default to global scope. Listing masks stored values. Credentials typed through `env set` still go through the normal composer history path. Machine credential secrets are loaded from workspace `[mcp_client_credentials.<server>]` tables; the add writer strips ID/secret fields rather than storing them through a guided credentials flow.

### Agent exposure, permissions, and output

Each discovered tool becomes `server__tool`, registered as an `MCPTool` (`src/ite/tools/mcp/mcp_manager.py:213`). Connected tools enter the same catalog as built-ins; the agent requests the current catalog each turn. A configured global `allowed_tools` list can filter advertised tools. There is no dedicated per-connection capability picker or demand-based MCP tool discovery in this path.

MCP annotations inform metadata: destructive tools are high risk, read-only tools are low risk, and unknown tools default to mutating/medium risk. Plan mode permits tools classified as non-mutating. Learning mode filters MCP tools from the catalog and rejects their invocation.

For current restricted permission presets, MCP is a capability that requires confirmation regardless of read-only hints (`src/ite/safety/permissions.py:110`). Full permissions bypass that confirmation. Local server launch happens through the manager outside tool-invocation approval; an enabled workspace definition with auto-connect can execute its command at startup. The process inherits the parent environment. A user-facing trust boundary for installing/starting a local connection needs explicit treatment; tool-call approval does not cover process startup.

Input schemas are rebuilt from only `properties`, `required`, and `additionalProperties`, losing other top-level JSON Schema fields. Results preserve the error flag but concatenate text blocks and stringify other content. Structured results and native image/audio/resource handling are not preserved through this wrapper.

The UI humanizes tool/server names and summarizes results. Errors have recovery copy for validation failures, missing identifiers, Chrome access, 404s, and some authentication failures. Context preflight uses naming/schema heuristics and optional configured discovery hints. Some errors say “Trying again” without an automatic retry in the wrapper; whether another attempt occurs depends on subsequent agent behavior. Optional identifier fields can also be treated as required by the detail-tool heuristic.

This is MCP **tools** support. No iTE integration for listing/reading MCP resources, fetching prompts, or a full MCP application UI was found in this implementation.

## Findings to fix

The first seven rows below were reproduced using temporary files and mocks; no real credentials were involved. Additional rows are verified by source inspection or response fixtures.

| Priority | Finding | User impact / evidence |
|---|---|---|
| P1 | Workspace secret writes replace the shared secrets file with only MCP env tables. | `save_mcp_env_var()` removed a fixture `mcp_client_credentials` section. Other sections such as OpenRouter credentials are also at risk. See `loader.py:1476`. |
| P1 | `/mcp reset A` deletes the entire shared OAuth token file. | A reset of server A removed a fixture file holding A and B. Other connections lose persisted OAuth state; already loaded tokens may continue temporarily. See `info.py:494`. |
| P1 | Global keyring secrets overwrite workspace/config env at connect. | A fixture workspace `TOKEN=workspace` became `TOKEN=global`. Scope choice can silently select the wrong account. See `mcp_manager.py:132`. |
| P1 | Secret set/unset does not invalidate the process keyring cache. | After caching an empty store, saving a new global secret still returned an empty store until explicit invalidation. Reset invalidates; normal env changes do not. See `loader.py:1286`, `loader.py:1507`. |
| P1 | MCP credential entry is not redacted from composer history. | `/mcp env set demo TOKEN fixture-token` is returned unchanged by `redact_sensitive_command_text()`. Composer records that text in memory. No claim of persisted disk history is made. See `_helpers.py:62`, `_composer.py:1910`. |
| P2 | Reload does not reconcile configured and live clients. | After loading a new definition, config contained `new` while manager retained `demo`; connecting `new` raised `Unknown MCP server`. Disabled/removed clients are not reconciled either. See `info.py:992`. |
| P2 | Connection names are not safely encoded in TOML table headers. | Saving `contains.dot` produced the nested key `contains`, losing the intended server identity. Spaces and other special characters also need validation/quoting. See `loader.py:1213`. |
| P2 | Input schema loses definitions and constraints. | A schema using `$ref` lost its top-level `$defs`. Other top-level combinators/constraints also disappear. See `mcp_tool.py:39`. |
| P2 | Structured response content is dropped. | A mocked successful response with structured content and no text became an empty successful output. Nontext blocks are stringified. See `client.py:354`. |
| P2 | Failed calls can leave a false “connected” state. | A `Connection closed` fixture left client status connected. Starting an already-connected client returns immediately, so explicit stop/start may be needed. See `client.py:354`, `mcp_manager.py:152`. |
| P2 | Invalid and disabled configurations disappear from management. | Invalid definitions are removed during load; disabled ones are skipped during initialization. Users cannot inspect/fix/enable them in the MCP list. |
| P2 | Doctor is a config summary, not a connection diagnostic. | Shows settings/key names, including `auth` verbatim. It does not check executable availability, endpoint reachability, OAuth discovery, callbacks, tool discovery, or a test call. A token in `auth` may be exposed in its output. See `info.py:796`. |
| P2 | Local execution trust is not covered by tool approval. | Workspace auto-connect can start arbitrary configured commands, with inherited environment, before an MCP tool call. Needs a clear install/start consent and trust model. |
| P2 | Product entry points and docs disagree. | Slash add is described as interactive but copies scopes; MCP guide describes only stdio/TOML/start/stop, omitting remote transports and authentication. |

Other engineering gaps: no per-call timeout exposed in MCP configuration; no iTE-managed disconnect/re-auth retry policy; no live tool-list refresh; weak validation of URL/timeout/credential fields; raw stderr/provider errors can reach UI/logs without MCP-specific secret redaction; file stores use per-instance locks and shared temporary filenames, leaving concurrent-session write races to address. These are source-level concerns; their real-provider failure rates were not measured.

## Verification and limits

- Ran `.venv/bin/python -m pytest tests/test_mcp.py tests/test_cli_modes.py tests/test_info_commands.py tests/test_tool_narrative.py -q`: **73 passed, 2 failed, 2 subtests passed**.
- Failures: `test_load_config_merges_system_and_workspace_mcp_secrets` and `test_mcp_env_import_defaults_to_global_scope_and_reloads_runtime`. Both expect global keyring values during config load/reload, while current code loads them lazily at connect. These are existing baseline failures, not introduced changes. Tests and behavior need an explicit consistent contract; the separate cache and precedence reproductions establish runtime defects independently.
- Ran a real temporary FastMCP stdio fixture: ready → connected, one tool discovered/registered as `fixture__greet`, call returned `Hello, MCP audit`, stop removed the tool and returned to ready, shutdown completed.
- Ran isolated fixtures for reset isolation, scope precedence, cache refresh, secret-table preservation, live configuration reload, name serialization, history redaction, schema preservation, structured output, and disconnected status.
- Read the active MCP client/manager/wrapper/auth modules, config loading/writing, CLI and slash handlers, session/catalog/permissions paths, Reup command/tool rendering and composer, docs/help, tests, and packaging hooks. Avoided legacy UI snapshots.
- Ran the repo-audit skill's pattern and coverage scanners. Their results were not treated as proof: the pattern scanner produced unused-import false positives, and the directory-only coverage scan missed tests living in the repository's `tests/` directory. Manual test mapping and execution informed this report.
- Local runtime used FastMCP 3.2.4 and MCP SDK 1.27.0. No live provider OAuth, remote HTTP/SSE endpoint, WebSocket server, Windows/Linux keyring, frozen executable, or mobile browser callback was exercised. This is not a claim of end-to-end certification for those paths.

## Proposed user experience

Use **Connections** as the user-facing concept and retain MCP terminology in advanced settings/help. A user should be able to complete this journey inside Reup:

1. Open Connections and choose **Add connection**.
2. Select a curated service, paste a provider's connection URL/configuration, or choose a custom local server.
3. See a plain-language explanation of what iTE can access/do and whether a local program will run.
4. Choose **Sign in** or enter an API key in a masked field. Show a browser-open fallback link, waiting state, cancel, and retry.
5. Validate configuration and dependencies, connect, and discover capabilities. Explain failures with an actionable fix.
6. Show connection ready, account/workspace when obtainable, and useful capability examples. Do not invent account identity when the provider cannot supply it.
7. Let the user connect/disconnect, enable/disable, choose capabilities, reconnect/sign out, change account, inspect sanitized diagnostics, and remove the connection.

Store scopes internally; present them as “Available in all projects” and “Only this project.” Define account/credential scope separately from tool availability. Custom TOML and command entry remain advanced paths. Hosted connections reduce local dependency work for ordinary users; local connections still need clear dependency checks and launch consent.

A curated service entry needs more than a name and icon: capabilities, verified endpoint or versioned command recipe, auth method, credential fields, scopes, supported platforms, dependencies, instructions, and known recovery actions. User-supplied configuration should be parsed into this model and reviewed before running executable commands. Avoid promising that every arbitrary MCP server can have identical one-click setup.

## Implementation order and acceptance criteria

### 1. Repair the foundation

Preserve unrelated secrets tables; isolate per-connection token deletion; define and enforce scope precedence; invalidate secret caches on writes; redact secret input and diagnostics; preserve complete schemas/results; reconcile live clients with persisted configuration; retain invalid/disabled entries with repairable states. Add regression tests for the reproduced defects.

Acceptance: changing or removing credentials for A never changes B; newly added connections work without restarting; removed/disabled connections no longer advertise callable tools; workspace account choice wins according to the documented rule; secret text cannot reappear via history or diagnostics.

### 2. Give all surfaces one connections service

Move create/update/remove, enable/disable, credentials, connect/disconnect, re-authentication, tool selection, and diagnostic operations into a shared application service. The CLI, slash commands, native Reup screens, and remote surface should call the same operations rather than mutating manager internals. Preserve configuration compatibility during migration.

Separate persistent definition, credential/account reference, desired enabled state, live connection state, and discovered capabilities. Model states such as needs setup, needs sign-in, connecting, connected, disconnected, and failed with typed errors and explicit actions. A disconnected connection is still installed and manageable.

Acceptance: CLI add and in-app add mean the same thing; copy-to-another-scope has its own action; statuses reflect actual lifecycle transitions; install/start trust is distinct from approval of individual remote actions.

### 3. Deliver the native Connections flow

Build an accessible keyboard-driven Reup manager and add/sign-in flows, starting with custom URL plus a small curated set of services selected for iTE users. Include masked credentials, cancel/retry, scope choice, capability descriptions, dependency checks, and sanitized diagnostics. Update empty states, command completion, and docs together.

Acceptance: a user can add an authenticated connection, use it, fix expired authentication, and remove it without editing TOML. Local executable setup tells them what will run and explains missing dependencies.

### 4. Strengthen runtime behavior and broaden capability support

Add bounded startup/call cancellation, connection health tracking, safe reconnection, tool-list refresh, and capability filtering/discovery to manage large catalogs. Do not blindly retry a mutating tool after an ambiguous transport failure. Revisit annotation trust and heuristic preflight so valid optional inputs are not rejected. Decide resources/prompts/media/application support based on actual user tasks.

Acceptance: dropped connections stop being presented as healthy; retries cannot duplicate writes; updated tools appear without a restart; users can see and control available capabilities; media/structured results survive the full model/UI path.

### 5. Validate distribution and real journeys

Add local fixture-server coverage and authenticated HTTP/SSE tests; verify OAuth callback/cancel/expiry, missing executables, timeout, keyring failure, multi-session credential writes, startup trust, large catalogs, per-connection removal, and packaged runtime behavior. Test macOS/Windows/Linux and the remote browser experience explicitly. Version compatibility requirements for FastMCP should match verified distributions.

The first product milestone should be a complete, reliable “add → sign in → use → reconnect → remove” journey. A large connection catalog should follow that milestone.
