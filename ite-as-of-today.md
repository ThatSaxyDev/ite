# iTE — codebase overview as of 2026-09-30

> Snapshot taken 2026-09-30 at commit `79eaaa0` ("Preserve conversation scroll position during streaming"), package `ite-agent` v0.2.25.
> Everything below was read from source, not from marketing copy.
> `src/ite/ui/reup/legacy/` was deliberately **not** read — it is a pre-refactor archive that `AGENTS.md` forbids loading.

---

## What it is

A Python 3.11+ CLI / Textual TUI coding agent, shipped both as a standalone binary and a PyPI package.

```bash
curl -fsSL https://ite.kiishi.space/install.sh | bash     # macOS / Linux
irm https://ite.kiishi.space/install.ps1 | iex             # Windows PowerShell
pipx install ite-agent                                     # or from PyPI
```

Scale: **~73k LOC** of source (excluding `legacy/`), **85 test files / ~29k LOC** of tests.

---

## Core architecture

| Layer | Location | What it does |
|---|---|---|
| Entry point | `src/ite/main.py:140` | Click group `IteGroup` → `run_reup(config)` |
| Agent loop | `src/ite/agent/agent.py:1510` (`_agentic_loop`) | Streaming tool-calling loop; `AgentEvent` generator |
| Events | `src/ite/agent/events.py:34` | Typed event stream (text deltas, tool start/complete, compaction, plan-ready) |
| LLM client | `src/ite/client/llm_client.py` (1,640 lines) | OpenAI-compatible abstraction, streaming, retries |
| Context | `src/ite/context/manager.py`, `compaction.py`, `loop_detector.py` | Token budgeting, auto-compaction, loop detection |
| Tools | `src/ite/tools/base.py:166` (`Tool` ABC), `registry.py:118` (`invoke`) | 47 registered built-ins + MCP |
| Safety | `src/ite/safety/approval.py:271`, `sandbox.py:18` | 5 approval modes, path sandbox, git sandbox |
| UI | `src/ite/ui/reup/` | Textual app, ~24.7k LOC |

### CLI surface

```
ite                                  # launch Reup TUI
ite --cwd / --model / --api-key / --base-url / --resume-last / --upgrade
ite mcp add <server> <url|command>    # persist MCP server definitions
ite cloud login|status|logout        # iTE Cloud session
ite remote host enroll|status|forget # enroll this machine as a host
ite remote serve                     # host supervisor (multi-user runtime)
ite remote child                     # internal, one provisioned runtime process
```

---

## Tool system

Everything is a `Tool` subclass (`ToolKind`: READ / WRITE / SHELL / NETWORK / MEMORY / MCP).

**47 registered built-ins** across `src/ite/tools/builtin/`:

| Category | Tools |
|---|---|
| Files | `read_file`, `write_file`, `edit` |
| Structured config | `read_toml`/`write_toml`, `read_yaml`/`write_yaml`, `read_env`/`write_env`, `read_json`/`edit_json` |
| Search / nav | `grep`, `glob`, `list_dir` |
| Shell | `shell`, `shell_start`, `shell_poll`, `shell_send`, `shell_stop` (persistent sessions) |
| Verification | `run_tests`, `run_linter`, `run_typecheck` (auto-detects project commands) |
| Network | `http_request`, `web_search`, `web_fetch` |
| Media / docs | `read_pdf`, `read_image` (OCR), `read_document` (docx/xlsx/pptx/odt/rtf/epub), `list_archive` |
| Git | `git_status`, `git_diff`, `git_log` (read) · `git_branch`, `git_commit`, `git_push`, `git_remote` (write) |
| Agent state | `todos`, `memory`, `goal_progress`, `goal_outcome`, `plan_question` |
| Skills | `skills` |
| Subagent runtime | `spawn_subagent`, `spawn_subagents`, `wait_subagent`, `list_subagents`, `cancel_subagent`, `subagent_metrics` |

### Notable design choices

- **Structured editors over raw text.** `ToolSelectionPolicy` (`tools/policy.py:17`) actively *blocks* `read_file` / `edit` on `.json` / `.toml` / `.yaml` / `.env` / `.pdf` / office / image targets and redirects to the structured reader. Returns a `PolicyDecision` carrying `reason` + `redirect_to`.
- **LLM-arg repair.** `registry.py:387` normalizes param aliases (`file`→`path`, `old`→`old_string`) and regex-scrapes malformed `raw_arguments` JSON.
- **Plan-mode enforcement.** The same policy blocks anything lacking `allowed_in_plan_mode` while planning, except `shell` when `is_safe_command()` passes. It also redirects trivial `subagent_*` lookups back to `grep` (`_looks_like_simple_lookup`, `policy.py:209`).
- **MCP.** `mcp_manager.py:213` namespaces remote tools as `server__tool`; removal is prefix-based. `MCPTool` derives mutability from `readOnlyHint` / `destructiveHint` and adds a preflight layer that suggests a sibling list/search tool when an identifier param is missing.
- **Custom tools.** Drop a `.py` in `.ite/tools/`; discovered by reflection (`discovery.py:34`).
- **Full inventory every turn.** `get_schemas()` (`registry.py:94`) is called on each LLM turn with no filtering — the model sees all 47+ schemas every time, never a trimmed subset.

### Gap: `apply_patch` is registered nowhere

`ApplyPatchTool` (`tools/builtin/apply_patch.py:46`) is implemented, referenced in `registry.py:474` normalization, in `agent.py:1466`, and in `subagent.py:122`'s mutating set — and the system prompt actively instructs the model to prefer it (`prompts/system.py:447`).

But it is **not** listed in `get_all_builtin_tools()` nor in `builtin/__init__.py`'s `__all__`, so `create_default_registry()` never registers it. **Unreachable in practice.**

---

## Subagents

Two distinct mechanisms:

**1. Synchronous — a subagent *is* a tool.**
`SubagentTool` (`tools/subagent.py:61`) wraps a `SubagentDefinition` (`name`, `goal_prompt`, `allowed_tools`, `max_turns`, `timeout_seconds`, `inactivity_timeout_seconds`, `retry_attempts`). Tool name is `subagent_<definition.name>`. Execution clones the config with a narrowed allowlist, spins a child `Agent`, and enforces both an absolute deadline *and* a separate inactivity timeout. Retries reuse the child session and feed prior-attempt context forward.

`supports_subagent_use=False` — subagents cannot spawn subagents, preventing recursion.

Six built-ins: `codebase_investigator`, `code_reviewer`, `security_auditor`, `tooling_guardian`, `init_investigator`, `verification_reviewer` (all read-only except the last, which also gets `shell`).

**2. Async / batch — fire and poll.**
`spawn_subagent` / `spawn_subagents` / `wait_subagent` / `list_subagents` / `cancel_subagent` / `subagent_metrics` (`builtin/subagent_runtime_tools.py`) delegate to `agent/subagent_runtime.py`, letting the parent start work and poll later.

**User-defined subagents** live in `.ite/subagents/*.toml` (project overrides global by name), authored via `/subagent list|create|delete`.

---

## Extensibility

- **Skills** — `SKILL.md` bundles with YAML frontmatter plus lazily-loaded `reference/` files. `SkillManager` walks 18 discovery roots (`skills/manager.py:117`) including `~/.agents/skills` plus compat mirrors for Claude, Codex, Cursor, Gemini, OpenCode, Kiro, and Pi (both global and project variants), plus iTE overrides. Workspace trust gating lives in `skills/trust.py`.
- **Hooks** — user shell commands at `BEFORE_AGENT` / `AFTER_AGENT` / `BEFORE_TOOL` / `AFTER_TOOL` / `ON_ERROR` (`hooks/hook_system.py:56`). Context is injected via env (`ITE_TRIGGER`, `ITE_TOOL_NAME`, `ITE_TOOL_PARAMS`, `ITE_RESPONSE`, `ITE_ERROR`). Timeouts kill the whole process group.
- **AGENTS.md** scope hierarchy — deeper files override parents; `/init` generates one.

---

## Safety / approval gating

Three layers, applied in order:

1. **Policy** — `ApprovalManager.check_approval()` (`safety/approval.py:271`). Non-mutating tools auto-pass. Then: low-risk in-session tools (`todos`, `memory`) → always-confirm tools (`git_commit`, `git_push`) → shell commands routed to `_assess_command_safety()` → non-shell mutations policy-switched by approval mode → default prompt. Command classification is pure regex, compound-aware (`&& || ; |`, `$(...)` unwrapping) with git-subcommand allowlists.
2. **Tool-level path check** — `Tool._sandbox_check()` (`tools/base.py:231`) → `validate_path()` (`safety/sandbox.py:18`), resolving symlinks against cwd + data dir + `allowed_paths`. Violations surface as tool errors, not exceptions.
3. **Wiring** — `ApprovalManager` built in `agent/session.py:95`, UI callback attached at `agent/agent.py:91`, threaded through every `tool_registry.invoke(...)`.

`GitSandbox` (`safety/git_sandbox.py:19`) adds optional branch-level isolation: stash WIP → `ite/sandbox-{ts}` → `diff()` / `accept()` / `reject()`, with orphan recovery.

---

## Textual UI (`src/ite/ui/reup/`)

`ReupApp` (`app.py:332`) is a mixin stack: `CloudMixin, PanelsMixin, ComposerMixin, ThreadsMixin, TurnMixin, StreamingMixin, App`.

| File | Lines | Role |
|---|---:|---|
| `modals.py` | ~3,600 | 18 `ModalScreen` classes (pickers, confirm, commit, setup, activity) |
| `_streaming.py` | 3,273 | Assistant text streaming + **all** tool-card rendering |
| `_turn.py` | 2,861 | Turn orchestration, central event router `handle_agent_event:2223`, approvals |
| `_panels.py` | 2,731 | Panel show/hide, change-review source + diff preview, commit/stage/discard |
| `_composer.py` | 2,482 | Composer chrome, slash palette, drag-drop, voice, send/queue/steer |
| `tool_views.py` | 1,746 | Per-tool Rich renderers + syntax/theme utilities |
| `_cloud.py` | 1,666 | Cloud auth state machine, bundled models, usage polling, shell-surface ladder |
| `app.py` | 1,653 | `compose()` tree, ~200 state fields, theme tokens, theme re-render |
| `_threads.py` | 1,298 | Thread registry, header refresh, auto-save, session naming |
| `widgets/` | ~1,300 | `prompt_area`, `message_row`, `side_panels`, `tool_cards`, `thread_switcher`, `remote_bridge`, `state` |
| `styles/*.tcss` | 8 files | `base`, `workspace`, `conversation`, `modals`, `settings`, `modal_details`, `shared`, `update_required` |

**Panels are mounted, not composed.** Each `_show_*` mounts onto `self.screen` on demand and hides the others. `aside-panel` is the exception — a persistent right-hand column in the tree.

**Shell state** resolves through `_apply_shell_surface()` (`_cloud.py:973`), a mutual-exclusion priority ladder: startup → required-update → signed-out → onboarding → session-switch → settings → chat.

**Tool cards.** `add_tool_call_start` (`_streaming.py:2248`) picks `ShellToolCard` for shell, `CompactToolCard` (+ `mcp-card` class) for MCP, else plain `CompactToolCard`. Outcome border colors: success `#2f9e63`, policy-redirect `#4d79c7`, recoverable `#a06b15`, failure `#b23a3a`. Completed cards collapse into `ToolCardStack` with read dedupe and recovery demotion. `_tool_completion_state` is what makes theme re-render possible.

**Theme.** The active Textual theme is the single source of truth. `watch_theme` (`app.py:1251`) re-renders completed tool cards, assistant Rich cards, and open panels — per `DESIGN.md` §12, switching is incomplete until historical transcript surfaces repaint.

`DESIGN.md` at the repo root is the binding UI contract: ~750 lines on terminal-specific layout rules, explicit widget sizing, spacing economics, modal consistency, and a 17-item regression checklist.

---

## Surfaces beyond the TUI

This package is one of 7 in a monorepo, and the agent has several non-TUI personalities:

- **`src/ite/remote/`** — full multi-user remote runtime. TLS websocket protocol (`security.py:37`), pair-code pairing and trusted-device store (`server.py:135`), per-UID/GID process isolation and orphan reaping (`supervisor.py:145`), cloud relay (`relay.py:55`), GitHub App linkage (`github.py`). Backs the Flutter mobile companion (`ite_remote`) and requires iTE Pro.
- **`src/ite/cloud/`** — browser OAuth + OS keychain storage (`auth.py:53`, 1,176 lines), entitlements with grace windows, bundled model catalog, usage summaries. Thread-safe refresh.
- **`src/ite/telegram/`** — a Telegram bot that runs as an asyncio task *inside* the TUI and calls the Agent API directly (not via TLS). Bridges messages to `on_submit_prompt` / `on_cancel_turn` and round-trips inline keyboards for approvals via futures.
- **`src/ite/integrations/open_island/`** — opt-in (disabled by default) macOS notch-overlay mirroring over a local unix socket (`bridge.py:42`). Plan in `docs/design/open-island-ite-bridge-plan.md`.
- **`src/ite/voice/`** — speech-to-text, cloud-first with local Groq fallback and a hallucination filter (`transcription.py:126`).
- **`src/ite/auth/`** — full OpenRouter OAuth2 PKCE flow with loopback callback, headless mode, and Arc-specific browser handling (`openrouter_pkce.py`).

---

## Memory

`MemoryManager` (`memory/manager.py:267`) — JSON-backed `short_term` / `long_term` / `episodic` / `semantic` stores, atomic writes, degraded mode.

- Ranking: hotness decay + lexical overlap
- Long-term preference supersession on overlap
- Episodic capped at 50, with a low-value filter
- `memory/intent.py` parses natural-language memory directives, exact-recall probes, conditional preferences
- `memory/session_memory.py` — per-session working-memory markdown artifact, `0600`, atomic replace, falls back to `.ite/session_memory/` if the data dir is unwritable

The agent short-circuits **before** calling the model on three memory fast paths (`agent.py:298`, `:321`, `:333`).

---

## Build & release

`scripts/build_runtime.py` (592 lines) is the single source of truth for artifacts.

- Targets: `darwin-arm64`, `darwin-x64`, `linux-x64` (tar.gz), `win32-x64` (zip)
- **Generates the PyInstaller spec at build time** into `build/runtime_specs/` — nothing is checked in
- Auto-harvests `__mypyc*.so` / `.pyd` extensions from site-packages
- Excludes tkinter, unittest, test, pdb, distutils, setuptools, pip, flet, prompt_toolkit
- Produces archives + SHA-256 + `dist/manifest.json`

Installers:
- `install.sh` (399 lines) — detect target → dep check → fetch manifest → idempotency check via `~/.ite/.sha256` stamp (deliberately does not touch existing pipx/uv installs) → resumable download → checksum verify → extract to `~/.ite/`
- `install.ps1` (263 lines) — Windows equivalent

`.github/workflows/build-runtime.yml` is the only CI workflow.

> ⚠️ **`scripts/github-release.sh` is destructive.** If a release for the version already exists it runs `gh release delete` then recreates it. Verify a version does not already exist before publishing.

> ⚠️ Known bug: `ite --upgrade` fails on Arch with `bash: symbol lookup error: rl_print_keybinding` — the `bash -c` wrapper is constructed in a way that breaks against Arch's readline linkage.

> ⚠️ CI is quota-fragile. v0.2.17 shipped without GitHub Actions because `actions/upload-artifact@v4` hit the artifact storage quota — all 4 build jobs compiled fine, only the upload step failed. Fallback path: bump version in `pyproject.toml` / `src/ite/__init__.py` / `AGENTS.md`, publish to PyPI via twine, build darwin-arm64 locally, create the GH release manually, `PUT` the macOS-only manifest to `ite-cloud-web` via `gh api`. Note the in-app updater hits cloud-api `/runtime/version-check`, not the manifest — so non-macOS users get an install notice that then fails.

---

## Design decisions worth knowing

- **`ToolSelectionPolicy` is a hard gate, not a hint.** It returns a `PolicyDecision` and the registry refuses the call. This is why `read_file` on a `pyproject.toml` fails even though `read_file` is an "allowed" tool.
- **Mutability is a `Tool` property, not a judgment call.** `is_mutating` drives approval gating, plan-mode restrictions, *and* subagent allowlists — three subsystems keyed off one boolean.
- **Slash commands live in `src/ite/commands/`**, one module per command group (`plan`, `goal`, `skills`, `subagent`, `todos`, `branch`, `publish`, `sandbox`, `remote`, `hooks`, `cloud`, `model`, `session`, `history`, `init`, `flow`, `aside`, `attach`, `csv2json`, `info`, `open_island`, `remind`).
- **The system prompt is one module.** `src/ite/prompts/system.py` assembles the full prompt, including the instruction that makes the missing `apply_patch` tool matter.

---

## Hygiene issues found

| Issue | Location |
|---|---|
| ~14.5k lines of dead pre-refactor god-class snapshots, not in the build | `src/ite/ui/reup/legacy/` |
| Dead packages containing only `__pycache__` | `computer_use/`, `runtime/`, `decisions/providers/` |
| Hardcoded bot token — should be rotated | `src/ite/telegram/bot.py:32` |
| Assertion-free "tests" | `tests/test_clipboard.py`, `tests/test_copy_detailed.py` |
| `app.run()` at import time — launches a Textual app on collection | `tests/test_textual_app.py` |
| No `conftest.py`, no pytest config; tests are unittest-style via pytest, fixtures hand-rolled per file | `tests/` |
| Repo-wide `ruff` / `mypy` known-red from pre-existing mixin errors (documented in `docs/design/open-island-*.md`) | — |
| `scripts/guard_mixin_imports.py` + `scan_*.py` exist as AST guards to keep the mixin split safe | `scripts/` |

---

## Monorepo context

`ite/` is one of 7 sub-projects under `itetheagt/`:

| Sub-project | Language | Entry point |
|---|---|---|
| `ite/` | Python ≥3.11 | `src/ite/main.py` |
| `ite-cloud-api/` | TypeScript 5 (ESM) | `src/index.ts` |
| `ite-cloud-web/` | React 19 + Vite | `src/main.tsx` |
| `ite-vscode/` | JavaScript | `extension.js` |
| `ite-intellij/` | Kotlin / JVM 21 | `src/main/kotlin/...` |
| `ite_admin/` | Dart 3 (Flutter desktop) | `lib/main.dart` |
| `ite_remote/` | Dart 3 (Flutter mobile) | `lib/main.dart` |

Sibling directories of note inside this repo: `docs/design/` (21 planning docs incl. `repository-tour.md`), `open-vibe-island/` (GPLv3 reference clone, gitignored), `.agents/skills/` + `.claude/skills/` (checked-in skill bundles), `.ite/` (workspace config, user skills, subagent TOMLs, hook log, pasted attachments).


