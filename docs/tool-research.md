# Tool System Research: Baseline Tool Gaps for a Production Coding Agent

**Context:** A general-purpose coding agent (not code-only), built on Python, using tools as its backbone for external world interaction.

**Goal:** Identify gaps in current baseline tools and recommend what's needed for production readiness, with MCP filling extensibility gaps.

---

## Current Baseline Tools (16 built-in)

| Category | Tools | Status |
|----------|-------|--------|
| **File Operations** | `read_file`, `write_file`, `edit`, `apply_patch` | ✅ Core coverage |
| **Search** | `grep`, `glob`, `list_dir` | ✅ Basic |
| **Execution** | `shell` | ⚠️ Needs hardening |
| **Web** | `web_search`, `web_fetch` | ✅ Basic |
| **Memory** | `memory`, `todos`, `plan_question` | ✅ Core |
| **Subagents** | `SubagentTool` | ✅ Dynamic |

---

## Critical Gaps for a General-Purpose Coding Agent

### 1. Git Operations — **CRITICAL**

Git is non-negotiable for any coding agent that touches real repositories.

**Current state:** No git tools. Agent relies on `shell` to run raw git commands.

**Problems:**
- Raw shell commands are brittle, error-prone, hard to parse
- No structured understanding of git state (branches, remotes, conflicts)
- Can't do meaningful PR review without git context

**Recommended tools:**
| Tool | Purpose |
|------|---------|
| `git_status` | Show modified/staged/untracked files |
| `git_diff` | Structured diff output with context |
| `git_log` | Recent commits, authorship |
| `git_branch` | List/create/switch branches |
| `git_commit` | Stage files and commit with message |
| `git_checkout` | Switch branches or restore files |
| `git_merge` | Merge branches (with conflict detection) |

**Reference:** Claude Code treats git as first-class. GitHub Copilot has git tools. This is industry standard.

---

### 2. Structured Data Manipulation — **HIGH PRIORITY**

Codebases contain JSON, YAML, TOML, XML, ENV files. Agent needs to read and write these reliably.

**Current state:** No structured data tools. Agent must parse via shell or raw text editing.

**Problems:**
- Editing YAML/JSON by string manipulation is error-prone
- No validation before write
- ENV file handling is dangerous with raw text tools

**Recommended tools:**
| Tool | Purpose |
|------|---------|
| `read_json` | Parse and read JSON files |
| `write_json` | Write JSON with validation |
| `read_yaml` | Parse YAML files |
| `write_yaml` | Write YAML with formatting |
| `read_toml` | Parse TOML (common in Python) |
| `read_env` | Read .env files safely |
| `edit_json` | Patch JSON paths (jq-like) |

---

### 3. Testing & Quality Assurance — **HIGH PRIORITY**

A coding agent that can't run or understand tests is limited to "dead code" scenarios.

**Current state:** No test tools. Agent relies on `shell` to run test commands.

**Problems:**
- No standardized test discovery or reporting
- Can't understand test failures in context
- No coverage awareness

**Recommended tools:**
| Tool | Purpose |
|------|---------|
| `run_tests` | Execute test suite, parse output |
| `get_test_status` | Check if specific tests pass/fail |
| `run_linter` | Execute linting, parse errors |
| `run_typecheck` | Execute type checking |
| `format_code` | Auto-format files (prettier, black, etc.) |

---

### 4. Image & Binary Inspection — **MEDIUM**

Modern codebases include images, PDFs, SVGs, icons. A general-purpose agent needs to inspect these.

**Current state:** None.

**Recommended tools:**
| Tool | Purpose |
|------|---------|
| `read_image` | Extract image metadata (dimensions, format) |
| `read_pdf` | Extract text from PDFs |
| `read_svg` | Parse SVG for inspection/modification |

---

### 5. Archive & Compression — **MEDIUM**

Codebases ship as archives. Agent should inspect them.

**Recommended tools:**
| Tool | Purpose |
|------|---------|
| `list_archive` | Inspect zip/tar contents |
| `extract_archive` | Extract to directory |
| `create_archive` | Package files |

---

### 6. HTTP/REST Client — **MEDIUM**

For agents working with APIs, webhooks, or microservices.

**Current state:** `web_fetch` exists but limited to GET on URLs.

**Recommended tools:**
| Tool | Purpose |
|------|---------|
| `http_request` | Full HTTP client (GET, POST, PUT, DELETE, headers, body) |

---

### 7. Database Operations — **LOW-MEDIUM** (depends on use case)

For agents that need to verify database migrations or run queries.

**Recommended tools:**
| Tool | Purpose |
|------|---------|
| `db_query` | Execute read-only SQL queries |
| `db_migrate_status` | Check migration state |

---

### 8. Terminal Session Management — **LOW** (nice to have)

Current `shell` executes commands in isolation. Persistent sessions would help with complex workflows.

**Recommended tools:**
| Tool | Purpose |
|------|---------|
| `shell_session` | Create/query/terminate shell sessions |
| `shell_send` | Send input to a session |

---

## Tool Quality Issues in Current Baseline

Even for tools that exist, several quality issues need addressing:

### Shell Tool (384 lines)
- Single command execution only
- No session/persistence
- No streaming output
- Command aliasing in registry is good but limited
- Sandbox compliance check exists but command allowlists would be safer

### Edit Tool (252 lines)
- String-matching approach is fragile for large files
- `apply_patch` (385 lines) exists as more robust alternative but may have overlap/confusion
- No atomic multi-file transactions

### Read File Tool (144 lines)
- Line offset/limit is good
- Binary file handling is unclear
- Large file truncation strategy needs verification

### Grep Tool (146 lines)
- Basic regex matching
- Missing: context lines, case sensitivity options, file type filters

---

## MCP as Extensibility Layer

Current architecture supports MCP tools (separate `_mcp_tools` dict in registry). This is the right approach for:

| Use Case | MCP Approach |
|----------|--------------|
| Database tools | `mcp-sqltool` or custom |
| Kubernetes | `mcp-kubernetes` |
| Cloud APIs | Custom MCP servers |
| Slack/Teams integration | `mcp-slack`, etc. |

**However:** MCP should extend, not replace. Baseline tools must work without MCP servers being configured.

---

## Prioritization Recommendation

### Phase 1: Immediate Production Needs
1. **Git tools** — Without git, the agent can't do real development
2. **Structured data tools** — JSON/YAML/ENV are everywhere
3. **Shell hardening** — Command allowlists, output streaming, session support

### Phase 2: Quality of Life
4. **Test runner integration** — Standardize test execution/parsing
5. **Linter/type-checker integration** — Format and validate code
6. **Image inspection** — SVGs, screenshots, icons

### Phase 3: Polish
7. **HTTP client** — For API-first workflows
8. **Archive tools** — Package inspection
9. **Terminal sessions** — Complex workflow support

---

## Implementation Considerations

### Tool Design Patterns to Follow
1. **Parameter normalization** — Already done in registry; continue for new tools
2. **Schema-driven params** — Use Pydantic models (existing pattern)
3. **Structured output** — Return parsed/typed results, not just strings
4. **Error categorization** — Distinguish user errors from system errors
5. **Dry-run support** — For destructive operations
6. **Parallel execution** — Read tools should be safe to parallelize

### Safety Requirements
1. Sandbox path validation (exists)
2. Command allowlists for shell
3. Rate limiting on network tools
4. Approval workflow for mutating tools (exists)
5. Audit logging/telemetry (exists in registry)

---

## Competitor Analysis

| Agent | Notable Tools |
|-------|--------------|
| **Claude Code** | Git native, test running, PR creation, MCP, subagents |
| **GitHub Copilot** | Code completion, PR summary, documentation generation |
| **Cursor Composer** | Multi-file editing, agentic editing across codebase |
| **OpenCode** | Session management, persistent storage, vim-like editing |
| **Augment Code** | Codebase intelligence, architectural pattern understanding |

**Common theme:** Git operations + test integration + MCP extensibility = table stakes.

---

## Conclusion

Your baseline tool set is a solid foundation for a **file-manipulation-focused** agent. However, for a **general-purpose coding agent**, you are missing:

1. **Git** — The single biggest gap
2. **Structured data** — JSON/YAML/ENV are critical
3. **Test integration** — Essential for a "live code" agent
4. **Quality tools** — Linting, formatting, type checking

MCP can fill specialized gaps, but these core categories should be built-in. They represent what users expect from any coding assistant that touches real codebases.

---

*Generated: March 2026*
