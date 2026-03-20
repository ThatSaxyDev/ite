# Tool System Research v2: Production Gaps and Build Plan for `ite`

**Context:** `ite` is a Python agent framework that uses tools as its execution backbone. This note evaluates the current tool surface in this repository, identifies production gaps, and recommends the next tools and hardening work to build.

**Scope of this document:**
- What tools exist in this repo today
- What is already strong
- What is missing for production readiness
- What should be built first

---

## Current Tool Inventory

### Built-in tools: 13

Defined in [src/ite/tools/builtin/__init__.py](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/tools/builtin/__init__.py).

| Category | Tools | Status |
|----------|-------|--------|
| File operations | `read_file`, `write_file`, `edit`, `apply_patch` | Strong baseline |
| Search and navigation | `grep`, `glob`, `list_dir` | Good baseline |
| Execution | `shell` | Useful but needs hardening |
| Web | `web_search`, `web_fetch` | Basic only |
| Session memory and workflow | `memory`, `todos`, `plan_question` | Good agent-specific baseline |

### Subagent tools: 5 in this workspace

Default subagents are defined in [src/ite/tools/subagent.py](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/tools/subagent.py):
- `subagent_codebase_investigator`
- `subagent_code_reviewer`
- `subagent_tooling_guardian`
- `subagent_verification_reviewer`

Project-defined subagent in this repo:
- `subagent_security_auditor` from [.ite/subagents/security_auditor.toml](/Users/kiishidavid/Documents/Dev/Projects/ite/.ite/subagents/security_auditor.toml)

### Discovered custom tools: 1 in this workspace

Project-defined custom tool:
- `test_tool` from [.ite/tools/test_tool.py](/Users/kiishidavid/Documents/Dev/Projects/ite/.ite/tools/test_tool.py)

### MCP tools: 0 currently connected

MCP support exists in the codebase via [src/ite/tools/mcp/mcp_manager.py](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/tools/mcp/mcp_manager.py), but no MCP servers are enabled in [.ite/config.toml](/Users/kiishidavid/Documents/Dev/Projects/ite/.ite/config.toml).

### Total active tools in this workspace: 19

- 13 built-ins
- 5 subagent tools
- 1 discovered custom tool

---

## How The Tool System Works Today

The current architecture is good and worth keeping.

### Core flow

The registry and invocation pipeline live in [src/ite/tools/registry.py](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/tools/registry.py):

1. Tool schemas are exposed to the model.
2. The model chooses a tool.
3. The registry normalizes parameters.
4. The registry validates parameters.
5. Policy checks run.
6. Approval checks run for mutating actions.
7. The tool executes.
8. Tool output is fed back into the agent loop.

The agent integrates this loop in [src/ite/agent/agent.py](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/agent/agent.py).

### Existing strengths

- Tool registration is centralized and deterministic.
- Tools are schema-driven with Pydantic validation.
- There is a policy layer for planning vs execution.
- There is an approval layer for mutating operations.
- Filesystem sandboxing exists.
- Built-in support exists for local custom tools and subagents.
- MCP is already designed as an extension layer.

This is a strong foundation for a local agent.

---

## What Is Already Good Enough

These areas are not the main problem.

### 1. File editing baseline is solid

The combination of `read_file`, `write_file`, `edit`, and especially `apply_patch` gives the agent a credible editing stack.

Important nuance:
- `edit` is fragile because it is string-match based.
- `apply_patch` is the stronger primitive and already supports atomic multi-file changes.

Conclusion:
- Do not replace this layer.
- Keep it and add better structured-edit tools beside it.

### 2. Search and navigation are adequate for baseline work

`grep`, `glob`, and `list_dir` are enough for codebase exploration.

They are not perfect, but they are not the main production blocker.

### 3. Tool-focused testing exists

The tooling layer is not untested. The current test suite includes coverage around:
- tool registry behavior
- shell safety behavior
- web tool contracts
- apply_patch
- todo scoping
- parameter normalization

This is materially better than a prototype with no verification story.

---

## Production Gaps

The current system is still not sufficient for production use, especially for a serious coding agent working on real repositories.

### 1. Git tools are the biggest missing first-class capability

**Severity:** Critical

Current state:
- There are git helper modules under [src/ite/git/](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/git), but they are not exposed as tools.
- The agent currently relies on raw `shell` for git operations.

Why this is a problem:
- Git state is core context for coding work.
- Raw shell output is harder for the agent to reason about reliably.
- There is no structured branch, diff, status, or commit model.
- Review and change validation are weaker without native git context.

Recommended first-party tools:
- `git_status`
- `git_diff`
- `git_log`
- `git_branch`
- `git_commit`

Optional later additions:
- `git_checkout`
- `git_merge`
- `git_stage`
- `git_unstage`

### 2. Structured config and data tools are missing

**Severity:** Critical

Current state:
- JSON, YAML, TOML, and `.env` files are edited as raw text.

Why this is a problem:
- Raw string edits are fragile for structured documents.
- The agent cannot validate syntax before write.
- Config updates are a common coding workflow, not an edge case.

Recommended tools:
- `read_json`
- `edit_json`
- `write_json`
- `read_yaml`
- `write_yaml`
- `read_toml`
- `write_toml`
- `read_env`
- `write_env`

If scope must stay tighter:
- Start with JSON, TOML, and `.env`
- Add YAML next

### 3. Test and quality tools should be first-class, not shell conventions

**Severity:** High

Current state:
- Testing, linting, and type checking all depend on raw `shell`.

Why this is a problem:
- Output parsing is inconsistent.
- The agent has no standardized notion of test failure vs infrastructure failure.
- There is no structured reporting by suite, file, or failure count.
- This is a major bottleneck for autonomous verification.

Recommended tools:
- `run_tests`
- `run_linter`
- `run_typecheck`
- `format_code`

Nice follow-ups:
- `get_test_status`
- `run_tests_changed_files`
- `run_tests_by_path`

### 4. Shell is useful but not yet production-hardened

**Severity:** High

Current state:
- `shell` has command classification, approvals, and sandbox path checks.
- This is implemented in [src/ite/tools/builtin/shell.py](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/tools/builtin/shell.py) and [src/ite/safety/approval.py](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/safety/approval.py).

Why this is still insufficient:
- Safety classification is regex-based and heuristic.
- Commands are one-shot only.
- There is no persistent session abstraction.
- There is no streaming execution model for long-running commands.
- There is no resource quota model.
- There is no robust policy around allowed executables by workspace or tool category.

Recommended improvements:
- Streaming shell output
- Persistent shell sessions
- Per-command execution metadata
- Allowlist/denylist by executable
- Better audit logging
- CPU/time/output quotas

### 5. Runtime robustness is a production blocker

**Severity:** High

This is easy to miss if you only count tools.

Current state:
- Session initialization loads memory and app state early in [src/ite/agent/session.py](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/agent/session.py).
- Memory writes go to app data paths via [src/ite/memory/manager.py](/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/memory/manager.py).

Observed issue:
- In a restricted environment, initialization can fail if those paths are not writable.

Why this matters:
- A production tool platform must degrade gracefully.
- Tooling quality is irrelevant if session startup is brittle.

Recommended work:
- Fallback memory mode when app-data storage is unavailable
- Clear startup diagnostics
- Read-only degraded mode
- Better separation between optional persistence and core tool availability

### 6. Web capabilities are basic, not production-grade

**Severity:** Medium

Current state:
- `web_search` is DuckDuckGo search wrapper only.
- `web_fetch` is direct GET plus basic HTML-to-markdown extraction.

Why this is limited:
- No source trust controls
- No auth support
- No POST/PUT/PATCH/DELETE
- No rate limiting
- No retries/backoff policy
- No provenance scoring
- No domain policies

Recommended addition:
- `http_request`

Recommended hardening:
- request/response schema support
- headers and body support
- timeout and retry policy
- domain allowlists

### 7. Binary and document inspection are missing

**Severity:** Medium

Current state:
- `read_file` correctly rejects binary files.
- There is no separate inspection path for images, PDFs, or SVGs.

Recommended tools:
- `read_image`
- `read_pdf`
- `read_svg`

This matters for modern repos with:
- screenshots
- design assets
- icons
- documentation PDFs

### 8. Archive tools are absent

**Severity:** Medium

Recommended tools:
- `list_archive`
- `extract_archive`
- `create_archive`

Useful for:
- release bundles
- vendor packages
- uploaded artifacts

### 9. Database tools are not core yet, but will matter if scope expands

**Severity:** Low to Medium

Recommended tools:
- `db_query`
- `db_migrate_status`

These should likely remain optional or MCP-based unless database work is a core product scenario.

---

## MCP Positioning

MCP is the right extension story, but not the baseline story.

That means:
- baseline coding workflows must work with built-in tools alone
- MCP should add specialized integrations
- MCP should not be required for basic software development tasks

Good MCP candidates:
- databases
- cloud providers
- Kubernetes
- Slack or ticketing systems
- proprietary internal systems

Bad use of MCP:
- depending on MCP for basic git, tests, or config editing

---

## Production Readiness Verdict

### Current maturity

| Area | Assessment |
|------|------------|
| Registry architecture | Strong |
| Validation and normalization | Strong |
| File editing | Good |
| Search/navigation | Good |
| Approval and sandbox model | Good baseline, not hardened |
| Web tools | Basic |
| Git support | Missing |
| Structured config editing | Missing |
| Test/lint/typecheck integration | Missing |
| Runtime robustness | Not production-ready |
| Observability and auditability | Partial |

### Bottom line

`ite` already has a serious local-agent tooling backbone.

It is not yet production-ready for a general-purpose coding agent because it still lacks:
- first-class git tools
- first-class structured config/data tools
- first-class verification tools
- hardened shell execution
- robust degraded startup behavior

---

## Recommended Build Order

This is the practical order to execute.

### Phase 0: Hardening before expansion

1. Make startup and memory persistence degrade gracefully
2. Improve shell observability and execution metadata
3. Add clearer failure modes around unavailable storage, hooks, and MCP

### Phase 1: Table-stakes coding tools

1. `git_status`
2. `git_diff`
3. `git_log`
4. `git_branch`
5. `git_commit`
6. `run_tests`
7. `run_linter`
8. `run_typecheck`

### Phase 2: Structured configuration tools

1. `read_json`
2. `edit_json`
3. `write_json`
4. `read_toml`
5. `write_toml`
6. `read_env`
7. `write_env`
8. `read_yaml`
9. `write_yaml`

### Phase 3: Shell and workflow upgrades

1. streaming shell output
2. persistent shell sessions
3. executable allowlists
4. resource quotas
5. improved structured error categories

### Phase 4: Breadth and polish

1. `http_request`
2. archive tools
3. image and PDF inspection
4. optional database tools

---

## Proposed Next 10 Tools

If the goal is to move the platform materially toward production, these are the highest-leverage next tools:

1. `git_status`
2. `git_diff`
3. `git_log`
4. `git_branch`
5. `git_commit`
6. `run_tests`
7. `run_linter`
8. `run_typecheck`
9. `read_json`
10. `edit_json`

These 10 would close the most important gap between "file editor with shell access" and "real coding agent."

---

## Final Recommendation

Do not rethink the whole tool architecture. The architecture is fine.

Do this instead:
- keep the existing registry, policy, approval, discovery, and MCP model
- harden startup and shell behavior
- add first-class built-ins for git, verification, and structured config
- treat MCP as an extension layer, not the baseline product

That is the shortest path from the current system to production readiness.

---

*Updated: March 20, 2026*
