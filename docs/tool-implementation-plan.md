# Tooling Implementation Plan

**Purpose:** Turn the production-gap research into an executable delivery plan for `ite`.

**Primary objective:** Move `ite` from a strong local-agent prototype to a production-capable coding agent by hardening the runtime and adding first-class tools for git, verification, and structured config editing.

**References:**
- [tool-research.md](/Users/kiishidavid/Documents/Dev/Projects/ite/docs/tool-research.md)
- [TOOLS.md](/Users/kiishidavid/Documents/Dev/Projects/ite/docs/TOOLS.md)

---

## Goals

By the end of this plan, `ite` should have:

1. Reliable startup behavior in restricted environments
2. First-class git tools instead of shell-only git usage
3. First-class test and quality tools instead of shell conventions
4. First-class structured config/data tools
5. A more production-ready shell execution model

---

## Non-Goals

These are explicitly out of scope for the first implementation cycle:

- full database tooling
- full cloud-provider integrations
- replacing MCP as the extension layer
- redesigning the core tool registry
- replacing `apply_patch` as the main multi-file editing primitive

---

## Delivery Strategy

Work in this order:

1. Stabilize startup and execution surfaces
2. Add the smallest set of tools that unlock real software development workflows
3. Add structured config tooling
4. Improve shell ergonomics and operational safety
5. Add breadth tools after the core path is strong

This avoids adding new tools on top of brittle runtime assumptions.

---

## Phase 0: Runtime Hardening

**Goal:** Ensure the agent starts and degrades safely before more tools are added.

### Work items

1. Make memory initialization resilient
- Add fallback behavior when app-data storage is unavailable
- Support a read-only or in-memory degraded mode
- Surface clear diagnostics instead of failing session startup

2. Improve session initialization fault tolerance
- Prevent optional systems from taking down the entire session
- Isolate failures in memory, hooks, and MCP initialization
- Record degraded capability state explicitly

3. Improve execution diagnostics
- Standardize error categories for tool initialization vs invocation failures
- Expose startup warnings to the UI and logs
- Preserve actionable metadata for operator debugging

### Deliverables

- startup fallback for memory persistence
- degraded-mode capability flagging
- clearer startup error reporting

### Acceptance criteria

- Agent session starts even when app-data writes are unavailable
- Tool registry remains available in degraded mode
- User-visible diagnostics explain what was disabled and why
- Tests cover unwritable storage and partial startup failure scenarios

---

## Phase 1: First-Class Git Tools

**Goal:** Remove git from the category of "raw shell convention."

### Tools to build

1. `git_status`
2. `git_diff`
3. `git_log`
4. `git_branch`
5. `git_commit`

### Design requirements

- Use the existing helpers under `src/ite/git/` where possible
- Return structured metadata, not only formatted text
- Distinguish clean repo, dirty repo, detached HEAD, and no-repo states
- Support dry-run or non-destructive inspection where relevant
- Keep approvals for mutating git operations

### Suggested output contracts

`git_status`
- branch name
- upstream state
- staged files
- unstaged files
- untracked files
- clean/dirty flag

`git_diff`
- target range or working tree scope
- changed files
- diff text
- summary counts

`git_log`
- commit list
- author
- date
- subject

`git_branch`
- current branch
- available branches
- created/switched branch when mutating

`git_commit`
- commit message
- commit SHA
- changed file count

### Deliverables

- five first-class git tools
- registry integration
- approval rules for mutating git operations
- tests for non-repo, dirty repo, and common git states

### Acceptance criteria

- Agent can inspect repo state without shell
- Agent can create a commit with structured results
- Common git failures are returned as readable typed errors
- Tests cover happy path and failure path for each git tool

---

## Phase 2: Verification Tools

**Goal:** Make code verification a first-class capability.

### Tools to build

1. `run_tests`
2. `run_linter`
3. `run_typecheck`
4. `format_code`

### Design requirements

- Wrap the existing project toolchain rather than inventing one
- Return structured summaries:
  - command run
  - exit code
  - files affected
  - error count
  - truncated/full output flags
- Classify failures into:
  - command not found
  - config error
  - test failures
  - infra/runtime failure

### Scope guidance

Start with convention-based detection:
- Python: `pytest`, `ruff`, `mypy`
- JS/TS: `npm test`, `pnpm test`, `eslint`, `tsc`

Prefer explicit config-driven runner selection later if needed.

### Deliverables

- four verification tools
- output parsing for common ecosystems
- shared command-run metadata model
- tests for runner detection and failure categorization

### Acceptance criteria

- Agent can run tests and report whether failures are product failures or runner failures
- Agent can invoke lint and typecheck without raw shell reasoning
- Outputs are compact, structured, and reusable in follow-up reasoning

---

## Phase 3: Structured Config and Data Tools

**Goal:** Stop treating config files as raw text by default.

### Tools to build

1. `read_json`
2. `edit_json`
3. `write_json`
4. `read_toml`
5. `write_toml`
6. `read_env`
7. `write_env`
8. `read_yaml`
9. `write_yaml`

### Implementation order

1. JSON
2. TOML
3. `.env`
4. YAML

### Design requirements

- Parse before mutate
- Validate before write
- Preserve stable formatting where practical
- Return parse errors distinctly from file I/O errors
- Support path-based edits for JSON

### Deliverables

- typed readers and writers for the four config families
- structured parse/error model
- tests for valid, invalid, and formatting-sensitive cases

### Acceptance criteria

- Agent can inspect and update JSON/TOML/ENV/YAML safely
- Invalid documents fail with helpful parse errors
- Common config changes no longer require brittle string replacement

---

## Phase 4: Shell Hardening

**Goal:** Keep shell powerful, but stop treating it as the default for everything.

### Work items

1. Streaming output
- Support incremental command output for long-running processes
- Preserve current timeout and sandbox behavior

2. Persistent shell sessions
- Add session create, send, read, terminate flow
- Support REPL-like workflows and long-lived dev servers

3. Execution policy upgrades
- Add executable allowlists or policy classes
- Improve resource quota controls
- Tighten output size and runtime controls

4. Better auditability
- Assign execution IDs
- Persist structured command metadata
- Improve operator-facing logs

### Deliverables

- streaming shell mode
- persistent shell sessions
- stronger executable policy controls
- richer execution metadata

### Acceptance criteria

- Long-running commands can stream output safely
- Multi-step shell workflows do not require command re-entry every turn
- Operators can inspect what was executed and why

---

## Phase 5: Secondary Breadth Tools

**Goal:** Expand capability after the core coding path is strong.

### Tools to consider

1. `http_request`
2. `list_archive`
3. `extract_archive`
4. `create_archive`
5. `read_image`
6. `read_pdf`
7. `read_svg`

### Recommendation

These should follow the core phases, not precede them.

---

## Cross-Cutting Engineering Requirements

These apply to every new tool.

### 1. Schema-first design

Every tool should:
- use Pydantic schemas
- define aliases where helpful
- return structured metadata

### 2. Strong error contracts

Every tool should distinguish:
- validation errors
- environment errors
- permission/sandbox errors
- domain-specific failures

### 3. Approval and policy integration

Every mutating tool must:
- declare affected paths where relevant
- integrate with approval flow
- respect plan mode restrictions

### 4. Testing

Every new tool should have:
- happy path tests
- permission/sandbox tests
- malformed input tests
- degraded environment tests where applicable

### 5. Observability

Every tool should emit:
- tool name
- duration
- success/failure
- key error category
- safe structured metadata

---

## Proposed Milestones

### Milestone 1

Runtime hardening complete.

Definition of done:
- restricted startup works
- degraded mode exists
- diagnostics improved

### Milestone 2

Git tools shipped.

Definition of done:
- `git_status`, `git_diff`, `git_log`, `git_branch`, `git_commit` available
- tests cover common repo states

### Milestone 3

Verification tools shipped.

Definition of done:
- `run_tests`, `run_linter`, `run_typecheck`, `format_code` available
- structured result contracts stable

### Milestone 4

Structured config tools shipped.

Definition of done:
- JSON, TOML, ENV, YAML tooling available
- parser and validation failures handled cleanly

### Milestone 5

Shell hardening complete.

Definition of done:
- streaming and session support available
- better controls and telemetry shipped

---

## Immediate Next Actions

Start here:

1. Implement Phase 0 fallback behavior for memory and startup
2. Expose existing git helper logic through `git_status`
3. Add `git_diff`
4. Add `run_tests`
5. Lock down result schemas and test conventions before adding more tools

If execution needs to be narrower, the first three concrete deliverables should be:

1. startup degraded mode
2. `git_status`
3. `run_tests`

---

## Summary

The shortest realistic path to production is:

1. harden startup
2. add git tools
3. add verification tools
4. add structured config tools
5. harden shell further

That sequence improves reliability first, then delivers the biggest capability wins, then broadens the platform without increasing fragility.

---

*Created: March 20, 2026*
