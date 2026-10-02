# iTE — codebase overview as of 2026-10-02

> Source baseline: `ae2f501a` (main/development synchronization), package `ite-agent` v0.2.31, plus the root cleanup accompanying this document.
> This is a source review and targeted verification snapshot, not a claim that every feature has been tested end to end.
> Counts use Git-tracked files and physical lines, excluding `src/ite/ui/reup/legacy/`. That archive was not read.

## Product and licensing

iTE is a Python 3.11+ coding agent for the terminal, with a Textual interface, an OpenAI-compatible model client, filesystem and shell tools, and optional cloud and remote integrations. It ships as a Python package and as PyInstaller standalone bundles.

The terminal runtime is open source under the [MIT License](LICENSE). GitHub recognizes the license on the public repository. The hosted web application and backend API are proprietary, separately offered subscription services. Runtime licensing does not grant cloud service access; third-party dependencies and bundled materials retain their own licenses.

```bash
curl -fsSL https://ite.kiishi.space/install.sh | bash
# Windows PowerShell:
# irm https://ite.kiishi.space/install.ps1 | iex
pipx install ite-agent
```

Installer source now lives in `scripts/install.sh` and `scripts/install.ps1`. The hosted installer URLs remain unchanged: the release publisher copies those files to the cloud web application's `public/` directory.

## Repository scale

| Area | Tracked files | Physical lines |
|---|---:|---:|
| Runtime Python, excluding legacy | 201 | 76,285 |
| Reup Python, included in runtime total | 37 | 27,539 |
| Reup stylesheets | 8 | 4,571 |
| Python files under tests | 106 | 33,991 |

These are file and line counts, not executed-test counts or coverage percentages. The builtin tool list contains **48 classes**. Session-specific learning tooling, specialist subagents, discovered custom tools, and connected MCP servers can add to the actual registry; allowlists and learning mode can reduce the schemas exposed to the model.

## Changes since the September 30 snapshot

The previous document described v0.2.25. Source now includes:

- Durable Goal mode with milestone plans, proof records, tool and verification metrics, persisted state, and controlled continuations.
- Experimental learning mode: the learner writes code while iTE provides conceptual guidance, hints, and review; a guided setup flow manages `learn.md` preferences.
- One `/permissions` surface replacing separate user-facing approval and sandbox controls.
- Context compaction improvements and provider-aware context-window discovery, including Ollama metadata.
- Background saved-thread loading, metadata sidecars, and preserved early thread-switcher interactions.
- Hierarchical slash-command completion, a command-argument catalog, and paced assistant text display.
- Evidence-based, cancellable `/init` generation, including positional `force` and `--force` forms.
- Cloud status request budgets, cached-state handling, and daemon workers that avoid blocking interpreter shutdown.
- AI-generated Conventional Commit validation and retries, a wrapping commit editor, and Windows installer/runtime packaging fixes.
- An explicit MIT license, distribution notices, and the root script cleanup.

## Architecture and configuration

| Layer | Source | Responsibility |
|---|---|---|
| CLI | [main.py](src/ite/main.py) | Click options, configuration, upgrade dispatch, TUI and remote entry points |
| Agent | [agent.py](src/ite/agent/agent.py), [events.py](src/ite/agent/events.py) | Streaming model/tool loop and typed events |
| Session | [session.py](src/ite/agent/session.py), [session_manager.py](src/ite/agent/session_manager.py) | Runtime services, saved sessions, checkpoints, goal and learning state |
| Model client | [llm_client.py](src/ite/client/llm_client.py) | OpenAI-compatible requests, streaming and retries |
| Context | [manager.py](src/ite/context/manager.py), [compaction.py](src/ite/context/compaction.py) | Prompt layers, token budgets, continuation summaries and retained transcripts |
| Tools | [registry.py](src/ite/tools/registry.py), [policy.py](src/ite/tools/policy.py) | Discovery, argument normalization, eligibility and invocation |
| Permissions | [permissions.py](src/ite/safety/permissions.py), [sandbox.py](src/ite/safety/sandbox.py) | Invocation authorization and path checks |
| UI | [app.py](src/ite/ui/reup/app.py), [styles](src/ite/ui/reup/styles) | Textual runtime and theme/layout rules |

Configuration is layered through `src/ite/config/loader.py`, using global `~/.ite/config.toml`, workspace `.ite/config.toml`, environment settings, and CLI overrides. `src/ite/config/config.py` holds Pydantic models and compatibility handling. `AGENTS.md` provides repository guidance; `DESIGN.md` is the terminal UI contract.

The CLI launches the TUI with `ite`. Options include `--cwd`, `--model`, `--api-key`, `--base-url`, `--resume-last`, and `--upgrade`. Other entry points manage MCP definitions, cloud login/status/logout, host enrollment, the remote supervisor, and internal remote child processes.

## Tool inventory and routing

The explicit builtin class list in [builtin/__init__.py](src/ite/tools/builtin/__init__.py) covers:

| Category | Tools |
|---|---|
| Files and navigation | `read_file`, `write_file`, `edit`, `grep`, `glob`, `list_dir` |
| Structured configuration | `read_toml`, `write_toml`, `read_yaml`, `write_yaml`, `read_env`, `write_env`, `read_json`, `edit_json` |
| Shell sessions | `shell`, `shell_start`, `shell_poll`, `shell_send`, `shell_stop` |
| Verification | `run_tests`, `run_linter`, `run_typecheck` |
| Network | `http_request`, `web_search`, `web_fetch` |
| Documents and media | `read_pdf`, `read_image`, `read_document`, `list_archive` |
| Git | `git_status`, `git_diff`, `git_log`, `git_branch`, `git_commit`, `git_push`, `git_remote` |
| State and planning | `todos`, `memory`, `goal_progress`, `goal_outcome`, `plan_question` |
| Skills | `skills` |
| Async subagents | `spawn_subagent`, `spawn_subagents`, `wait_subagent`, `list_subagents`, `cancel_subagent`, `subagent_metrics` |

Tool metadata drives mutability, planning eligibility, risk, and subagent eligibility. The deterministic selection policy redirects supported structured formats away from generic text operations and restricts mutations during the planning phase. The registry repairs common argument aliases and malformed argument encodings before invoking tools.

`get_schemas()` uses `get_tools()`: configured allowlists and learning mode are applied. The previous claim that every turn always exposes an unfiltered inventory was incorrect. Learning mode exposes its restricted inspection set and adds `learn_progress` through the session.

`web_search` runs the synchronous search client in a worker thread. `web_fetch` uses async HTTP and moves HTML parsing/conversion off the event loop. These changes address UI responsiveness; they do not make every tool nonblocking.

**Confirmed gap:** `ApplyPatchTool` exists in `src/ite/tools/builtin/apply_patch.py`, but is absent from the default builtin list and exports. Normalization and prompt references do not make it available in the default registry. Custom registration is a separate mechanism.

## Goal mode

[goal.py](src/ite/agent/goal.py) defines thread-scoped state outside the TUI. Statuses are `active`, `paused`, `blocked`, `budget_limited`, and `completed`. The state records milestones, proof entries, events, a blocker, latest evidence, and elapsed/work/model/tool/verification metrics.

`/goal <objective>` creates a goal; `/goal` inspects it; `pause`, `resume`, `edit`, and `clear` manage its lifecycle. Edits leave a goal paused. A saved active goal restores as paused after the runtime was not running. Clearing retains bounded goal history.

`goal_progress` records milestone planning and completion evidence; `goal_outcome` records terminal outcomes. The Reup turn layer schedules continuations when an active goal is eligible, keeps continuation state per thread, and pauses or limits work for user interruptions, approvals, blockers, and usage errors. This is runtime-driven continuation, not a persistent external scheduler.

Sources: [session lifecycle](src/ite/agent/session.py), [goal commands](src/ite/commands/goal.py), [turn orchestration](src/ite/ui/reup/_turn.py), [progress tool](src/ite/tools/builtin/goal_progress.py), [outcome tool](src/ite/tools/builtin/goal_outcome.py).

## Learning mode

Learning mode is an experimental capability boundary, not just a different system prompt. [learning.py](src/ite/agent/learning.py) restricts available tools and commands. Source-writing tools, shell execution, arbitrary MCP calls, and subagent execution are not in its inspection allowlist. It supports file/search/structured-read/git-read operations, web research, and `learn_progress`.

`/learn on` enables it, creates a baseline `learn.md` without overwriting an existing file, and starts with an assistant message inviting a learning objective. `/learn off` restores normal behavior while suspended goals remain paused. Other forms include `status`, `setup`, `init`, `reload`, `hint`, and `review`.

The guided setup flow collects objective, starting point, pace, and preferences, then offers a profile review. Profile helpers preserve surrounding content, reject malformed section markers and symbolic links, and enforce a 16 KiB UTF-8 limit. Unreadable profiles fall back to built-in preferences. Saved state includes phase, objective, next step, and hint level.

Output guards reject common implementation/code patterns. They are conservative heuristics, not a proof that prose cannot disclose a solution. See [commands](src/ite/commands/learn.py), [profile handling](src/ite/agent/learning_profile.py), [setup UI](src/ite/ui/reup/learning_setup.py), and [user guide](docs/learning.md).

## Permissions and safety boundaries

The current user-facing presets are:

| Preset | Behavior |
|---|---|
| Ask for approval | Ask before file mutations, commands, internet/integration capabilities, and external file access |
| Automatic | Allow workspace file tools; ask before commands, internet/integration capabilities, and external access; Git commit/push remain confirmable |
| Full access | Remove iTE's approval and filesystem restrictions |

`/permissions` displays or changes the preset; `ask`, `automatic`, and `full access` are the command forms. The configuration default is Automatic. Older approval policy values remain internally for compatibility and custom configurations.

[Invocation authorization](src/ite/safety/permissions.py) validates parameters, collects path operands, resolves them, and obtains one-operation approval where required. [Path validation](src/ite/safety/sandbox.py) resolves filesystem boundaries and symlinks. Shell, network, arbitrary MCP, and child-agent capabilities receive explicit checks because file-operand checks alone cannot contain them.

These are **application-level controls, not an operating-system process sandbox**. `GitSandbox` is a separate optional branch-isolation workflow for accepting/rejecting changes and recovering orphaned work. Planning and learning restrictions are enforced in addition to permission presets.

## Context, models, and persistence

Context is assembled from prompt layers including current instructions, memory, skills, goal/runtime state, prior compact state, and the transcript tail. [ChatCompactor](src/ite/context/compaction.py) constructs bounded continuation summaries without first modifying live context, carries prior summaries forward, chunks oversized histories, and reports errors when a summary cannot fit. Tool outputs retain their beginning and end when shortened for compaction; full transcripts remain available separately.

Model configuration records a context-window value and its source. Bundled model metadata updates both app and active session settings. [Ollama discovery](src/ite/client/ollama_metadata.py) reads running allocation or `num_ctx`/model metadata without running inference. It distinguishes an allocated local window from a model's theoretical maximum and has a metadata fallback for cloud models.

[SessionManager](src/ite/agent/session_manager.py) saves JSON atomically and writes compact metadata sidecars. Sidecar validation uses file metadata before reuse, with transcript reads as fallback. [Thread loading](src/ite/ui/reup/_threads.py) uses background workers and workspace-keyed caches, exposes loading/failure state, and avoids repeatedly parsing full saved transcripts on the UI thread.

Memory remains JSON-backed across short-term, long-term, episodic, and semantic stores, with atomic writes and degraded operation. Ranking combines recency/access hotness with lexical overlap; overlapping long-term preferences can supersede old entries. Episodic storage caps entries at 50. Session working memory is a separate markdown artifact with restricted file permissions and fallback storage.

Sources: [memory manager](src/ite/memory/manager.py), [memory intent](src/ite/memory/intent.py), [session memory](src/ite/memory/session_memory.py).

## Subagents and extensions

Five specialist definitions ship in [subagent.py](src/ite/tools/subagent.py): `codebase_investigator`, `code_reviewer`, `tooling_guardian`, `init_investigator`, and `verification_reviewer`. The prior claim that `security_auditor` is a sixth default was incorrect; a workspace definition can supply it separately.

Synchronous specialist tools narrow a child agent's allowlist and enforce absolute and inactivity deadlines, with configured retries. They mark `supports_subagent_use=False` to prevent recursive use through that mechanism. The asynchronous runtime tracks queued/running/completed/failed/cancelled/timed-out runs, reuse, retries, and circuit-breaker metrics. User definitions are loaded from global/workspace `.ite/subagents/*.toml` with workspace overrides.

Custom Python tools are discovered from `.ite/tools/`. Skills are `SKILL.md` bundles with frontmatter and supporting references, discovered from 18 global/project compatibility roots and iTE overrides. Workspace skills have trust controls. MCP tools are namespaced as `server__tool`, derive metadata from server hints, and can be added/started/stopped/diagnosed through commands.

Hooks run shell commands around agent/tool/error lifecycle events, with environment context and process-group timeout handling. Instruction files follow a scoped hierarchy. `/init` runs the read-only `init_investigator`, records actual read evidence, validates draft paths and supported commands, honors an instruction-size budget, and supports cancellation without treating unverified prose as repository evidence.

## Terminal interface

`ReupApp` combines Cloud, Panels, Composer, Threads, Turn, and Streaming mixins. Its Python files range from 1,399 lines in `_threads.py` to 3,801 in `modals.py`; several remain substantial modules despite the earlier split. Eight modular `.tcss` files replace the old single stylesheet.

The interface includes thread switching/history, file attachments, changes/diff review, workboard, goals, settings/model selection, commands, approvals, and transient side questions. Theme changes repaint existing transcript/tool/panel surfaces. Tool results have success/redirect/recoverable/failure treatments, and completed calls can collapse into stacks.

[AssistantTypingBuffer](src/ite/ui/reup/assistant_typing.py) separates display timing from network chunk arrival and accelerates completion for long buffered replies. [Command completion](src/ite/ui/reup/command_completion.py) builds hierarchical choices from registered argument forms, leaving required placeholders non-runnable. The composer now labels file attachment actions explicitly. AI-generated commit subjects are validated as Conventional Commits, with malformed generations retried before acceptance.

Sources: [composer](src/ite/ui/reup/_composer.py), [command catalog](src/ite/commands/help_catalog.py), [commit validation](src/ite/git/commit_messages.py), [layout contract](DESIGN.md).

## Cloud and companion surfaces

Cloud integration manages browser authentication, persisted sessions, entitlement state, model catalogs, activity, and usage. It distinguishes signed-out/offline/denied states and retains useful cached settings during refresh failures.

[Status request budgets](src/ite/cloud/request_budget.py) scope background reads to a five-second deadline, at most two seconds per transport request, and no retries. Async status reads use disposable daemon workers with cancellation flags. Cancelling cannot interrupt blocked urllib/DNS work, but that work no longer holds the default executor open during shutdown. These budgets do not globally alter interactive login, refresh, or transcription requests.

Other runtime surfaces include:

- `src/ite/remote/`: TLS WebSocket pairing/trusted devices, cloud relay, headless hosts, and a supervisor that provisions per-user child processes. Supervisor isolation is platform/privilege-dependent and is distinct from terminal permission presets.
- `src/ite/telegram/`: an in-process Telegram bridge that forwards prompts and approval responses to the active runtime.
- `src/ite/integrations/open_island/`: opt-in macOS overlay integration over a local Unix socket.
- `src/ite/voice/`: OpenAI-compatible audio transcription with retries and a no-speech/hallucination filter; UI/cloud code selects service credentials and routing.
- `src/ite/auth/`: OpenRouter OAuth PKCE and callback handling.

Source presence is not evidence that every companion service, entitlement, or deployed endpoint works in production. This review did not connect to cloud services or mobile devices.

## Build, release, and root cleanup

[scripts/build_runtime.py](scripts/build_runtime.py) generates the PyInstaller spec and produces `darwin-arm64`, `darwin-x64`, and `linux-x64` tarballs plus a `win32-x64` ZIP, SHA-256 files, and a release manifest. It discovers mypyc `.so`/`.pyd` extensions. Runtime bundles include the MIT notice inside the executable bundle so installation retains it, including on Windows.

`pyproject.toml` declares `license = "MIT"` and `license-files = ["LICENSE"]`. Source and wheel builds were verified to include the complete license and MIT metadata. This does not retroactively replace already published packages or standalone binaries.

The only tracked GitHub Actions workflow is [build-runtime.yml](.github/workflows/build-runtime.yml). It runs on development pushes or manual dispatch and skips a version already published in `ite-releases`. It builds the platform matrix, uploads artifacts with seven-day retention, creates the release, and updates the private web repository's manifest. It is a release pipeline, not a general test/lint/typecheck CI gate.

[scripts/publish-release.sh](scripts/publish-release.sh) now reads installers from `scripts/` and still publishes them at the original web paths. **The manual [github-release.sh](scripts/github-release.sh) deletes an existing same-version release before recreating it**; the workflow's skip-existing behavior is different.

Root cleanup in this snapshot:

- `_eval_optimizer.py` moved to `scripts/_eval_optimizer.py`, with its source import path and usage updated.
- `_smoke_render.py` moved to `scripts/_smoke_render.py`, with script-relative source/CSS paths and an import-safe entry guard.
- `install.sh` and `install.ps1` moved to `scripts/`; publisher and installer-test paths updated.
- `interesting-readme.md` deleted; `README.md` is the main project README.

Historical Arch upgrade and Actions storage-quota reports from the old overview were not reproduced here. They should not be presented as confirmed current failures. The current Unix upgrade implementation pipes a curl subprocess to bash rather than constructing a `bash -c` command.

## Verification and remaining issues

Verified during this cleanup/review:

- The relocated modal smoke script runs headlessly and renders both inspected modals.
- The relocated optimizer script runs; its schema comparison reports 8,554 original versus 8,159 compact tokens for the builtin list in this environment. This is a synthetic measurement, not a production savings guarantee.
- Bash syntax checks pass for the installer and publisher. The publisher dry run uses the relocated sources, and an isolated copy check confirms both installers and the manifest land at their expected hosted paths.
- Source and wheel builds succeed for v0.2.31; all 48 local links in this overview resolve.
- Nine focused regression files produced **40 passed, 2 failed**, plus 2 passing subtests. The two failures were five-second worker-start timeouts in `test_web_tool_responsiveness.py`.
- Cloud status regressions produced **9 passed**, with a warning about an unawaited thread-tab refresh coroutine.
- A separate Goal mode run stopped at its first failure: **3 passed, 1 failed**. Its partial `Session` fixture omits the `learning` field now required by `create_goal`.
- A larger combined run was interrupted after failures and a stall; it is not counted as a completed verification run. Full-suite collection is also affected by the issues below. Runtime source and the failing test files were unchanged by this cleanup.

Confirmed existing issues and limits:

| Finding | Evidence / consequence |
|---|---|
| Default registry lacks `apply_patch` | Implementation exists but the builtin inventory does not register it |
| Full test collection is not clean | `tests/test_reup_modals.py` imports absent `SettingsScreen` from `settings.py` |
| Goal regression fixture is incomplete | `tests/test_goal.py` constructs a partial `Session` without `learning`, then calls `create_goal` |
| Web responsiveness regressions fail locally | HTML conversion and search worker-start assertions time out in `tests/test_web_tool_responsiveness.py`; the failure cause was not repaired or attributed to production performance in this review |
| Interactive code executes during collection | `tests/test_textual_app.py` calls `app.run()` at import time |
| Embedded Telegram token literal | `src/ite/telegram/bot.py` contains a default token literal; validity was not checked and its value is intentionally omitted here. Remove it from source and rotate any real exposed credential |
| Workspace artifacts already tracked | `.ite/` files remain tracked despite the ignore rule; ignoring a path does not untrack existing files |
| No dedicated test configuration | No tracked pytest config or `conftest.py` was found; automatic collection can import interactive utilities |
| No fresh repo-wide lint/typecheck result | Historical ruff/mypy failures are not a substitute for running those checks on the current revision |
| Legacy archive remains | Pre-refactor snapshots were excluded from review and line counts; they are not evidence about the active runtime |

This document distinguishes implemented mechanisms from deployment guarantees. It is not a full security audit, dependency-license audit, benchmark, or coverage report.

## Monorepo boundary

The public runtime lives in `ite/`. Sibling projects include `ite-cloud-api` (TypeScript/Fastify), `ite-cloud-web` (React/Vite), `ite-vscode` (JavaScript), `ite-intellij` (Kotlin/JVM), `ite_admin` (Flutter desktop), and `ite_remote` (Flutter mobile). They have independent builds and project instructions. This snapshot reviews runtime integration points; it does not claim the private cloud stack is MIT-licensed.
