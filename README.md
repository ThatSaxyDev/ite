# iTE - Interactive Terminal Environment

An AI coding agent for your terminal. Connect the model service you want to use and get to work.

## Installation

### Recommended public install

Install `ite` globally with `pipx`:

```bash
pipx install ite-agent
```

Then launch it:

```bash
ite
```

### Option 1: Development Install (Local)

Clone the repository and install in editable mode:

```bash
git clone https://github.com/ThatSaxyDev/ite.git
cd ite
pip install -e .
```

### Option 2: Install from Source (Global)

Install globally using `pipx` (recommended) or `pip`:

### Method 1: `pipx` (recommended)

We recommend `pipx` so the `ite` command is available globally without conflicting with other Python packages.

```bash
brew install pipx
pipx ensurepath
pipx install ite-agent
ite
```

### Method 2: Standard pip

If you prefer standard pip:

```bash
pip install ite-agent
```

Note: you may need to add your Python binary location to your `PATH` to run `ite` directly.

### Option 3: Install from Git

```bash
pipx install git+https://github.com/ThatSaxyDev/ite.git
```

## Distribution

To distribute ITE, you can build a wheel file:

1. Install `build`:
   ```bash
   pip install build
   ```

2. Build the package:
   ```bash
   python -m build
   ```

This generates `dist/ite_agent-0.0.22-py3-none-any.whl`, which can be shared and installed anywhere:

```bash
pipx install ite_agent-0.0.22-py3-none-any.whl
```

## Usage

```bash
# Start interactive session
ite
```

## Quickstart

The launch path is intentionally narrow:

1. Install `ite`.
2. Start the app with `ite`.
3. Sign in through the hosted browser flow at `https://ite.kiishi.space`.
4. Run `/setup`.
5. Enter your OpenAI-compatible `base_url`, `api_key`, and `model`.
6. Send a prompt.

By default, `ite` now talks to the hosted cloud API at `https://ite-cloud-api.onrender.com`.
For local API development, override it with `ITE_CLOUD_API_URL=http://127.0.0.1:4000`.

Supported setup:

- OpenAI-compatible provider endpoint
- provider API key
- exact model name exposed by that provider

Examples include OpenAI-compatible hosted providers and self-hosted gateways that expose the same chat API shape.

### Skills

`ite` supports interoperable `SKILL.md` bundles for reusable specialist behavior.

- Put shared skills in `.agents/skills`
- Put private local overrides in `.ite/skills`
- Use `/skills` to list, inspect, and activate them
- Trust repo-provided skills with `/skills trust`
- Install local packs with `/skills add <path>`

See [docs/SKILLS.md](docs/SKILLS.md) for the supported roots, frontmatter, and commands.

## Configuration

iTE works with the model service and credentials you choose.

```bash
# Start iTE
ite

# Configure your provider (required on first run)
/setup

# Enter your provider base URL, API key, and model name
# Then start prompting immediately
```

If sign-in fails:

- verify that the browser opened the real hosted app
- verify that the API origin and web origin match the deployed environment
- sign out and run the hosted login flow again

If setup fails:

- confirm the provider uses an OpenAI-compatible API shape
- confirm the base URL is correct, including `/v1` when required
- confirm the model name is exactly what the provider exposes
- confirm the API key is valid for that provider

**What's available now:**
- Sign in with GitHub for session management
- setup with any OpenAI-compatible provider
- Full terminal AI coding experience

**Coming soon:**
- Bundled model access (no provider key needed)
- Paid plans with hosted inference

## Architecture

ITE is an AI coding agent combining four major capabilities: a terminal UI for interactive conversation, tool execution with policy controls, persistent multi-layered memory, and session-based state management with recovery features.

### Core Components

**CLI (`main.py`)** — The main orchestrator handles terminal interaction: reading multi-line input with paste detection, processing slash commands, detecting user intent for planning vs execution, and rendering the TUI. It includes intelligent paste detection that waits briefly for follow-up lines, intent detection that prompts users to enable/disable plan mode appropriately, and auto-save after every agent turn plus checkpoints every 5 turns.

**Agent (`agent/agent.py`)** — Drives the core agentic loop with plan mode handling, memory integration, response controls, and automatic todo progression.

- **Plan Mode**: A state machine with phases "idle" → "asking_questions" → "writing_plan" → "awaiting_implementation_confirmation" → "executing". The agent asks 3-5 clarifying questions based on task complexity, then writes a plan for user approval before execution begins.
- **Execution Mode**: Seeds todo items automatically from multi-step user requests, then auto-completes them based on tool invocations (file writes complete implementation todos, test/lint commands complete verification todos).
- **Memory Integration**: Intercepts explicit memory instructions ("remember...") and exact recall probes ("what phrase did I ask you to remember") for direct processing without LLM calls.
- **Response Controls**: Reads user preferences from memory and adjusts outputs (e.g., flattening bullet points if user prefers that).

**Session (`agent/session.py`)** — Maintains all per-conversation state including the LLM client, tool registry, context manager, memory manager, plan state, todo tool, change history, hook system, and MCP manager.

**Session Persistence (`agent/session_manager.py`)**

- Sessions stored in `{data_dir}/sessions/{session_id}.json`
- Checkpoints in `{data_dir}/checkpoints/{session_id}_{timestamp}.json`
- Snapshot compaction keeps the 12 most recent tool results intact, truncates older ones to 480 chars, tool call args to 320 chars, and messages over 12K chars
- Atomic writes with fsync for reliability
- Automatic quarantine of corrupt session files

### Memory System (`memory/manager.py`)

Four stores with different scopes:

| Store | Scope | Location |
|-------|-------|----------|
| short_term | Per-session | `{data_dir}/memory/sessions/{session_id}/` |
| long_term | User-global | `{data_dir}/memory/long_term.json` |
| semantic | Per-workspace | `{data_dir}/memory/projects/{hash}/semantic.json` |
| episodic | Per-workspace | `{data_dir}/memory/projects/{hash}/episodic.json` |

Retrieval uses weighted scoring: lexical match (query terms in key/summary/value), hotness (recency × access frequency with 7-day half-life decay), and store-specific boosts to favor recent over global memory. Supports conditional preferences that activate only in specific query contexts (e.g., "prefer bullet lists when explaining architecture").

### Tools System

- **Registry** (`tools/registry.py`): Maintains available tools with OpenAI function-calling schemas
- **Builtin Tools** (`tools/builtin/`): todos (planning/execution scopes), memory, plan_question, file operations, shell, glob, grep, web_search, web_fetch
- **MCP Integration** (`tools/mcp/`): Connects to external MCP servers, transparently registering their tools
- **Policy** (`tools/policy.py`): Sandbox restrictions for file operations
- **Approval Manager**: Gates dangerous operations (deletions, destructive shell) with TUI callbacks

### Context Management (`context/manager.py`)

Maintains conversation history with token estimation, triggers compression via ChatCompactor when nearing limits, and prunes tool outputs. Compression generates a summary using the LLM and records it as an episodic memory entry.

### Additional Subsystems

- **Loop Detector** (`context/loop_detector.py`): Detects repetitive patterns and injects loop-breaker prompts
- **Change History** (`agent/change_history.py`): Records file diffs from successful writes
- **Hook System** (`hooks/`): Lifecycle callbacks (before/after agent runs)
- **TUI** (`ui/tui.py`): Rich-based terminal UI with streaming, tool visualization, and confirmation prompts
