# Tools

iTE includes a comprehensive set of built-in tools for reading, writing, searching, executing, and managing your codebase.

## Tool Categories

| Category | Purpose |
|----------|---------|
| **Read** | Explore and understand your codebase |
| **Write** | Create and modify files |
| **Execute** | Run commands and scripts |
| **Search** | Find code patterns and references |
| **Meta** | Manage tasks, memory, and context |
| **Verification** | Run tests, linting, and type checks |
| **Subagent** | Spawn specialist agents |

## Read Tools

### File Reading

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with optional offset and limit |
| `read_json` | Read and parse JSON files |
| `read_toml` | Read and parse TOML files |
| `read_yaml` | Read and parse YAML files |
| `read_env` | Read .env files |
| `read_pdf` | Extract PDF text as Markdown with layout, table, and scanned-page detection |
| `read_document` | Convert Word, Excel, PowerPoint, OpenDocument, RTF, EPUB, CSV to Markdown |
| `read_image` | Read image metadata and extract text with OCR |

### Directory & Search

| Tool | Description |
|------|-------------|
| `list_dir` | List directory contents |
| `glob` | Find files by pattern (supports `**` for recursive) |
| `grep` | Search for patterns in file content |

### Archive Inspection

| Tool | Description |
|------|-------------|
| `list_archive` | Inspect zip or tar archives |

**Examples:**
```
# Read a specific file
read_file path="src/main.py"

# Read with offset and limit
read_file path="src/main.py" offset=1 limit=50

# Find all Python files
glob pattern="**/*.py"

# Search for a pattern
grep pattern="class.*Agent" path="src"

# List directory
list_dir path="src"
```

## Write Tools

| Tool | Description |
|------|-------------|
| `write_file` | Create or overwrite files |
| `edit` | Make surgical text replacements |
| `apply_patch` | Apply multi-file patch edits |
| `edit_json` | Edit JSON files using structured paths |
| `edit_toml` | Edit TOML files using structured paths |
| `edit_yaml` | Edit YAML files using structured paths |
| `write_env` | Set/delete variables in .env files |

**Examples:**
```
# Create a new file
write_file path="config.yaml" content="..."

# Surgical edit
edit path="src/main.py" old_string="..." new_string="..."

# JSON edit
edit_json path="package.json" json_path="dependencies.react" operation="set" value="^18.0.0"

# TOML edit
edit_toml path="pyproject.toml" key_path="project.version" value="1.2.3"

# Multi-file patch
apply_patch patch="..."
```

## Execute Tools

| Tool | Description |
|------|-------------|
| `shell` | Execute shell commands with optional timeout |
| `shell_start` | Start persistent shell sessions |
| `shell_poll` | Read output from running sessions |
| `shell_send` | Send input to running sessions |
| `shell_stop` | Terminate running sessions |

**Examples:**
```
# Run a command
shell command="pytest tests/"

# With timeout
shell command="sleep 10" timeout=5

# Start persistent session
shell_start command="npm run dev"

# Poll for output
shell_poll session_id="..."
```

## Search Tools

| Tool | Description |
|------|-------------|
| `grep` | Search file contents with regex |
| `glob` | Find files by name pattern |

**grep Options:**
- `pattern`: Regex pattern to search for
- `path`: File or directory to search
- `case_insensitive`: Case-insensitive search

## Meta Tools

| Tool | Description |
|------|-------------|
| `todos` | Manage task lists |
| `memory` | Store and retrieve persistent memory |
| `plan_question` | Ask structured planning questions |
| `skills` | List, activate, and inspect skills |

### Todos

Scopes: `planning` (internal) and `execution` (user-facing)

```
todos action="add" content="Fix authentication bug"
todos action="complete" id="..."
todos action="list"
```

### Memory

Stores:
- `short_term`: Session-scoped notes
- `long_term`: Persistent user preferences
- `semantic`: Project-specific knowledge
- `episodic`: Session milestones

```
memory action="set" key="preferred_test_cmd" value="pytest" store="semantic"
memory action="get" key="preferred_test_cmd"
memory action="list"
```

## Git Tools

| Tool | Description |
|------|-------------|
| `git_status` | Inspect repository state |
| `git_diff` | Show working tree diffs |
| `git_log` | View commit history |
| `git_branch` | List, create, or switch branches |
| `git_commit` | Create commits |
| `git_push` | Push to remote |
| `git_remote` | Manage remotes |

## Web Tools

| Tool | Description |
|------|-------------|
| `web_search` | Search the web |
| `web_fetch` | Fetch and extract page content |
| `http_request` | Make HTTP requests |

## Verification Tools

| Tool | Description |
|------|-------------|
| `run_tests` | Run project tests |
| `run_linter` | Run project linter |
| `run_typecheck` | Run type checker |

These auto-detect project configuration and run appropriate commands.

## Subagent Tools

| Tool | Description |
|------|-------------|
| `spawn_subagent` | Start specialist subagents |
| `spawn_subagents` | Start multiple subagents in parallel |
| `wait_subagent` | Wait for subagent completion |
| `list_subagents` | List active subagents |
| `cancel_subagent` | Cancel running subagents |

**Examples:**
```
# Spawn a specialist
spawn_subagent subagent="security_auditor" goal="Audit auth code"

# Parallel spawning
spawn_subagents requests=[{subagent: "reviewer", goal: "..."}, ...]

# Wait for completion
wait_subagent run_ids=["..."] return_when="all_completed"
```

## Tool Risk Levels

Tools are classified by risk:

| Level | Description |
|-------|-------------|
| `LOW` | Safe read-only operations |
| `MEDIUM` | Mutating operations (requires approval based on mode) |
| `HIGH` | Destructive operations (always requires approval) |

## Tool Access Types

| Type | Description |
|------|-------------|
| `read` | Read-only access |
| `write` | Can modify files or state |

View all tools with their risk levels and access types using `/tools` in iTE.

---

[Learn about subagents →](subagents.md)
